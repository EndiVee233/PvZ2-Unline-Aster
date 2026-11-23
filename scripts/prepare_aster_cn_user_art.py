"""Read the authorized user panel art from a local PvZ2 CN Android package."""

import lzma
from struct import unpack_from
from zipfile import ZipFile

from PIL import Image

from bake_rgba_resources import decode
from build_aster_legacy_endless_gameplay import package_data
from merge_legacy_pvp_resources import Bundle
from prepare_offline_pvp_seagull_hd import replace_section, texture_section


CN_VERSION = "4.2.8"
SOURCE = {
    "uiactive": {
        "UI_WorldMap_1200": {
            "USER_BUTTON": "IMAGE_UI_HUD_WORLDMAP_PERSONAL_INFO",
            "USER_BUTTON_DOWN": "IMAGE_UI_HUD_WORLDMAP_PERSONAL_INFO_DOWN",
        },
    },
    "uicommon": {
        "UI_UserInfo_1200": {
            "CN_USER_DAVE": "IMAGE_UI_USERINFO_DAVE01",
            "CN_USER_HINT": "IMAGE_UI_USERINFO_CHANGEHEADSHOT",
            "CN_USER_GIFT": "IMAGE_UI_USERINFO_GIFT_ICON",
            "CN_USER_NAME": "IMAGE_UI_USERINFO_INPUTFRAME",
            "CN_USER_PREVIEW": "IMAGE_UI_USERINFO_HEADSHOTFRAME",
            "CN_USER_AVATAR_1": "IMAGE_UI_USERINFO_MALE",
            "CN_USER_AVATAR_2": "IMAGE_UI_USERINFO_FEMALE",
        },
        "UI_AlwaysLoaded_1200": {
            "CN_USER_FRAME": "IMAGE_UI_DIALOG_ASSET_DIALOGGREENBORDER",
            "CN_USER_PAPER": "IMAGE_UI_DIALOG_ASSET_WHITE_BG",
            "CN_USER_CLOSE": "IMAGE_UI_DIALOG_ASSET_ROUND_CLOSE_BTN",
            "CN_USER_CLOSE_DOWN": "IMAGE_UI_DIALOG_ASSET_ROUND_CLOSE_BTN_DOWN",
            "CN_USER_CLOSE_TAB": "IMAGE_UI_DIALOG_ASSET_CLOSE_BTN",
            "CN_USER_CLOSE_TAB_DOWN": "IMAGE_UI_DIALOG_ASSET_CLOSE_DOWN",
            "CN_USER_ACTION": "IMAGE_UI_GENERIC_LIGHT_BUTTON_GREEN",
            "CN_USER_ACTION_DOWN": "IMAGE_UI_GENERIC_LIGHT_BUTTON_GREEN_DOWN",
        },
    },
    "uiactive3": {
        "UI_Avatars_1200": {
            f"CN_USER_AVATAR_{slot}": f"IMAGE_UI_JOUST_AVATARS_AVATAR_{avatar}"
            for slot, avatar in enumerate((24, 6, 9, 16), 3)
        }
    },
}


def unwrap(data):
    """Expand the public package's block-compressed RSB format."""
    version, expected, stored, block_size, count = unpack_from("<IQQII", data, 4)
    if data[:4] != b"RSLB" or version != 1 or stored + 32 != len(data) or count != (expected + block_size - 1) // block_size:
        raise ValueError("Unexpected Chinese resource bundle")
    result = bytearray(expected)
    cursor = 0
    for i in range(count):
        start, length, offset, packed_length, _, _ = unpack_from("<QQQIII", data, 32 + 36 * i)
        if start != cursor or not 0 < length <= expected - start or offset + packed_length > len(data):
            raise ValueError("Invalid resource block bounds")
        properties, dictionary = unpack_from("<BI", data, offset)
        filters = [dict(id=lzma.FILTER_LZMA1, dict_size=dictionary, lc=properties % 9,
                        lp=properties // 9 % 5, pb=properties // 45)]
        raw = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
        output = raw.decompress(data[offset + 5:offset + packed_length], max_length=length)
        if len(output) != length:
            raise ValueError("Truncated Chinese resource block")
        result[start:start + length] = output
        cursor += length
    if cursor != expected:
        raise ValueError("Truncated Chinese resource bundle")
    return result


def crop_sprites(bundle, group, mapping):
    index, = (i for i, row in enumerate(bundle.groups) if row["ID"] == group["id"])
    atlas_first = unpack_from("<I", bundle.infos[index], 200)[0]
    lookup = {row["id"]: row for row in group["resources"]}
    files = dict(bundle.files(index))
    textures = texture_section(bundle.payloads[index])
    atlases = {}
    for target, source in mapping.items():
        item = lookup[source]
        atlas_key = item["parent"]
        if atlas_key not in atlases:
            path = "ATLASES\\" + lookup[atlas_key]["path"][-1].upper() + ".PTX"
            _, offset, size, slot, _, _, width, height = files[path]
            fmt = unpack_from("<I", bundle.textures[atlas_first + slot], 12)[0]
            pixels = decode(bytes(textures[offset:offset + size]), width, height, fmt)
            atlases[atlas_key] = Image.frombytes("RGBA", (width, height), pixels)
        atlas = atlases[atlas_key]
        x, y, width, height = (item[field] for field in ("ax", "ay", "aw", "ah"))
        if x < 0 or y < 0 or x + width > atlas.width or y + height > atlas.height:
            raise ValueError(f"Sprite rectangle exceeds atlas: {source}")
        yield target, atlas.crop((x, y, x + width, y + height))


def nine_slice(source, size, left, top):
    """Extend the flat middle of the original frame and preserve its corners."""
    width, height = size
    result = Image.new("RGBA", size)
    xs = (0, left, source.width - left, source.width)
    ys = (0, top, source.height - top, source.height) if top else (0, source.height)
    dx = (0, left, width - left, width)
    dy = (0, top, height - top, height) if top else (0, height)
    for row in range(len(ys) - 1):
        for column in range(3):
            tile = source.crop((xs[column], ys[row], xs[column + 1], ys[row + 1]))
            dimensions = (dx[column + 1] - dx[column], dy[row + 1] - dy[row])
            if tile.size != dimensions:
                tile = tile.resize(dimensions, Image.Resampling.BILINEAR)
            result.paste(tile, (dx[column], dy[row]))
    return result


def extract_cn_user_art(apk):
    sprites = {}
    with ZipFile(apk) as archive:
        for member, groups in SOURCE.items():
            bundle = Bundle(unwrap(archive.read(f"assets/{member}.rsb.smf")))
            manifest = {group["id"]: group for group in bundle.manifest()[2]["groups"]}
            for group, mapping in groups.items():
                sprites.update(crop_sprites(bundle, manifest[group], mapping))

    frame = sprites["CN_USER_FRAME"].resize((222, 223), Image.Resampling.LANCZOS)
    sprites["CN_USER_FRAME"] = nine_slice(frame, (1020, 672), 98, 98)
    sprites["CN_USER_PAPER"] = nine_slice(sprites["CN_USER_PAPER"], (506, 549), 38, 38)
    sprites["CN_USER_PREVIEW"] = nine_slice(sprites["CN_USER_PREVIEW"], (459, 425), 15, 15)
    for key in ("CN_USER_ACTION", "CN_USER_ACTION_DOWN"):
        original = sprites[key].resize((80, 100), Image.Resampling.LANCZOS)
        sprites[key] = nine_slice(original, (580, 100), 32, 0)
    return sprites


def append_cn_user_credit(bundle, description="用户界面素材提取自"):
    path = "PROPERTIES\\CREDITS.TXT"
    index, = (i for i in range(len(bundle.groups)) if path in dict(bundle.files(i)))
    files = dict(bundle.files(index))
    _, offset, size = files[path]
    data = package_data(bundle.payloads[index])
    original = data[offset:offset + size]
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    credit = ("", "", "{TITLE_CH}素材来源", description,
              f"《植物大战僵尸2》中文版 {CN_VERSION}", "", "")
    updated = original + newline.join(line.encode("utf-8") for line in credit)
    files[path] = (0, len(data), len(updated))
    replace_section(bundle, index, sorted(files.items()), data + updated)
