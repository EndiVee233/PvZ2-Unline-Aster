"""Package the A327 player export and friend sync changes over A326 ARM32."""
import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from build_aster_adventure_records import social_dex
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version


SOCIAL_DEX = "classes8.dex"
A326_SOCIAL_DEX = "cf09c2e7066e8c1af60a6c28f3238d524ab31b8c45b1f19520ea0b562ff26427"


def build(base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        if sha256(apk.read(SOCIAL_DEX)).hexdigest() != A326_SOCIAL_DEX:
            raise ValueError("Expected the A326 social DEX in classes8.dex")
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 327, 326, prefix="A")
    dex = social_dex(output / "social-dex", sdk)
    result = output / "PvZ2-Unline-Aster-A327-ARM32-WSA-existing-data.apk"
    pack_apk(base, {SOCIAL_DEX: dex, "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
