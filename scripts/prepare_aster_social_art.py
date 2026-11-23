"""Pack the supplied social UI sprites used by Aster's native level menu."""

from io import BytesIO
from pathlib import Path
import json
import struct
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageOps

from merge_legacy_pvp_resources import Bundle, trie_write, u32

GROUP = "UI_AsterSocial"
ATLAS = GROUP + "_1536_00"
# UI_Avatars_1536, PvZ2 International Android 13.6.1 (1067).
# The filenames retain the suffix of IMAGE_UI_JOUST_AVATARS_AVATAR_*.
ARENA_AVATARS = (18, 22, 24, 6, 9, 16)
IMAGES = {
    "UI_Rank": (
        ("MY_SCORE", "SCORE_PAPER"),
        ("TAB_NORMAL", "TAB_NORMAL"),
        ("TAB_SELECT", "TAB_SELECTED"),
        ("TAB_DISABLE", "TAB_LOCKED"),
        ("LINE_LEFT", "LINE_LEFT"),
        ("LINE_RIGHT", "LINE_RIGHT"),
    ),
    "UI_Friend": (
        ("ITEM_BG", "FRIEND_ROW"),
        ("HEAD_BACKGROUD", "FRIEND_AVATAR"),
        ("BORROWP_SELECT_HOVER", "FRIEND_HOVER"),
        ("BORROWP_ITEM_BG", "BORROW_ROW"),
        ("BORROWP_WINDOWTOPPER", "BORROW_TOPPER"),
    ),
}


def read_sprites(archive):
    sprites = {}
    with ZipFile(archive) as source:
        for group, entries in IMAGES.items():
            folder = group + "_640.json_sliced_merged/"
            metadata = json.loads(source.read(folder + group + "_1536.json"))
            atlas, = (item for item in metadata["resources"] if item.get("atlas"))
            indexed = {item["id"]: item for item in metadata["resources"] if not item.get("atlas")}
            with Image.open(BytesIO(source.read(folder + group.upper() + "_1536_00.png"))) as image:
                if image.size != (atlas["width"], atlas["height"]) or image.mode != "RGBA":
                    raise ValueError(f"Unexpected atlas dimensions or channels for {group}")
                for original, name in entries:
                    item = indexed["IMAGE_" + group.upper() + "_" + original]
                    x, y, w, h = (item[key] for key in ("ax", "ay", "aw", "ah"))
                    if (item["parent"] != atlas["id"] or min(x, y) < 0 or min(w, h) < 1
                            or x + w > image.width or y + h > image.height):
                        raise ValueError(f"Invalid atlas rectangle for {item['id']}")
                    sprite = image.crop((x, y, x + w, y + h))
                    if name in ("BORROW_TOPPER", "BORROW_ROW"):
                        sprite = sprite.resize((w // 2, h // 2), Image.Resampling.LANCZOS)
                    sprites[name] = sprite
    art = Path(__file__).resolve().parents[1] / "src" / "adventure-records" / "art"
    for name in ("BORROW_NORMAL", "BORROW_PRESSED"):
        with Image.open(art / (name.lower().replace("_", "-") + ".png")) as image:
            sprites[name] = image.copy()
    for slot, source_id in enumerate(ARENA_AVATARS, start=1):
        with Image.open(art / "arena-avatars" / f"{source_id}.png") as image:
            if image.mode != "RGBA" or image.size != (256, 256):
                raise ValueError(f"Invalid Arena avatar {source_id}")
            sprites[f"ARENA_AVATAR_{slot}"] = image.copy()
    # UI_Joust_Meter_1536, PvZ2 International Android 13.6.1 (1067).
    for part in ("background", "face", "hour", "minute", "center"):
        with Image.open(art / "arena-clock" / f"arena-clock-{part}.png") as image:
            if image.mode != "RGBA":
                raise ValueError(f"Invalid Arena clock sprite {part}")
            sprites[f"ARENA_CLOCK_{part.upper()}"] = image.copy()
    # TimerLabel uses JoustGameScore, the original fbUsv8C5eI digit face.
    for glyph in range(11):
        with Image.open(art / "arena-clock" / f"arena-clock-digit-{glyph}.png") as image:
            sprites[f"ARENA_CLOCK_DIGIT_{glyph:02}"] = image.copy()
    return sprites


def pack_sprites(sprites, slot):
    width, padding = 4096, 4
    x = y = padding
    shelf = 0
    placements = []
    atlas_id = "ATLASIMAGE_ATLAS_" + ATLAS.upper()
    resources = [dict(id=atlas_id, type="Image", path=["atlases", ATLAS],
                      slot=slot, atlas=True, runtime=True, width=width)]
    for name, image in sorted(sprites.items(), key=lambda item: -item[1].height):
        if x + image.width + padding > width:
            x = padding
            y += shelf + padding
            shelf = 0
        placements.append((image, (x, y)))
        resources.append(dict(id="IMAGE_ASTER_SOCIAL_" + name, type="Image", parent=atlas_id,
                              path=["images", "1536", "aster_social", name.lower()],
                              slot=slot + len(resources),
                              ax=x, ay=y, aw=image.width, ah=image.height, aflags=15))
        x += image.width + padding
        shelf = max(shelf, image.height)
    height = 1 << (y + shelf + padding - 1).bit_length()
    if height > 4096 or any(x + image.width + padding > width for image, (x, _) in placements):
        raise ValueError("Social sprites exceed the supported atlas size")
    resources[0]["height"] = height
    canvas = Image.new("RGBA", (width, height))
    for image, position in placements:
        canvas.paste(image, position)
    return canvas, resources


def add_social_art(original, archive, cn_user_apk=None):
    bundle = Bundle(original)
    manifest_index, manifest_path, manifest = bundle.manifest()
    if any(group["id"].startswith(GROUP) for group in manifest["groups"]):
        raise ValueError("Social menu art is already installed")
    slot = manifest["slot_count"]
    sprites = read_sprites(archive) if archive else {}
    if cn_user_apk:
        from prepare_aster_cn_user_art import append_cn_user_credit, extract_cn_user_art

        sprites.update(extract_cn_user_art(cn_user_apk))
        append_cn_user_credit(bundle)
    else:
        with Image.open(Path(__file__).resolve().parents[1] / "src/adventure-records/art/user-button.png") as icon:
            sprites["USER_BUTTON"] = icon.resize((280, 180), Image.Resampling.LANCZOS)
    atlas, resources = pack_sprites(sprites, slot)
    width, height = atlas.size
    pixels = atlas.tobytes()
    index = len(bundle.groups)
    stem = GROUP + "_1536"
    assert bundle.h["ptxInfo_EachLength"] == 24

    head = bytearray(4096)
    head[:4] = b"pgsr"
    struct.pack_into("<I", head, 4, 4)
    struct.pack_into("<4I", head, 20, len(head), len(head), 0, 0)
    struct.pack_into("<3I", head, 40, len(head), len(pixels), len(pixels))
    path = f"ATLASES\\{ATLAS.upper()}.PTX"
    table = trie_write([(path, (1, 0, len(pixels), 0, 0, 0, width, height))], 1)
    struct.pack_into("<II", head, 0x48, len(table), 0x5c)
    head[0x5c:0x5c + len(table)] = table

    info = bytearray(bundle.h["rsgpInfo_EachLength"])
    info[:len(stem)] = stem.encode("ascii")
    struct.pack_into("<II", info, 196, 1, len(bundle.textures))
    pool = bytearray(bundle.h["autopoolInfo_EachLength"])
    pool_name = (stem + "_AutoPool").encode("ascii")
    pool[:len(pool_name)] = pool_name
    struct.pack_into("<I", pool, 136, u32(bundle.pools[0], 136))
    bundle.groups.append({"ID": stem})
    bundle.infos.append(info)
    bundle.pools.append(pool)
    bundle.textures.append(bytearray(struct.pack("<6I", width, height, width * 4, 0, 0, 100)))
    bundle.payloads.append(head + pixels)
    bundle.sync_info(index)

    comp = bytearray(bundle.h["compositeInfo_EachLength"])
    comp[:len(GROUP)] = GROUP.encode("ascii")
    struct.pack_into("<II", comp, 128, index, 1536)
    struct.pack_into("<I", comp, 1152, 1)
    bundle.composites.append(comp)
    manifest["groups"].extend([
        dict(type="composite", id=GROUP, subgroups=[dict(id=stem, res="1536")]),
        dict(type="simple", id=stem, parent=GROUP, res="1536", resources=resources),
    ])
    manifest["slot_count"] += len(resources)
    bundle.replace_manifest(manifest_index, manifest_path, manifest)
    built = bundle.build()

    check = Bundle(built)
    if check.manifest()[2] != manifest or check.payloads[index][len(head):] != pixels:
        raise ValueError("Social atlas failed resource round-trip")
    for resource, image in zip(resources[1:], sorted(sprites.values(), key=lambda img: -img.height)):
        x, y, w, h = (resource[key] for key in ("ax", "ay", "aw", "ah"))
        if atlas.crop((x, y, x + w, y + h)).tobytes() != image.tobytes():
            raise ValueError("Social sprite changed during packing")
    return built


def edit_social_atlas(original, additions, recolor=None):
    """Add sprites below the existing cells, optionally updating existing artwork in place."""
    from prepare_offline_pvp_seagull_hd import texture_section

    bundle = Bundle(original)
    manifest_index, manifest_path, manifest = bundle.manifest()
    stem = GROUP + "_1536"
    group, = (entry for entry in manifest["groups"] if entry["id"] == stem)
    index, = (i for i, entry in enumerate(bundle.groups) if entry["ID"] == stem)
    atlas, = (entry for entry in group["resources"] if entry.get("atlas"))
    (path, image_info), = bundle.files(index)
    width, height = atlas["width"], atlas["height"]
    block = bundle.payloads[index]
    pixels = texture_section(block)
    if (path != f"ATLASES\\{ATLAS.upper()}.PTX" or image_info[:3] != (1, 0, len(pixels))
            or image_info[-2:] != (width, height) or len(pixels) != width * height * 4
            or u32(block, 16) & 1):
        raise ValueError("Expected the existing uncompressed RGBA social atlas")
    canvas = Image.frombytes("RGBA", (width, height), pixels)
    existing = [entry for entry in group["resources"] if entry.get("parent") == atlas["id"]]
    if recolor:
        for entry in existing:
            key = entry["id"].removeprefix("IMAGE_ASTER_SOCIAL_")
            if key in recolor:
                x, y, w, h = (entry[field] for field in ("ax", "ay", "aw", "ah"))
                sprite = canvas.crop((x, y, x + w, y + h))
                canvas.paste(round_avatar(sprite, recolor[key]), (x, y))
    y = max(entry["ay"] + entry["ah"] for entry in existing) + 4
    x = 4
    for name, image in additions.items():
        if image.mode != "RGBA" or x + image.width + 4 > width or y + image.height + 4 > height:
            raise ValueError(f"Invalid sprite or no room in the social atlas: {name}")
        canvas.paste(image, (x, y))
        group["resources"].append(dict(
            id="IMAGE_ASTER_SOCIAL_" + name, type="Image", parent=atlas["id"],
            path=["images", "1536", "aster_social", name.lower()],
            slot=manifest["slot_count"], ax=x, ay=y, aw=image.width, ah=image.height, aflags=15,
        ))
        x += image.width + 4
        manifest["slot_count"] += 1
    offset = u32(block, 40)
    bundle.payloads[index] = block[:offset] + canvas.tobytes() + block[offset + len(pixels):]
    bundle.replace_manifest(manifest_index, manifest_path, manifest)
    return bundle.build()


def round_avatar(sprite, color):
    """Crop the character to a circle and antialias the colored ring."""
    diameter = min(sprite.size) * 2
    image = Image.new("RGBA", (diameter, diameter))
    draw = ImageDraw.Draw(image)

    def circle(inset):
        return (inset, inset, diameter - inset - 1, diameter - inset - 1)

    highlight = tuple((value * 3 + 255) // 4 for value in color)
    shade = tuple(value * 3 // 5 for value in color)
    draw.ellipse(circle(round(diameter * .01)), fill=(30, 25, 25))
    draw.ellipse(circle(round(diameter * .024)), fill=shade)
    draw.ellipse(circle(round(diameter * .039)), fill=highlight)
    draw.ellipse(circle(round(diameter * .049)), fill=color)
    draw.ellipse(circle(round(diameter * .078)), fill=shade)
    inset = round(diameter * .09)
    size = diameter - 2 * inset
    portrait = ImageOps.fit(sprite, (size, size), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size))
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    image.paste(portrait, (inset, inset), mask)
    return ImageOps.pad(image, sprite.size, method=Image.Resampling.LANCZOS)


def add_round_avatars(original):
    legacy_colors = (
        (104, 189, 239), (223, 82, 72), (201, 151, 65),
        (232, 56, 66), (236, 143, 43), (239, 245, 248),
    )
    recolor = {f"ARENA_AVATAR_{i}": color for i, color in enumerate(legacy_colors, 1)}
    recolor.update({f"CN_USER_AVATAR_{i}": legacy_colors[i - 1] for i in range(3, 7)})
    recolor["FRIEND_AVATAR"] = (90, 145, 68)
    additions = {}
    art = Path(__file__).resolve().parents[1] / "src/adventure-records/art/arena-avatars"
    new_avatars = (
        (8, (173, 79, 194)), (14, (109, 219, 239)), (20, (181, 125, 64)),
        (21, (192, 95, 213)), (23, (242, 187, 60)), (25, (130, 163, 105)),
    )
    for i, (source, color) in enumerate(new_avatars, 7):
        with Image.open(art / f"{source}.png") as sprite:
            if sprite.size != (256, 256) or sprite.mode != "RGBA":
                raise ValueError(f"Unexpected Arena avatar sprite: {source}")
            additions[f"CN_USER_AVATAR_{i}"] = round_avatar(sprite, color)
    return edit_social_atlas(original, additions, recolor)
