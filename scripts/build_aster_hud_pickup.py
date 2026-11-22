"""Build the shared A228 HUD, map, Gold Leaf and pickup fixes over A227."""
import argparse
from copy import copy
from hashlib import sha256
from pathlib import Path
import re
import struct
from zipfile import ZipFile

from build_aster_compact_resources import BASELINE, PREFIX, ResourceZip, copy_compressed_entry, pack_pool, split_archive
from build_aster_legacy_endless_gameplay import BOOTSTRAP, Bundle, replace_rton
from build_aster_pvp_feedback import pack_apk
from build_aster_rgba_background_pilot import ASSET, PLAN, create_plan
from build_aster_save_path_fix import manifest_version
from prepare_offline_pvp_seagull_hd import replace_section, section, texture_section
from rebuild_bootstrap_dex import rebuild_bootstrap

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "assets/pvz2tool/version/base/smf/"
PORTRAIT = "IMAGE_UI_HUD_INGAME_PROGRESS_METER_ZOMBOSS_HEAD"
UI_IMAGES = "UIImages_1536"
GOLD_TILE = "GoldTileModule_1536"


def group_index(bundle, name):
    index, = (i for i, group in enumerate(bundle.groups) if group["ID"] == name)
    return index


def manifest_group(manifest, name):
    group, = (g for g in manifest["groups"] if g["id"] == name)
    return group["resources"]


def restore_boss_portraits(base, donor):
    index = group_index(base, UI_IMAGES)
    donor_index = group_index(donor, UI_IMAGES)
    manifest_index, path, manifest = base.manifest()
    images = manifest_group(manifest, UI_IMAGES)
    references = {r["id"]: r for r in manifest_group(donor.manifest()[2], UI_IMAGES)}
    count, first = struct.unpack_from("<II", base.infos[index], 196)
    donor_count, donor_first = struct.unpack_from("<II", donor.infos[donor_index], 196)
    assert count == donor_count == 1
    source_texture = donor.textures[donor_first]
    source_width, source_height, _, fmt = struct.unpack_from("<4I", source_texture)
    source_bytes = texture_section(donor.payloads[donor_index])
    block = 5
    source_stride = ((source_width + block - 1) // block) * 16
    assert fmt == 161 and len(source_bytes) >= source_stride * ((source_height + block - 1) // block)

    files = base.files(index)
    gpu = texture_section(base.payloads[index])
    additions = []
    for variant, image_id in enumerate((PORTRAIT, PORTRAIT + "_DARK")):
        assert all(r["id"] != image_id for r in images)
        image = copy(references[image_id])
        assert image["parent"] == "ATLASIMAGE_ATLAS_UIIMAGES_1536_00"
        x, y, width, height = (image[k] for k in ("ax", "ay", "aw", "ah"))
        left, top = x // block, y // block
        right = (x + width + block - 1) // block
        bottom = (y + height + block - 1) // block
        crop = b"".join(source_bytes[row * source_stride + left * 16:row * source_stride + right * 16]
                        for row in range(top, bottom))
        width, height = (right - left) * block, (bottom - top) * block
        assert len(crop) == width * height // (block * block) * 16
        atlas_name = f"UIImages_1536_Zomboss_{variant:02}"
        atlas_id = f"ATLASIMAGE_ATLAS_{atlas_name.upper()}"
        slot = manifest["slot_count"]
        images.append(dict(slot=slot, id=atlas_id, path=["atlases", atlas_name], type="Image",
                           atlas=True, width=width, height=height))
        image.update(slot=slot + 1, parent=atlas_id, ax=x % block, ay=y % block)
        images.append(image)
        manifest["slot_count"] += 2

        files.append((f"ATLASES\\{atlas_name.upper()}.PTX",
                      (1, len(gpu), len(crop), count + variant, 0, 0, width, height)))
        gpu += crop + bytes((-len(crop)) % 4096)
        texture = copy(source_texture)
        struct.pack_into("<III", texture, 0, width, height, width * 16 // (block * block))
        additions.append(texture)

    base.textures[first + count:first + count] = additions
    struct.pack_into("<I", base.infos[index], 196, count + len(additions))
    for other, info in enumerate(base.infos):
        other_count, other_start = struct.unpack_from("<II", info, 196)
        if other != index and other_count and other_start > first:
            struct.pack_into("<I", info, 200, other_start + len(additions))
    replace_section(base, index, files, section(base, index), gpu)
    group = base.payloads[index]
    gpu_start = struct.unpack_from("<I", group, 40)[0]
    packed = pack_pool(bytes(group[gpu_start:]))
    del group[gpu_start:]
    group.extend(packed)
    struct.pack_into("<I", group, 16, 1)
    struct.pack_into("<I", group, 44, len(packed))
    base.sync_info(index)
    base.replace_manifest(manifest_index, path, manifest)


def restore_gold_leaf(base, donor):
    manifest_index, path, manifest = base.manifest()
    images = manifest_group(manifest, GOLD_TILE)
    refs = {tuple(r["path"]): r for r in manifest_group(donor.manifest()[2], GOLD_TILE)}
    animation = section(base, group_index(base, "GoldTileModule_Common"))
    assert animation == section(donor, group_index(donor, "GoldTileModule_Common"))
    changed = 0
    for image in images:
        if image.get("atlas"):
            continue
        corrected = refs[tuple(image["path"])]
        assert corrected["id"].encode("ascii") in animation
        assert all(image[k] == corrected[k] for k in ("parent", "ax", "ay", "aw", "ah"))
        assert image["id"].replace("IMAGE_EFFECTS_", "IMAGE_BACKGROUNDS_", 1) == corrected["id"]
        image["id"] = corrected["id"]
        changed += 1
    assert changed == 13
    base.replace_manifest(manifest_index, path, manifest)
    # Baseline migration compares bundle lengths. Give the updated resident
    # manifest one reserved page so upgrades also replace the old bundle.
    group = base.payloads[manifest_index]
    size = struct.unpack_from("<I", group, 32)[0] + 4096
    struct.pack_into("<II", group, 28, size, size)
    struct.pack_into("<I", group, 40, len(group) + 4096)
    group.extend(bytes(4096))
    base.sync_info(manifest_index)


def fix_zoom_layout(document):
    objects = document["objects"]
    button, = (r for r in objects if r.get("aliases") == ["UIWorldMapZoomButton"])
    assert button["objdata"]["Class"] == "WorldMap_ZoomButton"
    objects[:] = [r for r in objects if r.get("aliases") != ["UIWorldMapZoomButton1"]]
    button["objdata"]["SingleInstance"] = 1


def relocate_prefetch(shim, original, rebuilt):
    """Retarget only the offsets and pool lengths of existing ASTC cache rows."""
    before = iter(original.groups)
    pool_record = struct.Struct("<QQIII")
    changed = 0
    for after in rebuilt.groups:
        prior = next(before)
        assert prior["ID"] == after["ID"]
        old_slot = original.payloads[prior["fields"][2]]
        new_slot = rebuilt.payloads[after["fields"][2]]
        old_gpu, old_packed, old_raw = struct.unpack_from("<III", old_slot, 40)
        if not old_packed:
            continue
        new_gpu, new_packed, new_raw = struct.unpack_from("<III", new_slot, 40)
        old_fields = pool_record.pack(len(original.data), prior["fields"][0] + old_gpu,
                                      old_packed, old_raw, old_slot[16] & 1)
        hits = shim.count(old_fields)
        if not hits:
            continue
        assert new_raw >= old_raw
        assert texture_section(new_slot)[:old_raw] == texture_section(old_slot)
        new_fields = pool_record.pack(len(rebuilt.data), after["fields"][0] + new_gpu,
                                      new_packed, new_raw, new_slot[16] & 1)
        shim = shim.replace(old_fields, new_fields)
        changed += hits
    return shim, changed


def rebuild_content(source, reference, out, baseline, shim):
    transforms = {"uicommon.rsb.smf": restore_boss_portraits, "plant1.rsb.smf": restore_gold_leaf}
    archive_path = out / "resources.zip"
    with ResourceZip(source) as stream, ZipFile(stream) as original, ZipFile(reference) as donor, \
            ZipFile(archive_path, "w", allowZip64=False) as target:
        for entry in original.infolist():
            name = entry.filename.removeprefix(PREFIX)
            if name not in transforms:
                copy_compressed_entry(original, entry, target)
                continue
            prior = Bundle(original.read(entry))
            base = Bundle(prior.data)
            transforms[name](base, Bundle(donor.read(REFERENCE + name)))
            result = base.build()
            check = Bundle(result)
            index, _, manifest = check.manifest()
            assert manifest == base.manifest()[2]
            for i, payload in enumerate(check.payloads):
                if i != index:
                    assert payload == base.payloads[i]
            old_record = name.encode("ascii") + struct.pack(">I", entry.file_size)
            assert baseline.count(old_record) == 1 and len(result) != entry.file_size
            baseline = baseline.replace(old_record, name.encode("ascii") + struct.pack(">I", len(result)))
            shim, prefetches = relocate_prefetch(shim, prior, check)
            assert prefetches == {"plant1.rsb.smf": 82, "uicommon.rsb.smf": 55}[name]
            target.writestr(copy(entry), result)
            print(f"{name}: {entry.file_size} -> {len(result)}, {prefetches} prefetch entries", flush=True)
    return split_archive(archive_path, out), baseline, shim


def rebuild_dynamic_bootstrap(dex, output, dynamic, updated_dynamic, *, transform=None):
    old_hash, new_hash = sha256(dynamic).hexdigest(), sha256(updated_dynamic).hexdigest()
    literals = {old_hash: new_hash}
    if len(dynamic) != len(updated_dynamic):
        literals[hex(len(dynamic))] = hex(len(updated_dynamic))

    def allow_previous(smali):
        marker = ".method private static isSupportedResourcePredecessor(Ljava/lang/String;)Z\n    .registers 2\n"
        assert smali.count(marker) == 1
        patched = smali.replace(marker, marker + f"""
    const-string v0, "{old_hash}"
    invoke-virtual {{v0, p0}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :prior_resource_checks
    const/4 v0, 0x1
    return v0
    :prior_resource_checks
""")
        return transform(patched) if transform else patched
    return rebuild_bootstrap(dex, output, literals, ROOT.parent / "tools/apktool.jar",
                             transform=allow_previous)


def build(base, output, reference, sdk, ndk, signing):
    from prepare_aster_auto_pickup import patch_native

    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A227-{abi}.apk" for abi in ("ARM32", "ARM64")}
    members = {"ARM32": "lib/armeabi/libSrc.so", "ARM64": "assets/guest_libs/libSrc_a32.so"}
    shims = {"ARM32": "lib/armeabi/libRestart.so", "ARM64": "assets/guest_libs/libRestart_a32.so"}
    with ZipFile(sources["ARM32"]) as arm32, ZipFile(sources["ARM64"]) as arm64:
        dynamic = arm32.read(ASSET)
        baseline = arm32.read(BASELINE)
        engine = arm32.read(members["ARM32"])
        shim = arm32.read(shims["ARM32"])
        assert engine == arm64.read(members["ARM64"])
        assert shim == arm64.read(shims["ARM64"])
        assert dynamic == arm64.read(ASSET) and baseline == arm64.read(BASELINE)
        assert all(arm32.getinfo(f"assets/pvz2data.zip.00{i}").CRC ==
                   arm64.getinfo(f"assets/pvz2data.zip.00{i}").CRC for i in (1, 2, 3))
    patched_engine = patch_native(engine, ndk, output / "native")
    maps = Bundle(dynamic)
    for layout in ("IPAD", "IPHONE", "IPHONE5", "IPHONESTRETCH"):
        replace_rton(maps, f"PACKAGES\\UI_{layout}.RTON", fix_zoom_layout, allow_growth=True)
    updated_dynamic = maps.build()
    plan = create_plan(updated_dynamic, output)
    parts, updated_baseline, updated_shim = rebuild_content(sources["ARM32"], reference, output, baseline, shim)

    for abi, source in sources.items():
        with ZipFile(source) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 228, 227, prefix="A")
            dex = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / f"bootstrap-{abi}",
                                            dynamic, updated_dynamic)
        changes = {**parts, ASSET: updated_dynamic, PLAN: plan, BASELINE: updated_baseline,
                   members[abi]: patched_engine, shims[abi]: updated_shim,
                   "AndroidManifest.xml": manifest, BOOTSTRAP: dex}
        final = output / f"PvZ2-Unline-Aster-A228-{abi}.apk"
        pack_apk(source, changes, sdk, final, signing)
        print(final, flush=True)
    for part in parts.values():
        part.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "reference", "sdk", "ndk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
