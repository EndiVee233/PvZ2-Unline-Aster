"""Build A230 from the A228 resource set and the A229 native update."""
import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, Bundle, create_plan, rebuild_dynamic_bootstrap, replace_rton
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version


def fix_freeze_effects(document):
    # Native chilling/freezing looks up POPANIM_EFFECTS_FROSTBITE_CHILL_PLANT.
    # PlantAudioGroups is also the stock dependency list for effects such as GoldTileModule.
    corrected = set()
    for record in document["objects"]:
        groups = record.get("objdata", {}).get("PlantAudioGroups", [])
        if "FreezonEffectGroup" not in groups:
            continue
        assert "FrostbiteIceBlockPlantGroup" not in groups
        groups[groups.index("FreezonEffectGroup")] = "FrostbiteIceBlockPlantGroup"
        corrected.update(record["aliases"])
    assert corrected == {"iceburg", "wintermelon", "iceshroom", "cottonyeti"}


def fix_duplicate_endless(document):
    widgets = document["objects"]
    duplicate, = (r for r in widgets if r.get("aliases") == ["UIWorldMapRechargeGiftButton"])
    active, = (r for r in widgets if r.get("aliases") == ["UIWorldMapDailyAchievementButton"])
    for widget in (duplicate, active):
        assert widget["objdata"]["Class"] == "WorldMap_BossFightButton"
        assert widget["objdata"]["PositionOffset"]["y"] == -150
    # Map initialization resolves this alias before it checks visibility.
    # Restore the reference layout's hidden recharge widget and keep the
    # real Endless button on the right side of the map.
    duplicate["objdata"].update(
        Class="WorldMap_RechargeGiftButton",
        SizeFromImage="IMAGE_UI_HUD_WORLDMAP_RECHARGEGIFT",
        ParentAnchor="BottomLeft",
        Anchor="BottomLeft",
        PositionOffset={"x": -999, "y": -230},
    )


def build(base, previous, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: previous / f"PvZ2-Unline-Aster-A229-{abi}.apk" for abi in ("ARM32", "ARM64")}
    with ZipFile(sources["ARM32"]) as apk:
        prior = apk.read(ASSET)
    with ZipFile(base / "PvZ2-Unline-Aster-A228-ARM32.apk") as apk:
        bundle = Bundle(apk.read(ASSET))
    replace_rton(bundle, r"PACKAGES\PLANTTYPES.RTON", fix_freeze_effects, allow_growth=True)
    replace_rton(bundle, r"PACKAGES\UI_IPHONE.RTON", fix_duplicate_endless, allow_growth=True)
    dynamic = bundle.build()
    plan = create_plan(dynamic, output)
    for abi, source in sources.items():
        with ZipFile(source) as apk:
            assert apk.read(ASSET) == prior
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 230, 229, prefix="A")
            boot = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / f"bootstrap-{abi}", prior, dynamic)
        final = output / f"PvZ2-Unline-Aster-A230-{abi}.apk"
        pack_apk(source, {ASSET: dynamic, PLAN: plan, BOOTSTRAP: boot, "AndroidManifest.xml": manifest},
                 sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "previous", "output", "sdk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
