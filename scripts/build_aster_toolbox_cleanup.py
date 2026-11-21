"""Remove the retired launcher while preserving Aster's saved-profile migration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version

ROOT = Path(__file__).resolve().parents[1]
TOOLBOX_COMPONENTS = {
    ("service", "io.github.dreammooncai.pvz2tool.service.LocalVpnService"),
    ("provider", "com.petterp.floatingx.assist.FxContentProvider"),
    ("provider", "androidx.startup.InitializationProvider"),
    ("provider", "com.kdroid.androidcontextprovider.ContextInitProvider"),
    ("receiver", "androidx.profileinstaller.ProfileInstallReceiver"),
    ("uses-library", "androidx.window.extensions"),
    ("uses-library", "androidx.window.sidecar"),
    ("uses-permission", "android.permission.SYSTEM_ALERT_WINDOW"),
}
SOURCE_DEX = {f"classes{i}.dex" for i in range(3, 8)}
MOVE_DEX = {f"classes{i}.dex": f"classes{i - 4}.dex" for i in range(8, 12)}
TOOLBOX_PAYLOAD = {
    "kotlin-tooling-metadata.json", "res/mipmap-hdpi-v4/bg_fill_image.jpg",
    "res/drawable/game_fill_bg.xml",
}


def replace_toolbox_window_background(table):
    # Preserve the existing theme and window flags. Only change the two
    # windowBackground values (default and v28) to an opaque black color.
    old = struct.pack("<IHBBI", 0x01010054, 8, 0, 0x01, 0x660800d7)
    black = struct.pack("<IHBBI", 0x01010054, 8, 0, 0x1c, 0xff000000)
    if table.count(old) != 2:
        raise ValueError("Unexpected old launcher background theme entries")
    return table.replace(old, black)


def strip_manifest(original):
    data = manifest_version(original, 203, 202, prefix="A")
    pool = 8
    kind, header, pool_size, count, styles, flags, offsets, _ = struct.unpack_from("<HH6I", data, pool)
    if (kind, header, styles, flags) != (1, 28, 0, 0):
        raise ValueError("Unexpected manifest string pool")
    strings = []
    for index in range(count):
        at = pool + offsets + struct.unpack_from("<I", data, pool + header + index * 4)[0]
        length = struct.unpack_from("<H", data, at)[0]
        strings.append(data[at + 2:at + 2 + 2 * length].decode("utf-16le"))

    offset = pool + pool_size
    result = bytearray(data[:offset])
    removed = set()
    skip = 0
    while offset < len(data):
        kind, header, size = struct.unpack_from("<HHI", data, offset)
        if size < header or header < 8 or offset + size > len(data):
            raise ValueError("Invalid binary XML chunk")
        if kind == 0x102:
            if skip:
                skip += 1
            else:
                ext = offset + header
                tag, first, stride, count = struct.unpack_from("<IHHH", data, ext + 4)
                for i in range(count):
                    attr = ext + first + i * stride
                    key = struct.unpack_from("<I", data, attr + 4)[0]
                    if strings[key] == "name" and data[attr + 15] == 3:
                        value = struct.unpack_from("<I", data, attr + 16)[0]
                        pair = (strings[tag], strings[value])
                        if pair in TOOLBOX_COMPONENTS:
                            if pair in removed:
                                raise ValueError(f"Duplicate toolbox component: {pair}")
                            removed.add(pair)
                            skip = 1
                        break
        if not skip:
            result.extend(data[offset:offset + size])
        elif kind == 0x103:
            skip -= 1
        offset += size
    if skip or removed != TOOLBOX_COMPONENTS:
        raise ValueError(f"Incomplete toolbox removal: {TOOLBOX_COMPONENTS - removed}")
    struct.pack_into("<I", result, 4, len(result))
    return bytes(result)


def shared_classes(records, scratch, jdk):
    apktool = ROOT.parent / "tools/apktool.jar"
    inputs = scratch / "input"
    inputs.mkdir()
    refs = {"androidx.core.content.FileProvider"}
    toolbox_hashes = {}
    for abi, apk, manifest in records:
        with ZipFile(apk) as archive:
            for name in archive.namelist():
                if re.fullmatch(r"classes\d*\.dex", name):
                    data = archive.read(name)
                    if name in SOURCE_DEX:
                        digest = hashlib.sha256(data).digest()
                        if toolbox_hashes.setdefault(name, digest) != digest:
                            raise ValueError(f"Different old toolbox DEX for {abi}: {name}")
                        if abi == "ARM32":
                            (inputs / name).write_bytes(data)
                    else:
                        (inputs / f"{abi}-{name}").write_bytes(data)
                elif name.endswith(".so"):
                    refs.update(m.decode("ascii") for m in re.findall(
                        rb"(?:[a-zA-Z0-9_$-]+[./]){2,}[a-zA-Z0-9_$-]+", archive.read(name)) if len(m) < 170)
            # The manifest uses UTF-16; exclude orphan names from removed elements.
            _, names = manifest_components(manifest)
            refs.update(names)
    (inputs / "external-class-references.txt").write_text("\n".join(sorted(refs)), encoding="ascii")
    repair = ROOT / "scripts/RepairDex.java"
    prune = ROOT / "scripts/PruneToolboxDex.java"
    subprocess.run([jdk / "bin/javac.exe", "-cp", apktool, "-d", scratch, repair, prune], check=True)
    classpath = os.pathsep.join(map(str, (apktool, scratch)))
    java = [jdk / "bin/java.exe", "-Xmx900m", "-cp", classpath]
    smali = scratch / "smali"
    subprocess.run([*java, "PruneToolboxDex", inputs, smali], check=True)
    result = scratch / "retained.dex"
    subprocess.run([*java, "RepairDex", "encode", smali, result], check=True)
    return result.read_bytes()


def manifest_components(data):
    """Return element count and named declarations from binary XML."""
    pool = 8
    _, pool_header, size, _, _, _, offsets, _ = struct.unpack_from("<HH6I", data, pool)

    def string(index):
        at = pool + offsets + struct.unpack_from("<I", data, pool + pool_header + index * 4)[0]
        length = struct.unpack_from("<H", data, at)[0]
        return data[at + 2:at + 2 + 2 * length].decode("utf-16le")

    count, names = 0, set()
    at = pool + size
    while at < len(data):
        kind, header, size = struct.unpack_from("<HHI", data, at)
        if kind == 0x102:
            count += 1
            ext = at + header
            _, first, stride, length = struct.unpack_from("<IHHH", data, ext + 4)
            for i in range(length):
                attr = ext + first + i * stride
                if data[attr + 15] == 3 and string(struct.unpack_from("<I", data, attr + 4)[0]) == "name":
                    names.add(string(struct.unpack_from("<I", data, attr + 16)[0]))
        at += size
    return count, names


def build(base, output, sdk, jdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(jdk / "bin") + os.pathsep + os.environ["PATH"]
    records = []
    for abi in ("ARM32", "ARM64"):
        source = base / f"PvZ2-Unline-Aster-A202-{abi}.apk"
        with ZipFile(source) as archive:
            manifest = strip_manifest(archive.read("AndroidManifest.xml"))
        records.append((abi, source, manifest))
    with TemporaryDirectory(prefix="toolbox-dex-", dir=output) as folder:
        trimmed = shared_classes(records, Path(folder), jdk)
    report = {}
    for abi, source, manifest in records:
        with ZipFile(source) as archive:
            assets = {n for n in archive.namelist() if n.startswith("assets/pvz2tool/")}
            if "assets/pvz2tool/dream.yml" not in assets or not TOOLBOX_PAYLOAD <= set(archive.namelist()):
                raise ValueError(f"Unexpected toolbox assets for {abi}")
            replacements = {new: archive.read(old) for old, new in MOVE_DEX.items()}
            replacements.update({"AndroidManifest.xml": manifest, "classes3.dex": trimmed})
            replacements["resources.arsc"] = replace_toolbox_window_background(archive.read("resources.arsc"))
            exclude = assets | TOOLBOX_PAYLOAD | MOVE_DEX.keys()
            old_dex = sum(archive.getinfo(name).file_size for name in SOURCE_DEX)
            removed_assets = sum(archive.getinfo(name).file_size for name in assets | TOOLBOX_PAYLOAD)
        final = output / f"PvZ2-Unline-Aster-A203-{abi}.apk"
        pack_apk(source, replacements, sdk, final, signing, excluded=exclude)
        report[abi] = {
            "apk_bytes_saved": source.stat().st_size - final.stat().st_size,
            "toolbox_asset_files_removed": len(assets | TOOLBOX_PAYLOAD),
            "toolbox_asset_bytes_removed": removed_assets,
            "dex_bytes_saved": old_dex - len(trimmed),
            "removed_manifest_entries": sorted(name for _, name in TOOLBOX_COMPONENTS),
        }
        print(final, report[abi]["apk_bytes_saved"], "bytes saved", flush=True)
    (output / "toolbox-cleanup.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "output", "sdk", "jdk", "signing"):
        parser.add_argument("--" + argument, type=Path, required=True)
    build(**vars(parser.parse_args()))
