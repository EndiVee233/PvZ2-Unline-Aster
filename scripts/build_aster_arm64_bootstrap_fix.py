"""Package A529 with the rebuilt ARM64 bridge and the A528 game fixes."""

import argparse
from io import BytesIO
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_STORED, ZipFile

from elftools.elf.elffile import ELFFile

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version


ENGINE = "lib/armeabi/libSrc.so"
ARM64_ENGINE = "assets/guest_libs/libSrc_a32.so"
ARM64_HOST = "lib/arm64-v8a/libSrc.so"
MANIFEST = "AndroidManifest.xml"
WORLD_ARCHIVE = "assets/reconstruction/mausoleum.rsb.smf"


def verify_guest_layout(apk, images, replacements):
    entries = re.findall(
        r'\{"[^"]+", "(guest_libs/[^"]+)", (0x[0-9a-f]+), (0x[0-9a-f]+)\}',
        images.read_text(encoding="utf8"),
    )
    members = {"assets/" + asset for asset, _, _ in entries}
    if not entries or members != {name for name in apk.namelist() if name.startswith("assets/guest_libs/")}:
        raise ValueError("ARM64 bridge guest list differs from the packaged assets")
    previous_limit = 0
    for asset, base_text, limit_text in entries:
        member = "assets/" + asset
        base, limit = int(base_text, 16), int(limit_text, 16)
        if not previous_limit <= base < limit or apk.getinfo(member).compress_type != ZIP_STORED:
            raise ValueError(f"Invalid reservation or compressed guest asset: {member}")
        previous_limit = limit
        engine = replacements[member] if member in replacements else apk.read(member)
        elf = ELFFile(BytesIO(engine))
        segments = [segment for segment in elf.iter_segments() if segment["p_type"] == "PT_LOAD"]
        end = base + max(segment["p_vaddr"] + segment["p_memsz"] for segment in segments)
        if end > limit:
            raise ValueError(f"{member} maps through 0x{end:08x}, beyond 0x{limit:08x}")
        print(f"{member}: 0x{base:08x} to 0x{end:08x}, limit 0x{limit:08x}", flush=True)


def build(accepted, previous_arm64, native, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sdk / "cmake/3.22.1/bin/cmake.exe", "--build", native, "--parallel", "6"], check=True)
    strip = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe"
    host = output / "arm64-host.so"
    subprocess.run([strip, "--strip-debug", "-o", host, native / "a7/libSrc.so"], check=True)
    with ZipFile(accepted) as arm32, ZipFile(previous_arm64) as arm64:
        manifest32 = manifest_version(arm32.read(MANIFEST), 529, 528, prefix="A")
        updates = {
            ARM64_HOST: host.read_bytes(),
            ARM64_ENGINE: arm32.read(ENGINE),
            WORLD_ARCHIVE: arm32.read(WORLD_ARCHIVE),
            WORLD_ARCHIVE + ".spec": arm32.read(WORLD_ARCHIVE + ".spec"),
            MANIFEST: manifest_version(arm64.read(MANIFEST), 529, 525, prefix="A"),
        }
        verify_guest_layout(arm64, native / "aster_images.inc", updates)

    package64 = output / "PvZ2-Unline-Aster-A529-ARM64.apk"
    pack_apk(previous_arm64, updates, sdk, package64, signing)
    print(package64, flush=True)
    package32 = output / "PvZ2-Unline-Aster-A529-ARM32.apk"
    pack_apk(accepted, {MANIFEST: manifest32}, sdk, package32, signing)
    print(package32, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("accepted", "previous-arm64", "native", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
