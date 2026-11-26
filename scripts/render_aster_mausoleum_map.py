"""Render the editor's Qin map export as a native 1536-tier map sprite."""

from base64 import b64decode
from io import BytesIO
import json
from math import ceil, dist, floor
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter


ATLAS_SCALE = 25 / 64
# The Egypt overview-to-detail zoom is about 3.1×. At the native close zoom
# this island needs 2.8× the authored extent to give the same overview framing.
WORLD_SCALE = 2.8
TILE_SIZE = 2048
TILE_OVERLAP = 4
SKY = "carpet-sky"
RAILINGS = Path(__file__).resolve().parents[1] / "src/mausoleum-map/art/railing-occlusion.json"


def embedded_image(value):
    header, encoded = value.split(",", 1)
    if header not in {"data:image/webp;base64", "data:image/png;base64"}:
        raise ValueError(f"Unexpected map image type: {header}")
    with Image.open(BytesIO(b64decode(encoded, validate=True))) as image:
        return image.convert("RGBA")


def carpet_masks(scenery):
    red, green, blue = np.asarray(scenery, dtype=np.int16)[:, :, :3].transpose(2, 0, 1)
    saturation = (red - green) * 20 - red * 12
    carpet = np.clip(np.minimum(saturation * 9, (red - blue - 14) * 22), 0, 255)
    core = Image.fromarray(carpet.astype(np.uint8))
    # The lighter woven edge touches the carpet. Recover it only near that
    # contact so the separately colored rails and scenery stay in front.
    edge = np.clip(np.minimum((red - green - 22) * 14, (red - blue - 10) * 16), 0, 255)
    trim = ImageChops.multiply(core.filter(ImageFilter.MaxFilter(5)), Image.fromarray(edge.astype(np.uint8)))
    return core, ImageChops.lighter(core, trim)


def preserve_railings(surface, source_size, top):
    layout = json.loads(RAILINGS.read_text(encoding="utf-8"))
    scale = source_size[0] / layout["sourceSize"][0]
    mask = Image.new("L", surface.size)
    draw = ImageDraw.Draw(mask)
    for group in layout["groups"]:
        bases = []
        for x, y, fix_x, fix_y, half_width in group:
            x, y = x * scale, y * scale + top
            fix_x, fix_y = fix_x * scale, fix_y * scale + top
            radius = half_width * scale
            draw.ellipse((x - radius, y - 4 * scale, x + radius, y + 5 * scale), fill=255)
            draw.polygon(((x - radius, y), (x + radius, y), (fix_x + radius, fix_y),
                          (fix_x - radius, fix_y)), fill=255)
            draw.ellipse((fix_x - radius, fix_y - 3 * scale, fix_x + radius, fix_y + 5 * scale), fill=255)
            bases.append((fix_x, fix_y))
        if len(bases) == 2:
            draw.line(bases, fill=255, width=round(7 * scale))
    return ImageChops.subtract(surface, mask)


def fit_road(points, source_mask, density):
    """Measure the carpet edges along each of the editor's straight legs."""
    plane = np.asarray(source_mask)
    segments = []
    for a, b in zip(points, points[1:]):
        a, b = np.array(a), np.array(b)
        length = dist(a, b)
        unit = (b - a) / length
        normal = np.array((-unit[1], unit[0]))
        offsets = np.arange(-13.0, 13.01, .5)
        scans = []
        for t in np.linspace(.15, .85, 15):
            xy = (a + unit * length * t + offsets[:, None] * normal) * density
            x, y = np.rint(xy).astype(int).T
            hits = plane[y, x] > 125
            changes = np.flatnonzero(np.diff(np.r_[False, hits, False]))
            if not len(changes):
                continue
            starts, stops = changes[::2], changes[1::2]
            largest = np.argmax(stops - starts)
            low, high = offsets[starts[largest]], offsets[stops[largest] - 1]
            if high - low >= 7:
                scans.append((t, (high + low) / 2, high - low))
        if len(scans) < 5:
            segments.append((a, b, length, 19.0))
            continue
        ts, centers, widths = np.array(scans).T
        median = np.median(centers)
        kept = np.abs(centers - median) <= 3
        slope, intercept = np.polyfit(ts[kept], centers[kept], 1) if kept.sum() >= 3 else (0, median)
        ends = np.clip((intercept, slope + intercept), -6, 6)
        width = float(np.clip(np.quantile(widths, .8) + 5.2, 16, 24))
        segments.append((a + normal * ends[0], b + normal * ends[1], length, width))
    for i in range(1, len(segments)):
        a, end, length, width = segments[i - 1]
        start, b, next_length, next_width = segments[i]
        left, right = end - a, b - start
        axes = np.column_stack((left, -right))
        if abs(np.linalg.det(axes)) > 1:
            join = a + left * np.linalg.solve(axes, start - a)[0]
            if dist(join, points[i]) <= 9:
                segments[i - 1] = (a, join, length, width)
                segments[i] = (join, b, next_length, next_width)
    return segments


def road_strip(segments, material, coverage):
    scale = WORLD_SCALE / ATLAS_SCALE
    projected = [(a * scale, b * scale, width * scale) for a, b, width in segments]
    points = [point for a, b, _ in projected for point in (a, b)]
    border = ceil(17 * scale)
    x0 = max(0, floor(min(p[0] for p in points)) - border)
    y0 = max(0, floor(min(p[1] for p in points)) - border)
    x1 = min(coverage.width, ceil(max(p[0] for p in points)) + border)
    y1 = min(coverage.height, ceil(max(p[1] for p in points)) + border)
    layer = Image.new("RGBA", (x1 - x0, y1 - y0))
    index = 0
    for start, end, width in projected:
        length = dist(start, end)
        if length < scale:
            continue
        count = max(1, round(length / (15 * scale)))
        dx, dy = (end[0] - start[0]) / count, (end[1] - start[1]) / count
        direction = -1 if dx * dy < 0 else 1
        along = np.array((abs(dx), direction * abs(dy)))
        across = np.array((-1.0, direction * .5))
        perpendicular_span = abs(along[0] * across[1] - along[1] * across[0]) / np.linalg.norm(along)
        across *= width / perpendicular_span
        source = np.array(((60, -60), (30 * direction, 30 * direction)))
        transform = source @ np.linalg.inv(np.column_stack((along * 1.045, across)))
        radius = ceil(max(abs(dx), abs(dy), abs(across[0])) * 1.15)
        for position in range(count):
            x = start[0] + dx * (position + .5)
            y = start[1] + dy * (position + .5)
            left, top = floor(x - radius), floor(y - radius)
            center = np.array((68, 36)) + transform @ np.array((left - x, top - y))
            a, b, c, d = transform.ravel()
            tile = material[index % len(material)].transform(
                (2 * radius, 2 * radius), Image.Transform.AFFINE,
                (a, b, center[0], c, d, center[1]), Image.Resampling.BICUBIC,
            )
            layer.alpha_composite(tile, (left - x0, top - y0))
            index += 1
    floor_alpha = coverage.crop((x0, y0, x1, y1))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), floor_alpha))
    bounds = layer.getbbox()
    return (x0 + bounds[0], y0 + bounds[1], layer.crop(bounds)) if bounds else None


def upscale_scenery(scenery, backdrop, upscaler):
    backdrop.alpha_composite(scenery)
    with TemporaryDirectory(prefix="aster-qin-") as directory:
        source = Path(directory) / "source.png"
        result = Path(directory) / "restored.png"
        backdrop.convert("RGB").save(source)
        subprocess.run([upscaler, "-i", source, "-o", result,
                        "-m", upscaler.parent / "models", "-n", "realesrgan-x4plus-anime",
                        "-s", "4", "-t", "256"], check=True)
        with Image.open(result) as image:
            restored = image.convert("RGBA")
    assert restored.size == (scenery.width * 4, scenery.height * 4)
    restored.putalpha(scenery.getchannel("A").resize(restored.size, Image.Resampling.LANCZOS))
    return restored


def render_map(project_path, upscaler):
    project = json.loads(project_path.read_text(encoding="utf-8"))
    if project["format"] != "unline-map-editor" or project["version"] != 1:
        raise ValueError("Expected a version 1 world map editor export")
    assets = {asset["id"]: asset for asset in project["assets"]}
    sky, = (item for item in project["objects"] if item["asset"] == SKY)
    sky_asset = assets[SKY]
    size = round(sky_asset["w"]), 640
    # Reassemble the source pixels before rescaling so adjacent cutouts meet cleanly.
    sky_image = embedded_image(sky_asset["src"])
    density = sky_image.width / sky_asset["w"]
    scenery = Image.new("RGBA", tuple(round(value * density) for value in size))
    for item in sorted(project["objects"], key=lambda item: item["layer"]):
        if item["asset"] == SKY:
            continue
        asset = assets[item["asset"]]
        sprite = embedded_image(asset["src"])
        left = round((item["x"] - asset["w"] / 2) * density)
        top = round((item["y"] - asset["h"]) * density)
        scenery.alpha_composite(sprite, (left, top))
    scale = WORLD_SCALE / ATLAS_SCALE
    plan = project["routePlan"]
    backdrop = Image.new("RGBA", scenery.size, "#172238")
    sky_top = round((sky["y"] - sky_asset["h"]) * density)
    backdrop.alpha_composite(sky_image, (0, sky_top))
    enhanced = upscale_scenery(scenery, backdrop, upscaler)
    target_size = tuple(round(value * scale) for value in size)
    canvas = Image.blend(scenery.resize(target_size, Image.Resampling.LANCZOS),
                         enhanced.resize(target_size, Image.Resampling.LANCZOS), .78)
    core, surface = carpet_masks(scenery)
    surface = preserve_railings(surface, sky_image.size, sky_top)
    fitted = {path["id"]: fit_road(path["points"], core, density) for path in plan["paths"]}
    return canvas, plan, surface.resize(canvas.size, Image.Resampling.BILINEAR), fitted


def map_tiles(canvas):
    for y in range(0, canvas.height, TILE_SIZE):
        for x in range(0, canvas.width, TILE_SIZE):
            left, top = max(0, x - TILE_OVERLAP), max(0, y - TILE_OVERLAP)
            right = min(x + TILE_SIZE + TILE_OVERLAP, canvas.width)
            bottom = min(y + TILE_SIZE + TILE_OVERLAP, canvas.height)
            tile = canvas.crop((left, top, right, bottom))
            bounds = tile.getbbox()
            if bounds:
                yield left + bounds[0], top + bounds[1], tile.crop(bounds)
