"""Rebuild the Qin route as separate road cells on the native map axes."""

from collections import defaultdict
from itertools import pairwise
import json
from math import hypot

from PIL import Image, ImageChops, ImageDraw, ImageEnhance
import numpy as np

from render_aster_mausoleum_map import ATLAS_SCALE, WORLD_SCALE


# Half steps from the Egypt and Pirate mainline position records. The two
# screen-space directions intentionally have different slopes.
AXES = ((38.87, 16.45), (31.175, -18.55))
NEIGHBORS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def project(point):
    u, v = point
    return (AXES[0][0] * u + AXES[1][0] * v, AXES[0][1] * u + AXES[1][1] * v)


def route_corners(points, origin):
    corners = [origin]
    for a, b in pairwise(points):
        dx, dy = (b[0] - a[0]) * WORLD_SCALE, (b[1] - a[1]) * WORLD_SCALE
        steps = [(dx * x + dy * y) / (x * x + y * y) for x, y in AXES]
        axis = max(range(2), key=lambda i: abs(steps[i]) * hypot(*AXES[i]))
        amount = round(steps[axis])
        u, v = corners[-1]
        if amount == 0:
            raise ValueError(f"Road leg is shorter than one grid cell: {a} to {b}")
        corners.append((u + amount, v) if axis == 0 else (u, v + amount))
    return corners


def cells_between(a, b):
    length = abs(a[0] - b[0]) + abs(a[1] - b[1])
    dx, dy = ((b[0] - a[0]) // length, (b[1] - a[1]) // length)
    return [(a[0] + dx * step, a[1] + dy * step) for step in range(length + 1)]


def grid_location(reference, corners, point):
    best = None
    for (a, b), (start, end) in zip(pairwise(reference), pairwise(corners)):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = min(1, max(0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        error = hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)
        if best is None or error < best[0]:
            line = cells_between(start, end)
            best = error, line[round(t * (len(line) - 1))]
    return best[1]


def grid_layout(plan):
    paths = sorted(plan["paths"], key=lambda path: path["kind"] != "main")
    main_reference = paths[0]["points"]
    main = route_corners(main_reference, (0, 0))
    all_cells, layout = set(), []
    anchors = defaultdict(list)
    for node in plan["nodes"]:
        anchors[node["route"]].append(node)
    for path in paths:
        reference = path["points"]
        if path["kind"] == "main":
            corners = main
        else:
            junction = grid_location(main_reference, main, reference[0])
            corners = route_corners(reference, junction)
        cells = [corners[0]]
        for a, b in pairwise(corners):
            cells.extend(cells_between(a, b)[1:])
        intersection = all_cells.intersection(cells[1:])
        if len(set(cells)) != len(cells) or intersection:
            raise ValueError(f"{path['id']} has overlapping route cells: {sorted(intersection)}")
        all_cells.update(cells)
        nodes = [
            dict(id=node["id"], kind=node["kind"], cell=grid_location(reference, corners, (node["x"], node["y"])))
            for node in anchors[path["id"]]
        ]
        layout.append(dict(id=path["id"], kind=path["kind"], corners=corners, cells=cells, nodes=nodes))
    intended = {frozenset(edge) for route in layout for edge in pairwise(route["cells"])}
    joined = {frozenset(((u, v), (u + du, v + dv))) for u, v in all_cells
              for du, dv in NEIGHBORS if (u + du, v + dv) in all_cells}
    if joined != intended:
        raise ValueError("Grid snapping created an unintended junction")
    return layout


def quad(cell, half=.5):
    u, v = cell
    return [(u - half, v + half), (u + half, v + half), (u + half, v - half), (u - half, v - half)]


def planar_patch(texture, corners):
    """Sample a flat texture into a projected parallelogram at subpixel precision."""
    points = np.asarray(corners, dtype=float)
    x, y = np.floor(points.min(axis=0)).astype(int)
    right, bottom = np.ceil(points.max(axis=0)).astype(int)
    axes = np.column_stack((points[1] - points[0], points[3] - points[0]))
    inverse = np.diag(texture.size) @ np.linalg.inv(axes)
    bias = inverse @ (np.array((x, y)) - points[0])
    a, b, c, d = inverse.ravel()
    patch = texture.transform((right - x + 1, bottom - y + 1), Image.Transform.AFFINE,
                              (a, b, bias[0], c, d, bias[1]), Image.Resampling.BICUBIC)
    return patch, (int(x), int(y))


def relief(canvas, corners, height, faces):
    for side in faces:
        a, b = corners[side], corners[(side + 1) % 4]
        ImageDraw.Draw(canvas).polygon((a, b, (b[0], b[1] + height), (a[0], a[1] + height)),
                                      fill=faces[side])


def rectified_material(sprite, background):
    # The native road sprite is a diamond. Rectify its upper face once, then
    # reproject it to the same quad used for carpet and grass.
    corners = (67, 6, 9, 36, 69, 63, 126, 34)
    face = sprite.transform((128, 128), Image.Transform.QUAD, corners, Image.Resampling.BICUBIC)
    result = Image.new("RGBA", face.size, background)
    result.alpha_composite(face)
    return result


def stone_panel(sprite):
    """Use the source stone grain with a panel ruled in square coordinates."""
    size = 192
    panel = Image.new("RGBA", (size, size), "#3c5058")
    draw = ImageDraw.Draw(panel)
    draw.rectangle((4, 4, 187, 187), fill="#637a84")
    draw.rectangle((9, 9, 182, 182), fill="#41565e")
    draw.rectangle((14, 14, 177, 177), fill="#78939d")
    grain = rectified_material(sprite, "#617984").crop((41, 41, 88, 88))
    grain = grain.resize((152, 152), Image.Resampling.BICUBIC)
    panel.alpha_composite(grain, (20, 20))
    draw.line((14, 177, 14, 14, 177, 14), fill="#91a9b1", width=2)
    draw.line((177, 14, 177, 177, 14, 177), fill="#435c66", width=3)
    for x, y in ((18, 18), (173, 18), (173, 173), (18, 173)):
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#42565d")
        draw.ellipse((x - 3, y - 4, x + 2, y + 1), fill="#93a6af")
    return panel


def curb_surfaces(sprite):
    # Rectify three of the generated curb blocks into reusable top and side
    # faces. Their source corners are measured inside the opaque stone.
    tops = (
        (560, 525, 686, 577, 858, 495, 746, 438),
        (764, 431, 879, 488, 1065, 402, 949, 345),
        (972, 334, 1085, 390, 1254, 305, 1155, 250),
    )
    side = (900, 508, 901, 591, 1066, 516, 1066, 431)
    face = lambda corners: sprite.transform(
        (192, 96), Image.Transform.QUAD, corners, Image.Resampling.BICUBIC,
    )
    return [face(corners) for corners in tops], face(side)


def atlas_bounds(cells):
    coords = [project(point) for cell in cells for point in quad(cell, .76)]
    left = min(p[0] for p in coords) - 3
    top = min(p[1] for p in coords) - 8
    width = round((max(p[0] for p in coords) - left + 3) / ATLAS_SCALE)
    height = round((max(p[1] for p in coords) - top + 19) / ATLAS_SCALE)
    return left, top, width, height


def render_grid(layout, curb_material, plate, light, dark, grass=False, locked=True, curb_layer=None):
    roads = {cell: path["kind"] for path in reversed(layout) for cell in path["cells"]}
    left, top, width, height = atlas_bounds(roads)
    canvas = Image.new("RGBA", (width, height))

    def xy(point):
        x, y = project(point)
        return ((x - left) / ATLAS_SCALE, (y - top) / ATLAS_SCALE)

    def paste(texture, shape, target=canvas):
        sprite, position = planar_patch(texture, [xy(point) for point in shape])
        target.alpha_composite(sprite, position)

    base = ImageDraw.Draw(canvas)
    curb_height = 9 / ATLAS_SCALE
    curb_light, front_face = curb_material
    curb_dark = [ImageEnhance.Brightness(material).enhance(.80) for material in curb_light]
    stone = stone_panel(plate)
    greens = (rectified_material(light, "#6b9d1c"), rectified_material(dark, "#608e20"))
    cells = sorted(roads, key=lambda cell: (project(cell)[1], project(cell)[0]))
    sides, corners = [], set()
    for u, v in cells:
        top_face = list(map(xy, quad((u, v))))
        base.polygon(top_face, fill="#50152d")
        relief(canvas, top_face, curb_height, {1: "#171d2b", 2: "#253546"})
        for du, dv in NEIGHBORS:
            if (u + du, v + dv) not in roads:
                sides.append((u, v, du, dv))
        for du, dv in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
            if all(neighbor not in roads for neighbor in ((u + du, v), (u, v + dv), (u + du, v + dv))):
                corners.add((u + .5 * du, v + .5 * dv, du, dv))
    for u, v in cells:
        shape = quad((u, v))
        if roads[(u, v)] == "branch" and locked:
            paste(stone, shape)
        elif grass:
            paste(greens[(u + v) % 2], shape)
        else:
            color = ("#661e3b", "#691f3d", "#68203c")[(u - v) % 3]
            base.polygon(list(map(xy, shape)), fill=color)

    # Draw only boundary edges. Use separate cap stones at convex corners so
    # neither branch crosses nor bends expose a seam in the top of the curb.
    blocks = []
    for u, v, du, dv in sides:
        for index, (start, end) in enumerate(((-.5, -.055), (-.045, .5))):
            points = [(u + du * a + dv * b, v + dv * a + du * b)
                      for a, b in ((.5, start), (.72, start), (.72, end), (.5, end))]
            faces = curb_dark if du == -1 or dv == 1 else curb_light
            blocks.append((points, faces[(u * 7 + v + index) % len(faces)]))
    for u, v, du, dv in sorted(corners):
        points = ((u, v), (u + du * .22, v), (u + du * .22, v + dv * .22), (u, v + dv * .22))
        blocks.append((points, curb_light[0]))
    curb_target = canvas if curb_layer is None else curb_layer
    curb_draw = ImageDraw.Draw(curb_target)
    for points, texture in sorted(blocks, key=lambda block: sum(xy(point)[1] for point in block[0])):
        border = list(map(xy, points))
        center_y = sum(y for _, y in border) / len(border)
        for a, b in pairwise(border + [border[0]]):
            if (a[1] + b[1]) / 2 > center_y + .1:
                if a[0] > b[0]:
                    a, b = b, a
                face = [a, b, (b[0], b[1] + curb_height), (a[0], a[1] + curb_height)]
                sprite, position = planar_patch(front_face, face)
                curb_target.alpha_composite(sprite, position)
        curb_draw.polygon(border, fill="#3c536b")
        paste(texture, points, curb_target)
    if curb_layer is not None:
        canvas.alpha_composite(curb_layer)
    return canvas


def cell_surface(cells, textures, bounds, curb_alpha):
    left, top, _, _ = bounds
    patches = []
    for u, v in cells:
        screen = [((x - left) / ATLAS_SCALE, (y - top) / ATLAS_SCALE)
                  for x, y in map(project, quad((u, v)))]
        patches.append(planar_patch(textures[(u + v) % len(textures)], screen))
    x0 = min(x for _, (x, _) in patches)
    y0 = min(y for _, (_, y) in patches)
    right = max(x + tile.width for tile, (x, _) in patches)
    bottom = max(y + tile.height for tile, (_, y) in patches)
    layer = Image.new("RGBA", (right - x0, bottom - y0))
    for tile, (x, y) in patches:
        layer.alpha_composite(tile, (x - x0, y - y0))
    visible = ImageChops.invert(curb_alpha.crop((x0, y0, right, bottom)))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), visible))
    return layer, x0, y0


def build_route_only(project_path, curb, materials, output, progress=False):
    plan = json.loads(project_path.read_text(encoding="utf-8"))["routePlan"]
    layout = grid_layout(plan)
    with Image.open(curb) as source:
        texture = curb_surfaces(source.convert("RGBA"))
    bounds = atlas_bounds({cell for route in layout for cell in route["cells"]})
    left, top, width, height = bounds
    curb_layer = Image.new("RGBA", (width, height)) if progress else None
    terrain = render_grid(layout, texture, *materials, locked=not progress, curb_layer=curb_layer)
    if not progress:
        preview = render_grid(layout, texture, *materials, grass=True)
        preview.thumbnail((1600, 850), Image.Resampling.LANCZOS)
        preview.save(output / "mausoleum-route-grass.png")
    geometry = dict(axes=AXES, gridOriginPixels=(-left / ATLAS_SCALE, -top / ATLAS_SCALE),
                    worldUnitsPerPixel=ATLAS_SCALE, imageSize=(width, height), routes=layout)
    (output / "mausoleum-route.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    return terrain, plan, layout, bounds, curb_layer.getchannel("A") if progress else None
