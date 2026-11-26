"""Add the Chinese Qin zombie almanac cards to an existing Aster build."""

import argparse
from copy import copy
from io import BytesIO
from pathlib import Path
import re
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from PIL import Image

from build_aster_compact_resources import BASELINE, PREFIX, ResourceZip, copy_compressed_entry, split_archive
from build_aster_hud_pickup import group_index, manifest_group, relocate_prefetch
from build_aster_legacy_endless_gameplay import level_document, package_data, replace_rton
from build_aster_mausoleum_zombies import (
    ASSET, BOOTSTRAP, LAWN_STRINGS, PLAN, SHEET_PACKAGE, TYPE_PACKAGE, Bundle,
    create_plan, rebuild_dynamic_bootstrap, resource, texture_section,
)
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version
from prepare_aster_cn_user_art import crop_sprites, unwrap
from prepare_aster_pvp_runtime import file_offset
from prepare_offline_pvp_seagull_hd import replace_section
from prepare_profile_memory import branch


UI_BUNDLE = "uicommon.rsb.smf"
PORTRAIT_GROUP = "UI_ZombieAlmanac"
PORTRAIT_PREFIX = "IMAGE_UI_ZOMBIEALMANAC_PACKETS_ZOMBIES_"
CN_PREVIEW = "IMAGE_UI_PLANTBG_CARD_PLANT_BG_MAUSOLEUM"
PREVIEW = "IMAGE_UI_CARDS_BACKGROUNDS_CARD_PLANT_BG_MAUSOLEUM"
ATLAS_NAME = "ui_zombiealmanac_1536_qin"
ATLAS_ID = "ATLASIMAGE_ATLAS_" + ATLAS_NAME.upper()
QIN_CARD_TYPES = (
    "mausoleum_basic", "mausoleum_flag", "mausoleum_armor1", "mausoleum_armor2",
    "mausoleum_gargantuar", "mausoleum_imp", "mausoleum_archer", "mausoleum_vendor",
    "mausoleum_piggy", "mausoleum_cavalry", "qin_shield_segment", "qin_jingke",
    "qin_taoist", "mausoleum_drunkard",
)


def game_properties(document):
    row, = [row for row in document["objects"] if row.get("aliases") == ["DefaultGameProps"]]
    return row["objdata"]


def zombie_types(bundle):
    document = level_document(resource(bundle, TYPE_PACKAGE), TYPE_PACKAGE)
    return {name: row["objdata"] for row in document["objects"]
            if row.get("objclass") == "ZombieType" for name in row.get("aliases", ())}


def lawn_strings(bundle):
    source = resource(bundle, LAWN_STRINGS).decode("utf-8-sig")
    return dict(re.findall(r"(?m)^\[([^\]\r\n]+)\][ \t]*\r?\n([^\r\n]+)", source))


def add_qin_order(target, donor):
    local = zombie_types(target)
    original = zombie_types(donor)
    order = game_properties(level_document(resource(donor, SHEET_PACKAGE), SHEET_PACKAGE))["ZombieAlmanacOrder"]
    names = tuple(name for name in order if name in local and name in original
                  and original[name].get("HomeWorld") == "mausoleum")
    assert names == QIN_CARD_TYPES
    expected, current = lawn_strings(donor), lawn_strings(target)
    for name in names:
        for suffix in ("", "_DESCRIPTION_HEADER", "_DESCRIPTION"):
            key = f"ZOMBIE_{name.upper()}{suffix}"
            # Combat imports already carry the original descriptions.
            assert current[key] == expected[key], key

    def append_order(document):
        entries = game_properties(document)["ZombieAlmanacOrder"]
        assert not set(entries).intersection(names)
        entries.extend(names)

    replace_rton(target, SHEET_PACKAGE, append_order, allow_growth=True)
    return names


def register_zombie_card_types(engine):
    elf = ELFFile(BytesIO(engine))
    segment_index, segment = [(i, segment) for i, segment in enumerate(elf.iter_segments())
                              if segment["p_type"] == "PT_LOAD"][-1]
    assert segment["p_flags"] == 5 and segment["p_filesz"] == segment["p_memsz"]
    assert segment["p_offset"] + segment["p_filesz"] == len(engine)
    native = bytearray(engine)
    native.extend(bytes(-len(native) % 4))
    origin = segment["p_vaddr"] + len(native) - segment["p_offset"]
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    # Extend the native zombie enum used by the profile's defeated-zombie list.
    # Reserve stable IDs outside the original list, including its later unlocks.
    aliases = [(i + 0x200, name) for i, name in enumerate(QIN_CARD_TYPES)]
    aliases.extend((0x20a, name) for name in ("qin_shield_pair", "qin_shield_triad"))
    rows = "\n".join(f'.word alias_{i} - table\n.word {value}' for i, (value, _) in enumerate(aliases))
    strings = "\n".join(f'alias_{i}: .asciz "{name}"' for i, (_, name) in enumerate(aliases))
    # Aster also hooks the constructor entry at startup. Extend the two
    # return paths so that hook can still relocate the stock prologue.
    constructor_exits = (0xa60970, 0xa60990)
    ctor_hook = f"""
        push {{r4-r7,ip,lr}}
        sub sp,sp,#8
        add r4,r8,#4
        adr r5,table
        mov r6,r5
        mov r7,#{len(aliases)}
    next_alias:
        ldr r1,[r6],#4
        add r1,r5,r1
        add r2,sp,#4
        mov r0,sp
        blx #0x14ed0e0
        mov r0,r4
        mov r1,sp
        bl #0x498158
        ldr r1,[r6],#4
        str r1,[r0]
        ldr r0,[sp]
        sub r0,r0,#12
        add r1,sp,#4
        blx #0x14ebf58
        subs r7,r7,#1
        bne next_alias
        mov r0,r8
        add sp,sp,#8
        pop {{r4-r7,ip,pc}}
    table:
        {rows}
        {strings}
        .align 2
    """
    native.extend(bytes(assembler.asm(ctor_hook, origin)[0]))

    # Keep the existing guard for unregistered units and the separate quest
    # tracker. Registered Qin types now use the ordinary discovery update.
    kill_site = 0x220664
    kill_offset = file_offset(elf, kill_site)
    old_call, = struct.unpack_from("<I", engine, kill_offset)
    assert old_call >> 24 == 0xeb
    old_guard = kill_site + 8 + (((old_call & 0xffffff) ^ 0x800000) - 0x800000) * 4
    assert segment["p_vaddr"] <= old_guard < origin
    guard_offset = file_offset(elf, old_guard)
    assert engine[guard_offset:guard_offset + 4] == bytes.fromhex("1f402de9")
    kill_hook = segment["p_vaddr"] + len(native) - segment["p_offset"]
    native.extend(bytes(assembler.asm(f"""
        push {{r0-r2,lr}}
        add r0,r0,#0x148
        bl #0x497a20
        cmp r0,#0
        pop {{r0-r2,lr}}
        bne #0x711c60
        push {{r0-r4,lr}}
        b #{old_guard + 4}
    """, kill_hook)[0]))
    for site in constructor_exits:
        offset = file_offset(elf, site)
        assert engine[offset:offset + 4] == bytes.fromhex("0800a0e1")
        native[offset:offset + 4] = branch(site, origin, True)
    native[guard_offset:guard_offset + 4] = branch(old_guard, kill_hook)
    size = len(native) - segment["p_offset"]
    struct.pack_into("<II", native, elf["e_phoff"] + elf["e_phentsize"] * segment_index + 16, size, size)
    return native


def read_qin_portraits(bundle, names):
    group, = [row for row in bundle.manifest()[2]["groups"] if row["id"] == PORTRAIT_GROUP + "_1200"]
    ids = [PORTRAIT_PREFIX + name.upper() for name in names]
    source = {row["id"]: row for row in group["resources"]}
    pixels = crop_sprites(bundle, group, dict(zip(ids, ids, strict=True)))
    portraits = {}
    for key, image in pixels:
        size = tuple(round(value * 1536 / 1200) for value in image.size)
        anchor = {axis: round(source[key][axis] * 1536 / 1200) for axis in ("x", "y") if axis in source[key]}
        # The Chinese card allows a lower foot position. Match the stock
        # Aster tutorial portrait's baseline and keep weapons inside the rim.
        width, height = size
        anchor["x"] = min(anchor.get("x", 0), 209 - width)
        anchor["y"] = min(anchor.get("y", 0), 288 - height)
        assert anchor["x"] >= 12 and anchor["y"] >= 12, key
        portraits[key] = (image.resize(size, Image.Resampling.LANCZOS), anchor)
    return portraits


def read_qin_preview(bundle):
    group, = [row for row in bundle.manifest()[2]["groups"]
              if any(image["id"] == CN_PREVIEW for image in row.get("resources", ()))]
    (_, image), = crop_sprites(bundle, group, {PREVIEW: CN_PREVIEW})
    size = tuple(round(value * 1536 / 1200) for value in image.size)
    assert size == (552, 545)
    return image.resize(size, Image.Resampling.LANCZOS), {}


def append_portrait_atlas(bundle, portraits):
    group = PORTRAIT_GROUP + "_1536"
    index = group_index(bundle, group)
    manifest_index, manifest_path, manifest = bundle.manifest()
    images = manifest_group(manifest, group)
    used_ids = {row["id"] for row in images}
    assert ATLAS_ID not in used_ids and not used_ids.intersection(portraits)
    slot = manifest["slot_count"]
    x = y = row_height = 0
    atlas_width = 1024
    gutter = 2
    placements = []
    for key in sorted(portraits, key=lambda key: -portraits[key][0].height):
        sprite, anchor = portraits[key]
        width, height = sprite.size
        assert width + 2 * gutter <= atlas_width
        if x + width + 2 * gutter > atlas_width:
            x, y, row_height = 0, y + row_height, 0
        placements.append((sprite, x + gutter, y + gutter))
        images.append(dict(
            id=key, type="Image", path=["images", "1536", "qin_almanac", key.lower()],
            slot=slot + len(placements), parent=ATLAS_ID, ax=x + gutter, ay=y + gutter,
            aw=width, ah=height, aflags=15, **anchor,
        ))
        x += width + 2 * gutter
        row_height = max(row_height, height + 2 * gutter)
    atlas_height = (y + row_height + 3) & ~3
    canvas = Image.new("RGBA", (atlas_width, atlas_height))
    for sprite, x, y in placements:
        canvas.paste(sprite, (x, y))
    images.insert(0, dict(id=ATLAS_ID, type="Image", path=["atlases", ATLAS_NAME], slot=slot,
                         atlas=True, runtime=True, width=atlas_width, height=atlas_height))
    manifest["slot_count"] += len(placements) + 1

    # Append to the stock almanac RSG so opening the zombie tab loads the cards.
    # Keep the original texture bytes in place for existing decoder cache entries.
    count, first = struct.unpack_from("<II", bundle.infos[index], 196)
    slot = first + count
    bundle.textures.insert(slot, bytearray(struct.pack(
        "<6I", atlas_width, atlas_height, atlas_width * 4, 0, 0, 100,
    )))
    struct.pack_into("<I", bundle.infos[index], 196, count + 1)
    for i, info in enumerate(bundle.infos):
        start, = struct.unpack_from("<I", info, 200)
        if i != index and start >= slot:
            struct.pack_into("<I", info, 200, start + 1)

    pixels = canvas.tobytes()
    gpu = texture_section(bundle.payloads[index])
    assert len(gpu) % 4096 == 0
    files = dict(bundle.files(index))
    files[f"ATLASES\\{ATLAS_NAME.upper()}.PTX"] = (
        1, len(gpu), len(pixels), count, 0, 0, atlas_width, atlas_height,
    )
    replace_section(bundle, index, files.items(), package_data(bundle.payloads[index]), gpu + pixels,
                    allow_header_growth=True)
    bundle.replace_manifest(manifest_index, manifest_path, manifest)


def rebuild_resources(base, baseline, shim, portraits, work):
    archive_path = work / "resources.zip"
    with ResourceZip(base) as stream, ZipFile(stream) as original, \
            ZipFile(archive_path, "w", allowZip64=False) as target:
        for entry in original.infolist():
            if entry.filename != PREFIX + UI_BUNDLE:
                copy_compressed_entry(original, entry, target)
                continue
            prior = Bundle(original.read(entry))
            updated = Bundle(prior.data)
            append_portrait_atlas(updated, portraits)
            result = updated.build()
            check = Bundle(result)
            assert check.manifest()[2] == updated.manifest()[2]
            record = UI_BUNDLE.encode("ascii") + struct.pack(">I", entry.file_size)
            assert baseline.count(record) == 1
            baseline = baseline.replace(record, UI_BUNDLE.encode("ascii") + struct.pack(">I", len(result)))
            shim, count = relocate_prefetch(shim, prior, check)
            assert count >= 55
            target.writestr(copy(entry), result)
    return split_archive(archive_path, work), baseline, shim


def build(base, donor, output, sdk, signing):
    work = output.parent
    work.mkdir(parents=True, exist_ok=True)
    shim_name = ENGINE.rsplit("/", 1)[0] + "/libRestart.so"
    with ZipFile(base) as app, ZipFile(donor) as source:
        old = app.read(ASSET)
        target = Bundle(old)
        reference = Bundle(unwrap(source.read("assets/dynamic.rsb.smf")))
        names = add_qin_order(target, reference)
        preview = read_qin_preview(reference)
        del reference
        portraits = read_qin_portraits(Bundle(unwrap(source.read("assets/" + UI_BUNDLE))), names)
        portraits[PREVIEW] = preview
        updated = target.build()
        plan = create_plan(updated, work, rgba_atlases=len(target.textures) - 2)
        dex = rebuild_dynamic_bootstrap(app.read(BOOTSTRAP), work / "bootstrap", old, updated)
        manifest = manifest_version(app.read(MANIFEST), 423, 419, prefix="A")
        baseline, shim = app.read(BASELINE), app.read(shim_name)
        engine = register_zombie_card_types(app.read(ENGINE))
        print(f"Verified {len(names)} original entries and portraits", flush=True)
    del target, old
    parts, baseline, shim = rebuild_resources(base, baseline, shim, portraits, work)
    changes = {**parts, BASELINE: baseline, shim_name: shim, ASSET: updated, PLAN: plan,
               BOOTSTRAP: dex, MANIFEST: manifest, ENGINE: engine}
    pack_apk(base, changes, sdk, output, signing)
    for part in parts.values():
        part.unlink()
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "donor", "output", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
