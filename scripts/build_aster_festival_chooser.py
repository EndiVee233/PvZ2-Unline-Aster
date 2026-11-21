"""Build A236 with a mandatory Festival Endless seed chooser and checkpoint recovery."""
import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_hud_pickup import (
    ASSET, BOOTSTRAP, PLAN, Bundle, create_plan, rebuild_dynamic_bootstrap, replace_rton,
)
from build_aster_legacy_endless_gameplay import ACTIVITY_LEVEL
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_auto_pickup import patch_native


def require_seed_chooser(document):
    seed_bank, = (record["objdata"] for record in document["objects"]
                  if record["objclass"] == "SeedBankProperties" and record.get("aliases") == ["SeedBank"])
    assert seed_bank["SelectionMethod"] == "chooser" and seed_bank["AlwaysUseChooser"] is False
    seed_bank["AlwaysUseChooser"] = True


def build(base, stock, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A232-{abi}.apk" for abi in ("ARM32", "ARM64")}
    engines = {"ARM32": "lib/armeabi/libSrc.so", "ARM64": "assets/guest_libs/libSrc_a32.so"}
    with ZipFile(stock / "PvZ2-Unline-Aster-A227-ARM32.apk") as apk:
        engine = patch_native(apk.read(engines["ARM32"]), ndk, output / "native",
                              world_resources=True, mount_campaign=True, guard_chooser_resume=True)
    with ZipFile(sources["ARM32"]) as apk:
        previous = apk.read(ASSET)
    bundle = Bundle(previous)
    replace_rton(bundle, ACTIVITY_LEVEL, require_seed_chooser)
    updated = bundle.build()
    plan = create_plan(updated, output)
    for abi, source in sources.items():
        with ZipFile(source) as apk:
            assert apk.read(ASSET) == previous
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 236, 232, prefix="A")
            dex = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / f"bootstrap-{abi}", previous, updated)
        changes = {ASSET: updated, PLAN: plan, "AndroidManifest.xml": manifest, BOOTSTRAP: dex, engines[abi]: engine}
        final = output / f"PvZ2-Unline-Aster-A236-{abi}.apk"
        pack_apk(source, changes, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "stock", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
