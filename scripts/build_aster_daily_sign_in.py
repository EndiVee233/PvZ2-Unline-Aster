"""Restore the original sign-in screen with a local Aster calendar."""
import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from build_aster_hud_pickup import (
    ASSET, BOOTSTRAP, PLAN, Bundle, create_plan, rebuild_dynamic_bootstrap, replace_rton,
)
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_auto_pickup import patch_native


LAYOUTS = ("UI_IPHONE", "UI_IPHONE5", "UI_IPHONESTRETCH")
SIGN_ICON = "IMAGE_UI_HUD_WORLDMAP_DAILY_SIGN_REWARD"
A227_ENGINE = "3c75aed0a739086093b8d4bff607a9a96e90b8fea75b72d82fdf3c52f279c112"


def restore_map_entry(document):
    entry, = (record["objdata"] for record in document["objects"]
              if record.get("aliases") == ["UIWorldMapLoginRewardButton"])
    back, = (record["objdata"] for record in document["objects"]
             if record.get("aliases") == ["UIWorldMapBackButton"])
    if entry["Class"] not in ("WorldMap_LotteryButton", "WorldMap_BossFightButton",
                             "WorldMap_LoginRewardButton"):
        raise ValueError("Unexpected original daily sign-in widget")
    # Both sprites are the same height. Keep them on the same top-bar row.
    # The return arrow is 152 atlas pixels wide (61 UI units) with a 9-unit gap.
    position = back["PositionOffset"]
    entry.update(
        Class="WorldMap_LoginRewardButton",
        SizeFromImage=SIGN_ICON,
        Parent=back["Parent"],
        ParentAnchor=back["ParentAnchor"],
        Anchor=back["Anchor"],
        PositionOffset={"x": position["x"] + 70, "y": position["y"]},
        ScalePositionOffset=back["ScalePositionOffset"],
    )


def patch_resources(previous):
    bundle = Bundle(previous)
    for layout in LAYOUTS:
        replace_rton(bundle, f"PACKAGES\\{layout}.RTON", restore_map_entry, allow_growth=True)
    return bundle.build()


def build(base, stock, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A236-{abi}.apk" for abi in ("ARM32", "ARM64")}
    engines = {"ARM32": "lib/armeabi/libSrc.so", "ARM64": "assets/guest_libs/libSrc_a32.so"}
    with ZipFile(stock / "PvZ2-Unline-Aster-A227-ARM32.apk") as apk:
        engine = apk.read(engines["ARM32"])
    if sha256(engine).hexdigest() != A227_ENGINE:
        raise ValueError("Unexpected A227 guest engine")
    engine = patch_native(engine, ndk, output / "native", world_resources=True,
                          mount_campaign=True, guard_chooser_resume=True, offline_sign_in=True)
    with ZipFile(sources["ARM32"]) as apk:
        previous = apk.read(ASSET)
    updated = patch_resources(previous)
    plan = create_plan(updated, output)
    for abi, source in sources.items():
        with ZipFile(source) as apk:
            assert apk.read(ASSET) == previous
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 243, 236, prefix="A")
            dex = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / f"bootstrap-{abi}", previous, updated)
        changes = {ASSET: updated, PLAN: plan, "AndroidManifest.xml": manifest, BOOTSTRAP: dex, engines[abi]: engine}
        final = output / f"PvZ2-Unline-Aster-A243-{abi}.apk"
        pack_apk(source, changes, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "stock", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
