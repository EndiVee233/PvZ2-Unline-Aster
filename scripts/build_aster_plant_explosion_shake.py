"""Use the Dark Ages Zomboss landing shake for plant explosions."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


ENGINE = "lib/armeabi/libSrc.so"
BASE_ENGINE = "9413a716cbb722f1946968b8f651b33d32147acab59727436cfe9125a53e7d52"
SHAKE_BOARD = 0x207BDC
PLANT_EXPLOSIONS = (
    (0x54524C, 0xE3A03000),  # Cherry Bomb
    (0x545D80, 0xE1A03009),  # Small Cherry
    (0x54F56C, 0xE1A0300A),  # E.M.Peach
    (0x56C6B8, 0xE1A03009),  # Potato Mine
    (0x58BD70, 0xE1A0300A),  # Explode-o-nut
)


def patch_engine(engine):
    if sha256(engine).hexdigest() != BASE_ENGINE:
        raise ValueError("Expected the A331 ARM32 guest engine")
    elf = ELFFile(BytesIO(engine))
    patched = bytearray(engine)
    for site, duration_word in PLANT_EXPLOSIONS:
        start = file_offset(elf, site - 16)
        original = struct.pack("<4I", duration_word, 0xE3A01003, 0xE59206BC, 0xE3E02003)
        if (engine[start:start + 16] != original
                or engine[start + 16:start + 20] != branch(site, SHAKE_BOARD, True)):
            raise ValueError(f"Unexpected plant shake call at {site:#x}")
        # Keep the board and stock ShakeBoard call. The Dark Ages landing event
        # passes X=5 and Y=-5 for 0.2 seconds. Use a 1/16-second pulse here.
        struct.pack_into("<4I", patched, start, 0xE3A035F6, 0xE3A01005, 0xE59206BC, 0xE3E02004)
    return bytes(patched)


def build(base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        native = patch_engine(apk.read(ENGINE))
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 332, 331, prefix="A")
    result = output / "PvZ2-Unline-Aster-A332-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: native, "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
