"""Build the isolated resource-group reader on the A198 release candidates."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_STORED

from elftools.elf.elffile import ELFFile
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_CZ_SHA = "3c3ea7b1f0c5ddb124200ed60a39d426867ce4a7b89a567cb1db185fae49680c"
ENGINE_SHA = "1443c8421ab9c8b795fb513e16019613af270a6b1aca176d3e8e4a3d8d2d6f74"
# The donor's installer checks this entry and the three GPU length instructions.
RESOURCE_SITES = {
    0x11CAD54: bytes.fromhex("f04f2de920b08de21cd04de20040a0e1"),
    0x11CB02C: bytes.fromhex("000053e3"),
    0x11CB248: bytes.fromhex("000053e3"),
    0x11CB290: bytes.fromhex("000052e3"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reader(donor, engine):
    require(hashlib.sha256(donor).hexdigest() == ARCHIVE_CZ_SHA, "Unexpected reference libczProject")
    require(hashlib.sha256(engine).hexdigest() == ENGINE_SHA, "Expected the A198 ARM32 engine")
    engine_elf = ELFFile(io.BytesIO(engine))
    for address, expected in RESOURCE_SITES.items():
        offset = next(engine_elf.address_offsets(address, len(expected)))
        require(engine[offset:offset + len(expected)] == expected, f"Engine signature mismatch at {address:#x}")
    result = bytearray(donor)
    elf = ELFFile(io.BytesIO(donor))
    initializers = elf.get_section_by_name(".init_array")
    require(initializers.data() == bytes.fromhex("f9790000e96400000d650000496500005965000000000000"),
            "Unexpected constructor layout")
    # Replace the general game-hook installer with just the resource installer.
    # The other initializers set up the library's own C++ and thread-local state.
    struct.pack_into("<I", result, initializers["sh_offset"], 0x66F9)
    strings = elf.get_section_by_name(".dynstr")
    soname = next(elf.get_section_by_name(".dynamic").iter_tags("DT_SONAME"))
    offset = strings["sh_offset"] + soname["d_val"]
    prior = b"libczProject.so\0"
    require(result[offset:offset + len(prior)] == prior, "Unexpected SONAME")
    result[offset:offset + len(prior)] = b"libAsterRsg.so".ljust(len(prior), b"\0")
    symbols = elf.get_section_by_name(".dynsym")
    for index, symbol in enumerate(symbols.iter_symbols()):
        if symbol.name and symbol["st_shndx"] != "SHN_UNDEF":
            # Keep self-relocations by symbol number. The reader has no public ABI.
            offset = symbols["sh_offset"] + index * symbols["sh_entsize"] + 13
            result[offset] = (result[offset] & ~3) | 2   # STV_HIDDEN
    return bytes(result)


def bootstrap(original, out, jdk, apktool):
    javac, java = [jdk / "bin" / name for name in ("javac.exe", "java.exe")]
    subprocess.run([javac, "-cp", apktool, "-d", out, ROOT / "scripts/RepairDex.java"], check=True)
    repair = [java, "-Xmx384m", "-cp", str(apktool) + os.pathsep + str(out), "RepairDex"]
    input_dex, result = out / "original.dex", out / "patched.dex"
    input_dex.write_bytes(original)
    tree = out / "smali"
    subprocess.run([*repair, "decode", input_dex, tree], check=True)
    worker = tree / "com/popcap/pvz2cthd/AsterNativeWarmup$1.smali"
    old = worker.read_text(encoding="utf8")
    count = 'const/4 v1, 0x4\n\n    :try_start_3\n    new-array'
    last = 'const-string v3, "Restart"\n\n    const/4 v5, 0x3\n\n    aput-object v3, v2, v5'
    require(old.count(count) == old.count(last) == 1, "Unexpected A198 native load sequence")
    new = old.replace(count, count.replace("0x4", "0x5")).replace(last, last + '''

    const-string v3, "AsterRsg"

    const/4 v5, 0x4

    aput-object v3, v2, v5''')
    worker.write_text(new, encoding="utf8")
    subprocess.run([*repair, "encode", tree, result], check=True)
    return result.read_bytes()


def build(args):
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(args.jdk / "bin") + os.pathsep + os.environ["PATH"]
    with ZipFile(args.donor) as donor:
        cz = donor.read("lib/libczProject.so")
    with ZipFile(args.arm32) as arm32:
        adapter = reader(cz, arm32.read("lib/armeabi/libSrc.so"))
    (args.output / "libAsterRsg.so").write_bytes(adapter)
    for architecture, source, entry in (
            ("ARM32", args.arm32, "lib/armeabi/libAsterRsg.so"),
            ("ARM64", args.arm64, "assets/guest_libs/libAsterRsg_a32.so")):
        with ZipFile(source) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 199, 198, prefix="A")
            changes = {"AndroidManifest.xml": manifest}
            if architecture == "ARM32":
                with TemporaryDirectory(dir=args.output) as temp:
                    changes["classes8.dex"] = bootstrap(apk.read("classes8.dex"), Path(temp), args.jdk, args.apktool)
            else:
                require(hashlib.sha256(apk.read("assets/guest_libs/libSrc_a32.so")).hexdigest() == ENGINE_SHA,
                        "ARM64 guest must use the same A198 engine")
                host = args.host.read_bytes()
                require(host[:5] == b"\x7fELF\x02" and b"guest_libs/libAsterRsg_a32.so\0" in host,
                        "ARM64 host needs ASTER_RESIDENT_EXPERIMENT=ON")
                changes["lib/arm64-v8a/libSrc.so"] = host
        final = args.output / f"PvZ2-Unline-Aster-A199-{architecture}.apk"
        pack_apk(source, changes, args.sdk, final, args.signing, extra_entries={entry: adapter})
        with ZipFile(final) as apk:
            require(apk.getinfo(entry).compress_type == ZIP_STORED, "Resource reader must be an uncompressed APK entry")
        with final.open("rb") as fp:
            print(final, hashlib.file_digest(fp, "sha256").hexdigest(), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("donor", "arm32", "arm64", "host", "sdk", "jdk", "signing", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--apktool", type=Path, default=ROOT.parent / "tools/apktool.jar")
    build(parser.parse_args())
