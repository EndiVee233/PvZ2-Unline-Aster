"""Adapt Qin overlay layers to Aster's original animation rigs."""

from math import cos, sin
import struct

from pam_transform_index import PamIndex


ARMOR_WRAPPERS = {"_zombie_armor_bucket_states", "_zombie_armor_cone_states"}
INDEX_MASK = {"moves": 0x3ff, "adds": 0x7ff, "rem": 0x7ff}


def replace_index(raw, index, mask):
    flags, = struct.unpack_from("<H", raw)
    tail = raw[6:] if flags & mask == mask else raw[2:]
    if index >= mask:
        return struct.pack("<Hi", (flags & ~mask) | mask, index) + tail
    return struct.pack("<H", (flags & ~mask) | index) + tail


def armor_move(raw, record, index, offset):
    flags = record["flags"] & ~INDEX_MASK["moves"]
    assert flags in (0x0800, 0x4800)
    x, y = record["pos"]
    shift_x, shift_y = offset
    rotation = raw[2:4] if flags & 0x4000 else b""
    angle = struct.unpack("<h", rotation)[0] / 1000 if rotation else 0
    x += round(cos(angle) * shift_x - sin(angle) * shift_y)
    y += round(sin(angle) * shift_x + cos(angle) * shift_y)
    return struct.pack("<H", flags | index) + rotation + struct.pack("<ii", x, y)


def armor_children(rig, sprite):
    frame, = sprite["frames"]
    assert not frame["rem"] and not frame["commands"] and len(frame["adds"]) == 3
    positions = {item["index"]: item for item in frame["moves"]}
    children = []
    for item in frame["adds"]:
        move = positions[item["index"]]
        assert item["sprite"] and item["name"] is None and move["flags"] == (0x0800 | item["index"])
        name = rig.sprites[item["res"]]["name"]
        assert name.startswith(("zombie_armor_bucket_", "zombie_armor_cone_"))
        children.append((item["res"], move["pos"]))
    return children


def write_section(records):
    if not records:
        return b""
    count = len(records)
    head = bytes((count,)) if count < 255 else struct.pack("<BH", 255, count)
    return head + b"".join(records)


def adapt_mausoleum_pam(raw, *, infantry=False):
    rig = PamIndex(raw)
    wrappers = {i: armor_children(rig, sprite) for i, sprite in enumerate(rig.sprites)
                if infantry and sprite["name"] in ARMOR_WRAPPERS}
    assert len(wrappers) == (2 if infantry else 0)
    omit = {i for i, sprite in enumerate(rig.sprites)
            if sprite["name"] == "ink" or (infantry and sprite["name"].startswith("zombie_armor_brick_"))}
    stride = 3 if infantry else 1
    edits = []
    for sprite in rig.sprites:
        # Each affected layer number has the same meaning throughout this timeline.
        assigned = {}
        for frame in sprite["frames"]:
            for item in frame["adds"]:
                key = item["res"] if item["sprite"] else -1
                assigned.setdefault(item["index"], set()).add(key)
        removed = {i for i, choices in assigned.items() if choices & omit}
        expanded = {i: wrappers[next(iter(choices))] for i, choices in assigned.items()
                    if choices & wrappers.keys() and len(choices) == 1}
        assert all(assigned[i] <= omit for i in removed)
        assert all(i in expanded for i, sources in assigned.items() if sources & wrappers.keys())
        if not removed and not expanded:
            continue
        factor = stride if expanded else 1
        for frame in sprite["frames"]:
            data = raw[frame["start"]:frame["end"]]
            removals, appends, moves = [], [], []
            for index, (start, end) in zip(frame["rem"], frame["remove_records"], strict=True):
                if index in removed:
                    continue
                for layer in range(len(expanded.get(index, (None,)))):
                    removals.append(replace_index(raw[start:end], factor * index + layer, INDEX_MASK["rem"]))
            for item, (start, end) in zip(frame["adds"], frame["append_records"], strict=True):
                index = item["index"]
                if index in removed:
                    continue
                if index in expanded:
                    assert end - start == 3
                    for layer, (child, _) in enumerate(expanded[index]):
                        appends.append(struct.pack("<HB", 0x8000 | (factor * index + layer), child))
                else:
                    appends.append(replace_index(raw[start:end], factor * index, INDEX_MASK["adds"]))
            for move in frame["moves"]:
                index = move["index"]
                if index in removed:
                    continue
                encoded = raw[move["start"]:move["end"]]
                if index in expanded:
                    for layer, (_, offset) in enumerate(expanded[index]):
                        moves.append(armor_move(encoded, move, factor * index + layer, offset))
                else:
                    moves.append(replace_index(encoded, factor * index, INDEX_MASK["moves"]))
            flags = data[0] & ~7
            sections = []
            for bit, records in ((1, removals), (2, appends), (4, moves)):
                if records:
                    flags |= bit
                    sections.append(write_section(records))
            suffix = raw[frame["events_start"]:frame["end"]]
            edits.append((frame["start"], frame["end"], bytes((flags,)) + b"".join(sections) + suffix))

    assert edits, "No Qin animation overlays found"
    result = bytearray(raw)
    for start, end, data in sorted(edits, reverse=True):
        result[start:end] = data
    parsed = PamIndex(bytes(result))
    for before, after in zip(rig.sprites, parsed.sprites, strict=True):
        for source, target in zip(before["frames"], after["frames"], strict=True):
            assert (source["label"], source["commands"]) == (target["label"], target["commands"])
            assert all(not item["sprite"] or item["res"] not in omit | wrappers.keys()
                       for item in target["adds"])
    return bytes(result)
