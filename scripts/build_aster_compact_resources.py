"""Pack losslessly compressed UI and startup resource groups into A202."""
import argparse
from copy import copy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryFile
from zipfile import ZIP_STORED, ZipFile
import zlib

from elftools.elf.elffile import ELFFile
from build_aster_arm64_game import copy_compressed_entry
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from index_texture_prefetch import ResourceZip, rsbtool
from package_baked_rgba import PARTS, PREFIX
from rebuild_bootstrap_dex import rebuild_bootstrap

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = {"init.rsb.smf", "uiactive.rsb.smf", "uicommon.rsb.smf"}
BASELINE = "assets/reconstruction/aster-background-baseline"
BLOCK = 4096
CHUNK = 1024 * 1024


def require(test, message):
    if not test:
        raise ValueError(message)


def read_exact(stream, length):
    data = stream.read(length)
    require(len(data) == length, "Truncated resource bundle")
    return data


def pack_pool(data, *, include_empty=False):
    if not data and not include_empty:
        return b""
    packed = zlib.compress(data, 6)
    packed += bytes(-len(packed) % BLOCK)
    require(zlib.decompress(packed) == data, "Resource pool failed lossless round-trip")
    return packed


def rewrite_bundle(source, target, before, compressed_groups):
    lead = read_exact(source, 112)
    require(lead[:4] == b"1bsr", "Expected a plain RSB bundle")
    header_size = struct.unpack_from("<I", lead, 12)[0]
    require(len(lead) <= header_size < before and header_size % BLOCK == 0, "Invalid RSB header size")
    header = bytearray(lead + read_exact(source, header_size - len(lead)))
    structure = rsbtool.parse_head(header)
    groups = rsbtool.read_rsgp_info(header, structure["rsgpInfo_BeginOffset"],
                                   structure["rsgp_Number"], structure["rsgpInfo_EachLength"])
    target.write(header)
    gpu_relocations = {}
    savings = {"resident": 0, "gpu": 0}
    compressed_count = 0
    for group in sorted(groups, key=lambda item: item["fields"][0]):
        offset, length = group["fields"][:2]
        require(source.tell() == offset and length % BLOCK == 0, "Unexpected RSG gaps or alignment")
        data = read_exact(source, length)
        flag, header_bytes, resident, stored, raw, _, gpu, gpu_stored, gpu_raw = struct.unpack_from(
                "<9I", data, 16)
        require(data[:4] == b"pgsr" and flag == 0 and header_bytes == resident
                and header_bytes >= BLOCK and stored == raw and gpu_stored == gpu_raw
                and resident + stored == gpu and gpu + gpu_stored == length,
                "Unexpected resource-group pool layout: " + group["ID"])
        entry = group["at"]
        require(header[entry + 140:entry + 176] == data[16:36] + data[32:36] + data[40:52],
                "RSG descriptor does not match its parent")
        compressed = group["ID"] in compressed_groups
        if compressed:
            # The reference's compressed GPU-only groups still have a
            # physical zlib stream for the empty resident pool.
            first = pack_pool(data[resident:gpu], include_empty=True)
            second = pack_pool(data[gpu:])
            compressed_count += 1
        else:
            first, second = data[resident:gpu], data[gpu:]
        new_start = target.tell()
        new_gpu = resident + len(first)
        new_length = new_gpu + len(second)
        require(new_length % BLOCK == 0, "Invalid compact group size")
        updated = bytearray(data[:resident])
        struct.pack_into("<I", updated, 16, 3 if compressed else 0)
        struct.pack_into("<I", updated, 28, len(first))
        struct.pack_into("<II", updated, 40, new_gpu, len(second))
        struct.pack_into("<II", header, entry + 128, new_start, new_length)
        header[entry + 140:entry + 176] = updated[16:36] + updated[32:36] + updated[40:52]
        target.write(updated)
        target.write(first)
        target.write(second)
        if gpu_raw:
            gpu_relocations[offset + gpu] = (new_start + new_gpu, len(second), gpu_raw, compressed)
        savings["resident"] += raw - len(first)
        savings["gpu"] += gpu_raw - len(second)
    require(source.tell() == before and not source.read(1), "Unexpected bytes after last RSG")
    size = target.tell()
    require(before - size == sum(savings.values()) > 0, "Resource saving does not match the pools")
    target.seek(0)
    target.write(header)
    target.seek(0)
    digest = hashlib.file_digest(target, "sha256").hexdigest()
    target.seek(0)
    return {"old_size": before, "size": size, "sha256": digest, "savings": savings,
            "groups": len(groups), "groups_compressed": compressed_count}, gpu_relocations


def reference_groups(path):
    """Only compact groups for which the reference uses the compressed layout."""
    result = {}
    with ZipFile(path) as archive:
        for name in BUNDLES:
            asset = archive.read("assets/pvz2tool/version/base/smf/" + name)
            structure = rsbtool.parse_head(asset)
            groups = rsbtool.read_rsgp_info(asset, structure["rsgpInfo_BeginOffset"],
                                          structure["rsgp_Number"], structure["rsgpInfo_EachLength"])
            result[name] = {group["ID"] for group in groups if group["fields"][3] == 3}
            require(result[name], "Reference has no compressed groups: " + name)
    return result


def resource_zip(base, scratch, path, group_selection):
    report, relocations = {}, {}
    with ZipFile(ResourceZip(base)) as original, ZipFile(path, "w", allowZip64=False) as rebuilt:
        for entry in original.infolist():
            name = entry.filename.removeprefix(PREFIX)
            if name not in BUNDLES:
                copy_compressed_entry(original, entry, rebuilt)
                continue
            with original.open(entry) as source, TemporaryFile(dir=scratch) as compact:
                result, relocations[name] = rewrite_bundle(source, compact, entry.file_size, group_selection[name])
                report[name] = result
                info = copy(entry)
                info.file_size = result["size"]
                info.compress_type = ZIP_STORED
                with rebuilt.open(info, "w") as output:
                    shutil.copyfileobj(compact, output, CHUNK)
                print(f'{name}: {result["old_size"]:,} -> {result["size"]:,} bytes', flush=True)
        require(report.keys() == BUNDLES, "The startup and UI bundles must all be present")
    with ZipFile(path) as rebuilt:
        total = sum(item.file_size for item in rebuilt.infolist())
        for name, result in report.items():
            with rebuilt.open(PREFIX + name) as source:
                require(hashlib.file_digest(source, "sha256").hexdigest() == result["sha256"],
                        "Compact archive member differs")
    return report, relocations, total


def relocate_index(index, target, report, relocations):
    row = re.compile(r'^(\s*\{"([^"]+)",)(\d+)ULL,(\d+)ULL,(\d+)U,(\d+)U,(\d+)U,(.*)$')
    counts = dict.fromkeys(BUNDLES, 0)
    lines = []
    for line in index.read_text(encoding="ascii").splitlines():
        match = row.fullmatch(line)
        if match and match[2] in BUNDLES:
            prefix, name, size, part, packed, raw, compressed, tail = match.groups()
            require(int(size) == report[name]["old_size"], "The old prefetch index has a different RSB size")
            new_part, new_packed, new_raw, new_compressed = relocations[name][int(part)]
            require(int(raw) == new_raw and packed == raw and compressed == "0",
                    "The prefetch source does not match the uncompressed pool")
            line = (f"{prefix}{report[name]['size']}ULL,{new_part}ULL,{new_packed}U,"
                    f"{new_raw}U,{int(new_compressed)}U,{tail}")
            counts[name] += 1
        lines.append(line)
    require(all(counts.values()), "At least one compact resource has no relocated prefetch entries")
    target.write_text("\n".join(lines) + "\n", encoding="ascii")
    return counts


def baseline(original, report):
    result = bytearray(original)
    count = struct.unpack_from(">H", result)[0]
    position = 2
    migrated = set()
    for _ in range(count):
        length = struct.unpack_from(">H", result, position)[0]
        position += 2
        name = result[position:position + length].decode("ascii")
        position += length
        if name in report:
            require(struct.unpack_from(">I", result, position)[0] == report[name]["old_size"],
                    "Previous installed resource size differs")
            struct.pack_into(">I", result, position, report[name]["size"])
            migrated.add(name)
        position += 4
    require(migrated == BUNDLES and position == len(result), "Unexpected resource migration table")
    return bytes(result)


def stream_reader(adapter, engine):
    require(hashlib.sha256(adapter).hexdigest() ==
            "20602bb39fa0938bc893ccb4dd41e6197635c846735865bd42309528fe268eb2",
            "Expected the isolated A199 reader")
    executable = ELFFile(BytesIO(engine))
    for address, signature in ((0x1455f70, "f04f2de920b08de21cd04de2003090e5"),
                               (0x11cb130, "18482de90040a0e10cb08de2040090e5")):
        expected = bytes.fromhex(signature)
        start = next(executable.address_offsets(address, len(expected)))
        require(engine[start:start + len(expected)] == expected, "Resource-stream engine entry differs")
    module = ELFFile(BytesIO(adapter))
    first = module.get_section_by_name(".init_array")["sh_offset"]
    trace = next(module.address_offsets(0xf356, 2))
    require(struct.unpack_from("<I", adapter, first)[0] == 0x66f9 and adapter[trace:trace + 2] == b"\xa8\xb1",
            "Resource-stream adapter has a different layout")
    data = bytearray(adapter)
    # The full resource-only initializer first installs the same reader,
    # then supplies the GPU decompression buffers before entering the engine.
    struct.pack_into("<I", data, first, 0xf0fd)
    # Keep the buffer setup, skip the reference's per-group descriptor logger.
    data[trace:trace + 2] = b"\x00\xbf"
    return bytes(data)


def nullable_tile_size(project):
    require(hashlib.sha256(project).hexdigest() ==
            "eb62a1a9828498b2ed028233d5efc3eb8e5cf2d4274b6e5da31dc92a73330dfd",
            "Expected the A201 game hook module")
    module = ELFFile(BytesIO(project))
    signature = bytes.fromhex("ca6822f00302a02a04bf10207047")
    hook = next(module.address_offsets(0xd880, len(signature)))
    require(project[hook:hook + len(signature)] == signature, "ASTC tile size hook differs")
    # GPU decompression requests a scratch tile with no texture descriptor.
    # CBZ passes this case to the original callback, which supplies a default.
    # Formats 160 through 163 still return 16; the fallback keeps its offset.
    replacement = bytes.fromhex("29b1ca689208282a01d110207047")
    return project[:hook] + replacement + project[hook + len(signature):]


def split_archive(path, out):
    length = path.stat().st_size
    part_size = (length + len(PARTS) - 1) // len(PARTS)
    result = {}
    with path.open("rb") as stream:
        for name in PARTS:
            part = out / Path(name).name
            with part.open("wb") as output:
                left = min(part_size, length - stream.tell())
                while left:
                    chunk = read_exact(stream, min(left, CHUNK))
                    output.write(chunk)
                    left -= len(chunk)
            result[name] = part
        require(stream.tell() == length, "Resource archive split lost bytes")
    path.unlink()
    return result


def build(args):
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(args.jdk / "bin") + os.pathsep + os.environ["PATH"]
    inner = out / "resources.zip"
    arm32 = args.base / "PvZ2-Unline-Aster-A201-ARM32.apk"
    report, relocations, total = resource_zip(arm32, out, inner, reference_groups(args.reference))
    index = out / "prefetch_index.inc"
    counts = relocate_index(args.index, index, report, relocations)
    shim_dir = out / "shim"
    subprocess.run([sys.executable, ROOT / "src/glshim/build.py",
                    "--ndk", args.ndk, "--astc", args.astc, "--output", shim_dir,
                    "--cache-root", "/data/data/com.pvz2unline.aster/cache", "--prefetch-index", index],
                   check=True)
    shim = (shim_dir / "libRestart.so").read_bytes()
    parts = split_archive(inner, out)
    for abi, folder, suffix in (("ARM32", "lib/armeabi", ""), ("ARM64", "assets/guest_libs", "_a32")):
        member = f"{folder}/libRestart{suffix}.so"
        reader = f"{folder}/libAsterRsg{suffix}.so"
        engine = f"{folder}/libSrc{suffix}.so"
        project = f"{folder}/libczProject{suffix}.so"
        source = args.base / f"PvZ2-Unline-Aster-A201-{abi}.apk"
        with ZipFile(source) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 202, 201, prefix="A")
            classes = rebuild_bootstrap(apk.read("classes8.dex"), out / ("boot-" + abi),
                                        {"0xa3aca280L": f"{total:#x}L",
                                         "2.6 GB": f"{total / 1e9:.1f} GB"},
                                        ROOT.parent / "tools/apktool.jar")
            sizes = baseline(apk.read(BASELINE), report)
            adapter = stream_reader(apk.read(reader), apk.read(engine))
            game_hooks = nullable_tile_size(apk.read(project))
        final = out / f"PvZ2-Unline-Aster-A202-{abi}.apk"
        pack_apk(source, {**parts, "AndroidManifest.xml": manifest, "classes8.dex": classes,
                          BASELINE: sizes, member: shim, reader: adapter, project: game_hooks},
                 args.sdk, final, args.signing)
        print(final, flush=True)
    for part in parts.values():
        part.unlink()
    (out / "resource-report.json").write_text(json.dumps(
        {"bundles": report, "prefetch_entries_relocated": counts, "unpacked_bytes": total}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "reference", "sdk", "ndk", "jdk", "astc", "index", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(parser.parse_args())
