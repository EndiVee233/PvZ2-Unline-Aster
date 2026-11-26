"""Build the Qin battlefields and the Day 1 zombie showcase."""

import argparse
from copy import copy, deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import struct
import subprocess
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from PIL import Image

from build_aster_adventure_records import FLAGS
from build_aster_compact_resources import BASELINE, PREFIX, ResourceZip, copy_compressed_entry, pack_pool, split_archive
from build_aster_hud_pickup import UI_IMAGES, group_index, manifest_group, relocate_prefetch
from build_aster_legacy_endless_gameplay import level_document, package_data, replace_rton
from build_aster_mausoleum_map import add_art
from build_aster_mausoleum_zombies import (
    ASSET, BOOTSTRAP, GROUP as INFANTRY_GROUP, PLAN, SHEET_PACKAGE, TEST_LEVEL, TYPE_PACKAGE, Bundle,
    LAWN_STRINGS, add_group, add_strings, append_definitions, create_plan, rebuild_dynamic_bootstrap,
    resource, texture_section,
)
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version
from pam_transform_index import PamIndex
from prepare_aster_cn_user_art import append_cn_user_credit, crop_sprites, unwrap
from prepare_aster_pvp_runtime import file_offset
from prepare_aster_qin_native_music import chapter_audio
from prepare_mausoleum_zombie_pam import adapt_mausoleum_pam
from prepare_offline_pvp_seagull_hd import replace_section
from prepare_profile_memory import branch


LEVEL_MODULES = r"PACKAGES\LEVELMODULES.RTON"
PLANT_TYPES = r"PACKAGES\PLANTTYPES.RTON"
GRID_TYPES = r"PACKAGES\GRIDITEMTYPES.RTON"
PROJECTILES = r"PACKAGES\PROJECTILETYPES.RTON"
ART_GROUP = "QinChapterOneBattlefield"
BACKGROUND = "IMAGE_BACKGROUNDS_UNCHARTED_MAUSOLEUM"
BRICKS = "IMAGE_UI_MAUSOLEUM_TUNNEL_BRICK1"
RIDER = "mausoleum_cavalry"
STAGE = "AsterQinChapterOneStage"
CURVED_STAGE = "AsterQinCurvedTunnelStage"
CURVED_BG = BACKGROUND + "_BENT"
PIGGY = "mausoleum_piggy"
VENDOR = "mausoleum_vendor"
ARCHER = "mausoleum_archer"
ARCHER_GROUP = "ZombieMausoleumArcherGroup"
ARCHER_SHEET = "ZombieMausoleumArcherDefault"
ARCHER_ACTION = "QinArcherProjectileAction"
ARCHER_BOLT = "ArcherProjectileDefault"
ARCHER_PAMS = ("POPANIM_ZOMBIE_ZOMBIE_MAUSOLEUM_ARCHER", "POPANIM_EFFECTS_ZOMBIE_MAUSOLEUM_ARCHER_BULLET")
DRUNKARD = "mausoleum_drunkard"
ASSASSIN = "qin_jingke"
ASSASSIN_GROUP = "ZombieQinJingkeGroup"
ASSASSIN_SHEET = "ZombieQinJingkeDefault"
ASSASSIN_PAM = "POPANIM_ZOMBIE_ZOMBIE_QIN_JINGKE"
TAOIST = "qin_taoist"
TAOIST_GROUP = "ZombieQinTaoistGroup"
TAOIST_PAMS = (
    "POPANIM_ZOMBIE_ZOMBIE_QIN_TAOIST",
    "POPANIM_EFFECTS_ZOMBIE_QIN_TAOIST_SKILL",
    "POPANIM_EFFECTS_ZOMBIE_QIN_TAOIST_SOULFIRE",
)
TERRACOTTA_SMALL = "qin_terracotta_small"
TERRACOTTA_GENERAL = "qin_terracotta_mid"
TERRACOTTA_GROUP = "ZombieQinTerracottaGroup"
TERRACOTTA_PAMS = (
    "POPANIM_ZOMBIE_ZOMBIE_QIN_TERRACOTTA_SMALL",
    "POPANIM_ZOMBIE_ZOMBIE_QIN_TERRACOTTA_MID",
)
TERRACOTTA_RUIN = "terracottaArmy"
TERRACOTTA_RUIN_PAM = "POPANIM_GRIDITEM_QIN_TERRACOTTA_RUIN"
DRUNKARD_GROUP = "ZombieMausoleumDrunkGroup"
DRUNKARD_PAMS = (
    "POPANIM_ZOMBIE_ZOMBIE_MAUSOLEUM_DRUNK",
    "POPANIM_EFFECTS_ZOMBIE_MAUSOLEUM_DRUNK_EFFECT",
)
SHIELD_SEGMENT = "qin_shield_segment"
SHIELD_PAIR = "qin_shield_pair"
SHIELD_TRIAD = "qin_shield_triad"
SHIELD_ALMANAC = "qin_shield_almanac"
SHIELD_GROUP = "ZombieQinShieldGroup"
SHIELD_PAM = "POPANIM_ZOMBIE_ZOMBIE_QIN_SHIELD"
HAY = "uncharted_haystack"
HAY_GRID = "uncharted_haystack_grid"
HAY_GROUP = "PlantUnchartedHaystack"
HAY_PAM = "POPANIM_PLANT_UNCHARTED_HAYSTACK"
HAY_PACKET = "IMAGE_UI_PACKETS_UNCHARTED_HAYSTACK"
QIN_TEST_PLANTS = (HAY, "peashooter", "cabbagepult", "snowpea",
                   "splitpea", "hypnoshroom", "sunbean", "wallnut")
MOWER_MODULE = "MausoleumMowers"
MOWER_GROUP = "MausoleumMowerGroup"
MOWER_PAM = "POPANIM_MOWERS_MOWER_MAUSOLEUM"
QIN_ATLASES_1200 = {
    INFANTRY_GROUP: (512, 1024),
    "ZombieMausoleumGargantuarGroup": (1024, 1024),
    "ZombieMausoleumImpGroup": (256, 256),
    "ZombieMausoleumCavalryGroup": (256, 512),
    "ZombieMausoleumPiggyGroup": (256, 512),
    "ZombieMausoleumVendorGroup": (512, 512),
    ARCHER_GROUP: (2048, 2048),
    DRUNKARD_GROUP: (1024, 1024),
    SHIELD_GROUP: (512, 512),
    HAY_GROUP: (256, 256),
}
UPSTREAM = "fe3afbd1c6d286026c0b860d42b8eb333b7df799c548d4d18826c5fcbcdc74b5"
UPDATE = 0x22930c
OLD_UPDATE = 0x1a95e28
ROOT = Path(__file__).resolve().parents[1]


def from_group(archive, member, group, ids):
    source = Bundle(unwrap(archive.read(f"assets/{member}.rsb.smf")))
    row, = [g for g in source.manifest()[2]["groups"] if g["id"] == group]
    images = dict(crop_sprites(source, row, {name: name for name in ids}))
    offsets = {asset["id"]: {axis: asset[axis] for axis in ("x", "y") if axis in asset}
               for asset in row["resources"] if asset["id"] in images}
    return images, offsets


def read_board_art(archive, straight, curved):
    art, offsets = from_group(archive, "steam", "DelayLoad_Background_Uncharted_Mausoleum_1200",
                              [BACKGROUND + "_TEXTURE" + suffix for suffix in ("", "_LEFT", "_RIGHT")])
    original_floor = art[BACKGROUND + "_TEXTURE"]
    assert original_floor.size == (1600, 1200)
    route_tiles = {item["Img"] for item in straight + curved}
    brick_keys = [f"{BRICKS}_{row + 1}_{col + 1}" for row in range(5) for col in range(9)]
    cells, _ = from_group(archive, "uicommon", "UI_MausoleumTunnel_1200", [*sorted(route_tiles), *brick_keys])
    for layout, key in ((straight, BACKGROUND), (curved, CURVED_BG)):
        floor = original_floor.copy()
        route_cells = {(road["GridX"], road["GridY"]): road["Img"] for road in layout}
        for row in range(5):
            for col in range(9):
                x, y = 400 + 128 * col, 320 + 152 * row
                texture = route_cells.get((col, row))
                if texture:
                    tile = cells[texture]
                    floor.alpha_composite(tile, (x, y))
                else:
                    tile = cells[f"{BRICKS}_{row + 1}_{col + 1}"]
                    assert 128 <= tile.width <= 136 and 152 <= tile.height <= 160
                    floor.alpha_composite(tile, (x - 4, y - 4))
        art[key + "_TEXTURE"] = floor
    # Donor pixels are 1200-tier. The image origin properties already use the
    # stage's 1536-tier coordinates, so only the pixel rectangles are scaled.
    scaled_art = {name: image.resize((round(image.width * 1536 / 1200), 1536), Image.Resampling.LANCZOS)
                  for name, image in art.items()}
    assert offsets[BACKGROUND + "_TEXTURE"] == {"x": 556}
    assert offsets[BACKGROUND + "_TEXTURE_RIGHT"] == {"x": 2604}
    offsets[CURVED_BG + "_TEXTURE"] = offsets[BACKGROUND + "_TEXTURE"]
    return scaled_art, offsets


def stage_row(donor_stage, name, prefix):
    data = deepcopy(donor_stage["objdata"])
    data.update(ResourceGroupNames=[ART_GROUP, "Game_Tombstones_Dynamic", "AudioEgypt", HAY_GROUP],
                StagePrefix="mausoleum", BackgroundImagePrefix=prefix)
    assert data["MusicSuffix"] == "Uncharted"
    assert donor_stage["objclass"] == "StageModuleProperties"
    return dict(objclass=donor_stage["objclass"], aliases=[name], objdata=data)


def adapt_type(rows):
    for name, role in ((RIDER, "Cavalry"), (PIGGY, "Piggy"), (VENDOR, "Vendor")):
        zombie = rows[name]["objdata"]
        assert zombie["ZombieClass"] == f"ZombieMausoleum{role}"
        groups = [f"ZombieMausoleum{role}Group"]
        if name == VENDOR:
            groups.append("ZombieMausoleumPiggyGroup")
        zombie.update(ZombieClass="ZombieBasic", AnimRigClass="ZombieAnimRig_Tutorial",
                      ResourceGroups=groups)


def adapt_sheet(rows):
    for role, tunnel_speed, speed in (("Cavalry", 0.45, 0.185), ("Piggy", 2, 1), ("Vendor", 0.25, 0.19)):
        sheet = rows[f"ZombieMausoleum{role}Default"]
        assert sheet["objclass"] == f"ZombieMausoleum{role}Props"
        data = sheet["objdata"]
        assert data.pop("TunnelSpeed") == tunnel_speed and data["Speed"] == speed
        del data["TunnelAnimRateOverride"]
        if role == "Vendor":
            assert data.pop("SetPigInterval") == 6
        sheet["objclass"] = "ZombiePropertySheet"


def archer_animation(name, raw):
    if name != ARCHER_PAMS[0]:
        return raw
    raw = adapt_mausoleum_pam(raw)
    frames = PamIndex(raw).sprites[-1]["frames"]
    labels = {frame["label"]: i for i, frame in enumerate(frames) if frame["label"]}
    shoot = frames[labels["shoot"]]
    assert raw[frames[labels["shoot"] - 1]["start"]] & 16
    assert sum(frame["commands"].count(("use_action", ""))
               for frame in frames[labels["shoot"]:labels["endshoot"]]) == 1
    # Preserve the donor's separate crouch, crouched idle and stand-up clips.
    # The legacy ranged rig only needs a new name for the release clip.
    result = bytearray(raw)
    start = shoot["events_start"]
    result[start:start + 2 + len("shoot")] = struct.pack("<H", len("throw")) + b"throw"
    assert PamIndex(result).sprites[-1]["frames"][labels["shoot"]]["label"] == "throw"
    return bytes(result)


def add_archer(target, donor, zombie_resources, manifest):
    add_group(target, manifest, zombie_resources, ARCHER_GROUP, ARCHER_PAMS, transform=archer_animation)

    def adapt_archer_type(rows):
        data = rows[ARCHER]["objdata"]
        assert data["ZombieClass"] == "ZombieMausoleumArcher"
        data.update(ZombieClass="ZombieIceAgeHunter", AnimRigClass="ZombieAnimRig_Hunter",
                    ResourceGroups=[ARCHER_GROUP], AudioGroups=[])

    def adapt_archer_sheet(rows):
        sheet = rows[ARCHER_SHEET]
        assert sheet["objclass"] == "ZombieMausoleumArcherProps"
        data = sheet["objdata"]
        interval = data.pop("ShootInterval")
        assert interval == 4
        del data["SpiritTypeName"]
        sheet["objclass"] = "ZombieIceAgeHunterProps"
        data.update(Actions=[f"RTID({ARCHER_ACTION}@.)"], NearAttackRange=1, FarAttackRange=9,
                    SnowballsPerBarrage=1, ChillInsteadOfFreeze=False)

    def add_archer_action(document):
        clone_definition(
            document, "ZombieIceAgeProjectileAction", ARCHER_ACTION,
            Projectile=f"RTID({ARCHER_BOLT}@ProjectileTypes)", ProjectileSound="",
            TimeBeforeFirst={"Min": 4, "Max": 4}, TimeBetween={"Min": 4, "Max": 4},
            TimeBetweenBarrages={"Min": 4, "Max": 4},
            SpawnOffset={"x": 0, "y": 0, "z": 70}, ApexHeight=350, TimeUntilHit=1,
        )

    def adapt_archer_bolt(rows):
        sheet = rows[ARCHER_BOLT]
        assert sheet["objclass"] == "ArcherProjectileProps" and sheet["objdata"]["ClassName"] == "ArcherProjectile"
        sheet["objclass"] = "ProjectilePropertySheet"
        del sheet["objdata"]["ClassName"]
        sheet["objdata"]["ImpactSoundEvent"] = "Play_CabbagePult_Impact"

    append_definitions(target, donor, TYPE_PACKAGE, (ARCHER,), adapt_archer_type)
    append_definitions(target, donor, SHEET_PACKAGE, (ARCHER_SHEET,), adapt_archer_sheet)
    replace_rton(target, SHEET_PACKAGE, add_archer_action, allow_growth=True)
    append_definitions(target, donor, PROJECTILES, (ARCHER_BOLT,), adapt_archer_bolt)
    add_strings(target, donor, (ARCHER,))


def add_drunkard(target, donor, zombie_resources, manifest):
    def animation(name, raw):
        if name == DRUNKARD_PAMS[0]:
            rig = PamIndex(raw)
            assert {"walk", "drink", "spray", "eat", "die"} <= {
                frame["label"] for frame in rig.sprites[-1]["frames"]
            }
            if any(sprite["name"] == "ink" for sprite in rig.sprites):
                return adapt_mausoleum_pam(raw)
        return raw

    def adapt_drunkard_type(rows):
        data = rows[DRUNKARD]["objdata"]
        assert data["ZombieClass"] == "ZombieDrunkard"
        data.update(ZombieClass="ZombieBasic", AnimRigClass="ZombieAnimRig_Tutorial",
                    ResourceGroups=[DRUNKARD_GROUP], AudioGroups=[])

    add_group(target, manifest, zombie_resources, DRUNKARD_GROUP, DRUNKARD_PAMS, transform=animation)
    append_definitions(target, donor, TYPE_PACKAGE, (DRUNKARD,), adapt_drunkard_type)
    append_definitions(target, donor, SHEET_PACKAGE, ("ZombieDrunkardDefault",))
    add_strings(target, donor, (DRUNKARD,))


def add_shield(target, donor, zombie_resources, manifest):
    stock_camel, = [
        row["objdata"] for row in level_document(resource(donor, SHEET_PACKAGE), SHEET_PACKAGE)["objects"]
        if "ZombieCamelDefault" in row.get("aliases", [])
    ]

    def adapt_types(rows):
        for name, row in rows.items():
            data = row["objdata"]
            assert data["ZombieClass"] == "ZombieQinShield"
            data.update(ZombieClass="ZombieCamel", AnimRigClass="ZombieAnimRig_Camel",
                        BoardAlmanac=name == SHIELD_SEGMENT, Placeable=name != SHIELD_ALMANAC,
                        ResourceGroups=[SHIELD_GROUP, "ZombieEgyptCamelGroup", "ZombieEgyptBasicGroup"])
            if name in (SHIELD_PAIR, SHIELD_TRIAD):
                data["DisplayTypeName"] = SHIELD_SEGMENT
            else:
                data.pop("DisplayTypeName", None)

    def adapt_sheet(rows):
        sheet = rows["ZombieQinShieldDefault"]
        assert sheet["objclass"] == "ZombieCamelProps" and sheet["objdata"]["Hitpoints"] == 1800
        data = sheet["objdata"]
        del data["ScaledProps"]
        # Qin's shield wears with body health, with no separate Camel sign.
        data.update(InitialFrontSignHealth=0, InitialBodySignHealth=0, SignHealthStates=3)
        for key in ("SizeType", "MinLevel", "MaxLevel", "FirstWave", "ZombieLevelStats"):
            data[key] = stock_camel[key]

    add_group(target, manifest, zombie_resources, SHIELD_GROUP, (SHIELD_PAM,), adapt=True)
    append_definitions(target, donor, TYPE_PACKAGE,
                       (SHIELD_SEGMENT, SHIELD_PAIR, SHIELD_TRIAD, SHIELD_ALMANAC), adapt_types)
    append_definitions(target, donor, SHEET_PACKAGE, ("ZombieQinShieldDefault",), adapt_sheet)
    add_strings(target, donor, (SHIELD_SEGMENT,))


def add_assassin(target, donor, zombie_resources, manifest):
    add_group(target, manifest, zombie_resources, ASSASSIN_GROUP, (ASSASSIN_PAM,), adapt=True)
    resize_qin_atlas(target, manifest, ASSASSIN_GROUP, (2048, 2048))
    legacy, = [row["objdata"] for row in level_document(resource(target, SHEET_PACKAGE), SHEET_PACKAGE)["objects"]
               if "ZombieMausoleumDefault" in row.get("aliases", [])]

    def adapt_assassin_type(rows):
        data = rows[ASSASSIN]["objdata"]
        data.update(ZombieClass="ZombieBasic", AnimRigClass="ZombieAnimRig_Tutorial", AudioGroups=[])

    def adapt_assassin_sheet(rows):
        row = rows[ASSASSIN_SHEET]
        row["objclass"] = "ZombiePropertySheet"
        data = row["objdata"]
        assert data.pop("AssassinateDamage") == 300
        del data["SpiritTypeName"], data["ZombieArmorProps"], data["ScaledProps"]
        # The legacy engine stores the scroll in its damageable armor slot.
        data.update(Helm="cone", HelmHitpoints=600, SizeType=legacy["SizeType"],
                    ZombieLevelStats=legacy["ZombieLevelStats"])

    append_definitions(target, donor, TYPE_PACKAGE, (ASSASSIN,), adapt_assassin_type)
    append_definitions(target, donor, SHEET_PACKAGE, (ASSASSIN_SHEET,), adapt_assassin_sheet)
    add_strings(target, donor, (ASSASSIN,))


def resize_qin_atlas(bundle, manifest, group_name, source_dimensions):
    group = group_name + "_1536"
    index = group_index(bundle, group)
    count, slot = struct.unpack_from("<II", bundle.infos[index], 196)
    width, height, stride, pixel_format, _, _ = struct.unpack("<6I", bundle.textures[slot])
    assert count == 1 and pixel_format == 0 and stride == width * 4
    def scale(value):
        return round(value * 1536 / 1200)

    dimensions = tuple(map(scale, source_dimensions))
    if (width, height) == dimensions:
        return
    assert (width, height) == source_dimensions, group_name
    name, entry = bundle.files(index)[0]
    kind, byte_offset, size, texture_id, format_flags, unused, file_width, file_height = entry
    assert kind == 1 and size == width * height * 4 and (file_width, file_height) == source_dimensions
    pixels = texture_section(bundle.payloads[index])[byte_offset:byte_offset + size]
    image = Image.frombytes("RGBA", (width, height), pixels)
    scaled = image.resize(dimensions, Image.Resampling.LANCZOS).tobytes()
    bundle.textures[slot][:] = struct.pack("<6I", *dimensions, dimensions[0] * 4, 0, 0, 100)
    new_entry = (1, 0, len(scaled), texture_id, format_flags, unused, *dimensions)
    replace_section(bundle, index, [(name, new_entry)], b"", scaled)

    # PAM transforms stay in animation coordinates. Only remap rectangles
    # expressed in atlas pixels, using shared endpoints for adjacent slices.
    for row in manifest_group(manifest, group):
        if row.get("atlas"):
            row["width"], row["height"] = dimensions
        elif "parent" in row:
            x, y = row["ax"], row["ay"]
            row.update(ax=scale(x), ay=scale(y), aw=scale(x + row["aw"]) - scale(x),
                       ah=scale(y + row["ah"]) - scale(y))


def pack_terracotta_atlas(bundle, manifest):
    group = TERRACOTTA_GROUP + "_1536"
    index = group_index(bundle, group)
    count, first = struct.unpack_from("<II", bundle.infos[index], 196)
    assert count == 1 and first + 1 == len(bundle.textures)
    name, entry = bundle.files(index)[0]
    _, offset, size, _, _, _, width, height = entry
    assert (width, height) == (4096, 4096)
    pixels = texture_section(bundle.payloads[index])[offset:offset + size]
    source = Image.frombytes("RGBA", (width, height), pixels)
    resources = manifest_group(manifest, group)
    atlas, = [row for row in resources if row.get("atlas")]
    slices = [row for row in resources if row.get("parent") == atlas["id"]]

    # Scale the slices before packing to keep the legacy GPU allocation below 4096 per axis.
    pages = []
    limit = 4096
    gutter = 2
    for row in sorted(slices, key=lambda item: (-item["ah"], -item["aw"])):
        x, y, w, h = (row[key] for key in ("ax", "ay", "aw", "ah"))
        sw, sh = (max(1, round(v * 1536 / 1200)) for v in (w, h))
        sprite = source.crop((x, y, x + w, y + h)).resize((sw, sh), Image.Resampling.LANCZOS)
        boxw, boxh = sw + 2 * gutter, sh + 2 * gutter
        assert boxw <= limit and boxh <= limit, row["id"]
        placement = None
        for page_id, (shelves, images) in enumerate(pages):
            for shelf in shelves:
                if boxh <= shelf[2] and shelf[0] + boxw <= limit:
                    placement = (page_id, shelf, images)
                    break
            if placement is not None:
                break
            top = shelves[-1][1] + shelves[-1][2]
            if top + boxh <= limit:
                shelves.append([0, top, boxh])
                placement = (page_id, shelves[-1], images)
                break
        if placement is None:
            shelf = [0, 0, boxh]
            images = []
            placement = (len(pages), shelf, images)
            pages.append(([shelf], images))
        page_id, shelf, images = placement
        sx, sy = shelf[:2]
        images.append((sx, sy, sprite))
        shelf[0] += boxw
        parent = atlas["id"] if page_id == 0 else f'{atlas["id"]}_{page_id:02}'
        row.update(parent=parent, ax=sx + gutter, ay=sy + gutter, aw=sw, ah=sh)

    files, stream, textures = [], bytearray(), []
    for page_id, (shelves, images) in enumerate(pages):
        width = (max(shelf[0] for shelf in shelves) + 3) & ~3
        height = (shelves[-1][1] + shelves[-1][2] + 3) & ~3
        page = Image.new("RGBA", (width, height))
        for x, y, sprite in images:
            page.paste(sprite, (x + gutter, y + gutter))
        filename = name
        if page_id:
            stem = atlas["path"][-1] + f"_{page_id:02}"
            filename = name[:-4] + f"_{page_id:02}.PTX"
            resources.insert(page_id, dict(atlas, id=f'{atlas["id"]}_{page_id:02}',
                                          path=[*atlas["path"][:-1], stem], width=width, height=height,
                                          slot=manifest["slot_count"]))
            manifest["slot_count"] += 1
        else:
            atlas.update(width=width, height=height)
        pixels = page.tobytes()
        files.append((filename, (1, len(stream), len(pixels), page_id, 0, 0, width, height)))
        stream.extend(pixels)
        stream.extend(bytes(-len(stream) % 4096))
        textures.append(bytearray(struct.pack("<6I", width, height, width * 4, 0, 0, 100)))
    bundle.textures[first:] = textures
    struct.pack_into("<I", bundle.infos[index], 196, len(textures))
    replace_section(bundle, index, files, b"", stream, allow_header_growth=True)


def add_terracotta_ruin_animation(bundle, manifest, pams):
    path, raw = next((path, raw) for path, raw in pams.items() if path.endswith("_MID.PAM"))
    frame = PamIndex(raw).sprites[-1]["frames"][0]
    assert frame["label"] == "animation" and raw[frame["start"]] & 16
    static = bytearray(raw[:frame["events_start"]])
    static.extend(struct.pack("<H4s", 4, b"idle"))
    struct.pack_into("<Hhh", static, frame["start"] - 6, 1, 0, 0)
    assert PamIndex(static).sprites[-1]["frames"][0]["label"] == "idle"

    group = TERRACOTTA_GROUP + "_Common"
    index = group_index(bundle, group)
    rows = manifest_group(manifest, group)
    animation = next(r for r in rows if r["id"] == TERRACOTTA_PAMS[1])
    new_path = [*animation["path"][:-1], "qin_terracotta_ruin.pam"]
    rows.append(dict(animation, id=TERRACOTTA_RUIN_PAM, path=new_path, slot=manifest["slot_count"]))
    manifest["slot_count"] += 1
    files = dict(bundle.files(index))
    data = package_data(bundle.payloads[index])
    files["\\".join(new_path).upper()] = (0, len(data), len(static))
    replace_section(bundle, index, files.items(), data + static, allow_header_growth=True)


def add_taoist_and_terracotta(target, donor, zombie_resources, manifest):
    def adapt_animation(_name, raw):
        rig = PamIndex(raw)
        return adapt_mausoleum_pam(raw) if any(sprite["name"] == "ink" for sprite in rig.sprites) else raw

    add_group(target, manifest, zombie_resources, TAOIST_GROUP, TAOIST_PAMS, transform=adapt_animation)
    resize_qin_atlas(target, manifest, TAOIST_GROUP, (1024, 2048))
    pams = add_group(target, manifest, zombie_resources, TERRACOTTA_GROUP, TERRACOTTA_PAMS,
                     transform=adapt_animation)
    pack_terracotta_atlas(target, manifest)
    add_terracotta_ruin_animation(target, manifest, pams)

    legacy, = [row["objdata"] for row in level_document(resource(target, SHEET_PACKAGE), SHEET_PACKAGE)["objects"]
               if "ZombieMausoleumDefault" in row.get("aliases", ())]
    sheets = ("ZombieQinTaoistDefault", "ZombieQinTerracottaSmall", "ZombieQinTerracottaMid")

    def adapt_types(rows):
        for name, row in rows.items():
            row["objdata"].update(ZombieClass="ZombieBasic", AnimRigClass="ZombieAnimRig_Tutorial",
                                  AudioGroups=[], BoardAlmanac=name == TAOIST)

    def adapt_sheets(rows):
        taoist = rows[sheets[0]]["objdata"]
        assert taoist.pop("StartAttackCloumn") == 7 and taoist.pop("ActionCoolDown") == 10
        assert taoist.pop("TransToZombie") == TERRACOTTA_SMALL
        assert taoist.pop("TransFromZombies") == [
            "mausoleum_basic", "mausoleum_armor1", "mausoleum_armor2", "mausoleum_flag",
        ]
        del taoist["ScaledProps"]
        taoist.update(SizeType=legacy["SizeType"], ZombieLevelStats=legacy["ZombieLevelStats"])
        for name, row in rows.items():
            row["objclass"] = "ZombiePropertySheet"
            stats = row["objdata"]
            # The older ground-track player advances faster with these clips.
            stats["Speed"] = round(stats["Speed"] * 0.75, 4)
            stats["SpeedVariance"] = 0
            if name != sheets[0]:
                assert stats.pop("AttackUpPlantList") == ["moton", "agave", "lemon"]
                assert stats.pop("AttackUpRate") == 2.0

    append_definitions(target, donor, TYPE_PACKAGE, (TAOIST, TERRACOTTA_SMALL, TERRACOTTA_GENERAL), adapt_types)
    append_definitions(target, donor, SHEET_PACKAGE, sheets, adapt_sheets)
    add_strings(target, donor, (TAOIST,))
    replace_rton(target, GRID_TYPES, lambda doc: clone_definition(
        doc, "lilypad_untouch", TERRACOTTA_RUIN, TypeName=TERRACOTTA_RUIN,
        ResourceGroups=[TERRACOTTA_GROUP], Properties="RTID(QinTerracottaRuin@PropertySheets)",
    ), allow_growth=True)
    replace_rton(target, SHEET_PACKAGE, lambda doc: clone_definition(
        doc, "GridItemLilyPadUnTouchDefault", "QinTerracottaRuin", PopAnim=TERRACOTTA_RUIN_PAM,
        PopAnimRenderOffset={"x": 97, "y": 123},
    ), allow_growth=True)


def orient_archer_arrow(bundle, manifest):
    group = ARCHER_GROUP + "_1536"
    index = group_index(bundle, group)
    name, entry = bundle.files(index)[0]
    kind, offset, size, _, _, _, width, height = entry
    assert kind == 1 and offset == 0 and size == width * height * 4
    flight_image, = [
        row for row in manifest_group(manifest, group)
        if row["id"] == "IMAGE_EFFECTS_ZOMBIE_MAUSOLEUM_ARCHER_BULLET_ZOMBIE_MAUSOLEUM_ARCHER_BULLET_21X94"
    ]
    x, y, w, h = (flight_image[key] for key in ("ax", "ay", "aw", "ah"))
    image = Image.frombytes("RGBA", (width, height), texture_section(bundle.payloads[index])[:size])
    # Legacy arc rendering rotates a left-facing arrow along the arc's slope.
    # Rotate the donor artwork in its own slice to keep its anchor and trail.
    arrow = image.crop((x, y, x + w, y + h)).transpose(Image.Transpose.ROTATE_180)
    image.paste(arrow, (x, y))
    replace_section(bundle, index, [(name, entry)], b"", image.tobytes())


def add_qin_mower(target, donor, steam, manifest):
    add_group(target, manifest, steam, MOWER_GROUP, (MOWER_PAM,))
    resize_qin_atlas(target, manifest, MOWER_GROUP, (512, 1024))
    append_definitions(target, donor, LEVEL_MODULES, (MOWER_MODULE,))


def use_qin_mower(document):
    definition, = [r["objdata"] for r in document["objects"] if r["objclass"] == "LevelDefinition"]
    modules = definition["Modules"]
    original = "RTID(EgyptMowers@LevelModules)"
    modules[modules.index(original)] = f"RTID({MOWER_MODULE}@LevelModules)"


def use_qin_music(document):
    definition, = [r["objdata"] for r in document["objects"] if r["objclass"] == "LevelDefinition"]
    definition["MusicType"] = "MiniGame_A"


def update_stage(document, stage):
    definition, = [r["objdata"] for r in document["objects"] if r["objclass"] == "LevelDefinition"]
    definition["StageModule"] = f"RTID({stage}@LevelModules)"
    use_qin_mower(document)
    use_qin_music(document)
    default = "RTID(DefaultSeedBank@LevelModules)"
    modules = definition["Modules"]
    assert default in modules
    modules[modules.index(default)] = "RTID(QinSampleSeedBank@CurrentLevel)"
    document["objects"].append({
        "objclass": "SeedBankProperties", "aliases": ["QinSampleSeedBank"],
        "objdata": {"SelectionMethod": "preset", "PresetPlantList": list(QIN_TEST_PLANTS)},
    })


def update_encounter(document, *, prepared=False):
    level, waves = document["objects"][:2]
    if not prepared:
        update_stage(document, CURVED_STAGE)
        level["objdata"]["StartingSun"] = 2000
    encounters = (
        ((TAOIST, 2), ("mausoleum_armor1", 2), (TERRACOTTA_GENERAL, 4)),
        ((ASSASSIN, 2),),
        ((SHIELD_TRIAD, 4),),
        ((DRUNKARD, 1),),
        ((ARCHER, 2),),
        ((RIDER, 5),),
        ((PIGGY, 5),),
        ((VENDOR, 5),),
        (("mausoleum_basic", 1), ("mausoleum_armor1", 2), ("mausoleum_armor2", 4)),
        (("mausoleum_flag", 2), ("mausoleum_gargantuar", 4)),
    )
    pool = {}
    schedule = []
    for encounter in encounters:
        entries = []
        for name, row in encounter:
            entry = pool.setdefault(name, {"Type": f"RTID({name}@ZombieTypes)"})
            entries.append({**entry, "Row": str(row), "Level": 1})
        schedule.append(dict(DisableRandomSpawns=True, WaitUntilAllZombiesDie=True, Zombies=entries))
    # Preload followers even though the formation spawns them through native code.
    for name in (SHIELD_SEGMENT, TERRACOTTA_SMALL):
        pool[name] = {"Type": f"RTID({name}@ZombieTypes)"}
    waves["objdata"].update(WaveCount=len(schedule), FlagWaveInterval=len(schedule) + 1,
                            AddToZombiePool=list(pool.values()), Waves=schedule)


def clone_definition(document, source_alias, alias, **properties):
    assert not any(alias in row.get("aliases", []) for row in document["objects"])
    source, = [row for row in document["objects"] if source_alias in row.get("aliases", [])]
    entry = deepcopy(source)
    entry.pop("uid", None)
    entry["aliases"] = [alias]
    entry["objdata"].update(properties)
    document["objects"].append(entry)
    return entry


def add_haystack(bundle, donor):
    replace_rton(bundle, PLANT_TYPES, lambda doc: clone_definition(
        doc, "lilypad", HAY, TypeName=HAY, Properties="RTID(QinHaystack@PropertySheets)",
        PlantResourceGroups=[HAY_GROUP], PopAnim=HAY_PAM, HomeWorld="mausoleum",
    ), allow_growth=True)
    replace_rton(bundle, GRID_TYPES, lambda doc: clone_definition(
        doc, "lilypad", HAY_GRID, TypeName=HAY_GRID, Properties="RTID(QinHaystackGrid@PropertySheets)",
        ResourceGroups=[HAY_GROUP],
    ), allow_growth=True)

    def append_haystack_properties(document):
        clone_definition(document, "LilyPadDefault", "QinHaystack", ValidStages=["mausoleum"])
        clone_definition(document, "GridItemLilyPadDefault", "QinHaystackGrid", PopAnim=HAY_PAM, Height="normal")

    replace_rton(bundle, SHEET_PACKAGE, append_haystack_properties, allow_growth=True)
    strings = resource(donor, LAWN_STRINGS).decode("utf-8-sig")
    key = "PLANT_UNCHARTED_HAYSTACK"
    entry = re.search(r"(?m)^\[" + key + r"\][ \t]*\r?\n([^\r\n]+)", strings)
    value = entry[1] if entry else "草垛"
    index, = [i for i in range(len(bundle.groups)) if LAWN_STRINGS in dict(bundle.files(i))]
    files = dict(bundle.files(index))
    previous = resource(bundle, LAWN_STRINGS)
    newline = b"\r\n" if b"\r\n" in previous else b"\n"
    payload = previous + newline * 2 + f"[{key}]".encode("ascii") + newline + value.encode("utf-8") + newline
    data = package_data(bundle.payloads[index])
    files[LAWN_STRINGS] = (0, len(data), len(payload))
    replace_section(bundle, index, files.items(), data + payload)


def add_seed_packet(bundle, packet, offsets, encoder, work, *, image_id, alias, origin):
    # The stock seed renderer uses the resident card atlas.
    index = group_index(bundle, UI_IMAGES)
    manifest_index, manifest_path, manifest = bundle.manifest()
    images = manifest_group(manifest, UI_IMAGES)
    atlas = "ATLASIMAGE_ATLAS_UIIMAGES_1536_00"
    _, start, size, slot, _, _, width, height = dict(bundle.files(index))[r"ATLASES\UIIMAGES_1536_00.PTX"]
    first = struct.unpack_from("<I", bundle.infos[index], 200)[0]
    fmt = struct.unpack_from("<I", bundle.textures[first + slot], 12)[0]
    assert (fmt, width, height) == (161, 4096, 4096)
    block = 5
    x, y = origin
    tile_width, tile_height = ((extent + 4 + block - 1) // block * block for extent in packet.size)
    assert x >= 0 and y >= 0 and not (x % block or y % block)
    assert x + tile_width <= width and y + tile_height <= height
    for image in images:
        assert image["id"] != image_id
        if image.get("parent") == atlas:
            left, top, w, h = (image[k] for k in ("ax", "ay", "aw", "ah"))
            assert (left + w <= x or top + h <= y or
                    left >= x + tile_width or top >= y + tile_height), image["id"]

    canvas = Image.new("RGBA", (tile_width, tile_height))
    canvas.paste(packet, (2, 2))
    png, astc = (work / f"{alias}-packet.{suffix}" for suffix in ("png", "astc"))
    canvas.save(png)
    subprocess.run([encoder, "-cl", png, astc, "5x5", "-thorough", "-silent"], check=True)
    encoded = astc.read_bytes()
    assert encoded[:7] == bytes.fromhex("13aba15c050501")
    blocks = encoded[16:]
    row_bytes = tile_width // block * 16
    assert len(blocks) == tile_height // block * row_bytes
    stride = (width + block - 1) // block * 16
    assert size == stride * ((height + block - 1) // block)
    group = bundle.payloads[index]
    assert struct.unpack_from("<I", group, 16)[0] & 1
    gpu = bytearray(texture_section(group))
    for row in range(tile_height // block):
        dest = start + (y // block + row) * stride + x // block * 16
        gpu[dest:dest + row_bytes] = blocks[row * row_bytes:(row + 1) * row_bytes]
    packed = pack_pool(gpu)
    gpu_start = struct.unpack_from("<I", group, 40)[0]
    group[gpu_start:] = packed
    struct.pack_into("<I", group, 44, len(packed))
    bundle.sync_info(index)
    images.append(dict(
        type="Image", id=image_id, parent=atlas, slot=manifest["slot_count"],
        path=["images", "1536", "UICommon", "UI", "packets", alias],
        ax=x + 2, ay=y + 2, aw=packet.width, ah=packet.height, aflags=15, **offsets,
    ))
    manifest["slot_count"] += 1
    bundle.replace_manifest(manifest_index, manifest_path, manifest)


def rebuild_card_resources(base, baseline, shim, packet, offsets, encoder, work,
                           *, image_id=HAY_PACKET, alias=HAY, origin=(5, 3990)):
    name = "uicommon.rsb.smf"
    archive_path = work / "resources.zip"
    stream = ResourceZip(base)
    try:
        with ZipFile(stream) as original, ZipFile(archive_path, "w", allowZip64=False) as target:
            for entry in original.infolist():
                if entry.filename != PREFIX + name:
                    copy_compressed_entry(original, entry, target)
                    continue
                prior = Bundle(original.read(entry))
                bundle = Bundle(prior.data)
                add_seed_packet(bundle, packet, offsets, encoder, work,
                                image_id=image_id, alias=alias, origin=origin)
                result = bundle.build()
                check = Bundle(result)
                assert check.manifest()[2] == bundle.manifest()[2]
                record = name.encode("ascii") + struct.pack(">I", entry.file_size)
                assert baseline.count(record) == 1 and len(result) != entry.file_size
                baseline = baseline.replace(record, name.encode("ascii") + struct.pack(">I", len(result)))
                shim, count = relocate_prefetch(shim, prior, check, changed_atlases=(UI_IMAGES,))
                assert count >= 55
                target.writestr(copy(entry), result)
                print(f"{name}: {entry.file_size} -> {len(result)}, {count} prefetch entries", flush=True)
    finally:
        stream.map.close()
        stream.file.close()
    return split_archive(archive_path, work), baseline, shim


def route_source(layouts, work):
    lines = ["struct Cell { int col; int row; };"]
    for day, layout in enumerate(layouts, 1):
        cells = [(item["GridX"], item["GridY"]) for item in layout]
        if cells[0][0] == 0:
            cells.reverse()
        assert cells[0][0] == 8 and cells[-1][0] == 0 and len(cells) == len(set(cells))
        assert all(abs(x - u) + abs(y - v) == 1 for (x, y), (u, v) in zip(cells, cells[1:]))
        content = ", ".join(f"{{{x}, {y}}}" for x, y in cells)
        lines.append(f"static constexpr Cell qinRoad{day}[] = {{{content}}};")
    (work / "qin_routes.inc").write_text("\n".join(lines) + "\n", encoding="ascii")


def build_guest(engine, ndk, work, layouts, qin_bank, moton_bank=b"", tea_bank=b"", zoybean_bank=b"",
                *, zoybean_showcase=False):
    if sha256(engine).hexdigest() != UPSTREAM:
        raise ValueError("Expected the A374 shared guest")
    elf = ELFFile(BytesIO(engine))
    segments = [(i, row) for i, row in enumerate(elf.iter_segments()) if row["p_type"] == "PT_LOAD"]
    (state_id, state), (segment_id, segment) = segments[-2:]
    assert segment["p_flags"] == 5 and segment["p_filesz"] == segment["p_memsz"]
    assert state["p_flags"] == 6 and state["p_filesz"] < state["p_memsz"]
    assert segment["p_offset"] + segment["p_filesz"] == len(engine)
    state_address = (state["p_vaddr"] + state["p_memsz"] + 15) & ~15
    padding = -len(engine) % 16
    origin = segment["p_vaddr"] + segment["p_filesz"] + padding
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    obj, linker, output = (work / f"qin-tunnel.{ext}" for ext in ("o", "ld", "elf"))
    source = ROOT / "src/mausoleum-tunnel/tunnel.cpp"
    route_source(layouts, work)
    defines = ["-DASTER_ZOYBEAN_SHOWCASE"] if zoybean_showcase else []
    subprocess.run([clang, *FLAGS, *defines, "-I", work, "-c", source, "-o", obj], check=True)
    linker.write_text(f"""ENTRY(asterQinTunnelStep)
SECTIONS {{
  . = {origin};
  .payload : {{ *(.text*) *(.rodata*) }}
  . = {state_address};
  .runtime (NOLOAD) : {{ *(.bss*) *(COMMON) }}
  /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }}
}}
""", encoding="ascii")
    subprocess.run([clang, "--target=armv7a-linux-androideabi24", "-nostdlib", "-static", "-Wl,--no-undefined",
                    "-Wl,-T," + str(linker), obj, "-o", output], check=True)
    with output.open("rb") as stream:
        payload = ELFFile(stream)
        section = payload.get_section_by_name(".payload")
        assert section["sh_addr"] == origin
        assert all(not sec["sh_size"] for sec in payload.iter_sections()
                   if sec.name.startswith((".rel", ".data", ".bss", ".got")))
        runtime = payload.get_section_by_name(".runtime")
        assert runtime["sh_addr"] == state_address and runtime["sh_type"] == "SHT_NOBITS"
        runtime_end = state_address + runtime["sh_size"]
        assert runtime_end <= segment["p_vaddr"]
        code = bytearray(section.data())
        code.extend(bytes(-len(code) % 4))
        symbols = {sym.name: sym["st_value"] for sym in payload.get_section_by_name(".symtab").iter_symbols()}

    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def append_stub(assembly, *, use_base=False):
        address = origin + len(code)
        footer = "\n.ltorg\nbasepoint: .word 0" if use_base else "\n.ltorg"
        stub = bytes(assembler.asm(assembly + footer, address)[0])
        if use_base:
            stub = stub[:-4] + struct.pack("<I", address + len(stub) - 4)
        code.extend(stub)
        return address

    base_code = "adr r0,basepoint\nldr ip,[r0]\nsub r0,r0,ip"
    trampoline = append_stub(f"""
        push {{r4,lr}}
        mov r1,r0
        {base_code}
        ldr r2,={OLD_UPDATE}
        add r2,r0,r2
        bl #{symbols['asterQinTunnelStep']}
        pop {{r4,pc}}
    """, use_base=True)
    sound_event = 0x1ecd30
    original_sound_event = append_stub(f"""
        push {{r11,lr}}
        b #{sound_event + 4}
    """)
    qin_sound_event = append_stub(f"""
        push {{r4,lr}}
        sub sp,sp,#40
        mov r3,r2
        mov r2,r1
        mov r1,r0
        {base_code}
        ldr r4,={original_sound_event}
        str r4,[sp]
        ldr r4,=0x51494e42
        add r4,r4,r0
        str r4,[sp,#4]
        ldr r4,={len(qin_bank)}
        str r4,[sp,#8]
        ldr r4,=0x4d4f5442
        add r4,r4,r0
        str r4,[sp,#12]
        ldr r4,={len(moton_bank)}
        str r4,[sp,#16]
        ldr r4,=0x54454142
        add r4,r4,r0
        str r4,[sp,#20]
        ldr r4,={len(tea_bank)}
        str r4,[sp,#24]
        ldr r4,=0x5a4f5942
        add r4,r4,r0
        str r4,[sp,#28]
        ldr r4,={len(zoybean_bank)}
        str r4,[sp,#32]
        bl #{symbols['asterQinMusicEvent']}
        add sp,sp,#40
        pop {{r4,pc}}
    """, use_base=True)
    string_sound_event = 0x1ecd54
    moton_sound_event = append_stub(f"""
        push {{r0,r1,r2,r3,ip,lr}}
        ldr r0,[r1]
        bl #{symbols['asterMotonAudioEvent']}
        cmp r0,#0
        pop {{r0,r1,r2,r3,ip,lr}}
        ldrne r1,[r1]
        bne #{sound_event}
        push {{r11,lr}}
        b #{string_sound_event + 4}
    """)
    impact_sound = 0x7b4538
    moton_impact = append_stub(f"""
        push {{r0,r1,r2,r3,ip,lr}}
        mov r1,r0
        {base_code}
        bl #{symbols['asterMotonImpact']}
        cmp r0,#0
        pop {{r0,r1,r2,r3,ip,lr}}
        bxne lr
        push {{r4,r5,r6,r11,lr}}
        b #{impact_sound + 4}
    """, use_base=True)
    place = 0x219134
    original_placement = append_stub(f"""
        push {{r4,r5,r6,r7,r8,r9,r10,r11,lr}}
        b #{place + 4}
    """)
    placement = append_stub(f"""
        push {{r4,lr}}
        sub sp,sp,#8
        mov r3,r2
        mov r2,r1
        mov r1,r0
        {base_code}
        ldr r4,={original_placement}
        add r4,r4,r0
        str r4,[sp]
        bl #{symbols['asterQinCanPlant']}
        add sp,sp,#8
        pop {{r4,pc}}
    """, use_base=True)
    ground = append_stub(f"""
        push {{r0-r4,lr}}
        {base_code}
        bl #{symbols['asterQinGroundAlias']}
        str r0,[sp,#4]
        pop {{r0-r4,lr}}
        push {{r4,lr}}
        blx #0x14ed0e0
        pop {{r4,pc}}
    """, use_base=True)
    chewable = append_stub(f"""
        push {{r4,lr}}
        mov r2,r1
        mov r1,r0
        {base_code}
        bl #{symbols['asterQinChewable']}
        pop {{r4,pc}}
    """, use_base=True)
    archer_projectile = append_stub(f"""
        push {{r0-r3,ip,lr}}
        mov r1,r0
        mov r2,r7
        {base_code}
        bl #{symbols['asterQinAimArrow']}
        pop {{r0-r3,ip,lr}}
        mov r0,r6
        bx lr
    """, use_base=True)
    archer_target = append_stub(f"""
        push {{r4,lr}}
        mov r1,r0
        {base_code}
        bl #{symbols['asterQinArcherCanShoot']}
        pop {{r4,pc}}
    """, use_base=True)
    drop_headgear = append_stub(f"""
        push {{r4,lr}}
        sub sp,sp,#8
        str r3,[sp]
        mov r3,r2
        mov r2,r1
        mov r1,r0
        {base_code}
        bl #{symbols['asterQinDropHeadgear']}
        add sp,sp,#8
        pop {{r4,pc}}
    """, use_base=True)
    begin_bite = append_stub(f"""
        push {{r4,lr}}
        mov r3,r2
        mov r2,r1
        mov r1,r0
        {base_code}
        bl #{symbols['asterQinBeginBite']}
        pop {{r4,pc}}
    """, use_base=True)
    projectile_hit = append_stub(f"""
        mov r2,r6
        b #{symbols['asterQinProjectileHit']}
    """)
    damage_site = 0xa4cb94
    original_damage = append_stub(f"""
        push {{r4-r11,lr}}
        b #{damage_site + 4}
    """)
    take_damage = append_stub(f"""
        push {{r4,lr}}
        mov r2,r1
        mov r1,r0
        {base_code}
        ldr r3,={original_damage}
        add r3,r3,r0
        bl #{symbols['asterQinTakeDamage']}
        pop {{r4,pc}}
    """, use_base=True)
    shield_formation = append_stub(f"""
        push {{r0-r4,lr}}
        bl #{symbols['asterQinShieldFollowers']}
        cmp r0,#0
        movne r9,r0
        pop {{r0-r4,lr}}
        bne #0xb07330
        ldr ip,=0x14ebd4d - 0xb07324
        add ip,lr,ip
        bx ip
    """)
    shield_segment = append_stub(f"""
        push {{r4,lr}}
        mov r2,r1
        mov r1,r0
        {base_code}
        bl #{symbols['asterQinShieldSegment']}
        pop {{r4,pc}}
    """, use_base=True)
    camel_sign = append_stub(f"""
        push {{r4,lr}}
        mov r3,r2
        mov r2,r1
        mov r1,r0
        {base_code}
        bl #{symbols['asterQinCamelSign']}
        pop {{r4,pc}}
    """, use_base=True)
    shield_body_hit = append_stub(f"""
        push {{r0-r5,ip,lr}}
        vpush {{d0-d7}}
        mrs r4,apsr
        mov r2,ip
        mov r1,r10
        {base_code}
        bl #{symbols['asterQinShieldBodyHit']}
        msr apsr_nzcvq,r4
        vpop {{d0-d7}}
        pop {{r0-r5,ip,pc}}
    """, use_base=True)
    shield_initialize = append_stub(f"""
        push {{r4,lr}}
        bl #0xa55aec
        mov r1,r7
        {base_code}
        bl #{symbols['asterQinShieldArt']}
        pop {{r4,pc}}
    """, use_base=True)
    plant_blocked_site = 0x4b5928
    plant_spray_blocked = append_stub(f"""
        push {{r0-r4,lr}}
        mov r1,r0
        {base_code}
        bl #{symbols['asterQinPlantSprayStunned']}
        cmp r0,#0
        strne r0,[sp]
        pop {{r0-r4,lr}}
        bxne lr
        push {{r3,r4,r11,lr}}
        b #{plant_blocked_site + 4}
    """, use_base=True)

    def plant_index_entry(site, saved, alias_offset):
        return append_stub(f"""
            push {{r0-r4,lr}}
            add r2,r1,#{alias_offset}
            mov r1,r0
            {base_code}
            bl #{symbols['asterQinHaystackLegacyId']}
            cmn r0,#1
            strne r0,[sp]
            pop {{r0-r4,lr}}
            bxne lr
            push {{{saved}}}
            b #{site + 4}
        """, use_base=True)

    plant_index = plant_index_entry(0x4978b8, "r3,r4,r5,r6,r11,lr", 0)
    plant_index_from_type = plant_index_entry(0x497bd8, "r4,r5,r6,r7,r11,lr", 4)
    plant_index_from_weak = append_stub(f"""
        push {{r0-r4,lr}}
        mov r2,r1
        mov r1,r7
        {base_code}
        bl #{symbols['asterQinHaystackLegacyId']}
        cmn r0,#1
        strne r0,[sp]
        pop {{r0-r4,lr}}
        bne #0x497b98
        push {{r4,lr}}
        blx #0x14ecb0c
        pop {{r4,pc}}
    """, use_base=True)

    def skip_unregistered_zombie(goal):
        # The two stock quest trackers assert on an alias missing from their enum.
        # General death handling and the global kill counter run at the caller.
        return append_stub(f"""
            push {{r0,r1,r2,r3,r4,lr}}
            ldr r0,[r1]
            bl #{symbols['asterQinSkipLegacyZombieGoal']}
            cmp r0,#0
            pop {{r0,r1,r2,r3,r4,lr}}
            movne r0,#0
            bxne lr
            b #{goal}
        """)

    hypno = append_stub(f"""
        push {{r0,r1,r2,r3,ip,lr}}
        mov r1,r7
        {base_code}
        bl #{symbols['asterQinImmuneToHypnosis']}
        cmp r0,#0
        pop {{r0,r1,r2,r3,ip,lr}}
        bne #0x6b030c
        ldr r3,[fp,#-0x28]
        b #0x6b01f8
    """, use_base=True)
    add_condition = 0xa4ab70
    qin_condition = append_stub(f"""
        push {{r0,r1,r2,r3,ip,lr}}
        {base_code}
        bl #{symbols['asterQinRejectCondition']}
        cmp r0,#0
        pop {{r0,r1,r2,r3,ip,lr}}
        bxne lr
        push {{r4,r5,r6,r7,r8,r9,r10,r11,lr}}
        b #{add_condition + 4}
    """, use_base=True)

    patches = [
        (UPDATE, branch(UPDATE, OLD_UPDATE), trampoline, False),
        (sound_event, bytes.fromhex("00482de9"), qin_sound_event, False),
        (string_sound_event, bytes.fromhex("00482de9"), moton_sound_event, False),
        (impact_sound, bytes.fromhex("70482de9"), moton_impact, False),
        (add_condition, bytes.fromhex("f04f2de9"), qin_condition, False),
        (0x6b01f4, bytes.fromhex("28301be5"), hypno, False),
        (place, bytes.fromhex("f04f2de9"), placement, False),
        (0x69dcfc, bytes.fromhex("f73c39fa"), ground, True),
        (0x4978b8, bytes.fromhex("78482de9"), plant_index, False),
        (0x497b28, bytes.fromhex("f75341fa"), plant_index_from_weak, True),
        (0x497bd8, bytes.fromhex("f0482de9"), plant_index_from_type, False),
        # Both target scans use GridItem::CanBeEatenBy. The following stock
        # chew-state and damage handlers already accept ordinary grid items.
        (0xa55140, bytes.fromhex("33ff2fe1"), chewable, True),
        (0xa42090, bytes.fromhex("33ff2fe1"), chewable, True),
        (0xab837c, bytes.fromhex("0600a0e1"), archer_projectile, True),
        (0xc1f154, branch(0xc1f154, 0xc1ec30, True), archer_target, True),
        (0xc1f238, branch(0xc1f238, 0xc1ec30, True), archer_target, True),
        (0xa4234c, bytes.fromhex("33ff2fe1"), drop_headgear, True),
        (0xa579d0, branch(0xa579d0, 0xa558f0, True), begin_bite, True),
        (0xa57a2c, branch(0xa57a2c, 0xa558f0, True), begin_bite, True),
        (0x7b46d0, bytes.fromhex("33ff2fe1"), projectile_hit, True),
        (damage_site, bytes.fromhex("f04f2de9"), take_damage, False),
        # Reuse the Camel's own linking and spacing with Qin follower counts and type.
        (0xb07320, bytes.fromhex("899227fa"), shield_formation, True),
        (0xb06374, bytes.fromhex("33ff2fe1"), shield_segment, True),
        (0xb06538, bytes.fromhex("33ff2fe1"), shield_segment, True),
        # The preview compares its unit against the same follower type before
        # expanding a formation. This also stops a follower expanding itself.
        (0xb07424, bytes.fromhex("33ff2fe1"), shield_segment, True),
        (0xb062b4, branch(0xb062b4, 0xa4367c, True), camel_sign, True),
        (0xb062ec, branch(0xb062ec, 0xa4367c, True), camel_sign, True),
        (0xb072e4, branch(0xb072e4, 0xa4367c), camel_sign, False),
        # Update the shields after the normal body HP store, which is shared
        # by projectiles, continuous damage and instant kills.
        (0xa4de54, bytes.fromhex("38c18ae5"), shield_body_hit, True),
        (0xb07300, branch(0xb07300, 0xa55aec, True), shield_initialize, True),
        (plant_blocked_site, bytes.fromhex("18482de9"), plant_spray_blocked, False),
    ]
    for site, goal in ((0x220664, 0x711c60), (0x220688, 0x723bc8)):
        patches.append((site, branch(site, goal, True), skip_unregistered_zombie(goal), True))
    if tea_bank:
        # The bite paths also carry the exact zombie for virtual plant damage
        # calls whose damage payload may not retain the actor.
        for site, damage, eater in (
            (0xa4471c, "r7", "r4"), (0xa448d8, "r8", "r4"), (0xa44adc, "r5", "r6"),
        ):
            tea_bite = append_stub(f"""
                push {{r4,lr}}
                sub sp,sp,#8
                str {damage},[sp]
                mov r3,{eater}
                mov r2,r1
                mov r1,r0
                {base_code}
                bl #{symbols['asterElectriciteaZombieBite']}
                add sp,sp,#8
                pop {{r4,pc}}
            """, use_base=True)
            patches.append((site, bytes(assembler.asm(f"blx {damage}", site)[0]), tea_bite, True))
        # Observe damage and swallowing at the plant entry points. Zombie
        # subclasses can apply bite damage without using the common caller.
        for site, prologue, hook in (
            (0x4bd5a4, "f04f2de9", "asterElectriciteaBite"),
            (0x4b4ab4, "f04b2de9", "asterElectriciteaSwallowed"),
        ):
            original = append_stub(f"""
                .word 0x{int.from_bytes(bytes.fromhex(prologue), "little"):08x}
                b #{site + 4}
            """)
            tap = append_stub(f"""
                mov r2,r1
                mov r1,r0
                {base_code}
                ldr r3,={original}
                add r3,r0,r3
                b #{symbols[hook]}
            """, use_base=True)
            patches.append((site, bytes.fromhex(prologue), tap, False))
    if zoybean_bank:
        ground_step = 0xa4c840
        native_track_delta = 0xa62abc
        zoybean_step = append_stub(f"""
            push {{r4,lr}}
            bl #{native_track_delta}
            mov r2,r0
            mov r1,r4
            {base_code}
            bl #{symbols['asterZoybeanGroundStep']}
            pop {{r4,pc}}
        """, use_base=True)
        patches.append((ground_step, branch(ground_step, native_track_delta, True), zoybean_step, True))
        plant_food_site = 0x4be00c
        original_food = append_stub(f"""
            push {{r4-r11,lr}}
            b #{plant_food_site + 4}
        """)
        zoybean_food = append_stub(f"""
            push {{r0,r4,r5,lr}}
            bl #{original_food}
            mov r4,r0
            ldr r1,[sp]
            {base_code}
            bl #{symbols['asterZoybeanPlantFood']}
            mov r0,r4
            add sp,sp,#4
            pop {{r4,r5,pc}}
        """, use_base=True)
        patches.append((plant_food_site, bytes.fromhex("f04f2de9"), zoybean_food, False))
    if zoybean_showcase:
        # InitialPlantEntryProperties passes -1 for the player-owned rank.
        # Change only the preset placements of Qin Day 1 in the test package.
        initial_plant_call = 0x7ce32c
        add_plant = 0x21ab00
        copy_args = "".join(f"ldr ip,[sp,#{32+i*4}]\nstr ip,[sp,#{i*4}]\n" for i in range(6))
        initial_plant = append_stub(f"""
            push {{r0-r4,lr}}
            mov r3,r2
            mov r2,r1
            mov r1,r0
            {base_code}
            bl #{symbols['asterZoybeanShowcaseRank']}
            cmp r0,#0
            beq ungraded
            str r0,[sp,#32]
            mov ip,#1
            str ip,[sp,#28]
            pop {{r0-r4,lr}}
            ldr ip,[sp,#8]
            push {{r4,lr}}
            mov r4,ip
            sub sp,sp,#24
            {copy_args}
            bl #{add_plant}
            add sp,sp,#24
            mov r1,r0
            mov r2,r4
            {base_code}
            bl #{symbols['asterZoybeanShowcaseSetRank']}
            pop {{r4,pc}}
        ungraded:
            pop {{r0-r4,lr}}
            b #{add_plant}
        """, use_base=True)
        patches.append((initial_plant_call, branch(initial_plant_call, add_plant, True), initial_plant, True))
        # Give cards played on Qin Day 1 a test rank before the native boost roll.
        for rank_site, rank_setter in (
            (0x4b6884, "r3"), (0x4b68c0, "r8"), (0x4b6f78, "r9"), (0x4b7050, "r8"),
        ):
            placed_rank = append_stub(f"""
                push {{r0,r4,r5,lr}}
                mov r4,{rank_setter}
                mov r2,r1
                mov r1,r0
                {base_code}
                bl #{symbols['asterZoybeanShowcasePlantedRank']}
                mov r1,r0
                mov ip,r4
                pop {{r0,r4,r5,lr}}
                bx ip
            """, use_base=True)
            old = bytes(assembler.asm(f"blx {rank_setter}", rank_site)[0])
            patches.append((rank_site, old, placed_rank, True))
    if tea_bank or zoybean_bank:
        original_update = append_stub("""
            push {r4-r11,lr}
            b #0x4bf3dc
        """)
        tea_update = append_stub(f"""
            mov r1,r0
            {base_code}
            ldr r2,={original_update}
            add r2,r0,r2
            b #{symbols['asterElectriciteaTick']}
        """, use_base=True)
        patches.append((0x4bf3d8, bytes.fromhex("f04f2de9"), tea_update, False))
    if moton_bank or tea_bank or zoybean_bank:
        moton_food_enabled = append_stub(f"""
            mov r1,r0
            {base_code}
            b #{symbols['asterMotonCanUsePlantFood']}
        """, use_base=True)
        patches.append((0x4f3924, bytes.fromhex("04b02de5"), moton_food_enabled, False))
        for index, site, prologue in (
            (0, 0x4bd0d4, "push {r4-r11,lr}"),
            (1, 0x4bf3a0, "str r11,[sp,#-4]!"),
        ):
            moton_action = append_stub(f"""
                push {{r0-r4,lr}}
                mov r1,r0
                mov r2,#{index}
                {base_code}
                bl #{symbols['asterMotonAction']}
                cmp r0,#0
                pop {{r0-r4,lr}}
                bxne lr
                {prologue}
                b #{site + 4}
            """, use_base=True)
            patches.append((site, bytes(assembler.asm(prologue, site)[0]), moton_action, False))
    native = bytearray(engine)
    for site, expected, replacement, link in patches:
        at = file_offset(elf, site, 4)
        assert native[at:at + 4] == expected
        native[at:at + 4] = branch(site, replacement, link)
    # Wwise loads this bank directly from memory and retains the pointer.
    # Give it static storage and the engine's required 16-byte alignment.
    code.extend(bytes(-(origin + len(code)) % 16))
    bank_offset = origin + len(code)
    bank_address = struct.pack("<I", 0x51494e42)
    assert code.count(bank_address) == 1
    struct.pack_into("<I", code, code.index(bank_address), bank_offset)
    moton_address = struct.pack("<I", 0x4d4f5442)
    assert code.count(moton_address) == 1
    audio_padding = bytes(-(bank_offset + len(qin_bank)) % 16) if moton_bank else b""
    moton_offset = bank_offset + len(qin_bank) + len(audio_padding)
    struct.pack_into("<I", code, code.index(moton_address), moton_offset)
    tea_address = struct.pack("<I", 0x54454142)
    assert code.count(tea_address) == 1
    tea_padding = bytes(-(moton_offset + len(moton_bank)) % 16) if tea_bank else b""
    tea_offset = moton_offset + len(moton_bank) + len(tea_padding)
    struct.pack_into("<I", code, code.index(tea_address), tea_offset)
    zoybean_address = struct.pack("<I", 0x5a4f5942)
    assert code.count(zoybean_address) == 1
    zoybean_padding = bytes(-(tea_offset + len(tea_bank)) % 16) if zoybean_bank else b""
    struct.pack_into("<I", code, code.index(zoybean_address), tea_offset + len(tea_bank) + len(zoybean_padding))
    native.extend(bytes(padding) + code + qin_bank + audio_padding + moton_bank + tea_padding + tea_bank
                  + zoybean_padding + zoybean_bank)
    size = len(native) - segment["p_offset"]
    struct.pack_into("<II", native, elf["e_phoff"] + elf["e_phentsize"] * segment_id + 16, size, size)
    struct.pack_into("<I", native, elf["e_phoff"] + elf["e_phentsize"] * state_id + 20,
                     runtime_end - state["p_vaddr"])
    return bytes(native)


def build(base, donor, output, sdk, ndk, signing, astc_encoder):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(donor) as source:
        data = Bundle(unwrap(source.read("assets/dynamic.rsb.smf")))
        modules = level_document(resource(data, LEVEL_MODULES), LEVEL_MODULES)
        by_alias = {name: row for row in modules["objects"] for name in row.get("aliases", [])}
        stage = by_alias["UnchartedMausoleumStage"]
        reference_level = r"PACKAGES\LEVELS\UNCHARTED_MAUSOLEUM_N_1.RTON"
        assert level_document(resource(data, reference_level), reference_level)["objects"][0]["objdata"][
            "MusicType"] == "MiniGame_A"
        stages = [stage_row(stage, STAGE, BACKGROUND), stage_row(stage, CURVED_STAGE, CURVED_BG)]
        layouts = tuple(by_alias[name]["objdata"]["Roads"]
                        for name in ("TunnelDefendDefaultX", "TunnelDefendDefault1"))
        art, offsets = read_board_art(source, *layouts)
        packet_art, packet_offsets = from_group(source, "dynamic", "UI_AlwaysLoaded_Dynamic_1200", [HAY_PACKET])
        donor_zombie = Bundle(unwrap(source.read("assets/zombie3.rsb.smf")))
        donor_drunkard = Bundle(unwrap(source.read("assets/zombie2.rsb.smf")))
        donor_plant = Bundle(unwrap(source.read("assets/plant3.rsb.smf")))
        donor_steam = Bundle(unwrap(source.read("assets/steam.rsb.smf")))
        donor_twister = Bundle(unwrap(source.read("assets/twister.rsb.smf")))
        donor_init = Bundle(unwrap(source.read("assets/init.rsb.smf")))
        qin_bank = chapter_audio(donor_twister, donor_init)
        del donor_init, donor_twister
    with ZipFile(base) as archive:
        dynamic = archive.read(ASSET)
        target = Bundle(dynamic)
        manifest_index, manifest_path, manifest = target.manifest()
        add_art(target, manifest, art, group_name=ART_GROUP)
        assets = manifest["groups"][-1]["resources"]
        for asset in assets:
            asset.update(offsets.get(asset["id"], {}))
        for suffix in ("_TEXTURE_LEFT", "_TEXTURE_RIGHT"):
            original, = [row for row in assets if row["id"] == BACKGROUND + suffix]
            assets.append(dict(original, id=CURVED_BG + suffix, slot=manifest["slot_count"]))
            manifest["slot_count"] += 1

        for role in ("Cavalry", "Piggy", "Vendor"):
            add_group(target, manifest, donor_zombie, f"ZombieMausoleum{role}Group",
                      ("POPANIM_ZOMBIE_ZOMBIE_MAUSOLEUM_" + role.upper(),), adapt=role != "Piggy")
        add_archer(target, data, donor_zombie, manifest)
        add_shield(target, data, donor_zombie, manifest)
        add_assassin(target, data, donor_zombie, manifest)
        add_taoist_and_terracotta(target, data, donor_zombie, manifest)
        add_drunkard(target, data, donor_drunkard, manifest)
        add_group(target, manifest, donor_plant, HAY_GROUP, (HAY_PAM,))
        add_qin_mower(target, data, donor_steam, manifest)
        for group, dimensions in QIN_ATLASES_1200.items():
            resize_qin_atlas(target, manifest, group, dimensions)
        orient_archer_arrow(target, manifest)
        del donor_zombie, donor_drunkard, donor_plant, donor_steam
        append_definitions(target, data, TYPE_PACKAGE, (RIDER, PIGGY, VENDOR), adapt_type)
        sheets = tuple(f"ZombieMausoleum{role}Default" for role in ("Cavalry", "Piggy", "Vendor"))
        append_definitions(target, data, SHEET_PACKAGE, sheets, adapt_sheet)
        add_strings(target, data, (RIDER, PIGGY, VENDOR))
        add_haystack(target, data)
        del data
        append_cn_user_credit(target, description="秦始皇陵第一部分棋盘、坑道、草垛、僵尸、小推车与战斗音乐提取自")
        replace_rton(target, LEVEL_MODULES, lambda doc: doc["objects"].extend(stages), allow_growth=True)
        replace_rton(target, TEST_LEVEL, update_encounter, allow_growth=True)
        target.replace_manifest(manifest_index, manifest_path, manifest)
        updated = target.build()
        assert Bundle(updated).manifest()[2] == manifest
        plan = create_plan(updated, output.parent, rgba_atlases=len(target.textures) - 2)
        dex = rebuild_dynamic_bootstrap(archive.read(BOOTSTRAP), output.parent / "bootstrap", dynamic, updated)
        engine_name = ARM64_ENGINE if ARM64_ENGINE in archive.namelist() else ENGINE
        shim_name = str(Path(engine_name).parent / "libRestart.so").replace("\\", "/")
        if engine_name == ARM64_ENGINE:
            shim_name = "assets/guest_libs/libRestart_a32.so"
        engine = build_guest(archive.read(engine_name), ndk, output.parent, layouts, qin_bank)
        manifest_data = manifest_version(archive.read(MANIFEST), 419, 374, prefix="A")
        baseline, shim = archive.read(BASELINE), archive.read(shim_name)
    parts, baseline, shim = rebuild_card_resources(
        base, baseline, shim, packet_art[HAY_PACKET], packet_offsets[HAY_PACKET],
        astc_encoder, output.parent,
    )
    pack_apk(base, {**parts, BASELINE: baseline, shim_name: shim, ASSET: updated, PLAN: plan,
                    BOOTSTRAP: dex, engine_name: engine, MANIFEST: manifest_data}, sdk, output, signing)
    for part in parts.values():
        part.unlink()
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "donor", "output", "sdk", "ndk", "signing", "astc-encoder"):
        parser.add_argument("--" + argument, type=Path, required=True)
    build(**vars(parser.parse_args()))
