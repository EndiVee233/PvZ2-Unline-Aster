"""Build the Qin Day 1 Electrici-tea port from the 4.2.8 assets."""

import argparse
from copy import deepcopy
from pathlib import Path
import struct
import subprocess
import wave
from zipfile import ZipFile

from PIL import Image

from bake_rgba_resources import decode
from build_aster_hud_pickup import group_index
from build_aster_mausoleum_battle import (
    ASSET, BASELINE, BOOTSTRAP, ENGINE, LEVEL_MODULES, MANIFEST, PLAN,
    PLANT_TYPES, SHEET_PACKAGE, TEST_LEVEL, Bundle, add_group, append_definitions,
    build_guest, create_plan, from_group, level_document, manifest_group,
    manifest_version, pack_apk, rebuild_card_resources, rebuild_dynamic_bootstrap,
    replace_rton, resize_qin_atlas, resource, unwrap,
)
from build_aster_legacy_endless_gameplay import package_data
from build_aster_qin_almanac import register_zombie_card_types
from build_aster_qin_moton import add_plant_strings, prepare_moton_bank
from pam_transform_index import PamIndex
from prepare_aster_qin_native_music import ak_id, bank_chunks, bank_objects, write_bank
from prepare_offline_pvp_seagull_hd import replace_section, texture_section


PLANT = "electricitea"
GROUP = "PlantElectricitea"
PACKET = "IMAGE_UI_PACKETS_ELECTRICITEA"
ANIMATION = "POPANIM_PLANT_ELECTRICITEA"
SHEET = "ElectriciteaDefault"
VERSION = 444
INTERNATIONAL_MEDIA = {
    59116310: 614942744,
    128307160: 214902225,
    173728714: 494452004,
    179764614: 821068058,
    610075028: 450050439,
    624765489: 1039294224,
    631073945: 368666027,
}


def plant_food_animation(asset, raw):
    if asset != ANIMATION:
        return raw
    rig = PamIndex(raw)
    frames = rig.sprites[-1]["frames"]
    assert [frames[i]["label"] for i in (153, 162, 172, 208)] == [
        "plantfood_start", "plantfood_loop", "plantfood_end", "water",
    ]
    pulses = {158, 168, 178, 188, 198}
    rewritten = bytearray()
    previous = 0

    def text(value):
        encoded = value.encode()
        return struct.pack("<H", len(encoded)) + encoded

    for i in (98, *range(153, 208), 252):
        frame = frames[i]
        start, end = frame["start"], frame["end"]
        flags = raw[start] & ~(8 | 16 | 32)
        regular = i in (98, 252)
        if (regular or i == 207) and raw[start] & 16:
            flags |= 16
        label = frame["label"] if regular else "plantfood" if i == 153 else None
        commands = list(frame["commands"])
        if regular:
            commands = [command for command in commands if command[0] != "PlaySample"]
        if i in pulses:
            commands.append(("use_special", ""))
        if label:
            flags |= 8
        if commands:
            flags |= 32
        rewritten.extend(raw[previous:start])
        rewritten.append(flags)
        rewritten.extend(raw[start + 1:frame["events_start"]])
        if label:
            rewritten.extend(text(label))
        if commands:
            rewritten.append(len(commands))
            for command, parameter in commands:
                rewritten.extend(text(command) + text(parameter))
        previous = end
    rewritten.extend(raw[previous:])
    check = PamIndex(rewritten).sprites[-1]["frames"]
    assert len(check) == len(frames) and check[153]["label"] == "plantfood"
    assert sum(("use_special", "") in f["commands"] for f in check) == 5
    return bytes(rewritten)


def add_hit_effects(target, manifest, reed):
    """Keep the shared CN hit animations in the group that loads with Electrici-tea."""
    source_manifest = reed.manifest()[2]
    source_image_name = "PlantLightningReed_1200"
    source_image_group = group_index(reed, source_image_name)
    source_atlas, = (row for row in manifest_group(source_manifest, source_image_name) if row.get("atlas"))
    _, (kind, offset, size, _, _, _, width, height) = reed.files(source_image_group)[0]
    assert kind == 1 and (width, height) == (source_atlas["width"], source_atlas["height"])
    _, slot = struct.unpack_from("<II", reed.infos[source_image_group], 196)
    pixel_format = struct.unpack_from("<I", reed.textures[slot], 12)[0]
    texture = texture_section(reed.payloads[source_image_group])

    def scale(value):
        return round(value * 1536 / 1200)

    def append(rows, row):
        row["slot"] = manifest["slot_count"]
        manifest["slot_count"] += 1
        rows.append(row)

    atlas_group = group_index(target, GROUP + "_1536")
    atlas_rows = manifest_group(manifest, GROUP + "_1536")
    common_group = group_index(target, GROUP + "_Common")
    common_rows = manifest_group(manifest, GROUP + "_Common")
    common_files = dict(target.files(common_group))
    common_bytes = bytearray(package_data(target.payloads[common_group]))
    images = set()
    for row in manifest_group(source_manifest, "PlantLightningReed_Common"):
        if row["id"] not in ("POPANIM_EFFECTS_LIGHTNINGREED_HIT", "POPANIM_EFFECTS_LIGHTNINGREED_HIT_RED"):
            continue
        raw = resource(reed, "\\".join(row["path"]).upper())
        rig = PamIndex(raw)
        images.update(image["name"].split("|", 1)[1] for image in rig.images)
        new = deepcopy(row)
        new["id"] = new["id"].replace("LIGHTNINGREED", "ASTERTEAHITFX")
        new["path"][-1] = new["path"][-1].replace("lightningreed", "asterteahitfx")
        rewritten = raw.replace(b"LIGHTNINGREED", b"ASTERTEAHITFX")
        renamed = {image["name"].split("|", 1)[1] for image in PamIndex(rewritten).images}
        assert renamed == {image["name"].split("|", 1)[1].replace("LIGHTNINGREED", "ASTERTEAHITFX")
                           for image in rig.images}
        common_files["\\".join(new["path"]).upper()] = (0, len(common_bytes), len(rewritten))
        common_bytes.extend(rewritten)
        append(common_rows, new)
    assert images
    replace_section(target, common_group, common_files.items(), common_bytes, allow_header_growth=True)

    atlas_id = "ATLASIMAGE_ATLAS_ASTERTEAHITFX_1536_00"
    atlas_path = [*source_atlas["path"][:-1], "PLANTELECTRICITEA_1536_HIT_00"]
    width_out, height_out = scale(width), scale(height)
    append(atlas_rows, dict(source_atlas, id=atlas_id, path=atlas_path, width=width_out, height=height_out))
    for row in manifest_group(source_manifest, source_image_name):
        if row["id"] not in images:
            continue
        x, y, w, h = (row[key] for key in ("ax", "ay", "aw", "ah"))
        append(atlas_rows, dict(row, id=row["id"].replace("LIGHTNINGREED", "ASTERTEAHITFX"),
                                parent=atlas_id, ax=scale(x), ay=scale(y),
                                aw=scale(x + w) - scale(x), ah=scale(y + h) - scale(y)))
        images.remove(row["id"])
    assert not images

    image = Image.frombytes("RGBA", (width, height), decode(texture[offset:offset + size], width, height, pixel_format))
    pixels = image.resize((width_out, height_out), Image.Resampling.LANCZOS).tobytes()
    atlas_files = dict(target.files(atlas_group))
    atlas_bytes = bytearray(texture_section(target.payloads[atlas_group]))
    atlas_bytes.extend(bytes(-len(atlas_bytes) % 4096))
    count, first = struct.unpack_from("<II", target.infos[atlas_group], 196)
    assert first + count == len(target.textures)
    atlas_files["\\".join(atlas_path).upper() + ".PTX"] = (1, len(atlas_bytes), len(pixels), count, 0, 0,
                                                            width_out, height_out)
    atlas_bytes.extend(pixels)
    target.textures.append(bytearray(struct.pack("<6I", width_out, height_out, width_out * 4, 0, 0, 100)))
    struct.pack_into("<I", target.infos[atlas_group], 196, count + 1)
    replace_section(target, atlas_group, atlas_files.items(), b"", atlas_bytes, allow_header_growth=True)


def adapt_type(rows):
    plant = rows[PLANT]["objdata"]
    plant.update(PlantFramework="PlantFramework", AnimRigClass="PlantAnimRig", PlantAudioGroups=[GROUP])
    for field in ("PlantResourceGroups", "PlantPreviewResourceGroups", "PlantPieceImageName",
                  "AvatarPieceImageName", "Avatars"):
        plant.pop(field, None)


def adapt_sheet(rows):
    row = rows[SHEET]
    source = row["objdata"]
    row["objclass"] = "PlantPropertySheet"
    data = {key: source[key] for key in (
        "Cost", "Hitpoints", "MinLevel", "MaxLevel", "BoostRate", "PacketCooldown", "PlantGridType",
        "PlantFoodDurationSeconds", "ArtCenter", "IdleAnimationWeights", "PlantStats",
    )}
    data["DamageType"] = "lightning"
    data["PlantFoodPlayCount"] = 1
    # The ordinary attack is driven by the plant's grid-based update.
    data["Actions"] = [{
        "Type": "projectile", "Projectile": "RTID(PeaDefault@ProjectileTypes)",
        "CooldownTimeMin": 1.4, "CooldownTimeMax": 1.4, "TriggerType": "manual",
        "Damage": source["Actions"][0]["Damage"],
    }]
    data["PlantLevelStats"] = [
        {name: level[name] for name in ("AttackLevel", "HitPointsLevel", "PropertySkillType") if name in level}
        for level in source["PlantLevelStats"][:5]
    ]
    row["objdata"] = data


def international_pcm_media(raw, decoder, work):
    chunks = bank_chunks(raw, version=140)
    indexes = {key: (offset, size) for key, offset, size in struct.iter_unpack("<III", chunks[b"DIDX"])}
    assert set(indexes) == set(INTERNATIONAL_MEDIA.values())
    work.mkdir(parents=True, exist_ok=True)
    media = {}
    for legacy, source in INTERNATIONAL_MEDIA.items():
        offset, size = indexes[source]
        wem, wav = (work / f"electricitea-{source}.{suffix}" for suffix in ("wem", "wav"))
        wem.write_bytes(chunks[b"DATA"][offset:offset + size])
        subprocess.run([decoder, "-i", "-o", wav, wem], check=True, stdout=subprocess.DEVNULL)
        with wave.open(str(wav), "rb") as decoded:
            rate = decoded.getframerate()
            assert rate == 32000 and decoded.getnchannels() == 1 and decoded.getsampwidth() == 2
            pcm = decoded.readframes(decoded.getnframes())
        # Match the installed game's PCM WEM format, including the mono mask
        # and aligned start of the samples.
        fmt = struct.pack("<HHIIHHHHI", 0xfffe, 1, rate, rate * 2, 2, 16, 6, 0, 4)
        riff = (b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt +
                b"JUNK" + struct.pack("<II", 4, 0) + b"data" + struct.pack("<I", len(pcm)) + pcm)
        media[legacy] = b"RIFF" + struct.pack("<I", len(riff)) + riff
    return media


def prepare_tea_bank(raw, moton, media=None):
    chunks = bank_chunks(raw)
    objects = bank_objects(chunks)
    root = 1061931619
    kind, mixer = objects[root]
    assert kind == 7 and len(mixer) == 103
    assert struct.unpack_from("<II", mixer, 3) == (2730816983, 0)
    positioning = mixer.index(b"\xc7\0\0\1\0\0", 12)
    rtpc = positioning + 12
    assert struct.unpack_from("<H", mixer, rtpc)[0] == 1
    assert struct.unpack_from("<II", mixer, len(mixer) - 8) == (1, 33207767)
    objects[root] = kind, mixer[:positioning] + b"\0" + mixer[positioning + 1:rtpc] + b"\0\0" + mixer[-8:]
    if media:
        assert {row[0] for row in struct.iter_unpack("<III", chunks[b"DIDX"])} == set(media)
        data, index = bytearray(), bytearray()
        positions = {}
        start = 24 + len(chunks[b"BKHD"]) + len(chunks[b"DIDX"])
        for source, wem in sorted(media.items()):
            data.extend(bytes(-len(data) % 16))
            positions[source] = (start + len(data), len(wem))
            index.extend(struct.pack("<III", source, len(data), len(wem)))
            data.extend(wem)
        for object_id, (node_kind, body) in objects.items():
            if node_kind != 2:
                continue
            plugin, stream_type, source = struct.unpack_from("<IBI", body)
            assert plugin == 262145 and stream_type == 0 and source in positions
            sound = bytearray(body)
            struct.pack_into("<I", sound, 0, 65537)
            struct.pack_into("<II", sound, 13, *positions[source])
            objects[object_id] = node_kind, bytes(sound)
        chunks[b"DIDX"], chunks[b"DATA"] = index, data
    # The Chinese plant banks share actor-mixer IDs. Wwise indexes those
    # globally, so remap the shared nodes and links when both banks are loaded.
    shared = objects.keys() & bank_objects(bank_chunks(moton)).keys()
    renamed = {old: ak_id(f"Aster_Electricitea_{old}") for old in shared}
    assert set(renamed.values()).isdisjoint(objects)
    updated = {}
    for object_id, (kind, body) in objects.items():
        for old, new in renamed.items():
            body = body.replace(struct.pack("<I", old), struct.pack("<I", new))
        updated[renamed.get(object_id, object_id)] = kind, body
    for event in ("Attack", "Plantfood_Start", "Plantfood_Stop", "Water"):
        assert updated[ak_id("Play_Plant_ElectriciTea_" + event)][0] == 4
    return write_bank(chunks, updated)


def add_to_showcase(document):
    bank, = (row["objdata"] for row in document["objects"] if "QinSampleSeedBank" in row.get("aliases", []))
    cards = bank["PresetPlantList"]
    cards[cards.index("sunbean")] = PLANT


def build(base, donor, upstream, qin_bank, moton_bank, output, sdk, ndk, signing, astc_encoder,
          international_bank, vgmstream):
    work = output.parent
    work.mkdir(parents=True, exist_ok=True)
    shim_name = ENGINE.rsplit("/", 1)[0] + "/libRestart.so"
    moton = prepare_moton_bank(moton_bank.read_bytes())
    with ZipFile(base) as app, ZipFile(donor) as cn:
        old = app.read(ASSET)
        target = Bundle(old)
        source = Bundle(unwrap(cn.read("assets/dynamic.rsb.smf")))
        data = Bundle(unwrap(cn.read("assets/plant3.rsb.smf")))
        pams = tuple(row["id"] for row in manifest_group(data.manifest()[2], GROUP + "_Common")
                     if row["id"].startswith("POPANIM_"))
        index, path, manifest = target.manifest()
        add_group(target, manifest, data, GROUP, pams, transform=plant_food_animation)
        resize_qin_atlas(target, manifest, GROUP, (1024, 2048))
        add_hit_effects(target, manifest, Bundle(unwrap(cn.read("assets/plant1.rsb.smf"))))
        target.replace_manifest(index, path, manifest)
        del data
        append_definitions(target, source, PLANT_TYPES, (PLANT,), adapt_type)
        append_definitions(target, source, SHEET_PACKAGE, (SHEET,), adapt_sheet)
        add_plant_strings(target, source, PLANT, ("", "_DESCRIPTION_HEADER", "_DESCRIPTION", "_TOOLTIP",
                                                  "_PLANTFOOD_DESCRIPTION"))
        replace_rton(target, TEST_LEVEL, add_to_showcase, allow_growth=True)
        modules = level_document(resource(source, LEVEL_MODULES), LEVEL_MODULES)
        roads = {alias: row["objdata"] for row in modules["objects"] for alias in row.get("aliases", [])}
        layouts = tuple(roads[name]["Roads"] for name in ("TunnelDefendDefaultX", "TunnelDefendDefault1"))
        del source
        bank = resource(Bundle(unwrap(cn.read("assets/plant2.rsb.smf"))),
                        r"PLANT2_SOUNDBANKS\PLANT_ELECTRICITEA.BNK")
        media = international_pcm_media(international_bank.read_bytes(), vgmstream, work / "audio")
        tea = prepare_tea_bank(bank, moton, media)
        packets, anchors = from_group(cn, "dynamic", "UI_AlwaysLoaded_Dynamic_1200", [PACKET])
        with ZipFile(upstream) as original:
            engine = register_zombie_card_types(build_guest(
                original.read(ENGINE), ndk, work, layouts, qin_bank.read_bytes(), moton, tea,
            ))
        dynamic = target.build()
        assert Bundle(dynamic).manifest()[2] == manifest
        plan = create_plan(dynamic, work, rgba_atlases=len(target.textures) - 2)
        dex = rebuild_dynamic_bootstrap(app.read(BOOTSTRAP), work / "bootstrap", old, dynamic)
        android_manifest = manifest_version(app.read(MANIFEST), VERSION, 434, prefix="A")
        baseline, shim = app.read(BASELINE), app.read(shim_name)
    del target, old
    packet = packets[PACKET]
    scale = 1536 / 1200
    packet = packet.resize(tuple(round(axis * scale) for axis in packet.size), Image.Resampling.LANCZOS)
    anchor = {key: round(value * scale) for key, value in anchors[PACKET].items()}
    parts, baseline, shim = rebuild_card_resources(
        base, baseline, shim, packet, anchor, astc_encoder, work, image_id=PACKET, alias=PLANT, origin=(220, 3970),
    )
    changes = {**parts, BASELINE: baseline, shim_name: shim, ASSET: dynamic, PLAN: plan,
               BOOTSTRAP: dex, MANIFEST: android_manifest, ENGINE: engine}
    pack_apk(base, changes, sdk, output, signing)
    for part in parts.values():
        part.unlink()
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "donor", "upstream", "qin-bank", "moton-bank", "output", "sdk", "ndk",
                 "signing", "astc-encoder", "international-bank", "vgmstream"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
