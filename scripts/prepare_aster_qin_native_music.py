"""Build a standalone Wwise bank for Qin Chapter One's playlists."""

import struct

from build_aster_mausoleum_zombies import resource


WORLD_MUSIC_ROOT = 144683016
QIN_MUSIC_ROOT = 358091703
QIN_DONOR_BANK = r"UNCHARTED_SOUNDBANKS\UNCHARTED_MUSIC.BNK"
QIN_BANK_NAME = "Aster_Qin_Chapter_One"
PLAY = "Play_Aster_Qin_Chapter_One"
STOP = "Stop_Aster_Qin_Chapter_One"
MUSIC_BUS = 2680856269


def bank_chunks(raw, version=112):
    cursor = 0
    chunks = {}
    while cursor < len(raw):
        tag, size = struct.unpack_from("<4sI", raw, cursor)
        start = cursor + 8
        cursor = start + size
        assert tag not in chunks and cursor <= len(raw)
        chunks[tag] = raw[start:cursor]
    assert struct.unpack_from("<I", chunks[b"BKHD"])[0] == version
    return chunks


def bank_objects(chunks):
    hirc = chunks[b"HIRC"]
    count, = struct.unpack_from("<I", hirc)
    objects = {}
    cursor = 4
    for _ in range(count):
        kind, size, object_id = struct.unpack_from("<BII", hirc, cursor)
        assert size >= 4 and object_id not in objects
        objects[object_id] = (kind, hirc[cursor + 9:cursor + 5 + size])
        cursor += 5 + size
    assert cursor == len(hirc)
    return objects


def write_bank(chunks, objects):
    chunks[b"HIRC"] = struct.pack("<I", len(objects)) + b"".join(
        struct.pack("<BII", kind, len(body) + 4, object_id) + body
        for object_id, (kind, body) in objects.items()
    )
    return b"".join(struct.pack("<4sI", tag, len(data)) + data for tag, data in chunks.items())


def music_branch(objects):
    pending = [QIN_MUSIC_ROOT]
    branch = {}
    while pending:
        object_id = pending.pop()
        if object_id in branch or object_id == WORLD_MUSIC_ROOT:
            continue
        kind, body = objects[object_id]
        assert kind in (10, 11, 12, 13)
        branch[object_id] = (kind, body)
        # Dependencies can be referenced by playlists and by transition rules
        # as well as by the child array. Include all IDs from this music bank.
        for offset in range(len(body) - 3):
            dependency, = struct.unpack_from("<I", body, offset)
            if dependency in objects and dependency not in branch:
                pending.append(dependency)
    # The native bank reader resolves playlist nodes during registration.
    # Retain the donor's child-before-container order.
    return {object_id: item for object_id, item in objects.items() if object_id in branch}


def ak_id(name):
    value = 2166136261
    for letter in name.lower().encode("ascii"):
        value = ((value * 16777619) ^ letter) & 0xffffffff
    return value


def make_qin_bank(source, chapter, media):
    bank_id = ak_id(QIN_BANK_NAME)
    header = source[b"BKHD"][:4] + struct.pack("<I", bank_id) + source[b"BKHD"][8:]
    data = bytearray()
    index = bytearray()
    positions = {}
    for media_id, wem in sorted(media.items()):
        assert wem[:4] == b"RIFF" and wem[8:12] == b"WAVE"
        data.extend(bytes(-len(data) % 16))
        positions[media_id] = (len(data), len(wem))
        index.extend(struct.pack("<III", media_id, *positions[media_id]))
        data.extend(wem)
    data_start = 24 + len(header) + len(index)

    objects = {}
    for object_id, (kind, body) in chapter.items():
        if object_id == QIN_MUSIC_ROOT:
            # The chapter switch normally inherits the world container's
            # output bus. Keep the legacy mixer's native music bus.
            bus, parent = struct.unpack_from("<II", body, 4)
            assert (bus, parent) == (0, WORLD_MUSIC_ROOT)
            body = body[:4] + struct.pack("<II", MUSIC_BUS, 0) + body[12:]
        if kind == 11:
            count, plugin, stream, source_id, _ = struct.unpack_from("<IIBII", body, 1)
            assert count == 1 and plugin == 262145 and stream in (0, 2)
            offset, size = positions[source_id]
            body = (body[:9] + struct.pack("<BIIII", 0, source_id, bank_id, data_start + offset, size)
                    + body[26 if stream == 0 else 22:])
        objects[object_id] = kind, body

    # These are the v112 Play and Stop action layouts from the installed
    # world music bank. Scope each action to the separate chapter switch.
    target = struct.pack("<I", QIN_MUSIC_ROOT)
    actions = {
        PLAY: bytes.fromhex("0304") + target + bytes.fromhex("00000004") + struct.pack("<I", bank_id),
        STOP: bytes.fromhex("0301") + target + bytes.fromhex("00010fdc050000000300000000"),
    }
    for name, action in actions.items():
        event_id = ak_id(name)
        action_id = ak_id(name + "_Action")
        assert {event_id, action_id}.isdisjoint(objects)
        objects[action_id] = 3, action
        objects[event_id] = 4, struct.pack("<II", 1, action_id)

    name = QIN_BANK_NAME.encode("ascii")
    mappings = struct.pack("<IIIB", 1, 1, bank_id, len(name)) + name
    return write_bank({b"BKHD": header, b"DIDX": index, b"DATA": data, b"HIRC": b"", b"STID": mappings}, objects)

def chapter_audio(twister, init):
    source = bank_chunks(resource(twister, QIN_DONOR_BANK))
    branch = music_branch(bank_objects(source))
    embedded = {
        key: source[b"DATA"][offset:offset + size]
        for key, offset, size in struct.iter_unpack("<III", source[b"DIDX"])
    }
    source_ids = {struct.unpack_from("<I", body, 10)[0] for kind, body in branch.values() if kind == 11}
    media = {
        key: embedded[key] if key in embedded else resource(init, rf"INIT_STREAMINGWAVES\GLOBAL_DATA\{key}.WEM")
        for key in sorted(source_ids)
    }
    assert len(media) == 13 and {269637980, 969425404, 1007192730, 976028012} <= media.keys()
    assert 969574514 not in media
    return make_qin_bank(source, branch, media)
