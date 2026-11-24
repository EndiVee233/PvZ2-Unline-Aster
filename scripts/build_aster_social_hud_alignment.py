"""Build A350 with the aligned User and Friends buttons over A349."""

import argparse
from hashlib import sha256
from pathlib import Path
from shutil import copyfile
from zipfile import ZipFile

from build_aster_borrow_limit import HEADERS
from build_aster_borrow_preview import replace_adventure_payload
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version


A349_ENGINE = "23b39ea09a4240ef36c587c34708a6dd48d3b22d75b9fe88d86e72fbfd665d44"
MAP_HOOKS = {"asterUserDraw", "asterUserHit", "asterUserTouch"}


def build(base, prior, output, ndk, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in HEADERS:
        copyfile(prior.parent / name, output.parent / name)
    with ZipFile(base) as apk:
        manifest = manifest_version(apk.read(MANIFEST), 350, 349, prefix="A")
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        guest = apk.read(engine)
        if sha256(guest).hexdigest() != A349_ENGINE:
            raise ValueError("Expected the A349 shared guest")
    updated = replace_adventure_payload(guest, ndk, output.parent, prior, names=MAP_HOOKS)
    pack_apk(base, {engine: updated, MANIFEST: manifest}, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "prior", "output", "ndk", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
