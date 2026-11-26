"""Build the ARM32 test encounter for all four Zoybean Pod ranks."""

import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_mausoleum_battle import LEVEL_MODULES, clone_definition
from build_aster_qin_almanac import register_zombie_card_types
from build_aster_qin_zoybean import (
    ASSET, BOOTSTRAP, ENGINE, GATLING_ANIMATION, MANIFEST, PLAN, PLANT, PLANT_SHEET, SHEET_PACKAGE, TEST_LEVEL,
    TYPE_PACKAGE,
    Bundle, PamIndex, build_guest, create_plan, edit_animation, level_document, manifest_group,
    manifest_version, pack_apk, package_data, prepare_bank, prepare_moton_bank, rebuild_dynamic_bootstrap,
    replace_rton, replace_section, resource, unwrap, use_native_boost,
)


TARGET = "zoybean_showcase_target"


def showcase(document):
    definition, = (row["objdata"] for row in document["objects"] if row["objclass"] == "LevelDefinition")
    definition["Modules"].append("RTID(ZoybeanRankPlacements@CurrentLevel)")
    document["objects"].append({
        "objclass": "InitialPlantEntryProperties", "aliases": ["ZoybeanRankPlacements"],
        "objdata": {"Plants": [{"GridX": 0, "GridY": row, "PlantTypes": [PLANT]} for row in range(4)]},
    })
    waves, = (row["objdata"] for row in document["objects"] if "Waves" in row.get("aliases", ()))
    target = {"Type": f"RTID({TARGET}@ZombieTypes)"}
    waves.update(WaveCount=1, FlagWaveInterval=2, AddToZombiePool=[target], Waves=[{
        "DisableRandomSpawns": True, "WaitUntilAllZombiesDie": True,
        "Zombies": [{**target, "Row": str(row), "Level": 1, "Rise_GridX": 8, "Rise_GridY": row - 1}
                    for row in range(1, 5)],
    }])


def build(args):
    work = args.output.parent
    work.mkdir(parents=True, exist_ok=True)
    moton = prepare_moton_bank(args.moton_bank.read_bytes())
    with ZipFile(args.donor) as donor:
        source = Bundle(unwrap(donor.read("assets/dynamic.rsb.smf")))
        module_rows = level_document(resource(source, LEVEL_MODULES), LEVEL_MODULES)["objects"]
        by_alias = {alias: row["objdata"] for row in module_rows for alias in row.get("aliases", ())}
        routes = tuple(by_alias[name]["Roads"] for name in ("TunnelDefendDefaultX", "TunnelDefendDefault1"))
        del source
        audio = Bundle(unwrap(donor.read("assets/plant2.rsb.smf")))
        zoybean = prepare_bank(resource(audio, r"PLANT2_SOUNDBANKS\PLANT_ZOYBEAN.BNK"), moton)
        del audio
        art = Bundle(unwrap(donor.read("assets/zombie3.rsb.smf")))
        manifest = art.manifest()[2]
        common = manifest_group(manifest, "ZombieZoybeanPodBasicGroup_Common")
        basic = next(row for row in common if row["id"] == "POPANIM_ZOMBIE_ZOYBEANPOD_ZOMBIE")
        common = manifest_group(manifest, "ZombieZoybeanPodGatlingpeaGroup_Common")
        gatling = next(row for row in common if row["id"] == GATLING_ANIMATION)
        filename = "\\".join(gatling["path"]).upper()
        authored_tofu = resource(art, "\\".join(basic["path"]).upper())
        animation = edit_animation(GATLING_ANIMATION, resource(art, filename), standard_tofu=authored_tofu)
    with ZipFile(args.upstream) as upstream:
        engine = register_zombie_card_types(build_guest(
            upstream.read(ENGINE), args.ndk, work, routes, args.qin_bank.read_bytes(), moton,
            args.tea_bank.read_bytes(), zoybean, zoybean_showcase=True,
        ))
    (work / "aster-zoybean.so").write_bytes(engine)
    with ZipFile(args.base) as base:
        manifest = manifest_version(base.read(MANIFEST), args.version, args.base_version, prefix="A")
        changes = {MANIFEST: manifest, ENGINE: engine}
        changes.update(showcase_resources(base, work, filename, animation, existing=args.existing_showcase))
    pack_apk(args.base, changes, args.sdk, args.output, args.signing)
    print(args.output, flush=True)


def configure_native_boost(document):
    sheet, = (row["objdata"] for row in document["objects"] if PLANT_SHEET in row.get("aliases", ()))
    use_native_boost(sheet)


def showcase_resources(base, work, filename, animation, *, existing):
    old = base.read(ASSET)
    bundle = Bundle(old)
    if not existing:
        replace_rton(bundle, TYPE_PACKAGE, lambda doc: clone_definition(
            doc, "mausoleum_armor2", TARGET, TypeName=TARGET, Properties=f"RTID({TARGET}@PropertySheets)",
            BoardAlmanac=False,
        ), allow_growth=True)
        replace_rton(bundle, SHEET_PACKAGE, lambda doc: clone_definition(
            doc, "ZombieMausoleumArmor2Default", TARGET, Hitpoints=60000, Speed=0.06, SpeedVariance=0, EatDPS=40,
            CanSpawnPlantFood=False, HeadDropFraction=-1, ArmDropFraction=-1,
        ), allow_growth=True)
        replace_rton(bundle, TEST_LEVEL, showcase, allow_growth=True)
    replace_rton(bundle, SHEET_PACKAGE, configure_native_boost, allow_growth=True)
    index, = (i for i, entry in enumerate(bundle.groups) if entry["ID"] == "ZombieZoybeanPodGatlingpeaGroup_Common")
    entries = dict(bundle.files(index))
    data = package_data(bundle.payloads[index])
    kind, pos, size = entries[filename]
    assert kind == 0 and PamIndex(data[pos:pos + size]).sprites[-1]["frames"][25]["label"] == "born"
    if data[pos:pos + size] != animation:
        start = (len(data) + 4095) // 4096 * 4096
        entries[filename] = (0, start, len(animation))
        data = data.ljust(start, b"\0") + animation
        replace_section(bundle, index, entries.items(), data + bytes(-len(data) % 4096), allow_header_growth=True)
    dynamic = bundle.build()
    if dynamic == old:
        return {}
    atlas_count = len(bundle.textures)
    del bundle
    plan = create_plan(dynamic, work, rgba_atlases=atlas_count - 2)
    dex = rebuild_dynamic_bootstrap(base.read(BOOTSTRAP), work / "bootstrap", old, dynamic)
    return {ASSET: dynamic, PLAN: plan, BOOTSTRAP: dex}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "donor", "upstream", "qin-bank", "moton-bank", "tea-bank", "output",
                     "sdk", "ndk", "signing"):
        parser.add_argument("--" + argument, type=Path, required=True)
    parser.add_argument("--version", type=int, default=452)
    parser.add_argument("--base-version", type=int, default=451)
    parser.add_argument("--existing-showcase", action="store_true", help="reuse the encounter in a previous test APK")
    build(parser.parse_args())
