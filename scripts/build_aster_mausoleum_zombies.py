"""Import Qin infantry and reinforcements and optionally populate Mausoleum Day 1."""

import argparse
from copy import deepcopy
from pathlib import Path
import re
import struct
from zipfile import ZipFile

from bake_rgba_resources import decode
from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, Bundle, create_plan, rebuild_dynamic_bootstrap
from build_aster_legacy_endless_gameplay import level_document, package_data, replace_rton
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import MANIFEST
from build_aster_save_path_fix import manifest_version
from merge_legacy_pvp_resources import u32
from pam_transform_index import PamIndex
from prepare_aster_cn_user_art import append_cn_user_credit, unwrap
from prepare_mausoleum_zombie_pam import adapt_mausoleum_pam
from prepare_offline_pvp_seagull_hd import replace_section, texture_section


GROUP = "ZombieMausoleumGroup"
TYPES = ("mausoleum_basic", "mausoleum_armor1", "mausoleum_armor2")
SHEETS = ("ZombieMausoleumDefault", "ZombieMausoleumArmor1Default", "ZombieMausoleumArmor2Default")
TYPE_PACKAGE = r"PACKAGES\ZOMBIETYPES.RTON"
SHEET_PACKAGE = r"PACKAGES\PROPERTYSHEETS.RTON"
TEST_LEVEL = r"PACKAGES\LEVELS\MAUSOLEUM1.RTON"
LAWN_STRINGS = r"PROPERTIES\LAWNSTRINGS.TXT"
ANIMATION = "POPANIM_ZOMBIE_ZOMBIE_MAUSOLEUM_BASIC"
REINFORCEMENT_TYPES = ("mausoleum_flag", "mausoleum_gargantuar", "mausoleum_imp")
REINFORCEMENT_SHEETS = ("ZombieMausoleumFlagDefault", "ZombieMausoleumGargantuar", "ZombieMausoleumImpDefault")
FLAG_ANIMATION = "POPANIM_ZOMBIE_ZOMBIE_MAUSOLEUM_FLAG"
GARGANTUAR_ANIMATION = "POPANIM_ZOMBIE_ZOMBIE_MAUSOLEUM_GARGANTUAR"
IMP_ANIMATION = "POPANIM_ZOMBIE_ZOMBIE_MAUSOLEUM_IMP"


def resource(bundle, path):
    for index in range(len(bundle.groups)):
        entry = dict(bundle.files(index)).get(path)
        if entry is not None:
            kind, offset, size = entry
            assert kind == 0
            return package_data(bundle.payloads[index])[offset:offset + size]
    raise ValueError(f"Missing resource {path}")


def append_definitions(target, donor, path, aliases, adapt=None):
    document = level_document(resource(donor, path), path)
    rows = {name: row for row in document["objects"] for name in row.get("aliases", []) if name in aliases}
    assert set(rows) == set(aliases)
    if adapt is not None:
        adapt(rows)

    def append(document):
        existing = {name for row in document["objects"] for name in row.get("aliases", [])}
        assert existing.isdisjoint(aliases)
        document["objects"].extend(rows[name] for name in aliases)

    replace_rton(target, path, append, allow_growth=True)


def add_strings(target, donor, variants):
    original = resource(target, LAWN_STRINGS)
    source = resource(donor, LAWN_STRINGS).decode("utf-8-sig")
    strings = dict(re.findall(r"(?m)^\[([^\]\r\n]+)\][ \t]*\r?\n([^\r\n]+)", source))
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    additions = []
    for variant in variants:
        for suffix in ("", "_DESCRIPTION_HEADER", "_DESCRIPTION"):
            key = "ZOMBIE_" + variant.upper() + suffix
            assert f"[{key}]".encode() not in original
            additions.extend((f"[{key}]", strings[key], ""))
    updated = original + newline * 2 + newline.join(line.encode("utf-8") for line in additions)
    index, = (i for i in range(len(target.groups)) if LAWN_STRINGS in dict(target.files(i)))
    files = dict(target.files(index))
    data = package_data(target.payloads[index])
    files[LAWN_STRINGS] = (0, len(data), len(updated))
    replace_section(target, index, files.items(), data + updated)


def add_group(bundle, manifest, donor, group_name, wanted_animations, *, adapt=False, transform=None):
    source_manifest = {row["id"]: row for row in donor.manifest()[2]["groups"]}
    source_indices = {row["ID"]: i for i, row in enumerate(donor.groups)}
    image_group = group_name + "_1200"
    common_group = group_name + "_Common"
    target_group = group_name + "_1536"
    composite = deepcopy(source_manifest[group_name])
    atlas_manifest = deepcopy(source_manifest[image_group])
    common_manifest = deepcopy(source_manifest[common_group])
    animations = [row for row in common_manifest["resources"] if row["id"] in wanted_animations]
    assert {row["id"] for row in animations} == set(wanted_animations)
    pams = {}
    for animation in animations:
        path = "\\".join(animation["path"]).upper()
        raw = resource(donor, path)
        if adapt:
            raw = adapt_mausoleum_pam(raw, infantry=animation["id"] == ANIMATION)
        if transform:
            raw = transform(animation["id"], raw)
        pams[path] = raw
    rigs = [PamIndex(pam) for pam in pams.values()]
    images = {image["name"].split("|", 1)[1] for rig in rigs for image in rig.images}
    atlas_manifest["resources"] = [
        row for row in atlas_manifest["resources"] if row.get("atlas") or row["id"] in images
    ]
    assert {row["id"] for row in atlas_manifest["resources"] if "parent" in row} == images
    common_manifest["resources"] = animations
    atlas_manifest.update(id=target_group, res="1536")
    composite["subgroups"] = [{"id": target_group, "res": "1536"}, {"id": common_group}]

    # The donor and the installed game already share the same PAM image basis.
    # The tier selects the atlas while the original animation names remain intact.
    remap = {}
    for source_name, target_name in ((image_group, target_group), (common_group, common_group)):
        old = source_indices[source_name]
        index = len(bundle.groups)
        remap[old] = index
        info = bytearray(donor.infos[old])
        info[:128] = target_name.encode("ascii").ljust(128, b"\0")
        pool = bytearray(donor.pools[old])
        old_pool_name = source_name.encode("ascii")
        if pool[:128].startswith(old_pool_name):
            pool[:len(old_pool_name)] = target_name.encode("ascii")
        bundle.groups.append({"ID": target_name})
        bundle.infos.append(info)
        bundle.pools.append(pool)
        bundle.payloads.append(bytearray(donor.payloads[old]))
        if source_name == image_group:
            count, first = struct.unpack_from("<II", info, 196)
            assert count == 1
            width, height, _, fmt, _, _ = struct.unpack("<6I", donor.textures[first])
            name, entry = donor.files(old)[0]
            kind, offset, size, slot, _, _, w, h = entry
            assert len(donor.files(old)) == 1 and (kind, slot, w, h) == (1, 0, width, height)
            atlas = texture_section(donor.payloads[old])
            rgba = decode(atlas[offset:offset + size], width, height, fmt)
            struct.pack_into("<I", info, 200, len(bundle.textures))
            bundle.textures.append(bytearray(struct.pack("<6I", width, height, width * 4, 0, 0, 100)))
            replace_section(bundle, index, [(name, (1, 0, len(rgba), *entry[3:]))], b"", rgba)
        else:
            assert u32(info, 196) == 0
            struct.pack_into("<I", info, 200, len(bundle.textures))
            files = []
            data = bytearray()
            for path, pam in pams.items():
                files.append((path, (0, len(data), len(pam))))
                data.extend(pam)
                data.extend(bytes(-len(data) % 4096))
            replace_section(bundle, index, files, data)

    raw, = [c for c in donor.composites if c[:128].split(b"\0")[0].decode() == group_name]
    row = bytearray(raw)
    assert u32(row, 1152) == 2
    for index in range(2):
        offset = 128 + 16 * index
        new = remap[u32(row, offset)]
        tier = 1536 if bundle.groups[new]["ID"] == target_group else 0
        struct.pack_into("<II", row, offset, new, tier)
    bundle.composites.append(row)

    used = {r["id"] for g in manifest["groups"] for r in g.get("resources", [])}
    for group in (composite, atlas_manifest, common_manifest):
        for row in group.get("resources", []):
            assert row["id"] not in used
            used.add(row["id"])
            row["slot"] = manifest["slot_count"]
            manifest["slot_count"] += 1
        manifest["groups"].append(group)
    return pams


def adapt_reinforcement_types(rows):
    imp = rows["mausoleum_imp"]["objdata"]
    assert imp["ZombieClass"] == "ZombieImp" and imp["AnimRigClass"] == "ZombieAnimRig_MausoleumImp"
    imp["AnimRigClass"] = "ZombieAnimRig_Imp"
    gargantuar = rows["mausoleum_gargantuar"]["objdata"]
    assert gargantuar["ResourceGroups"] == [
        "ZombieMausoleumGargantuarGroup", "ZombieMausoleumImpGroup",
        "ZombieGargantuarEffects", "ZombieBronzeEffects",
    ]
    # Aster's ordinary Gargantuar uses the shared effects already loaded by the game.
    gargantuar["ResourceGroups"] = gargantuar["ResourceGroups"][:2]


def adapt_reinforcement_sheets(rows, pams):
    sheet = rows["ZombieMausoleumGargantuar"]["objdata"]
    assert sheet["ImpType"] == "mausoleum_imp"
    pam, = [raw for path, raw in pams.items() if path.endswith("MAUSOLEUM_GARGANTUAR.PAM")]
    rig = PamIndex(pam)
    sprite_names = {sprite["name"] for sprite in rig.sprites}
    for threshold in sheet["HealthThresholdToImpAmmoLayers"]:
        layers = threshold["ProjectileLayersToHide"]
        assert "zombie_imp_skull" in sprite_names and "zombie_imp_skull" in layers
        layers[:] = [name for name in layers if name in sprite_names]
        layers.append("_zombie_imp_head_top")
        assert set(layers) <= sprite_names


def add_test_wave(document, extended):
    level, waves = document["objects"]
    assert waves["objclass"] == "WaveGeneratorProperties"
    pool = [{"Type": f"RTID({name}@ZombieTypes)"} for name in TYPES]
    spawns = [{**entry, "Row": str(row), "Level": 1} for row, entry in enumerate(pool, 2)]
    schedule = [{"DisableRandomSpawns": True, "Zombies": spawns}]
    level["objdata"]["StartingSun"] = 3000 if extended else 1500
    if extended:
        reinforcements = [{"Type": f"RTID({name}@ZombieTypes)"}
                          for name in REINFORCEMENT_TYPES[:2]]
        pool.extend(reinforcements)
        schedule.append({"DisableRandomSpawns": True, "Zombies": [
            {**entry, "Row": str(row), "Level": 1} for row, entry in zip((2, 4), reinforcements)
        ]})
    waves["objdata"].update(AddToZombiePool=pool, Waves=schedule, WaveCount=len(schedule),
                            FlagWaveInterval=len(schedule) + 1)


def build(base, donor, output, sdk, signing, test_level, extended):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(donor) as archive:
        donor_data = Bundle(unwrap(archive.read("assets/dynamic.rsb.smf")))
        donor_art = Bundle(unwrap(archive.read("assets/zombie3.rsb.smf")))
    with ZipFile(base) as apk:
        dynamic = apk.read(ASSET)
        bundle = Bundle(dynamic)
        index, path, manifest = bundle.manifest()
        infantry_animations = (ANIMATION, FLAG_ANIMATION) if extended else (ANIMATION,)
        animations = add_group(bundle, manifest, donor_art, GROUP, infantry_animations, adapt=extended)
        if extended:
            animations.update(add_group(bundle, manifest, donor_art, "ZombieMausoleumGargantuarGroup",
                                        (GARGANTUAR_ANIMATION,), adapt=True))
            animations.update(add_group(bundle, manifest, donor_art, "ZombieMausoleumImpGroup",
                                        (IMP_ANIMATION,), adapt=True))
        del donor_art
        append_definitions(bundle, donor_data, TYPE_PACKAGE, TYPES)
        append_definitions(bundle, donor_data, SHEET_PACKAGE, SHEETS)
        if extended:
            append_definitions(bundle, donor_data, TYPE_PACKAGE, REINFORCEMENT_TYPES, adapt_reinforcement_types)
            append_definitions(bundle, donor_data, SHEET_PACKAGE, REINFORCEMENT_SHEETS,
                               lambda rows: adapt_reinforcement_sheets(rows, animations))
        variants = TYPES + REINFORCEMENT_TYPES if extended else TYPES
        add_strings(bundle, donor_data, variants)
        del donor_data
        description = "秦始皇陵僵尸素材提取自" if extended else "秦始皇陵普通、路障与铁桶僵尸素材提取自"
        append_cn_user_credit(bundle, description=description)
        if test_level:
            replace_rton(bundle, TEST_LEVEL, lambda doc: add_test_wave(doc, extended), allow_growth=True)
        bundle.replace_manifest(index, path, manifest)
        updated = bundle.build()
        parsed = Bundle(updated)
        assert parsed.manifest()[2] == manifest
        for animation_path, pam in animations.items():
            assert resource(parsed, animation_path) == pam
        atlas_count = len(bundle.textures)
        del parsed, bundle
        plan = create_plan(updated, output.parent, rgba_atlases=atlas_count - 2)
        dex = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output.parent / "bootstrap", dynamic, updated)
        apk_manifest = manifest_version(apk.read(MANIFEST), 374 if extended else 372, 371, prefix="A")
    pack_apk(base, {ASSET: updated, PLAN: plan, BOOTSTRAP: dex, MANIFEST: apk_manifest}, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "donor", "output", "sdk", "signing"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--test-level", action="store_true")
    parser.add_argument("--extended", action="store_true", help="Also add Qin flag, Gargantuar and Imp")
    build(**vars(parser.parse_args()))
