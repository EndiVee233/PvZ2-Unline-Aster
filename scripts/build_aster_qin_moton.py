"""Build the Qin Day 1 Moton showcase from the current Aster APK."""

import argparse
from pathlib import Path
import re
import struct
from zipfile import ZipFile

from PIL import Image

from build_aster_compact_resources import BASELINE
from build_aster_mausoleum_battle import (
    ASSET, BOOTSTRAP, ENGINE, LAWN_STRINGS, LEVEL_MODULES, MANIFEST, PLAN, PLANT_TYPES, PROJECTILES,
    SHEET_PACKAGE, TEST_LEVEL, Bundle, add_group, append_definitions, build_guest, create_plan,
    from_group, level_document, manifest_version, pack_apk, package_data, rebuild_card_resources,
    rebuild_dynamic_bootstrap, replace_rton, replace_section, resize_qin_atlas, resource, unwrap,
)
from build_aster_qin_almanac import register_zombie_card_types
from prepare_aster_qin_native_music import ak_id, bank_chunks, bank_objects, write_bank


PLANT = "moton"
GROUP = "PlantMoton"
PAMS = ("POPANIM_PLANT_MOTON", "POPANIM_EFFECTS_MOTON_EFFECT")
PROJECTILE_ALIASES = ("MotonDefault", "MotonPfDefault")
PACKET = "IMAGE_UI_PACKETS_MOTON"
AUDIO = r"PLANT2_SOUNDBANKS\PLANT_MOTON.BNK"
AUDIO_EVENTS = ("Play_Plant_Moton_Fire", "Play_Plant_Moton_Fire_Hit",
                "Play_Plant_Moton_PF", "Play_Plant_Moton_PF_Hit")
VERSION = 432


def prepare_moton_bank(raw):
    chunks = bank_chunks(raw)
    objects = bank_objects(chunks)
    root = 590249123
    kind, mixer = objects[root]
    assert kind == 7 and len(mixer) == 236
    assert struct.unpack_from("<II", mixer, 3) == (2730816983, 0)
    assert mixer[14] == 0xc7 and struct.unpack_from("<H", mixer, 26)[0] == 4
    assert struct.unpack_from("<II", mixer, len(mixer) - 8) == (1, 1061931619)
    # Use the native plant SFX bus, with centered playback and no donor
    # game-parameter curves on the imported top-level mixer.
    mixer = mixer[:14] + b"\0" + mixer[15:26] + b"\0\0" + mixer[-8:]
    objects[root] = kind, mixer
    assert all(objects[ak_id(event)][0] == 4 for event in AUDIO_EVENTS)
    return write_bank(chunks, objects)


def adapt_type(rows):
    plant = rows[PLANT]["objdata"]
    plant.update(PlantFramework="PlantFramework", PlantAudioGroups=[GROUP])
    for field in ("PlantResourceGroups", "PlantPieceImageName", "AvatarPieceImageName", "Avatars"):
        plant.pop(field, None)


def adapt_sheet(rows):
    sheet = rows["MotonDefault"]
    props = sheet["objdata"]
    for field in ("DisplayActions", "DisplayAvatarActions"):
        del props[field]
    for action in props["Actions"]:
        action["ProjectileLaunchSound"] = ""
    # Use the stock secondary-projectile flag so only the PAM's plant-food
    # command can select this action.
    props["Actions"][1].update(Type="projectile", SecondaryAction=True)


def adapt_projectiles(rows):
    for row in rows.values():
        props = row["objdata"]
        del props["ClassName"]
        # The legacy engine serializes DamageType as a single enumerator.
        props["DamageType"] = props["DamageType"][0]
        props["DamageFlags"] = ["shooter"]


def add_plant_strings(target, donor, plant=PLANT, suffixes=("", "_DESCRIPTION_HEADER", "_DESCRIPTION", "_TOOLTIP")):
    source = resource(donor, LAWN_STRINGS).decode("utf-8-sig")
    strings = dict(re.findall(r"(?m)^\[([^\]\r\n]+)\][ \t]*\r?\n([^\r\n]+)", source))
    original = resource(target, LAWN_STRINGS)
    newline = "\r\n" if b"\r\n" in original else "\n"
    additions = []
    for suffix in suffixes:
        key = plant.upper() + suffix
        assert ("[" + key + "]").encode() not in original
        additions.extend((f"[{key}]", strings[key], ""))
    updated = original + (newline * 2 + newline.join(additions)).encode()
    index, = (i for i in range(len(target.groups)) if LAWN_STRINGS in dict(target.files(i)))
    files = dict(target.files(index))
    data = package_data(target.payloads[index])
    files[LAWN_STRINGS] = (0, len(data), len(updated))
    replace_section(target, index, files.items(), data + updated)


def add_to_showcase(document):
    level = document["objects"][0]["objdata"]
    assert level["LevelNumber"] == 1
    bank, = (row["objdata"] for row in document["objects"] if "QinSampleSeedBank" in row.get("aliases", []))
    slots = bank["PresetPlantList"]
    slots[slots.index("peashooter")] = PLANT
    waves, = (row["objdata"]["Waves"] for row in document["objects"] if "Waves" in row.get("aliases", []))
    waves[0]["Zombies"][1]["HasPlantFood"] = True


def build(base, donor, upstream, qin_bank, output, sdk, ndk, signing, astc_encoder):
    work = output.parent
    work.mkdir(parents=True, exist_ok=True)
    shim_name = ENGINE.rsplit("/", 1)[0] + "/libRestart.so"
    with ZipFile(base) as app, ZipFile(donor) as source:
        old = app.read(ASSET)
        target = Bundle(old)
        reference = Bundle(unwrap(source.read("assets/dynamic.rsb.smf")))
        plant_art = Bundle(unwrap(source.read("assets/plant3.rsb.smf")))
        packets, anchors = from_group(source, "dynamic", "UI_AlwaysLoaded_Dynamic_1200", [PACKET])
        index, path, manifest = target.manifest()
        add_group(target, manifest, plant_art, GROUP, PAMS)
        resize_qin_atlas(target, manifest, GROUP, (1024, 2048))
        target.replace_manifest(index, path, manifest)
        del plant_art
        append_definitions(target, reference, PLANT_TYPES, (PLANT,), adapt_type)
        append_definitions(target, reference, SHEET_PACKAGE, ("MotonDefault",), adapt_sheet)
        append_definitions(target, reference, PROJECTILES, PROJECTILE_ALIASES, adapt_projectiles)
        add_plant_strings(target, reference)
        replace_rton(target, TEST_LEVEL, add_to_showcase, allow_growth=True)
        modules = level_document(resource(reference, LEVEL_MODULES), LEVEL_MODULES)
        by_alias = {name: row["objdata"] for row in modules["objects"] for name in row.get("aliases", [])}
        layouts = tuple(by_alias[name]["Roads"] for name in ("TunnelDefendDefaultX", "TunnelDefendDefault1"))
        del reference
        moton_bank = prepare_moton_bank(resource(Bundle(unwrap(source.read("assets/plant2.rsb.smf"))), AUDIO))
        with ZipFile(upstream) as original:
            engine = register_zombie_card_types(build_guest(
                original.read(ENGINE), ndk, work, layouts, qin_bank.read_bytes(), moton_bank,
            ))
        updated = target.build()
        assert Bundle(updated).manifest()[2] == manifest
        plan = create_plan(updated, work, rgba_atlases=len(target.textures) - 2)
        dex = rebuild_dynamic_bootstrap(app.read(BOOTSTRAP), work / "bootstrap", old, updated)
        android_manifest = manifest_version(app.read(MANIFEST), VERSION, 423, prefix="A")
        baseline, shim = app.read(BASELINE), app.read(shim_name)
    del target, old
    packet = packets[PACKET]
    scale = 1536 / 1200
    packet = packet.resize(tuple(round(axis * scale) for axis in packet.size), Image.Resampling.LANCZOS)
    anchor = {key: round(value * scale) for key, value in anchors[PACKET].items()}
    parts, baseline, shim = rebuild_card_resources(
        base, baseline, shim, packet, anchor, astc_encoder, work, image_id=PACKET, alias=PLANT, origin=(120, 3940),
    )
    changes = {**parts, BASELINE: baseline, shim_name: shim, ASSET: updated, PLAN: plan,
               BOOTSTRAP: dex, MANIFEST: android_manifest, ENGINE: engine}
    pack_apk(base, changes, sdk, output, signing)
    for part in parts.values():
        part.unlink()
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "donor", "upstream", "qin-bank", "output", "sdk", "ndk", "signing", "astc-encoder"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
