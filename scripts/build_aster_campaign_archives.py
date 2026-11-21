"""Build A232 with campaign archive loading and the original freeze dependency."""
import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_hud_pickup import (
    ASSET, BOOTSTRAP, PLAN, Bundle, create_plan, rebuild_dynamic_bootstrap, replace_rton,
)
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_auto_pickup import patch_native


def restore_freeze_group(document):
    corrected = set()
    for record in document["objects"]:
        groups = record.get("objdata", {}).get("PlantAudioGroups", [])
        if "FrostbiteIceBlockPlantGroup" in groups:
            groups[groups.index("FrostbiteIceBlockPlantGroup")] = "FreezonEffectGroup"
            corrected.update(record["aliases"])
    assert corrected == {"iceburg", "wintermelon", "iceshroom", "cottonyeti"}


def build(stock, base, previous, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    engines = {"ARM32": "lib/armeabi/libSrc.so", "ARM64": "assets/guest_libs/libSrc_a32.so"}
    with ZipFile(stock / "PvZ2-Unline-Aster-A227-ARM32.apk") as apk:
        engine = patch_native(apk.read(engines["ARM32"]), ndk, output / "native", world_resources=True,
                              mount_campaign=True)
    with ZipFile(base / "PvZ2-Unline-Aster-A230-ARM32.apk") as apk:
        baseline = apk.read(ASSET)
    with ZipFile(previous / "PvZ2-Unline-Aster-A231-ARM32.apk") as apk:
        prior = apk.read(ASSET)
    dynamic = Bundle(baseline)
    replace_rton(dynamic, r"PACKAGES\PLANTTYPES.RTON", restore_freeze_group, allow_growth=True)
    updated = dynamic.build()
    plan = create_plan(updated, output)
    for abi in engines:
        base_apk = base / f"PvZ2-Unline-Aster-A230-{abi}.apk"
        with ZipFile(base_apk) as apk:
            assert apk.read(ASSET) == baseline
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 232, 230, prefix="A")
        with ZipFile(previous / f"PvZ2-Unline-Aster-A231-{abi}.apk") as apk:
            assert apk.read(ASSET) == prior
            dex = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / f"bootstrap-{abi}", prior, updated)
        changes = {ASSET: updated, PLAN: plan, engines[abi]: engine,
                   "AndroidManifest.xml": manifest, BOOTSTRAP: dex}
        final = output / f"PvZ2-Unline-Aster-A232-{abi}.apk"
        pack_apk(base_apk, changes, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("stock", "base", "previous", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
