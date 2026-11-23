"""Prepare separate Arena definitions with the stock Pirate and West stages."""
from copy import deepcopy
from io import StringIO
import json

from prepare_offline_economy import Bundle, JSONDecoder, cipher
from prepare_offline_neighbor_catalog import decode, extract
from prepare_offline_pvp_seagull_hd import replace_section
from build_aster_legacy_endless_gameplay import package_data


PLANKS = "RTID(PiratePlanks@CurrentLevel)"
STAGES = {"pirate": "PirateStage", "west": "WestStage"}
ARENAS = {"battle": "arena_battle_test", "defense": "arena_plant_test"}


def level_definition(document):
    definition, = (item["objdata"] for item in document["objects"] if item["objclass"] == "LevelDefinition")
    return definition


def shop_definitions(bundle):
    pirate = decode(extract(bundle, "\\PIRATE1.RTON"))
    planks, = (item for item in pirate["objects"] if item["objclass"] == "PiratePlankProperties")
    planks["objdata"]["PlankRows"] = [0, 2, 4]
    for mode, arena in ARENAS.items():
        stock = decode(extract(bundle, f"\\{arena.upper()}.RTON"))
        for world, stage in STAGES.items():
            definition = deepcopy(stock)
            level = level_definition(definition)
            assert level["StageModule"] == "RTID(ArenaStage@LevelModules)"
            level["StageModule"] = f"RTID({stage}@LevelModules)"
            if world == "pirate":
                level["Modules"].insert(0, PLANKS)
                definition["objects"].append(deepcopy(planks))
            yield arena, f"arena_shop_{world}_{mode}", definition


def prepare_shop_terrain(original):
    bundle = Bundle(original)
    manifest_index, manifest_path, manifest = bundle.manifest()
    packages_index, = (i for i, group in enumerate(bundle.groups) if group["ID"] == "Packages")
    packages, = (group for group in manifest["groups"] if group["id"] == "Packages")
    resources = {item["id"]: item for item in packages["resources"]}
    previous = dict(bundle.files(packages_index))
    files = list(previous.items())
    data = bytearray(package_data(bundle.payloads[packages_index]))
    added = {}
    for arena, name, definition in shop_definitions(bundle):
        identifier = f"RESFILE_PACKAGES_LEVELS_{name.upper()}"
        assert identifier not in resources
        entry = deepcopy(resources[f"RESFILE_PACKAGES_LEVELS_{arena.upper()}"])
        entry.update(id=identifier, slot=manifest["slot_count"])
        entry["path"][-1] = name + ".rton"
        manifest["slot_count"] += 1
        packages["resources"].append(entry)
        path = "\\".join(entry["path"]).upper()
        assert path not in previous
        data.extend(bytes(-len(data) % 4096))
        raw = JSONDecoder().encode_root_object(StringIO(json.dumps(definition, ensure_ascii=False)))
        encoded = b"\x10\0" + cipher.encrypt(raw)
        files.append((path, (0, len(data), len(encoded))))
        data.extend(encoded)
        added[path] = definition

    prior_payloads = list(bundle.payloads)
    replace_section(bundle, packages_index, sorted(files), data)
    bundle.replace_manifest(manifest_index, manifest_path, manifest)
    updated = bundle.build()
    check = Bundle(updated)
    assert check.manifest()[2] == manifest
    check_files = dict(check.files(packages_index))
    assert all(check_files[key] == value for key, value in previous.items())
    after = package_data(check.payloads[packages_index])
    prior = package_data(prior_payloads[packages_index])
    assert after[:len(prior)] == prior
    assert all(decode(extract(check, name)) == value for name, value in added.items())
    assert all(payload == check.payloads[i] for i, payload in enumerate(prior_payloads)
               if i not in (manifest_index, packages_index))
    return updated
