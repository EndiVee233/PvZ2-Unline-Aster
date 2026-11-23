"""Update the A313 ARM32 calendar using Aster's existing reward card art."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_auto_pickup import patch_native


ENGINE = "lib/armeabi/libSrc.so"
A313_ENGINE = "9b7e4d446ee16a21d555b0533eaf2bf2f4376a8cce7a8bd3dc4993ec4f7ad498"


def build(base, sdk, ndk, output, sign_in_report, signing):
    with ZipFile(base) as apk:
        engine = apk.read(ENGINE)
        manifest = apk.read("AndroidManifest.xml")
    if sha256(engine).hexdigest() != A313_ENGINE:
        raise ValueError("Expected the A313 ARM32 guest")
    hooks = {int(site): address for site, address in json.loads(sign_in_report.read_text())["hooks"].items()}
    engine = patch_native(engine, ndk, output, offline_sign_in=True, refresh_sign_in=True,
                          sign_in_hooks=hooks, four_column_sign_in=True)
    (output / "libSrc.so").write_bytes(engine)
    if signing:
        manifest = manifest_version(manifest, 314, 313, prefix="A")
        apk = output / "PvZ2-Unline-Aster-A314-ARM32-WSA-existing-data.apk"
        pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, apk, signing)
        print(apk)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "sdk", "ndk", "output", "sign-in-report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--signing", type=Path)
    build(**vars(parser.parse_args()))
