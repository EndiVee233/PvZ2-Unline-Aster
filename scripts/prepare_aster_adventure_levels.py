"""Read the shipped map and level definitions for the native adventure menu."""

from pathlib import Path
import json
import re
from zipfile import ZipFile

from build_aster_legacy_endless_gameplay import level_document, package_data
from index_texture_prefetch import ResourceZip
from merge_legacy_pvp_resources import Bundle


WORLDS = {
    "egypt": "神秘埃及",
    "pirate": "海盗港湾",
    "cowboy": "狂野西部",
    "kongfu": "功夫世界",
    "future": "未来世界",
    "dark": "黑暗时代",
    "beach": "巨浪沙滩",
    "iceage": "冰河世界",
    "skycity": "天空之城",
    "lostcity": "失落之城",
}
LEVELS = "PACKAGES\\LEVELS\\"
MAPS = "PACKAGES\\WORLDS\\"
MODULES = "PACKAGES\\LEVELMODULES.RTON"
STRINGS = "PROPERTIES\\LAWNSTRINGS.TXT"
REFERENCE = re.compile(r"RTID\(([^@]+)@(CurrentLevel|LevelModules)\)")
SPECIAL_MODULES = {
    "BowlingMinigameProperties", "CamelMinigameProperties", "CannonMinigameProperties",
    "CowboyMinigameProperties", "EliminateProperties", "EvilDaveProperties",
    "FishingProperties", "OakTrainProperties", "PooyanProperties", "RiverCrossingProperties",
    "SeedRainProperties", "SingleHandedProperties", "SnakeProperties", "SunBombChallengeProperties",
    "TowerDefendProperties", "VaseBreakerPresetProperties", "ZombossBattleModuleProperties",
    "ZombossMechBattleModuleProperties",
}
GOALS = {
    "BlowZombie": "吹走至少 {Count} 个僵尸",
    "KillZombiesInTime": "{Time} 秒内消灭 {ZombiesToKill} 个僵尸",
    "PlantBeforeLine": "不能种在发霉的地盘上",
    "PlantFoodNonuse": "最多使用 {Count} 个能量豆",
    "PlantFreeze": "最多允许 {Count} 株植物结冰",
    "PlantsLost": "最多损失 {MaximumPlantsLost} 株植物",
    "PlantsSurvive": "通关时至少保住 {Count} 株植物",
    "SaveBombs": "不要引爆任何炸药桶",
    "SaveMowers": "保住全部小推车",
    "SimultaneousPlants": "场上最多同时有 {MaximumPlants} 株植物",
    "SpendSunHoldout": "{HoldoutSeconds} 秒内不使用阳光",
    "SunProduced": "至少生产 {TargetSun} 阳光",
    "SunUsed": "最多使用 {MaximumSun} 阳光",
    "ZombieDistance": "别让僵尸踩坏花坛",
}
MAIN_GOAL = "击败所有僵尸，完成主线关卡"


def read_documents(apk):
    documents = {}
    strings = {}
    with ZipFile(ResourceZip(apk)) as archive:
        for member in archive.namelist():
            name = Path(member).name
            if name not in {f"{world}.rsb.smf" for world in (*WORLDS, "init", "dynamic")}:
                continue
            bundle = Bundle(archive.read(member))
            for index, payload in enumerate(bundle.payloads):
                entries = [(name, offset, size) for name, (kind, offset, size, *_) in bundle.files(index)
                           if kind == 0 and (name in (MODULES, STRINGS) or name.startswith((MAPS, LEVELS)))]
                if not entries:
                    continue
                data = package_data(payload)
                for name, offset, size in entries:
                    raw = data[offset:offset + size]
                    if name == STRINGS:
                        try:
                            source = raw.decode("utf-8-sig")
                        except UnicodeDecodeError:
                            source = raw.decode("gb18030", errors="replace")
                        strings.update((f"[{key}]", " ".join(value.split())) for key, value in
                                       re.findall(r"^\[([^\r\n\]]+)\]\s*\n(.*?)(?=^\[|\Z)", source, re.M | re.S))
                    elif name.endswith(".RTON"):
                        documents[name] = level_document(raw, name)
    return documents, strings


def write_packet_anchors(apk, output):
    """Keep the original atlas offsets when drawing cropped seed-packet sprites."""
    with ZipFile(ResourceZip(apk)) as archive:
        member = next(name for name in archive.namelist() if name.endswith("/uicommon.rsb.smf"))
        bundle = Bundle(archive.read(member))
    group = next(item for item in bundle.manifest()[2]["groups"] if item["id"] == "UIImages_1536")
    offsets = {
        item["id"].removeprefix("IMAGE_UI_PACKETS_"): (item.get("x", 0), item.get("y", 0))
        for item in group["resources"]
        if item["id"].startswith("IMAGE_UI_PACKETS_") and item["path"][-2] == "packets"
    }
    for key in ("READY", "FRAME_2", "FRAME_3", "FRAME_4"):
        if key not in offsets:
            raise ValueError(f"Missing original packet sprite {key}")
    entries = [f'    {{"{key}", {x}, {y}}},' for key, (x, y) in sorted(offsets.items())]
    (output / "adventure_packet_anchors.inc").write_text("\n".join(entries) + "\n", encoding="ascii")


def keyed(objects):
    return {alias: obj for obj in objects for alias in obj.get("aliases", ())}


def write_user_plants(apk, output):
    from build_aster_hud_pickup import ASSET

    with ZipFile(apk) as archive:
        bundle = Bundle(archive.read(ASSET))
    name = "PACKAGES\\PLANTTYPES.RTON"
    index, = (i for i in range(len(bundle.groups)) if name in dict(bundle.files(i)))
    _, offset, size = dict(bundle.files(index))[name]
    raw = package_data(bundle.payloads[index])[offset:offset + size]
    types = keyed(level_document(raw, name)["objects"])
    aliases = sorted(alias for alias in types if re.fullmatch(r"[a-z0-9_]{1,31}", alias))
    (output / "adventure_user_plants.inc").write_text(
        "".join(f'    "{alias}",\n' for alias in aliases), encoding="ascii")


def level_key(alias):
    if alias in ("egypt1", "egypt2"):
        return int(alias[-1])
    value = 2166136261
    for byte in alias.encode("ascii"):
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return 0x40000000 | (value & 0x3fffffff)


def objective(obj, strings):
    kind = obj["objclass"].removeprefix("StarChallenge").removesuffix("Props")
    data = obj["objdata"]
    if kind == "BeatTheLevel":
        return strings.get(data.get("Description"), "完成本关目标")
    return GOALS[kind].format(**data)


def collect_levels(documents, strings):
    shared = keyed(documents[MODULES]["objects"])
    catalog = {}
    ids = set()
    for world, world_title in WORLDS.items():
        world_doc = documents[f"{MAPS}{world.upper()}.RTON"]
        events = next(obj["objdata"]["m_eventList"] for obj in world_doc["objects"]
                      if obj["objclass"] == "WorldData")
        for event in events:
            if event["m_eventType"] != "level":
                continue
            alias = event["m_dataString"].lower()
            resource = documents.get(f"{LEVELS}{alias.upper()}.RTON")
            if not resource or alias in catalog:
                continue
            objects = resource["objects"]
            current = keyed(objects)
            definition, = (obj["objdata"] for obj in objects if obj["objclass"] == "LevelDefinition")

            def resolve(ref):
                match = REFERENCE.fullmatch(ref)
                if match:
                    table = current if match[2] == "CurrentLevel" else shared
                    return table.get(match[1])
                return None

            modules = [obj for ref in definition["Modules"] if (obj := resolve(ref))]
            challenges = [obj["objdata"] for obj in modules if obj["objclass"] == "StarChallengeModuleProperties"]
            if not challenges:
                continue
            star_module, = challenges
            tiers = star_module["Challenges"]
            if not 1 <= len(tiers) <= 3 or not all(tiers):
                raise ValueError(f"Unexpected star challenges in {alias}")
            stage = resolve(definition["StageModule"])
            unlocks = stage["objdata"].get("StarChallengeUnlockLevel", [])
            shown_day = event.get("m_displayText", "")
            if shown_day.isdecimal():
                title = f"{world_title} · 第 {shown_day} 天"
            else:
                mode = strings.get(definition.get("Name"), world_title)
                day = str(definition["LevelNumber"])
                title = (mode.replace("{LEVEL_NUMBER}", day) if "{LEVEL_NUMBER}" in mode
                         else f"{mode} · 第 {day} 天")
            flags = {obj["objclass"] for obj in modules}
            formation = not (flags & SPECIAL_MODULES)
            planks = next((obj["objdata"]["PlankRows"] for obj in modules
                           if obj["objclass"] == "PiratePlankProperties"), range(5))
            key = level_key(alias)
            if key in ids or not re.fullmatch(r"[a-z0-9_]{1,47}", alias):
                raise ValueError(f"Invalid or duplicate adventure level key for {alias}")
            ids.add(key)
            catalog[alias] = dict(
                key=key, title=title,
                goals=[MAIN_GOAL, *["\n".join(objective(resolve(ref), strings) for ref in tier) for tier in tiers]],
                unlocks=unlocks,
                always=star_module.get("ChallengesAlwaysAvailable", False),
                formation=formation,
                plank_rows=sum(1 << row for row in set(planks)),
            )
    return catalog


def make_catalog(apk, output):
    levels = collect_levels(*read_documents(apk))
    offsets = {}
    texts = []
    length = 0

    def text_offset(text):
        nonlocal length
        if text not in offsets:
            offsets[text] = length
            length += len(text) + 1
            texts.append("U" + json.dumps(text, ensure_ascii=False)[:-1] + '\\0"')
        return offsets[text]

    rows = []
    java_levels = {}
    for alias, entry in sorted(levels.items()):
        goals = entry["goals"]
        unlocks = entry["unlocks"]
        if len(unlocks) > 2 or any(len(alias) >= 32 for alias in unlocks):
            raise ValueError(f"Too many star unlock levels for {alias}")
        title = text_offset(entry["title"])
        conditions = [text_offset(value) for value in goals] + [0] * (4 - len(goals))
        rows.append(f'    {{"{alias}", {entry["key"]}, {len(goals)-1}, '
                    f'{str(entry["always"]).lower()}, {str(entry["formation"]).lower()}, '
                    f'{entry["plank_rows"]}, {title}, '
                    + "{" + ", ".join(map(str, conditions)) + "}, "
                    + "{" + ", ".join(map(json.dumps, unlocks)) + "}},")
        java_levels[alias] = [entry["key"], len(goals) - 1, entry["formation"]]
    (output / "adventure_levels.inc").write_text(
        "static constexpr char32_t levelTexts[] =\n    " + "\n    ".join(texts) + ";\n"
        "static constexpr LevelInfo levels[] = {\n" + "\n".join(rows) + "\n};\n", encoding="utf-8")
    catalog = json.dumps(java_levels, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (output / "adventure-levels.json").write_bytes(catalog)
    return catalog
