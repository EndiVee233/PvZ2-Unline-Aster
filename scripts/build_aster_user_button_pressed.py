"""Package the User button pressed-state art and fixed bounds over Aster A347."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from PIL import Image

from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, create_plan, rebuild_dynamic_bootstrap
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_aster_social_art import USER_BUTTON_PRESSED, edit_social_atlas


A347_ENGINE = "9b79fb26b498bb10fc9dec5559aba97cf01c8d0296dbfeefefce5f8395c48297"
USER_PRESSED_INSET = 0x1C782E8


def patch_guest(engine):
    if sha256(engine).hexdigest() != A347_ENGINE:
        raise ValueError("Expected the A347 shared guest")
    offset = file_offset(ELFFile(BytesIO(engine)), USER_PRESSED_INSET, 4)
    # asterUserDraw already computed height / 10. Remove the conditional
    # addition of height / 40 and retain the following pressed-texture selection.
    if engine[offset:offset + 4] != bytes.fromhex("ac328310"):  # addne r3,r3,r12,lsr #5
        raise ValueError("Unexpected User button pressed inset instruction")
    return engine[:offset] + bytes.fromhex("0330a0e1") + engine[offset + 4:]  # mov r3,r3


def build(base, output, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk, Image.open(USER_BUTTON_PRESSED) as pressed:
        manifest = manifest_version(apk.read(MANIFEST), 349, 347, prefix="A")
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        guest = patch_guest(apk.read(engine))
        original = apk.read(ASSET)
        updated = edit_social_atlas(original, {}, replacements={"USER_BUTTON_DOWN": pressed})
        plan = create_plan(updated, output.parent, rgba_atlases=1)
        bootstrap = rebuild_dynamic_bootstrap(
            apk.read(BOOTSTRAP), output.parent / "bootstrap", original, updated
        )
    pack_apk(base, {MANIFEST: manifest, ASSET: updated, PLAN: plan, BOOTSTRAP: bootstrap, engine: guest},
             sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
