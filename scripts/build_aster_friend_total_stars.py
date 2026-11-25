"""Build A354 with total stars on the Friends roster and in player exports."""

import argparse
from hashlib import sha256
from pathlib import Path
from shutil import copyfile
from zipfile import ZipFile

from build_aster_adventure_records import social_dex
from build_aster_borrow_limit import HEADERS
from build_aster_borrow_preview import replace_adventure_payload
from build_aster_player_filenames import SOCIAL_DEX
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version


A352_ENGINE = "e11c1e9c6b2586d7a271df71f5f0301cadb09f1a47f7c5584267e44f2d9d5e74"
A352_SOCIAL_DEX = "1cf2dcdf94bc80aa439a3fcd513e91c68e7a6daa09fbf27b71672b5b75a79d4f"


def build(base, prior, output, ndk, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in HEADERS:
        copyfile(prior.parent / name, output.parent / name)
    with ZipFile(base) as apk:
        guest = apk.read(ENGINE)
        if (sha256(guest).hexdigest() != A352_ENGINE
                or sha256(apk.read(SOCIAL_DEX)).hexdigest() != A352_SOCIAL_DEX):
            raise ValueError("Expected the A352 ARM32 engine and social DEX")
        manifest = manifest_version(apk.read(MANIFEST), 354, 352, prefix="A")

    # A345 owns the social frame. The separate A350 map button hooks stay in place.
    guest = replace_adventure_payload(guest, ndk, output.parent, prior,
                                      names={"asterAdventureSocialFrame"})
    dex = social_dex(output.parent / "social-dex", sdk)
    pack_apk(base, {ENGINE: guest, SOCIAL_DEX: dex, MANIFEST: manifest}, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "prior", "output", "ndk", "sdk", "signing"):
        parser.add_argument("--" + name, required=True, type=Path)
    build(**vars(parser.parse_args()))
