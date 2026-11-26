"""Add the Qin mausoleum to Aster's world map and package its editor layout."""

import argparse
from collections import defaultdict
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
from io import BytesIO, StringIO
import json
from math import dist
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from PIL import Image, ImageOps

from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, create_plan, group_index, rebuild_dynamic_bootstrap
from build_aster_legacy_endless_gameplay import level_document, package_data, replace_rton
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version
from index_texture_prefetch import ResourceZip
from prepare_aster_cn_user_art import append_cn_user_credit, crop_sprites, unwrap
from prepare_aster_pvp_balance import Bundle, JSONDecoder, cipher, trie_write, u32
from prepare_aster_pvp_runtime import file_offset
from prepare_offline_pvp_seagull_hd import replace_section
from prepare_profile_memory import branch
from render_aster_mausoleum_map import ATLAS_SCALE, WORLD_SCALE, map_tiles, render_map, road_strip
from render_aster_mausoleum_route_only import build_route_only, cell_surface, project as project_cell
from render_aster_mausoleum_route_only import rectified_material, stone_panel
from draw_aster_mausoleum_roads import install_road_draw

WORLD = "mausoleum"
GROUP = "WorldMap_Mausoleum"
BACKGROUND = "IMAGE_WORLDMAP_MAUSOLEUM_BACKGROUND"
ISLAND = "IMAGE_UI_UNIVERSE_WORLDS_MAUSOLEUM"
TERRAIN_PREFIX = "IMAGE_WORLDMAP_MAUSOLEUM_ISLAND"
ROOT_MAP = r"PACKAGES\WORLDS\MAUSOLEUM.RTON"
LOST_CITY = r"PACKAGES\WORLDS\LOSTCITY.RTON"
MAP_LIST = r"PACKAGES\WORLDMAPLIST.RTON"
RESOURCES = r"PACKAGES\WORLDRESOURCES.RTON"
LAWN_STRINGS = r"PROPERTIES\LAWNSTRINGS.TXT"
RES_ID = 11
WORLD_ID = 13
MAP_WIDTH = round(1120 * WORLD_SCALE)
MAP_HEIGHT = round(666 * WORLD_SCALE)
ENTRY = "mausoleum_preview_entry"
FIRST_LEVEL_INDEX = 1301
LEVEL_BASELINE_OFFSET = 5.0
ROAD_IMAGE_PREFIX = "IMAGE_QIN_ROUTE_"
BASE_ENGINE = "e0465c8ab2048624daf345a49c8bfa4ac9333f4edfae4e5eb9ead10ce863dd74"


def add_gallery_entry(document):
    data = document["objects"][0]["objdata"]
    maps = data["MapList"]
    assert not any(row["MapName"] == WORLD for row in maps)
    lost_city = next(row for row in maps if row["MapName"] == "lostcity")
    row = dict(lost_city, MapName=WORLD, UnlockedFrom="", EntryPoint=ENTRY, TotalStars=0,
               UniverseIconOffset={"mX": 0, "mY": 0}, StarTaskLockPlantList=[], Actid=0, KeyActid=0)
    insert_at = next(i for i, item in enumerate(maps) if item["MapName"] == "ptt")
    assert insert_at == RES_ID and all(insert_at not in cell for cell in data["MapResourceGrid"])
    maps.insert(insert_at, row)


def add_world_resources(document):
    groups = document["objects"][0]["objdata"]["Groups"]
    # Hidden PTT follows the new world in the resource table. The old loader
    # compacts hidden entries, so the visible world's resource ID is its slot.
    position = next(i for i, group in enumerate(groups) if group.get("ID") == RES_ID)
    assert groups[position]["ImagePrefix"] == "IMAGE_WORLDMAP_PTT"
    groups[position]["ID"] = RES_ID + 1
    groups.insert(position, dict(ID=RES_ID, ResGroups=[GROUP], ImagePrefix="IMAGE_WORLDMAP_MAUSOLEUM",
                           AnimationPrefix="", AnimationDelays=[]))


def level_nodes(nodes):
    routes = defaultdict(list)
    for node in nodes:
        if node["kind"] == "route-level":
            routes[node["route"]].append(node)
    for route, route_nodes in routes.items():
        branch = route.removeprefix("branch-") if route != "main" else ""
        for day, node in enumerate(sorted(route_nodes, key=lambda item: item["distance"]), start=1):
            alias = f"{WORLD}_b{branch}_{day}" if branch else f"{WORLD}{day}"
            yield node["id"], (alias, branch, day)


def empty_level(index, branch, day):
    title = f"[MAUSOLEUM_BRANCH_{branch}_LEVEL_NAME]" if branch else "[MAUSOLEUM_LEVEL_NAME]"
    modules = ("StandardIntro", "DefaultSunDropper", "EgyptMowers", "DefaultSeedBank",
               "DefaultZombieWinCondition", "ZombiesDeadWinCon")
    return dict(version=1, objects=[
        dict(objclass="LevelDefinition", objdata=dict(
            Name=title, LevelNumber=day, LevelIndex=index,
            StageModule="RTID(EgyptStage@LevelModules)", Loot="RTID(NoLoot@LevelModules)",
            Modules=[f"RTID({name}@LevelModules)" for name in modules] + ["RTID(Waves@CurrentLevel)"],
        )),
        dict(objclass="WaveGeneratorProperties", aliases=["Waves"], objdata=dict(
            WaveCount=1, FlagWaveInterval=2, WaveSpendingPoints=0, WaveSpendingPointIncrement=0,
            Waves=[dict(DisableRandomSpawns=True, Zombies=[])],
        )),
    ])


def road_events(plan, levels):
    by_route = defaultdict(list)
    for node in plan["nodes"]:
        by_route[node["route"]].append((node["distance"], node["id"], (node["x"], node["y"])))
    main = [node for node in by_route["main"] if node[1] in levels]
    for route in plan["paths"]:
        path_id = route["id"]
        authored = by_route[path_id]
        points = route["points"]
        parent = ""
        if route["kind"] == "branch":
            parent = min(main, key=lambda node: dist(points[0], node[2]))[1]
        last_distance = max(node[0] for node in authored)
        ordered = list(authored)
        distance = 0
        for index, (a, b) in enumerate(zip(points, points[1:]), start=1):
            distance += dist(a, b)
            # Corners beside a node are already represented by that node.
            if distance < last_distance and all(dist(b, point) > 6 for _, _, point in authored):
                ordered.append((distance, f"mausoleum_road_{path_id}_{index}", b))
        for _, name, point in sorted(ordered):
            yield name, parent, point
            parent = name


def road_slice(segments, first, last):
    distance = 0
    for index, (a, b, length, width) in enumerate(segments):
        start, end = max(first, distance), min(last, distance + length)
        if end > start:
            # Extend the fitted legs through the bend. The carpet silhouette
            # clips the outside corner and keeps the railings above the tiles.
            if abs(start - distance) <= .05 and (index > 0 or first == 0):
                start -= 7
            if end >= distance + length - .05:
                end += 7
            yield a + (b - a) * ((start - distance) / length), a + (b - a) * ((end - distance) / length), width
        distance += length


def road_position(segments, distance):
    for a, b, length, _ in segments:
        if distance <= length:
            return a + (b - a) * (distance / length)
        distance -= length
    return segments[-1][1]


def surface_art(plan, terrain_size, floor, fitted, materials, reward):
    levels = dict(level_nodes(plan["nodes"]))
    by_route = defaultdict(list)
    for node in plan["nodes"]:
        if node["id"] in levels:
            by_route[node["route"]].append(node)
    for nodes in by_route.values():
        nodes.sort(key=lambda node: node["distance"])
    width, height = terrain_size
    offset_x = (MAP_WIDTH / ATLAS_SCALE - width) / 2
    offset_y = (MAP_HEIGHT / ATLAS_SCALE - height) / 2
    sprites, draw = {}, []

    def add(segments, material, alias, completed):
        strip = road_strip(segments, material, floor)
        if strip:
            x, y, sprite = strip
            key = f"{ROAD_IMAGE_PREFIX}{len(sprites):02}"
            sprites[key] = sprite
            draw.append((alias, key, x + offset_x, y + offset_y, completed))

    stone, light, dark = materials
    for route in plan["paths"]:
        points = route["points"]
        segments = fitted[route["id"]]
        nodes = by_route[route["id"]]
        branch = route["kind"] == "branch"
        total = sum(dist(a, b) for a, b in zip(points, points[1:]))
        if branch:
            junction = min(by_route["main"], key=lambda node: dist(points[0], (node["x"], node["y"])))
            add(list(road_slice(segments, 14, total)), [stone], levels[junction["id"]][0], 0)
        start = 6 if branch else 0
        for node, following in zip(nodes, nodes[1:] + [dict(distance=total)]):
            end = following["distance"]
            if end - start >= 1:
                add(list(road_slice(segments, start, end)), [light, dark], levels[node["id"]][0], 1)
            start = end
    key = ROAD_IMAGE_PREFIX + "REWARD"
    sprites[key] = reward
    scale = WORLD_SCALE / ATLAS_SCALE
    for node in plan["nodes"]:
        if node["kind"] == "route-reward":
            cx, cy = road_position(fitted[node["route"]], node["distance"])
            x = cx * scale + offset_x - reward.width / 2
            y = cy * scale + offset_y - reward.height * .74
            draw.append(("", key, x, y, 2))
    return sprites, draw


def grid_events(layout, bounds):
    left, top, _, _ = bounds
    junctions = {route["cells"][0] for route in layout if route["kind"] == "branch"}
    main_names = {}
    events = []
    for route in layout:
        cells = route["cells"]
        named = {node["cell"]: node["id"] for node in route["nodes"]}
        for cell in route["corners"]:
            named.setdefault(cell, f"mausoleum_grid_{cell[0]}_{cell[1]}")
        if route["kind"] == "main":
            for cell in junctions:
                named.setdefault(cell, f"mausoleum_grid_{cell[0]}_{cell[1]}")
            main_names = named
            parent = ""
        else:
            parent = main_names[cells[0]]
            cells = cells[1:]
        for cell in cells:
            if cell in named:
                x, y = project_cell(cell)
                name = named[cell]
                events.append((name, parent, ((x - left) / WORLD_SCALE, (y - top) / WORLD_SCALE)))
                parent = name
    return events


def grid_surface_art(plan, layout, bounds, curb_alpha, materials):
    levels = dict(level_nodes(plan["nodes"]))
    _, _, width, height = bounds
    offset_x = (MAP_WIDTH / ATLAS_SCALE - width) / 2
    offset_y = (MAP_HEIGHT / ATLAS_SCALE - height) / 2
    plate, light, dark = materials
    stone = (stone_panel(plate),)
    grass = (rectified_material(light, "#6b9d1c"), rectified_material(dark, "#608e20"))
    sprites, draw = {}, []

    def add(cells, textures, alias, state):
        sprite, x, y = cell_surface(cells, textures, bounds, curb_alpha)
        key = f"{ROAD_IMAGE_PREFIX}{len(sprites):02}"
        sprites[key] = sprite
        draw.append((alias, key, x + offset_x, y + offset_y, state))

    for route in layout:
        cells = route["cells"]
        nodes = sorted((cells.index(node["cell"]), levels[node["id"]][0])
                       for node in route["nodes"] if node["id"] in levels)
        branch = route["kind"] == "branch"
        if branch:
            junction = main_cells.index(cells[0])
            _, prerequisite = max(node for node in main_nodes if node[0] <= junction)
            add(cells[1:], stone, prerequisite, 0)
        else:
            main_cells, main_nodes = cells, nodes
        start = 1 if branch else 0
        for number, (_, alias) in enumerate(nodes):
            end = nodes[number + 1][0] if number + 1 < len(nodes) else len(cells) - 1
            add(cells[start:end + 1], grass, alias, 1)
            start = end
    return sprites, draw


def register_package(entries, data, manifest, path, document):
    key = "\\".join(path).upper()
    if key in entries:
        raise ValueError(f"Package already exists: {key}")
    raw = JSONDecoder().encode_root_object(StringIO(json.dumps(document)))
    encoded = b"\x10\0" + cipher.encrypt(raw)
    assert level_document(encoded, key) == document
    entries[key] = (0, len(data), len(encoded))
    data.extend(encoded)
    resources, = (group["resources"] for group in manifest["groups"] if group["id"] == "Packages")
    resource_id = "RESFILE_" + "_".join(path).removesuffix(".rton").upper()
    resources.append(dict(type="File", slot=manifest["slot_count"], id=resource_id, path=path))
    manifest["slot_count"] += 1


def add_world_map(bundle, manifest, terrain_size, tiles, plan, fitted, grid=None):
    index = group_index(bundle, "Packages")
    entries = dict(bundle.files(index))
    data = bytearray(package_data(bundle.payloads[index]))
    _, offset, size = entries[LOST_CITY]
    document = level_document(data[offset:offset + size], LOST_CITY)
    world = document["objects"][0]
    fields = world["objdata"]
    template = fields["m_mapPieces"][0]
    width, height = terrain_size
    offset_x = (MAP_WIDTH - width * ATLAS_SCALE) / 2
    offset_y = (MAP_HEIGHT - height * ATLAS_SCALE) / 2
    pieces = []
    for image_id, (x, y, tile) in enumerate(tiles):
        position = {"x": offset_x + (x + tile.width / 2) * ATLAS_SCALE, "y": offset_y + y * ATLAS_SCALE}
        pieces.append(dict(template, m_position=position, m_eventType="island",
                           m_imageID=image_id, m_eventId=image_id + 1, m_drawLayer=0))

    def node_position(x, y):
        return {"x": offset_x + x * WORLD_SCALE, "y": offset_y + y * WORLD_SCALE}

    anchor = dict(deepcopy(template), m_position={"x": MAP_WIDTH / 2, "y": MAP_HEIGHT / 2},
                  m_eventType="none", m_name=ENTRY, m_imageID=0, m_eventId=len(pieces) + 1)
    events = [anchor]
    levels = {}
    if plan is not None:
        levels = dict(level_nodes(plan["nodes"]))
        by_name = {node["id"]: node for node in plan["nodes"]}
        if grid is None:
            start = next(node for node in plan["nodes"] if levels.get(node["id"]) == (f"{WORLD}1", "", 1))
            anchor["m_position"] = node_position(start["x"], start["y"])
            entries_to_add = road_events(plan, levels)
        else:
            anchor["m_position"] = node_position(*grid[0][2])
            entries_to_add = grid
        for event_id, (name, parent, point) in enumerate(entries_to_add, start=anchor["m_eventId"] + 1):
            event = dict(anchor, m_eventId=event_id, m_name=name, m_position=node_position(*point),
                         m_eventType="path_node", m_parentEvent=parent, m_autoVisible=True)
            if name in levels:
                if grid is None:
                    node = by_name[name]
                    x, y = road_position(fitted[node["route"]], node["distance"])
                else:
                    x, y = point
                alias, branch, day = levels[name]
                label = f"{branch}-{day}" if branch else str(day)
                event.update(m_eventType="level", m_dataString=alias, m_displayText=label,
                             m_position=node_position(float(x), float(y + LEVEL_BASELINE_OFFSET)))
            events.append(event)
    world["uid"] = "95a80c54-6058-4848-aab3-15c4de3763ad"
    fields.update(m_worldName=WORLD, m_resGroupID=RES_ID, m_worldId=WORLD_ID,
                  m_mapPieces=pieces, m_eventList=events,
                  m_boundingRect=dict(mX=0, mY=0, mWidth=MAP_WIDTH, mHeight=MAP_HEIGHT))
    register_package(entries, data, manifest, ROOT_MAP.lower().split("\\"), document)
    for level_index, (alias, branch, day) in enumerate(levels.values(), start=FIRST_LEVEL_INDEX):
        register_package(entries, data, manifest, ["packages", "levels", f"{alias}.rton"],
                         empty_level(level_index, branch, day))
    replace_section(bundle, index, sorted(entries.items()), data, allow_header_growth=True)


def add_art(bundle, manifest, sprites, *, group_name=GROUP):
    subgroup = group_name + "_1536"
    first_slot = manifest["slot_count"]
    stream = bytearray()
    resources, files, textures = [], [], []
    for index, (key, image) in enumerate(sprites.items()):
        name = f"{subgroup}_{index:02}"
        atlas = "ATLASIMAGE_ATLAS_" + name.upper()
        gutter = 2
        width = (image.width + 2 * gutter + 3) & ~3
        height = (image.height + 2 * gutter + 3) & ~3
        padded = Image.new("RGBA", (width, height))
        padded.paste(image, (gutter, gutter))
        for row in (0, image.height - 1):
            edge = image.crop((0, row, image.width, row + 1))
            padded.paste(edge.resize((image.width, gutter)), (gutter, 0 if row == 0 else image.height + gutter))
        for column in (0, image.width - 1):
            x = 0 if column == 0 else image.width + gutter
            edge = padded.crop((column + gutter, 0, column + gutter + 1, image.height + 2 * gutter))
            padded.paste(edge.resize((gutter, edge.height)), (x, 0))
        pixels = padded.tobytes()
        files.append((f"ATLASES\\{name.upper()}.PTX",
                      (1, len(stream), len(pixels), index, 0, 0, width, height)))
        stream.extend(pixels)
        stream.extend(bytes(-len(stream) % 4096))
        textures.append(bytearray(struct.pack("<6I", width, height, width * 4, 0, 0, 100)))
        resources.extend((
            dict(id=atlas, type="Image", path=["atlases", name], slot=first_slot + 2 * index,
                 atlas=True, runtime=True, width=width, height=height),
            dict(id=key, type="Image", parent=atlas, path=["images", "1536", key.lower()],
                 slot=first_slot + 2 * index + 1, ax=gutter, ay=gutter, aw=image.width, ah=image.height,
                 aflags=15),
        ))
    table = trie_write(files, 1)
    header = bytearray((0x5c + len(table) + 4095) & ~4095)
    header[:4] = b"pgsr"
    struct.pack_into("<I", header, 4, 4)
    struct.pack_into("<4I", header, 20, len(header), len(header), 0, 0)
    struct.pack_into("<3I", header, 40, len(header), len(stream), len(stream))
    struct.pack_into("<II", header, 0x48, len(table), 0x5c)
    header[0x5c:0x5c + len(table)] = table

    index = len(bundle.groups)
    info = bytearray(bundle.h["rsgpInfo_EachLength"])
    info[:len(subgroup)] = subgroup.encode("ascii")
    struct.pack_into("<II", info, 196, len(textures), len(bundle.textures))
    pool = bytearray(bundle.h["autopoolInfo_EachLength"])
    pool_name = (subgroup + "_AutoPool").encode("ascii")
    pool[:len(pool_name)] = pool_name
    struct.pack_into("<I", pool, 136, u32(bundle.pools[0], 136))
    composite = bytearray(bundle.h["compositeInfo_EachLength"])
    composite[:len(group_name)] = group_name.encode("ascii")
    struct.pack_into("<II", composite, 128, index, 1536)
    struct.pack_into("<I", composite, 1152, 1)
    bundle.groups.append({"ID": subgroup})
    bundle.infos.append(info)
    bundle.pools.append(pool)
    bundle.textures.extend(textures)
    bundle.payloads.append(header + stream)
    bundle.composites.append(composite)
    bundle.sync_info(index)
    manifest["groups"].extend((
        dict(type="composite", id=group_name, subgroups=[dict(id=subgroup, res="1536")]),
        dict(type="simple", id=subgroup, parent=group_name, res="1536", resources=resources),
    ))
    manifest["slot_count"] += len(resources)


def add_localization(bundle, nodes):
    index = group_index(bundle, "Credits_Common")
    entries = dict(bundle.files(index))
    data = package_data(bundle.payloads[index])
    _, offset, size = entries[LAWN_STRINGS]
    strings = data[offset:offset + size]
    assert b"[WORLD_NAME_MAUSOLEUM]" not in strings
    names = {
        "MAUSOLEUM": "秦始皇陵",
        "WORLD_NAME_MAUSOLEUM": "秦始皇陵",
        "MAUSOLEUM_LEVEL_NAME": "秦始皇陵-第{LEVEL_NUMBER}天",
    }
    branches = dict.fromkeys(branch for _, (_, branch, _) in level_nodes(nodes) if branch)
    for branch in branches:
        names[f"MAUSOLEUM_BRANCH_{branch}_LEVEL_NAME"] = f"秦始皇陵-支线{branch}第{{LEVEL_NUMBER}}关"
    strings += "".join(f"\r\n\r\n[{name}]\r\n{value}\r\n" for name, value in names.items()).encode()
    entries[LAWN_STRINGS] = (0, len(data), len(strings))
    replace_section(bundle, index, sorted(entries.items()), data + strings)


def world_map_art(base):
    stream = ResourceZip(base)
    with closing(stream.file), closing(stream.map), ZipFile(stream) as resources:
        package = next(name for name in resources.namelist() if name.endswith("/pirate.rsb.smf"))
        bundle = Bundle(resources.read(package))
        ui_package = next(name for name in resources.namelist() if name.endswith("/uiactive.rsb.smf"))
        ui = Bundle(resources.read(ui_package))
    group, = (group for group in bundle.manifest()[2]["groups"]
              if group["id"] == "WorldMap_Pirate_NonPVR_1536")
    # Keep the engine's path graph and metrics while displaying the authored road surface.
    paths = {
        resource["id"].replace("_PIRATE_", "_MAUSOLEUM_"):
        Image.new("RGBA", (resource["aw"], resource["ah"]))
        for resource in group["resources"] if resource["id"].startswith("IMAGE_WORLDMAP_PATH_PIRATE_")
    }
    assert len(paths) == 9
    materials = ("LOCKED", "GRASS_LIGHT", "GRASS_DARK")
    tiles = [sprite for _, sprite in crop_sprites(
        bundle, group, {name: "IMAGE_WORLDMAP_PATH_PIRATE_" + name for name in materials}
    )]
    upgrades, = (group for group in ui.manifest()[2]["groups"] if group["id"] == "GameUpgrades_1536")
    reward, = (sprite for _, sprite in crop_sprites(
        ui, upgrades, {"reward": "IMAGE_WORLDMAP_COMMON_UPGRADE_GOLD_1"}
    ))
    return paths, tiles, reward


def patch_dynamic(dynamic, donor, picture, terrain_size, tiles, roads, fitted, paths, output, grid=None):
    bundle = Bundle(dynamic)
    manifest_idx, manifest_path, manifest = bundle.manifest()
    replace_rton(bundle, MAP_LIST, add_gallery_entry, allow_growth=True)
    replace_rton(bundle, RESOURCES, add_world_resources, allow_growth=True)
    replace_rton(bundle, r"PACKAGES\WORLDS\PTT.RTON",
                 lambda doc: doc["objects"][0]["objdata"].update(m_resGroupID=RES_ID + 1))
    add_localization(bundle, roads["nodes"] if roads is not None else [])
    append_cn_user_credit(bundle, description="秦始皇陵浮岛素材提取自")
    with ZipFile(donor) as apk:
        reference = Bundle(unwrap(apk.read("assets/uiactive.rsb.smf")))
    group, = (group for group in reference.manifest()[2]["groups"] if group["id"] == "UI_Universe_1200")
    sprites = dict(crop_sprites(reference, group, {ISLAND: ISLAND}))
    sprites[ISLAND].save(output / "mausoleum-island.png")
    with Image.open(picture) as original:
        sprites[BACKGROUND] = original.convert("RGBA")
    sprites.update((f"{TERRAIN_PREFIX}{i}", tile) for i, (_, _, tile) in enumerate(tiles, start=1))
    sprites.update(paths)
    add_world_map(bundle, manifest, terrain_size, tiles, roads, fitted, grid)
    add_art(bundle, manifest, sprites)
    bundle.replace_manifest(manifest_idx, manifest_path, manifest)
    updated = bundle.build()
    assert Bundle(updated).manifest()[2] == manifest
    return updated

def patch_engine(engine, surface_draw):
    if sha256(engine).hexdigest() != BASE_ENGINE:
        raise ValueError("Expected the A355 shared guest")
    elf = ELFFile(BytesIO(engine))
    index, segment = [(i, row) for i, row in enumerate(elf.iter_segments())
                      if row["p_type"] == "PT_LOAD"][-1]
    assert segment["p_flags"] == 5 and segment["p_filesz"] == segment["p_memsz"]
    assert segment["p_offset"] + segment["p_filesz"] == len(engine)
    patched = bytearray(engine)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def hook(address, expected, source, *, link):
        offset = file_offset(elf, address, 4)
        assert engine[offset:offset + 4] == expected
        patched.extend(bytes(-len(patched) % 4))
        entry = segment["p_vaddr"] + len(patched) - segment["p_offset"]
        patched.extend(assembler.asm(source, entry)[0])
        patched[offset:offset + 4] = branch(address, entry, link=link)

    # The new world is in the dynamic bundle that Aster mounts at startup.
    hook(0x415048, branch(0x415048, 0x1a68210), """
        ldr ip,[r1]
        ldr r2,[ip,#-12]
        cmp r2,#9
        bne stock_availability
        ldr r2,[ip]
        ldr r3,=0x7375616d
        cmp r2,r3
        ldreq r2,[ip,#4]
        ldreq r3,=0x75656c6f
        cmpeq r2,r3
        ldrbeq r2,[ip,#8]
        cmpeq r2,#109
        moveq r0,#1
        bxeq lr
    stock_availability:
        b #0x1a68210
        .ltorg
    """, link=False)

    # Load the extra float island with the other galaxy resources.
    for site, stock in ((0x988e50, 0x41c74c), (0x981404, 0x41c410)):
        # BLX to the old Thumb std::string ABI is emitted by its register form.
        hook(site, branch(site, stock, link=True), f"""
            push {{r4,r5,r6,lr}}
            mov r4,r0
            bl #{stock}
            sub sp,sp,#8
            mov r5,sp
            mov r0,r5
            adr r1,group_name
            add r2,sp,#4
            adr r3,construct_offset
            ldr ip,[r3]
            add ip,ip,r3
            blx ip
            mov r0,r4
            mov r1,r5
            bl #{stock}
            ldr r0,[r5]
            sub r0,r0,#12
            add r1,sp,#4
            adr r3,release_offset
            ldr ip,[r3]
            add ip,ip,r3
            blx ip
            add sp,sp,#8
            pop {{r4,r5,r6,pc}}
        construct_offset: .word 0
        release_offset: .word 0
        group_name: .asciz "{GROUP}"
        """, link=True)
        construct = patched.rindex(GROUP.encode() + b"\0") - 8
        release = construct + 4
        to_virtual = segment["p_vaddr"] - segment["p_offset"]
        struct.pack_into("<II", patched, construct,
                         (0x14ed0e1 - (to_virtual + construct)) & 0xffffffff,
                         (0x14ebf59 - (to_virtual + release)) & 0xffffffff)

    # Use Lost City's position for the preview without adding a fourth world
    # to the gate's three-world unlock animation.
    hook(0x987ed8, struct.pack("<I", 0xe594018c), f"""
        cmp r5,#4
        bne next_group
        cmp r6,#0
        beq next_group
        push {{r1,r2,r3,r4,r5,r6,r7,lr}}
        sub sp,sp,#16
        ldr r0,[r4,#0x1b4]
        ldr r1,[r4,#0x1b8]
    find_preview:
        cmp r0,r1
        beq layout_done
        ldr r7,[r0],#4
        ldr r2,[r7,#0x150]
        cmp r2,#{RES_ID}
        bne find_preview
        mov r0,r7
        mov r1,#1
        bl #0x98a9c0

        ldr r1,[r6,#0x28]
        ldr r2,[r6,#0x2c]
        ldr r3,[r6,#0x30]
        ldr r12,[r6,#0x34]
        add r1,r1,r3
        add r1,r1,r3,lsr #2
        str r1,[sp,#12]
        str r12,[sp]
        ldr r0,[r7]
        ldr r12,[r0,#0xac]
        mov r0,r7
        blx r12
        ldr r1,[sp,#12]
        ldr r2,[r6,#0x140]
        ldr r3,[r6,#0x144]
        ldr r12,[r6,#0x148]
        str r1,[r7,#0x13c]
        str r2,[r7,#0x140]
        str r3,[r7,#0x144]
        str r12,[r7,#0x148]
    layout_done:
        add sp,sp,#16
        pop {{r1,r2,r3,r4,r5,r6,r7,lr}}
    next_group:
        ldr r0,[r4,#0x18c]
        bx lr

    """, link=True)

    # This is the native world backdrop dispatch, before terrain or HUD draw.
    # Use the same viewport cover helper as Sky City with the Qin texture.
    hook(0x9dd5ac, struct.pack("<I", 0xe3500000), f"""
        cmp r0,#0
        beq stock_background
        ldr ip,[r0,#28]
        ldr r1,[ip,#-12]
        cmp r1,#9
        bne stock_background
        ldr r1,[ip]
        ldr r2,=0x7375616d
        cmp r1,r2
        ldreq r1,[ip,#4]
        ldreq r2,=0x75656c6f
        cmpeq r1,r2
        ldrbeq r1,[ip,#8]
        cmpeq r1,#109
        bne stock_background

        sub sp,sp,#64
        str r0,[sp]
        str r3,[sp,#4]
        mov ip,#0
        str ip,[sp,#8]
        str ip,[sp,#12]
        str ip,[sp,#16]
        adr ip,background_key
        str ip,[sp,#20]
        mov ip,#0
        str ip,[sp,#24]
        str ip,[sp,#28]
        add r0,sp,#32
        add r1,sp,#8
        mov r2,#2
        bl #0x7e8a28
        ldr r7,[sp,#36]
        add r0,sp,#24
        mov r2,#0
        mov r3,#0
        bl #0x1d9bb4
        ldr r0,[sp]
        ldr r3,[sp,#4]
        add sp,sp,#64
        cmp r7,#0
        beq stock_background

        mov r0,r5
        bl #0x116d800
        mov r2,#0
        str r2,[r5,#8]
        str r2,[r5,#12]
        strb r2,[r5,#0x64]
        mov r0,r5
        mov r1,r7
        bl #0x1a68490
        mov r0,r5
        bl #0x116d764
        b #0x9dd5f0
    stock_background:
        cmp r0,#0
        b #0x9dd5b0
    background_key: .asciz "{BACKGROUND}"
        .align 2
        .ltorg
    """, link=False)

    if surface_draw:
        install_road_draw(patched, segment["p_vaddr"] - segment["p_offset"], hook, surface_draw)
    size = len(patched) - segment["p_offset"]
    segment_header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, segment_header + 16, size, size)
    return bytes(patched)


def build(base, donor, background, project, upscaler, route_curb, route_levels, output, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    paths, materials, reward = world_map_art(base)
    grid = None
    if route_curb is not None:
        terrain, road_plan, layout, bounds, curb_alpha = build_route_only(
            project, route_curb, materials, output.parent, progress=route_levels,
        )
        if route_levels:
            roads, fitted, version = road_plan, None, 371
            grid = grid_events(layout, bounds)
            surfaces, surface_draw = grid_surface_art(road_plan, layout, bounds, curb_alpha, materials)
            paths.update(surfaces)
        else:
            roads, fitted, paths, surface_draw, version = None, None, {}, [], 370
        terrain.save(output.parent / "mausoleum-route-layer.png")
        with Image.open(background) as sky:
            stage = ImageOps.fit(sky.convert("RGBA"), (1700, 960))
        route_preview = terrain.copy()
        route_preview.thumbnail((1510, 831), Image.Resampling.LANCZOS)
        stage.alpha_composite(route_preview, ((stage.width - route_preview.width) // 2,
                                              (stage.height - route_preview.height) // 2))
        stage.save(output.parent / "route-only-full.png")
    else:
        terrain, roads, floor, fitted = render_map(project, upscaler.resolve())
        surface_sprites, surface_draw = surface_art(roads, terrain.size, floor, fitted, materials, reward)
        paths.update(surface_sprites)
        version = 368
    terrain_size = terrain.size
    preview = terrain.copy()
    preview.thumbnail((1088, 640), Image.Resampling.LANCZOS)
    preview.save(output.parent / "mausoleum-map.png")
    tiles = list(map_tiles(terrain))
    del terrain
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        patched = patch_engine(apk.read(engine), surface_draw)
        dynamic = apk.read(ASSET)
        world = patch_dynamic(dynamic, donor, background, terrain_size, tiles, roads, fitted, paths, output.parent,
                              grid)
        plan = create_plan(world, output.parent, rgba_atlases=3 + len(tiles) + len(paths))
        dex = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output.parent / "bootstrap", dynamic, world)
        manifest = manifest_version(apk.read(MANIFEST), version, 355, prefix="A")
    pack_apk(base, {engine: patched, ASSET: world, PLAN: plan, BOOTSTRAP: dex,
                    MANIFEST: manifest}, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "donor", "output", "sdk", "signing"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--upscaler", type=Path)
    mode.add_argument("--route-curb", type=Path)
    parser.add_argument("--route-levels", action="store_true", help="Test progression on the rebuilt grid")
    parser.add_argument("--background", type=Path,
                        default=Path(__file__).resolve().parents[1] / "src/mausoleum-map/art/background.png")
    parser.add_argument("--project", type=Path,
                        default=Path(__file__).resolve().parents[2]
                        / "tools/world-map-editor/web/projects/qin-carpet-routes.unline-map.json")
    args = parser.parse_args()
    if args.route_levels and args.route_curb is None:
        parser.error("--route-levels requires --route-curb")
    build(**vars(args))
