"""Build A343 with a compact, left-aligned plant upgrade skill row."""

import argparse
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile

from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS
from build_aster_resource_lifetime_fix import retain_group_for_reads
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


SKILL_LAYOUT = 0x81A864
SCALE_COMPACT_GAP = 0x81ADF4
ARM_NOP = bytes.fromhex("00f020e3")


def patch_engine(engine):
    # Build on the A342 resource lifetime fix and its verified A341 input.
    fixed = retain_group_for_reads(engine)
    elf = ELFFile(BytesIO(fixed))
    result = bytearray(fixed)

    # The 1.7.5 layout anchors the first skill at x=335 and uses a six-unit
    # gap when fragments are insufficient. Use that same gap in every state
    # to leave room for the upgrade button at its existing position.
    # r8 still holds the UI scale at the point where stock selects a gap.
    changes = (
        (SKILL_LAYOUT, "000057e3", bytes.fromhex("0800a0e1")),  # mov r0, r8
        (SKILL_LAYOUT + 4, "4b01001a", branch(SKILL_LAYOUT + 4, SCALE_COMPACT_GAP)),
        # Preserve the already scaled integer gap in the shared stack slot.
        (0x81AA70, "6a1037eb", ARM_NOP),
        # Each remaining skill adds its index times (image width + gap).
        # The stock conversion and multiplication here scaled the gap again.
        (0x81AA88, "8f1037eb", ARM_NOP),
        (0x81AA8C, "991137eb", ARM_NOP),
        (0x81AC1C, "2a1037eb", ARM_NOP),
        (0x81AC20, "341137eb", ARM_NOP),
        (0x81ACA0, "091037eb", ARM_NOP),
        (0x81ACA4, "131137eb", ARM_NOP),
    )
    for address, expected_hex, replacement in changes:
        offset = file_offset(elf, address)
        if result[offset:offset + 4] != bytes.fromhex(expected_hex):
            raise ValueError(f"Unexpected skill layout instruction at {address:#x}")
        result[offset:offset + 4] = replacement
    return bytes(result)


def build(base, output, sdk, signing, installed_resources=False):
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_engine(apk.read(engine)),
            MANIFEST: manifest_version(apk.read(MANIFEST), 343, 341, prefix="A"),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    pack_apk(base, updates, sdk, output, signing,
             excluded=RESOURCE_PARTS if installed_resources else ())
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--installed-resources", action="store_true")
    build(**vars(parser.parse_args()))
