"""Build A231 with shared collectible, cold effect and local world fixes."""
import argparse
from copy import copy
from pathlib import Path
import struct
from zipfile import ZipFile

from build_aster_hud_pickup import (
    ASSET, BASELINE, BOOTSTRAP, PLAN, PREFIX, Bundle, ResourceZip, copy_compressed_entry,
    create_plan, group_index, manifest_group, pack_pool, rebuild_dynamic_bootstrap,
    relocate_prefetch, replace_rton, replace_section, section, split_archive, texture_section,
)
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_auto_pickup import patch_native


ANIMATION = "POPANIM_EFFECTS_FROSTBITE_CHILL_PLANT"
ICE_GROUP = "FrostbiteIceBlockPlantGroup"


def replace_compressed_section(bundle, index, files, data, gpu):
    old = bundle.payloads[index]
    flags, data_size, gpu_size = (struct.unpack_from("<I", old, offset)[0] for offset in (16, 28, 44))
    assert flags == 3
    replace_section(bundle, index, files, data, gpu)
    group = bundle.payloads[index]
    data_start, _, _, _, gpu_start = struct.unpack_from("<5I", group, 24)
    data = group[data_start:gpu_start]
    gpu = group[gpu_start:]
    packed_data = pack_pool(data, include_empty=bool(data_size))
    packed_gpu = pack_pool(gpu, include_empty=bool(gpu_size))
    header = group[:data_start]
    struct.pack_into("<I", header, 16, flags)
    struct.pack_into("<II", header, 28, len(packed_data), len(data))
    struct.pack_into("<III", header, 40, len(header) + len(packed_data), len(packed_gpu), len(gpu))
    bundle.payloads[index] = header + packed_data + packed_gpu
    bundle.sync_info(index)


def add_cold_effect(original, source):
    bundle = Bundle(original.data)
    graphics = group_index(bundle, "LevelCommon2_1536")
    resident = group_index(bundle, "LevelCommon2_Common")
    ice_graphics = group_index(source, ICE_GROUP + "_1536")
    ice_resident = group_index(source, ICE_GROUP + "_Common")
    index, path, manifest = bundle.manifest()
    donor = source.manifest()[2]
    images = manifest_group(manifest, "LevelCommon2_1536")
    animation, = (r for r in manifest_group(donor, ICE_GROUP + "_Common") if r["id"] == ANIMATION)
    source_images = [r for r in manifest_group(donor, ICE_GROUP + "_1536")
                     if r["id"].startswith("IMAGE_EFFECTS_FROSTBITE_CHILL_PLANT_")]
    assert len(source_images) == 3

    filename = "\\".join(animation["path"]).upper()
    kind, offset, length = dict(source.files(ice_resident))[filename]
    assert kind == 0
    pam = section(source, ice_resident)[offset:offset + length]
    pam = pam.replace(b"FROSTBITE", b"ASTERCOLD").replace(b"frostbite", b"astercold")
    assert len(pam) == length

    count, first = struct.unpack_from("<II", bundle.infos[graphics], 196)
    donor_count, donor_first = struct.unpack_from("<II", source.infos[ice_graphics], 196)
    texture = source.textures[donor_first]
    width, height, _, fmt = struct.unpack_from("<4I", texture)
    assert count == donor_count == 1 and fmt == 161
    donor_pixels = texture_section(source.payloads[ice_graphics])
    stride = (width + 4) // 5 * 16
    assert len(donor_pixels) >= stride * ((height + 4) // 5)
    files = bundle.files(graphics)
    gpu = texture_section(bundle.payloads[graphics])
    additions = []
    for number, image in enumerate(source_images):
        x, y, w, h = (image[k] for k in ("ax", "ay", "aw", "ah"))
        left, top, right, bottom = x // 5, y // 5, (x + w + 4) // 5, (y + h + 4) // 5
        crop = b"".join(donor_pixels[row * stride + left * 16:row * stride + right * 16]
                        for row in range(top, bottom))
        w, h = (right - left) * 5, (bottom - top) * 5
        atlas = f"LevelCommon2_1536_Cold_{number:02}"
        atlas_id = "ATLASIMAGE_ATLAS_" + atlas.upper()
        slot = manifest["slot_count"]
        images.append(dict(slot=slot, id=atlas_id, path=["atlases", atlas], type="Image",
                           atlas=True, width=w, height=h))
        image = dict(image, id=image["id"].replace("FROSTBITE", "ASTERCOLD"), parent=atlas_id,
                     slot=slot + 1, ax=x % 5, ay=y % 5,
                     path=[part.replace("frostbite", "astercold") for part in image["path"]])
        assert image["id"].encode("ascii") in pam
        images.append(image)
        manifest["slot_count"] += 2
        files.append((f"ATLASES\\{atlas.upper()}.PTX", (1, len(gpu), len(crop), count + number, 0, 0, w, h)))
        gpu += crop + bytes(-len(crop) % 4096)
        replacement = copy(texture)
        struct.pack_into("<III", replacement, 0, w, h, w * 16 // 25)
        additions.append(replacement)

    bundle.textures[first + count:first + count] = additions
    struct.pack_into("<I", bundle.infos[graphics], 196, count + len(additions))
    for info in bundle.infos:
        other_count, other_start = struct.unpack_from("<II", info, 196)
        if other_count and other_start > first:
            struct.pack_into("<I", info, 200, other_start + len(additions))
    replace_compressed_section(bundle, graphics, files, section(bundle, graphics), gpu)

    alias = dict(animation, id=ANIMATION.replace("FROSTBITE", "ASTERCOLD"), slot=manifest["slot_count"],
                 path=[part.replace("frostbite", "astercold") for part in animation["path"]])
    manifest_group(manifest, "LevelCommon2_Common").append(alias)
    manifest["slot_count"] += 1
    resident_data = section(bundle, resident)
    files = bundle.files(resident) + [("\\".join(alias["path"]).upper(), (0, len(resident_data), len(pam)))]
    replace_compressed_section(bundle, resident, files, resident_data + pam, b"")
    bundle.replace_manifest(index, path, manifest)

    result = Bundle(bundle.build())
    assert result.manifest()[2] == manifest
    assert result.files(graphics) == bundle.files(graphics)
    assert section(result, resident)[len(resident_data):len(resident_data) + len(pam)] == pam
    assert all(a == b for i, (a, b) in enumerate(zip(original.payloads, result.payloads))
               if i not in (index, graphics, resident))
    return result


def rebuild_archives(apk, output, baseline, shim):
    archive = output / "resources.zip"
    with ResourceZip(apk) as stream, ZipFile(stream) as original, ZipFile(archive, "w", allowZip64=False) as target:
        name = "init.rsb.smf"
        entry = original.getinfo(PREFIX + name)
        prior = Bundle(original.read(entry))
        rebuilt = add_cold_effect(prior, Bundle(original.read(PREFIX + "iceage.rsb.smf")))
        record = name.encode("ascii") + struct.pack(">I", entry.file_size)
        assert baseline.count(record) == 1 and len(rebuilt.data) != entry.file_size
        baseline = baseline.replace(record, name.encode("ascii") + struct.pack(">I", len(rebuilt.data)))
        shim, relocated = relocate_prefetch(shim, prior, rebuilt)
        assert relocated == 13, relocated
        for member in original.infolist():
            if member == entry:
                target.writestr(copy(member), rebuilt.data)
            else:
                copy_compressed_entry(original, member, target)
        print(f"{name}: {entry.file_size} -> {len(rebuilt.data)}, {relocated} prefetch entries", flush=True)
    return split_archive(archive, output), baseline, shim


def remove_cold_world_dependency(document):
    corrected = set()
    for record in document["objects"]:
        groups = record.get("objdata", {}).get("PlantAudioGroups", [])
        if ICE_GROUP in groups:
            groups.remove(ICE_GROUP)
            corrected.update(record["aliases"])
    assert corrected == {"iceburg", "wintermelon", "iceshroom", "cottonyeti"}


def build(stock, previous, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: previous / f"PvZ2-Unline-Aster-A230-{abi}.apk" for abi in ("ARM32", "ARM64")}
    engines = {"ARM32": "lib/armeabi/libSrc.so", "ARM64": "assets/guest_libs/libSrc_a32.so"}
    shims = {"ARM32": "lib/armeabi/libRestart.so", "ARM64": "assets/guest_libs/libRestart_a32.so"}
    with ZipFile(stock / "PvZ2-Unline-Aster-A227-ARM32.apk") as apk:
        engine = patch_native(apk.read(engines["ARM32"]), ndk, output / "native", world_resources=True)
    with ZipFile(sources["ARM32"]) as apk:
        prior = apk.read(ASSET)
        baseline = apk.read(BASELINE)
        shim = apk.read(shims["ARM32"])
    dynamic = Bundle(prior)
    replace_rton(dynamic, r"PACKAGES\PLANTTYPES.RTON", remove_cold_world_dependency, allow_growth=True)
    dynamic = dynamic.build()
    plan = create_plan(dynamic, output)
    parts, updated_baseline, updated_shim = rebuild_archives(sources["ARM32"], output, baseline, shim)
    for abi, source in sources.items():
        with ZipFile(source) as apk:
            assert apk.read(ASSET) == prior and apk.read(BASELINE) == baseline and apk.read(shims[abi]) == shim
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 231, 230, prefix="A")
            dex = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / f"bootstrap-{abi}", prior, dynamic)
        changes = {**parts, ASSET: dynamic, PLAN: plan, BASELINE: updated_baseline, engines[abi]: engine,
                   shims[abi]: updated_shim, "AndroidManifest.xml": manifest, BOOTSTRAP: dex}
        final = output / f"PvZ2-Unline-Aster-A231-{abi}.apk"
        pack_apk(source, changes, sdk, final, signing)
        print(final, flush=True)
    for part in parts.values():
        part.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("stock", "previous", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
