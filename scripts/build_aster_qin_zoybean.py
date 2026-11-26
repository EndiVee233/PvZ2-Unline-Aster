"""Integrate Zoybean Pod and its friendly summons into Aster's Qin test level."""

import argparse
from copy import deepcopy
from functools import partial
from math import cos, radians, sin
from pathlib import Path
import struct
from zipfile import ZipFile

from PIL import Image

from build_aster_mausoleum_battle import (
    ASSET, BASELINE, BOOTSTRAP, ENGINE, LAWN_STRINGS, LEVEL_MODULES, MANIFEST, PLAN,
    PLANT_TYPES, PROJECTILES, SHEET_PACKAGE, TEST_LEVEL, TYPE_PACKAGE, Bundle, add_art, add_group,
    append_definitions, build_guest, create_plan, level_document, manifest_group, manifest_version,
    pack_apk, package_data, rebuild_card_resources, rebuild_dynamic_bootstrap, replace_rton,
    replace_section, resize_qin_atlas, resource, unwrap,
)
from build_aster_qin_almanac import register_zombie_card_types
from build_aster_qin_moton import prepare_moton_bank
from pam_transform_index import PamIndex
from prepare_opening_tutorial_resources import preload
from prepare_aster_cn_user_art import crop_sprites
from prepare_aster_qin_native_music import ak_id, bank_chunks, bank_objects, write_bank


PLANT = "zoybeanpod"
PLANT_ANIMATION = "POPANIM_PLANT_ZOYBEANPOD"
BATTLE_ANIMATION = f"{PLANT_ANIMATION}_BATTLE"
PLANT_SHEET = "ZoybeanpodDefault"
GATLING_ANIMATION = "POPANIM_ZOMBIE_ZOYBEANPOD_GATLINGPEA"
PACKET = "IMAGE_UI_PACKETS_ZOYBEANPOD"
SKILLS = r"PACKAGES\SKILLTYPES.RTON"
PROJECTILE = "ZombieZoybeanPodGatlingPeaDefault"
GATLING = "zombie_zoybeanpodgatlingpea"
GATLING_ARMORED = ("zoybeanpod_gatling_cone", "zoybeanpod_gatling_bucket")
GIANTS = ("zoybeanpod_gargantuar", "zoybeanpod_gargantuar2")
ACTORS = ("zoybeanpod_basic", "zoybeanpod_armor1", "zoybeanpod_armor2", GATLING, *GIANTS)
ACTOR_SHEETS = ("ZombieZoybeanPodBasic", "ZombieZoybeanPodArmor1", "ZombieZoybeanPodArmor2",
                "ZombieZoybeanpodGatlingPeaDefault", "ZombieZoybeanPodGargantuar")
SKILL_ROWS = ("Zoybeanpod_skill_level1", "Zoybeanpod_skill_level2")
SKILL_ICONS = tuple(f"IMAGE_UI_LEVELUP_ZOYBEANPOD_SKILL_LEVEL{i}" for i in (1, 5))
ART = (
    ("plant3", "PlantZoybeanPod", (1024, 1024)),
    ("zombie3", "ZombieZoybeanPodBasicGroup", (512, 1024)),
    ("zombie3", "ZombieZoybeanPodGargantuarGroup", (1024, 2048)),
    ("zombie3", "ZombieZoybeanPodGatlingpeaGroup", (512, 1024)),
)
VERSION = 451
BASE_VERSION = 444
GROWTH_CLIPS = (("idle", 0), ("transition", 43), ("idle2", 79), ("transition2", 120),
                ("idle3", 151), ("transition3", 172), ("idle4", 206), ("transition4", 266),
                ("water", 304))
CLIP_HOLD_FRAMES = 64
BIRTH_CLIPS = {
    "POPANIM_ZOMBIE_ZOYBEANPOD_ZOMBIE": ("born", 25),
    GATLING_ANIMATION: ("born", 25),
    "POPANIM_ZOMBIE_ZOYBEANPOD_GARGANTUAR": ("spawn", 16),
    "POPANIM_ZOMBIE_ZOYBEANPOD_GARGANTUAR_AVATAR": ("spawn", 16),
}


def attach_gatling_armor(raw, standard_raw):
    """Attach the six armor states to the donor's authored helmet track."""
    standard = PamIndex(standard_raw).sprites
    gatling_index = PamIndex(raw)
    gatling = gatling_index.sprites
    helmet = next(i for i, sprite in enumerate(gatling) if sprite["name"] == "Helmet")
    frames = gatling[-1]["frames"]
    armor_sprites = {sprite["name"]: i for i, sprite in enumerate(gatling)
                     if sprite["name"].startswith("zombie_armor_")}
    assert len(armor_sprites) == 6

    # The standard tofu's first walk frame gives the helmet poses relative
    # to its skull. Fit those poses to the narrower Gatling head.
    template = standard[-1]["frames"][134]
    parts = {standard[part["res"]]["name"]: part["index"] for part in template["adds"] if part["sprite"]}
    poses = {move["index"]: move for move in template["moves"]}
    skull = poses[parts["zombie_skull"]]
    assert skull["mat"] == (-1, 0, 0, 1)
    neutral = frames[134]
    assert neutral["label"] == "walk"
    tracks = {gatling[part["res"]]["name"]: part["index"] for part in neutral["adds"] if part["sprite"]}
    poses_at_rest = {move["index"]: move for move in neutral["moves"]}
    head_at_rest = poses_at_rest[tracks["_peashooter_head"]]
    helmet_at_rest = poses_at_rest[tracks["Helmet"]]
    assert head_at_rest["mat"] == helmet_at_rest["mat"] == skull["mat"]
    hx, hy = head_at_rest["pos"]
    hx_base, hy_base = helmet_at_rest["pos"]
    fit = 0.86
    local = []
    for name, sprite in armor_sprites.items():
        pose = poses[parts[name]]
        a, b, c, d = pose["mat"]
        x, y = pose["pos"]
        sx, sy = skull["pos"]
        a, b, c, d = -a * fit, -b * fit, c * fit, d * fit
        x, y = (sx - x) * fit, (y - sy) * fit
        cone = name.startswith("zombie_armor_cone_")
        art, = gatling[sprite]["frames"][0]["adds"]
        image = gatling_index.images[art["res"]]
        width, height = image["size"]
        im_a, _, _, im_d, im_x, im_y = image["mat"]
        center_x = im_x + width * im_a / 131072
        if cone:
            # Reverse the lean without changing the center of the carrot decal.
            x += 2 * a * center_x
            y += 2 * c * center_x
            a, c = -a, -c
        # Rotate each armor state around its own center so the brim sits on the crown.
        tilt = radians(-24 if cone else -28)
        cosine, sine = cos(tilt), sin(tilt)
        center_y = im_y + height * im_d / 131072
        aa, bb = cosine * a - sine * c, cosine * b - sine * d
        cc, dd = sine * a + cosine * c, sine * b + cosine * d
        x += (a - aa) * center_x + (b - bb) * center_y + 20 * (18 if cone else 8)
        y += (c - cc) * center_x + (d - dd) * center_y + 20 * 2
        a, b, c, d = aa, bb, cc, dd
        # Keep the brim behind and above the eye across animation and wear states.
        x += hx_base - hx - 20 * (64 if cone else 44)
        y += hy - hy_base - 20 * 18
        local.append((sprite, (a, b, c, d), (x, y)))

    assert max(part["index"] for frame in frames for part in frame["adds"]) < 997
    out = bytearray(raw[:frames[0]["start"]])
    helmet_tracks = {}
    for i, frame in enumerate(frames):
        record = bytearray(raw[frame["start"]:frame["end"]])
        if i == 538:
            # The separate particles clip already displays the detached pieces.
            assert frame["label"] == "particles"
            previous = frame["remove_records"]
            pos = previous[-1][1] - frame["start"] if previous else 1
            removed = b"".join(struct.pack("<H", 997 + j) for j in range(len(local)))
            if previous:
                assert record[1] != 255
                record[1] += len(local)
                record[pos:pos] = removed
            else:
                record[0] |= 1
                record[1:1] = bytes([len(local)]) + removed
        elif i < 538:
            for index in frame["rem"]:
                helmet_tracks.pop(index, None)
            for item in frame["adds"]:
                if item["sprite"] and item["res"] == helmet:
                    helmet_tracks[item["index"]] = ((1., 0., 0., 1.), (0, 0), 255)
            for move in frame["moves"]:
                if move["index"] in helmet_tracks:
                    _, _, alpha = helmet_tracks[move["index"]]
                    helmet_tracks[move["index"]] = (move["mat"], move["pos"],
                                                      move["color"][3] if move["color"] else alpha)
            assert len(helmet_tracks) <= 1
            (a, b, c, d), (x, y), alpha = next(iter(helmet_tracks.values()), ((1., 0., 0., 1.), (0, 0), 0))
            moves = bytearray()
            for j, (_, (aa, bb, cc, dd), (xx, yy)) in enumerate(local):
                matrix = (a * aa + b * cc, a * bb + b * dd, c * aa + d * cc, c * bb + d * dd)
                position = (x + a * xx + b * yy, y + c * xx + d * yy)
                moves.extend(struct.pack("<H4i2h4B", 0x3000 | (997 + j),
                                         *(round(v * 65536) for v in matrix),
                                         *(round(v) for v in position), 255, 255, 255, alpha))
            if frame["moves"]:
                start = frame["moves"][0]["start"] - frame["start"]
                count_offset = start - (3 if len(frame["moves"]) >= 255 else 1)
                count = len(frame["moves"]) + len(local)
                encoded = bytes([count]) if count < 255 else b"\xff" + struct.pack("<H", count)
                record[frame["events_start"] - frame["start"]:frame["events_start"] - frame["start"]] = moves
                record[count_offset:start] = encoded
            else:
                start = frame["events_start"] - frame["start"]
                record[0] |= 4
                record[start:start] = bytes([len(local)]) + moves
            if i == 0:
                add_count = frame["append_records"][0][0] - frame["start"] - 1
                add_end = frame["append_records"][-1][1] - frame["start"]
                assert record[add_count] == len(frame["adds"]) < 255 - len(local)
                record[add_count] += len(local)
                record[add_end:add_end] = b"".join(struct.pack("<HB", 0x8000 | (997 + j), sprite)
                                                    for j, (sprite, _, _) in enumerate(local))
        out.extend(record)
    updated = PamIndex(out).sprites[-1]["frames"]
    assert len(updated) == len(frames) and sum(part["index"] >= 997 for part in updated[0]["adds"]) == 6
    return bytes(out)


def face_gatling_right(raw, standard_raw):
    """Reflect the root around the same authored axis as the standard walk."""
    standard = PamIndex(standard_raw).sprites
    gatling = PamIndex(raw).sprites

    def heel_x(sprites):
        walk = sprites[-1]["frames"][134]
        heel = next(part["index"] for part in walk["adds"] if part["sprite"]
                    and sprites[part["res"]]["name"] == "zombie_foot_inner_heel")
        return next(move["pos"][0] for move in walk["moves"] if move["index"] == heel)

    doubled_axis = heel_x(standard) + heel_x(gatling)
    assert doubled_axis == 8180
    out = bytearray()
    start = 0
    for frame in gatling[-1]["frames"]:
        for move in frame["moves"]:
            flags = move["flags"]
            assert move["index"] < 1023
            at = move["start"] + 2
            if flags & 0x1000:
                a, b, c, d = struct.unpack_from("<4i", raw, at)
                at += 16
            elif flags & 0x4000:
                angle = struct.unpack_from("<h", raw, at)[0] / 1000
                a = d = round(cos(angle) * 65536)
                c = round(sin(angle) * 65536)
                b = -c
                at += 2
            else:
                a, b, c, d = 65536, 0, 0, 65536
            location = "<2i" if flags & 0x800 else "<2h"
            x, y = move["pos"]
            out.extend(raw[start:move["start"]])
            # PAM uses row-major affine terms: x' = a*x + b*y + tx.
            out.extend(struct.pack("<H4i", (flags & ~0x4000) | 0x1000, -a, -b, c, d))
            out.extend(struct.pack(location, doubled_axis - x, y))
            start = at + struct.calcsize(location)
    out.extend(raw[start:])
    return bytes(out)


def edit_animation(asset, raw, *, standard_tofu=None):
    if asset in BIRTH_CLIPS:
        if asset == GATLING_ANIMATION:
            raw = face_gatling_right(attach_gatling_armor(raw, standard_tofu), standard_tofu)
        label, first_visible = BIRTH_CLIPS[asset]
        frames = PamIndex(raw).sprites[-1]["frames"]
        first, visible = frames[0], frames[first_visible]
        assert first["label"] == label and not visible["label"]
        begin, insert = first["events_start"], visible["events_start"]
        record = raw[begin:begin + 2 + len(label)]
        updated = bytearray(raw)
        updated[visible["start"]] |= 8
        updated[insert:insert] = record
        updated[first["start"]] &= ~8
        del updated[begin:begin + len(record)]
        rebuilt = PamIndex(updated).sprites[-1]["frames"]
        assert len(rebuilt) == len(frames) and rebuilt[first_visible]["label"] == label
        return bytes(updated)
    if asset != PLANT_ANIMATION:
        return raw
    frames = PamIndex(raw).sprites[-1]["frames"]
    assert tuple((frame["label"], i) for i, frame in enumerate(frames) if frame["label"]) == GROWTH_CLIPS
    header = bytearray(raw[:frames[0]["start"]])
    count = len(frames) + (len(GROWTH_CLIPS) - 1) * CLIP_HOLD_FRAMES
    struct.pack_into("<Hhh", header, len(header) - 6, count, 0, count - 1)
    ends = {i - 1 for _, i in GROWTH_CLIPS[1:]}
    for i, frame in enumerate(frames):
        record = bytearray(raw[frame["start"]:frame["end"]])
        if i == 172:
            label = b"plantfood"
            event = frame["events_start"] - frame["start"]
            record[event:event + 2 + len(frame["label"])] = struct.pack("<H", len(label)) + label
        header.extend(record)
        if i in ends:
            # Aster advances PAMs on its render clock. Repeat the last pose
            # while the combat clock hands off to the next named clip.
            assert record[0] & 16
            header[-len(record)] &= ~16
            header.extend(bytes(CLIP_HOLD_FRAMES - 1) + b"\x10")
    result = bytes(header)
    assert len(PamIndex(result).sprites[-1]["frames"]) == count
    return result


def add_preview(bundle, manifest, donor):
    common = "PlantZoybeanPod_Common"
    entries = manifest_group(manifest, common)
    plant, = (entry for entry in entries if entry["id"] == PLANT_ANIMATION)
    preview = deepcopy(plant)
    raw = resource(donor, "\\".join(plant["path"]).upper())
    frames = PamIndex(raw).sprites[-1]["frames"]
    first_count = GROWTH_CLIPS[1][1]
    idle = bytearray(raw[:frames[first_count - 1]["end"]])
    struct.pack_into("<Hhh", idle, frames[0]["start"] - 6, first_count, 0, first_count - 1)
    assert [(i, frame["label"]) for i, frame in enumerate(PamIndex(idle).sprites[-1]["frames"])
            if frame["label"]] == [(0, "idle")]

    filename = Path(preview["path"][-1])
    preview["path"][-1] = filename.stem + "_Preview" + filename.suffix
    # Seed packet lookup derives its image ID from PlantType.PopAnim.
    plant["id"] = BATTLE_ANIMATION
    preview["slot"] = manifest["slot_count"]
    manifest["slot_count"] += 1
    entries.append(preview)
    group, = (i for i, entry in enumerate(bundle.groups) if entry["ID"] == common)
    files = dict(bundle.files(group))
    data = package_data(bundle.payloads[group])
    data += bytes(-len(data) % 4096)
    files["\\".join(preview["path"]).upper()] = (0, len(data), len(idle))
    replace_section(bundle, group, files.items(), data + idle, allow_header_growth=True)


def sprite_images(bundle, group_id, keys):
    group, = (row for row in bundle.manifest()[2]["groups"] if row["id"] == group_id)
    images = dict(crop_sprites(bundle, group, {key: key for key in keys}))
    offsets = {row["id"]: {k: row[k] for k in ("x", "y") if k in row}
               for row in group["resources"] if row["id"] in images}
    return {key: image.resize(tuple(round(size * 1536 / 1200) for size in image.size), Image.Resampling.LANCZOS)
            for key, image in images.items()}, {
                key: {k: round(value * 1536 / 1200) for k, value in offsets[key].items()} for key in offsets
            }


def adapt_type(rows):
    plant = rows[PLANT]["objdata"]
    plant.update(PlantFramework="PlantFramework", AnimRigClass="PlantAnimRig", HomeWorld="gacha",
                 PopAnim=PLANT_ANIMATION,
                 PlantAudioGroups=[group for _, group, _ in ART], AlmanacBackdropName="homeless")
    for name in ("PlantResourceGroups", "PlantPieceImageName", "AvatarPieceImageName"):
        plant.pop(name, None)


def use_native_boost(sheet):
    sheet["BoostRate"] = 0.5
    sheet["PlantLevelStats"][3]["AdvancedSkillType"] = "RTID(plant_wakeup_level1@SkillTypes)"


def adapt_sheet(rows):
    row = rows[PLANT_SHEET]
    original = row["objdata"]
    row["objclass"] = "PlantPropertySheet"
    row["objdata"] = {k: original[k] for k in ("Cost", "Hitpoints", "PacketCooldown", "PlantGridType",
                    "PlantFoodPlayCount", "SeedChooserPreviewAdjust", "ArtCenter", "PlantStats")}
    row["objdata"].update(MinLevel=1, MaxLevel=4, PlantFoodDurationSeconds=72 / 30,
                         IdleAnimationWeights={"idle": 1}, PlantFoodActivationSound="")
    row["objdata"]["Actions"] = [{
        "Type": "projectile", "TriggerType": "manual", "Projectile": f"RTID({PROJECTILE}@ProjectileTypes)",
        "Damage": 60, "CooldownTimeMin": 12, "CooldownTimeMax": 12,
    }]
    row["objdata"]["PlantLevelStats"] = original["PlantLevelStats"][:4]
    use_native_boost(row["objdata"])
    row["objdata"]["DisplayActions"] = [
        {"DisplayPlants": [{"PlantName": PLANT, "PosX": 0, "PosY": 1},
                           {"PlantName": "wallnut", "PosX": 4, "PosY": 1, "Hitpoint": 2000000}],
         "DisplayZombies": [{"ZombieName": "tutorial_armor2", "PosX": 6, "PosY": 1}],
         "DisplayTime": 20, "Level": level, "IsAvatar": False, "IsPlantfood": level == 4}
        for level in range(1, 5)
    ]
    row["objdata"]["DisplayAvatarActions"] = [{**row["objdata"]["DisplayActions"][-1],
                                                "IsAvatar": True, "Level": 1}]


def adapt_zombies(rows):
    for name, row in rows.items():
        zombie = row["objdata"]
        zombie.update(ZombieClass="ZombieBasic", AnimRigClass="ZombieAnimRig_Tutorial", BoardAlmanac=False,
                      HomeWorld="gacha", AudioGroups=[])
        if name in GIANTS:
            zombie["ResourceGroups"] = ["ZombieZoybeanPodGargantuarGroup"]


def adapt_zombie_sheets(rows):
    keys = ("ArtCenter", "AttackRect", "GroundTrackName", "HitRect", "Hitpoints", "ShadowOffset",
            "Speed", "ZombieLevelStats", "ZombieStats", "EatDPS")
    for alias, row in rows.items():
        source = row["objdata"]
        row["objclass"] = "ZombiePropertySheet"
        props = {k: source[k] for k in keys}
        # Aster signs the draw origin by facing. The donor art already faces
        # right, and its rig is kept unmirrored while the collision faces right.
        giant = alias == ACTOR_SHEETS[-1]
        props["ArtCenter"] = {**source["ArtCenter"], "x": -source["ArtCenter"]["x"] - (0 if giant else 8)}
        # Express the CN attack box toward the right-facing art in the
        # mirrored legacy coordinate system. Its dimensions stay identical.
        props["AttackRect"] = {**source["AttackRect"], "mX": -source["AttackRect"]["mX"]}
        props.update(SizeType="large" if giant else "small", CanSpawnPlantFood=False,
                     HeadDropFraction=-1, ArmDropFraction=-1, SpeedVariance=0)
        if alias in ACTOR_SHEETS[1:3]:
            cone = alias == ACTOR_SHEETS[1]
            armor = 370 if cone else 1100
            props.update(Helm="cone" if cone else "bucket", HelmHitpoints=armor,
                         Hitpoints=source["Hitpoints"] - armor)
        if alias == ACTOR_SHEETS[3]:
            props["EatDPS"] = 0
        row["objdata"] = props


def add_gatling_armor(document, *, sheets):
    name = ACTOR_SHEETS[3] if sheets else GATLING
    original, = (row for row in document["objects"] if name in row.get("aliases", ()))
    for alias, helm, health in zip(GATLING_ARMORED, ("cone", "bucket"), (370, 1100), strict=True):
        row = deepcopy(original)
        row["aliases"] = [alias]
        if sheets:
            row["objdata"].update(Helm=helm, HelmHitpoints=health)
        else:
            row["objdata"].update(TypeName=alias, Properties=f"RTID({alias}@PropertySheets)")
        document["objects"].append(row)


def adapt_projectile(rows):
    props = rows[PROJECTILE]["objdata"]
    props.pop("ClassName")
    props.update(CollisionFlags=["ground_zombies"], ProjectileType="CanBlock")


def add_showcase(document):
    seed_bank, = (row["objdata"] for row in document["objects"] if "QinSampleSeedBank" in row.get("aliases", ()))
    cards = seed_bank["PresetPlantList"]
    cards[cards.index("cabbagepult")] = PLANT
    preload(document, *(group for _, group, _ in ART))


def add_order_and_sheets(document):
    props, = (row["objdata"] for row in document["objects"] if "DefaultGameProps" in row.get("aliases", ()))
    for key in ("PlantTypeOrder", "PlantAlmanacOrder"):
        assert PLANT not in props[key]
        props[key].append(PLANT)
    add_gatling_armor(document, sheets=True)


def adapt_skill_icons(rows):
    rows[SKILL_ROWS[1]]["objdata"]["SkillIconImage"] = SKILL_ICONS[1]


def localize(bundle):
    strings = {
        "": "僵尸豆荚",
        "_DESCRIPTION_HEADER": "召唤豆腐僵尸，沿当前行向右攻击敌人",
        "_DESCRIPTION": "{KEYWORD}范围：{STAT}前方1行\n{KEYWORD}特点：{STAT}每12秒召唤一只友方豆腐僵尸。",
        "_TOOLTIP": "召唤向右攻击的豆腐僵尸",
        "_PLANTFOOD_DESCRIPTION": "召唤巨人豆腐僵尸，挥击同一行的敌人。",
        "_AVATAR_PLANTFOOD_DESCRIPTION": "召唤手持萝卜的巨人豆腐僵尸，挥击使敌人眩晕3秒。",
        "_SKILL_LEVEL1": "胡萝卜帽与西瓜帽",
        "_SKILL_LEVEL1_DES": "25%普通豆腐僵尸、50%胡萝卜帽、25%西瓜帽。",
        "_SKILL_LEVEL2": "机枪豆腐僵尸",
        "_SKILL_LEVEL2_DES": "5%普通、10%胡萝卜帽、75%西瓜帽、10%机枪。",
    }
    i, = (i for i in range(len(bundle.groups)) if LAWN_STRINGS in dict(bundle.files(i)))
    original = resource(bundle, LAWN_STRINGS)
    assert b"[ZOYBEANPOD]" not in original
    suffix = "".join(f"\r\n\r\n[ZOYBEANPOD{key}]\r\n{text}" for key, text in strings.items()).encode()
    entries = dict(bundle.files(i))
    data = package_data(bundle.payloads[i])
    entries[LAWN_STRINGS] = (0, len(data), len(original + suffix))
    replace_section(bundle, i, entries.items(), data + original + suffix)


def prepare_bank(raw, moton):
    chunks = bank_chunks(raw)
    objects = bank_objects(chunks)
    root = 1061931619
    kind, mixer = objects[root]
    assert kind == 7 and len(mixer) == 103 and struct.unpack_from("<II", mixer, 3) == (2730816983, 0)
    position = mixer.index(b"\xc7\0\0\1\0\0", 12)
    rtpc = position + 12
    assert struct.unpack_from("<H", mixer, rtpc)[0] == 1
    objects[root] = kind, mixer[:position] + b"\0" + mixer[position + 1:rtpc] + b"\0\0" + mixer[-8:]
    shared = objects.keys() & bank_objects(bank_chunks(moton)).keys()
    assert shared == {root}
    old, new = struct.pack("<I", root), struct.pack("<I", ak_id("Aster_Zoybean_Root"))
    remapped = {ak_id("Aster_Zoybean_Root") if key == root else key: (kind, body.replace(old, new))
                for key, (kind, body) in objects.items()}
    assert all(remapped[ak_id(f"Play_Plant_Zoybean_Transition_{i:02}")][0] == 4 for i in range(1, 5))
    return write_bank(chunks, remapped)


def build(base, donor, upstream, qin_bank, moton_bank, tea_bank, output, sdk, ndk, signing, astc_encoder):
    work = output.parent
    work.mkdir(parents=True, exist_ok=True)
    shim_name = ENGINE.rsplit("/", 1)[0] + "/libRestart.so"
    moton = prepare_moton_bank(moton_bank.read_bytes())
    with ZipFile(base) as app, ZipFile(donor) as cn:
        old = app.read(ASSET)
        target = Bundle(old)
        source = Bundle(unwrap(cn.read("assets/dynamic.rsb.smf")))
        index, path, manifest = target.manifest()
        for member in dict.fromkeys(member for member, _, _ in ART):
            art = Bundle(unwrap(cn.read(f"assets/{member}.rsb.smf")))
            art_manifest = art.manifest()[2]
            for source_member, group, dimensions in ART:
                if member != source_member:
                    continue
                animations = tuple(row["id"] for row in manifest_group(art_manifest, group + "_Common")
                                   if row["id"].startswith("POPANIM_"))
                standard_tofu = None
                if group == "ZombieZoybeanPodGatlingpeaGroup":
                    basic = next(row for row in manifest_group(art_manifest, "ZombieZoybeanPodBasicGroup_Common")
                                 if row["id"] == "POPANIM_ZOMBIE_ZOYBEANPOD_ZOMBIE")
                    standard_tofu = resource(art, "\\".join(basic["path"]).upper())
                add_group(target, manifest, art, group, animations,
                          transform=partial(edit_animation, standard_tofu=standard_tofu))
                resize_qin_atlas(target, manifest, group, dimensions)
                if group == "PlantZoybeanPod":
                    add_preview(target, manifest, art)
            del art
        icon_bundle = Bundle(unwrap(cn.read("assets/init.rsb.smf")))
        icons, _ = sprite_images(icon_bundle, "UI_LevelUp_1200", SKILL_ICONS)
        del icon_bundle
        add_art(target, manifest, icons, group_name="AsterZoybeanSkillIcons")
        target.replace_manifest(index, path, manifest)

        append_definitions(target, source, PLANT_TYPES, (PLANT,), adapt_type)
        append_definitions(target, source, SHEET_PACKAGE, (PLANT_SHEET,), adapt_sheet)
        append_definitions(target, source, TYPE_PACKAGE, ACTORS, adapt_zombies)
        append_definitions(target, source, SHEET_PACKAGE, ACTOR_SHEETS, adapt_zombie_sheets)
        append_definitions(target, source, PROJECTILES, (PROJECTILE,), adapt_projectile)
        append_definitions(target, source, SKILLS, SKILL_ROWS, adapt_skill_icons)
        replace_rton(target, TYPE_PACKAGE, lambda doc: add_gatling_armor(doc, sheets=False), allow_growth=True)
        replace_rton(target, SHEET_PACKAGE, add_order_and_sheets, allow_growth=True)
        replace_rton(target, TEST_LEVEL, add_showcase, allow_growth=True)
        localize(target)
        packets, anchors = sprite_images(source, "UI_AlwaysLoaded_Dynamic_1200", (PACKET,))
        modules = level_document(resource(source, LEVEL_MODULES), LEVEL_MODULES)
        by_alias = {a: row["objdata"] for row in modules["objects"] for a in row.get("aliases", ())}
        layouts = tuple(by_alias[name]["Roads"] for name in ("TunnelDefendDefaultX", "TunnelDefendDefault1"))
        del source
        audio_bundle = Bundle(unwrap(cn.read("assets/plant2.rsb.smf")))
        audio = prepare_bank(resource(audio_bundle, r"PLANT2_SOUNDBANKS\PLANT_ZOYBEAN.BNK"), moton)
        del audio_bundle
        with ZipFile(upstream) as original:
            engine = register_zombie_card_types(build_guest(original.read(ENGINE), ndk, work, layouts,
                                                            qin_bank.read_bytes(), moton, tea_bank.read_bytes(), audio))
        (work / "aster-zoybean.so").write_bytes(engine)
        dynamic = target.build()
        assert Bundle(dynamic).manifest()[2] == manifest
        plan = create_plan(dynamic, work, rgba_atlases=len(target.textures) - 2)
        dex = rebuild_dynamic_bootstrap(app.read(BOOTSTRAP), work / "bootstrap", old, dynamic)
        android_manifest = manifest_version(app.read(MANIFEST), VERSION, BASE_VERSION, prefix="A")
        baseline, shim = app.read(BASELINE), app.read(shim_name)
    del target, old
    parts, baseline, shim = rebuild_card_resources(base, baseline, shim, packets[PACKET], anchors[PACKET],
                                                   astc_encoder, work, image_id=PACKET, alias=PLANT, origin=(385, 3960))
    changes = {**parts, BASELINE: baseline, shim_name: shim, ASSET: dynamic, PLAN: plan,
               BOOTSTRAP: dex, MANIFEST: android_manifest, ENGINE: engine}
    pack_apk(base, changes, sdk, output, signing)
    for part in parts.values():
        part.unlink()
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for param in ("base", "donor", "upstream", "qin-bank", "moton-bank", "tea-bank", "output", "sdk", "ndk",
                  "signing", "astc-encoder"):
        parser.add_argument("--" + param, type=Path, required=True)
    build(**vars(parser.parse_args()))
