"""Build A346 with high view fixed and no view-angle settings row."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile

from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset


A345_ENGINE = "09968e4ca632648de82dddfdab956c277eba300d58922851a92026535cd4b572"
RETURN = "1eff2fe1"  # bx lr
RETURN_UNHANDLED = "0000a0e3" + RETURN  # mov r0,#0; bx lr

# These are the original A184 view helpers still called by A345. The
# outer settings hooks also dispatch automatic pickup, social settings
# and difficulty, so each view helper returns through its existing chain.
VIEW_PATCHES = (
    ("asterViewSettingsReady", 0x1A2CA20, "f04b2de9", RETURN),
    ("load saved view", 0x1A2CB08, "f04d2de9", RETURN),
    ("asterViewClick", 0x1A2CC34, "f04b2de918b08de2", RETURN_UNHANDLED),
    ("asterViewTitle", 0x1A2CE3C, "f0482de910b08de2", RETURN_UNHANDLED),
    ("asterViewRows", 0x1A2CEEC, "f04f2de91cb08de2", RETURN_UNHANDLED),
)


def patch_guest(engine):
    if sha256(engine).hexdigest() != A345_ENGINE:
        raise ValueError("Expected the A345 shared guest")
    elf = ELFFile(BytesIO(engine))
    # The legacy flag defaults to high. The disabled load and click
    # helpers were its only writers. Preserve the stock high-view paths.
    flag = file_offset(elf, 0x1B02004)
    if engine[flag] != 0:
        raise ValueError("A345 does not start in high view")

    result = bytearray(engine)
    for name, address, old_hex, new_hex in VIEW_PATCHES:
        old, new = bytes.fromhex(old_hex), bytes.fromhex(new_hex)
        offset = file_offset(elf, address, len(old))
        if engine[offset:offset + len(old)] != old:
            raise ValueError(f"Unexpected instructions for {name} at {address:#x}")
        result[offset:offset + len(new)] = new
    return bytes(result)


def build(base, output, sdk, signing, installed_resources=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_guest(apk.read(engine)),
            MANIFEST: manifest_version(apk.read(MANIFEST), 346, 345, prefix="A"),
        }
    pack_apk(base, updates, sdk, output, signing,
             excluded=RESOURCE_PARTS if installed_resources else ())
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--installed-resources", action="store_true")
    build(**vars(parser.parse_args()))
