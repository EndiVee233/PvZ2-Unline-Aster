"""Build A335 with the multi-star ribbon fix and the A334 sign-in renderer."""

import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_sign_in_plant_art import A333_ENGINE
from build_aster_star_difficulty import ENGINE, patch_guest
from prepare_aster_adventure_levels import make_catalog, write_packet_anchors, write_user_plants


A334_ENGINE = "ed20efee9788c69932005140067f74e39321e50da7acdfd9ef7ec49c0d0089b2"


def preserve_sign_in(rebuilt, original, installed):
    if (len(original) != len(installed) or sha256(original).hexdigest() != A333_ENGINE
            or sha256(installed).hexdigest() != A334_ENGINE):
        raise ValueError("Expected matching A333 and A334 ARM32 engines")
    result = bytearray(rebuilt)
    for offset, (old, current) in enumerate(zip(original, installed)):
        if old != current:
            if offset >= len(result) or result[offset] != old:
                raise ValueError(f"Ribbon and sign-in patches overlap at {offset:#x}")
            result[offset] = current
    return bytes(result)


def build(base, previous, installed, stock, prior, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    make_catalog(stock, output)
    write_packet_anchors(stock, output)
    write_user_plants(base, output)
    with ZipFile(base) as a332, ZipFile(previous) as a333, ZipFile(installed) as a334:
        engine = patch_guest(a332.read(ENGINE), ndk, output, prior)
        engine = preserve_sign_in(engine, a333.read(ENGINE), a334.read(ENGINE))
        manifest = manifest_version(a334.read("AndroidManifest.xml"), 335, 334, prefix="A")
    result = output / "PvZ2-Unline-Aster-A335-ARM32-WSA-existing-data.apk"
    pack_apk(installed, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "previous", "installed", "stock", "prior", "output", "sdk", "ndk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
