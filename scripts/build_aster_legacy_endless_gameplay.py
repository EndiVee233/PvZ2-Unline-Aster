"""Restore the world-specific stage and standard Danger Room gameplay in Egypt."""
import argparse
from copy import deepcopy
from hashlib import sha256
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import struct
from zipfile import ZipFile
import zlib

from build_aster_pvp_feedback import pack_apk
from build_aster_rgba_background_pilot import ASSET, PLAN, create_plan
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_balance import Bundle, JSONDecoder, RTONDecoder, cipher, trie_write, u32
from prepare_offline_pvp_seagull_hd import replace_section
from rebuild_bootstrap_dex import rebuild_bootstrap


ROOT = Path(__file__).resolve().parents[1]
LEVEL = r"PACKAGES\LEVELS\EGYPT_DANGERROOM.RTON"
ACTIVITY_LEVEL = r"PACKAGES\LEVELS\FESTIVAL_DANGERROOM_LEVEL_ENDLESS.RTON"
ACTIVITY_STARTER = "sunflower"
ACTIVITY_STARTERS = (("peashooter", 2), ("cabbagepult", 6))
ACTIVITY_SUN_PLANTS = (
    ("sunflower", 1), ("twinsunflower", 35), ("sunshroom", 54),
    ("sunbean", 55), ("goldleaf", 93), ("toadstool", 99), ("birthsunflower", 308),
)
PROPERTY_SHEETS = r"PACKAGES\PROPERTYSHEETS.RTON"
LEVEL_MODULES = r"PACKAGES\LEVELMODULES.RTON"
LAST_STAND = "RTID(LastStand@CurrentLevel)"
BOOTSTRAP = "classes4.dex"
LAWN_STRINGS = r"PROPERTIES\LAWNSTRINGS.TXT"
ACTIVITY_WELCOME_KEY = b"[DANGER_ROOM_FESTIVAL_LEVEL_ENDLESS_TITLE_WELCOME]"


def package_data(block):
    start = u32(block, 24)
    section = bytes(block[start:start + u32(block, 28)])
    return zlib.decompress(section) if u32(block, 16) & 2 else section


def level_document(raw, name=LEVEL):
    data = cipher.decrypt(raw[2:]) if raw.startswith(b"\x10\0") else raw
    if data[:4] != b"RTON":
        raise ValueError("Invalid Egypt Danger Room resource")
    stream = BytesIO(data[4:])
    stream.name = name
    return json.loads(RTONDecoder(repairFiles=False).parse_root_object(stream))


def restore_egypt(document):
    objects = document["objects"]
    definition, = (item["objdata"] for item in objects if item["objclass"] == "LevelDefinition")
    if (definition["StageModule"] != "RTID(EgyptStageEndless@LevelModules)" or
            definition["ForceNextLevel"] != "egypt_dangerroom" or not definition["IsDangerRoom"] or
            definition["StartingSun"] != 1500 or definition["MusicType"] != "MiniGame_A" or
            definition["LevelNumber"] != 666):
        raise ValueError("Unexpected Egypt Danger Room configuration")
    last_stand, = (item for item in objects if item.get("aliases") == ["LastStand"])
    if last_stand["objclass"] != "LastStandMinigameProperties":
        raise ValueError("Unexpected Last Stand alias")
    definition["Modules"].remove(LAST_STAND)
    objects.remove(last_stand)
    definition["StageModule"] = "RTID(EgyptStage@LevelModules)"
    definition["LevelNumber"] = 11
    del definition["StartingSun"], definition["MusicType"]


def replace_rton(bundle, name, transform, *, allow_growth=False):
    index, = (i for i in range(len(bundle.groups)) if name in dict(bundle.files(i)))
    old = bundle.payloads[index]
    entries = dict(bundle.files(index))
    kind, offset, size = entries[name]
    if kind != 0:
        raise ValueError("Unexpected level resource type")
    data = bytearray(package_data(old))
    before = bytes(data[offset:offset + size])
    document = level_document(before, name)
    transform(document)
    encoded = JSONDecoder().encode_root_object(StringIO(json.dumps(document, ensure_ascii=False)))
    if before.startswith(b"\x10\0"):
        encoded = b"\x10\0" + cipher.encrypt(encoded)
    if level_document(encoded, name) != document:
        raise ValueError(f"RTON did not round-trip: {name}")
    if len(encoded) <= size:
        data[offset:offset + size] = encoded.ljust(size, b"\0")
    elif allow_growth:
        offset = len(data)
        size = 0
        data.extend(encoded)
        data.extend(bytes((-len(data)) % 4096))
    else:
        raise ValueError(f"Cannot replace {name} within its original allocation")
    entries[name] = (kind, offset, len(encoded))
    header = bytearray(old[:u32(old, 24)])
    table = trie_write(entries.items(), 1)
    table_offset = u32(header, 0x4c)
    if table_offset + len(table) > len(header):
        raise ValueError("RSG index exceeds the header allocation")
    header[table_offset:table_offset + len(table)] = table
    struct.pack_into("<I", header, 0x48, len(table))
    struct.pack_into("<I", header, 0x10, u32(header, 16) & ~2)
    struct.pack_into("<II", header, 28, len(data), len(data))
    struct.pack_into("<I", header, 40, len(header) + len(data))
    bundle.payloads[index] = header + data + old[u32(old, 40):]
    bundle.sync_info(index)
    updated = package_data(bundle.payloads[index])
    old_data = package_data(old)
    if updated[:offset] != old_data[:offset] or updated[offset + size:len(old_data)] != old_data[offset + size:]:
        raise ValueError("Unrelated package resources changed")
    if dict(bundle.files(index)) != entries:
        raise ValueError("Resource index did not round-trip")


def patch_resource(original):
    bundle = Bundle(original)
    replace_rton(bundle, LEVEL, restore_egypt)
    return bundle.build()


def alias_data(objects, alias):
    data, = (entry["objdata"] for entry in objects if alias in entry.get("aliases", ()))
    return data


def reward_moneybag(document):
    definition, = (entry["objdata"] for entry in document["objects"]
                   if entry["objclass"] == "LevelDefinition")
    for prefix in ("First", "Replay"):
        definition[prefix + "RewardType"] = "collectable"
        definition[prefix + "RewardParam"] = "moneybag"


def patch_egypt_waves(original, iris_data, local_alias, *, moneybag=False, activity_music=False,
                      activity_starter=False, activity_last_stand=False, activity_welcome=False):
    iris = json.loads(iris_data.read_text(encoding="utf-8"))["iris"]
    reference = alias_data(iris[PROPERTY_SHEETS], "DefaultDangerRoomProps")
    original_pool = alias_data(iris[LEVEL], "Waves")["ZombiePool"]
    pool = [zombie["Type"] for zombie in original_pool]
    if len(set(pool)) != 8 or "RTID(mummy@ZombieTypes)" not in pool:
        raise ValueError("Unexpected Iris Egypt wave pool")

    def update_level(level):
        if moneybag:
            reward_moneybag(level)
        generator = alias_data(level["objects"], "EgyptDangerRoomWaveGenerator")
        for key in ("StartingPoints", "BasePointIncrementPerWave", "BasePointIncrementPerLevel"):
            generator[key] = reference[key]
        # Convert the flat Iris pool to Aster's per-floor records. Iris's
        # zombies have no tier scaling in this level.
        generator["ZombiePoolConfigs"] = [
            dict(MinSpawnLevel=1, MaxSpawnLevel=999, ZombieType=zombie, Level=1)
            for zombie in pool
        ]
        graves = alias_data(level["objects"], "EgyptGravestoneGenerator")
        graves.update(reference["EgyptData"]["GravestoneData"])

    def add_wave_properties(sheets):
        objects = sheets["objects"]
        template = alias_data(objects, "DefaultDangerRoomProps")
        settings = deepcopy(template)
        settings["FlagWaveSetupList"] = [
            {key: int(value) for key, value in entry.items()}
            for entry in reference["FlagWaveSetupList"]
        ]
        for key in ("PlantfoodSetupList", "AssignMinPlantfoodPerFlagWave"):
            settings[key] = reference[key]
        objects.append(dict(objclass="DangerRoomPropertySheet", aliases=[local_alias], objdata=settings))
        if activity_starter or activity_last_stand:
            activity = alias_data(objects, "Festival_level_endlessDangerRoomProps")
            if activity["StartingPlants"] or ACTIVITY_STARTER not in activity["BlackList"]:
                raise ValueError("Unexpected activity Endless starter or offer blacklist")
            if activity_last_stand:
                activity["StartingPlants"] = [name for name, _ in ACTIVITY_STARTERS]
                activity["BlackList"] = activity_blacklist(activity["BlackList"])
            else:
                activity["StartingPlants"].append(ACTIVITY_STARTER)

    def activity_blacklist(existing):
        return list(dict.fromkeys([*existing, *(name for name, _ in ACTIVITY_SUN_PLANTS)]))

    def allow_activity_starter_in_chooser(level):
        plants = alias_data(level["objects"], "SeedBank")["PlantBlackList"]
        plants.remove(ACTIVITY_STARTER)

    def restore_activity_rewards(level):
        if not any(LAST_STAND in entry["objdata"].get("Modules", []) for entry in level["objects"]):
            raise ValueError("Activity Last Stand module is missing")
        chooser = alias_data(level["objects"], "SeedBank")
        chooser["PlantBlackList"] = activity_blacklist(chooser["PlantBlackList"])
        reward_moneybag(level)

    bundle = Bundle(original)
    replace_rton(bundle, LEVEL, update_level)
    replace_rton(bundle, PROPERTY_SHEETS, add_wave_properties, allow_growth=True)
    if activity_music:
        replace_rton(bundle, LEVEL_MODULES, use_tutorial_music_for_activity, allow_growth=True)
    if activity_last_stand:
        replace_rton(bundle, ACTIVITY_LEVEL, restore_activity_rewards, allow_growth=True)
    elif activity_starter:
        replace_rton(bundle, ACTIVITY_LEVEL, allow_activity_starter_in_chooser)
    if activity_welcome:
        add_activity_welcome(bundle)
    return bundle.build()


def add_activity_welcome(bundle):
    index, = (i for i in range(len(bundle.groups)) if LAWN_STRINGS in dict(bundle.files(i)))
    files = dict(bundle.files(index))
    kind, offset, size = files[LAWN_STRINGS]
    data = package_data(bundle.payloads[index])
    strings = data[offset:offset + size]
    newline = b"\r\n" if b"\r\n" in strings else b"\n"
    original_key = b"[DANGER_ROOM_EGYPT_TITLE_WELCOME]" + newline
    end_marker = b"[PVZ2_CHINESE_END]" + newline
    if (kind != 0 or ACTIVITY_WELCOME_KEY in strings or strings.count(original_key) != 1
            or not strings.endswith(end_marker) or strings.count(end_marker) != 1):
        raise ValueError("Unexpected Danger Room welcome strings")
    welcome = strings.split(original_key, 1)[1].split(newline, 1)[0]
    entry = newline.join((ACTIVITY_WELCOME_KEY, welcome, b"", end_marker))
    updated = strings[:-len(end_marker)] + entry
    files[LAWN_STRINGS] = (kind, len(data), len(updated))
    replace_section(bundle, index, files.items(), data + updated)


def use_tutorial_music_for_activity(level_modules):
    objects = level_modules["objects"]
    activity = alias_data(objects, "FestivalStageLevelEndless")
    tutorial = alias_data(objects, "TutorialStage")
    tutorial_audio, = (group for group in tutorial["ResourceGroupNames"] if group.startswith("Audio"))
    activity["MusicSuffix"] = tutorial["MusicSuffix"]
    if tutorial_audio not in activity["ResourceGroupNames"]:
        activity["ResourceGroupNames"].append(tutorial_audio)


def build(base, output, sdk, jdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(jdk / "bin") + os.pathsep + os.environ["PATH"]
    original = None
    for abi in ("ARM32", "ARM64"):
        source = base / f"PvZ2-Unline-Aster-A204-{abi}.apk"
        with ZipFile(source) as apk:
            dynamic = apk.read(ASSET)
            dex = apk.read(BOOTSTRAP)
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 205, 204, prefix="A")
        if original is None:
            original = dynamic
            updated = patch_resource(original)
            plan = create_plan(updated, output)
        elif dynamic != original:
            raise ValueError("ARM64 resources differ from ARM32")
        old_hash = sha256(original).hexdigest()
        new_hash = sha256(updated).hexdigest()
        literals = {old_hash: new_hash}
        if len(original) != len(updated):
            literals[hex(len(original))] = hex(len(updated))
        dex = rebuild_bootstrap(dex, output / f"bootstrap-{abi}", literals, ROOT.parent / "tools/apktool.jar")
        final = output / f"PvZ2-Unline-Aster-A205-{abi}.apk"
        pack_apk(source, {ASSET: updated, PLAN: plan, BOOTSTRAP: dex,
                          "AndroidManifest.xml": manifest}, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "jdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
