"""Attach stock teleport and phase-change effects to the Egyptian Zomboss group."""

import argparse
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile
import zlib

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_adventure_records import FLAGS
from build_aster_hud_pickup import BOOTSTRAP, ROOT, group_index, manifest_group
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from merge_legacy_pvp_resources import Bundle
from pam_transform_index import PamIndex
from prepare_aster_pvp_runtime import file_offset
from prepare_offline_pvp_seagull_hd import replace_section, section, texture_section
from prepare_profile_memory import branch
from rebuild_bootstrap_dex import rebuild_bootstrap


DONOR = "ZombossMechCommonGroup"
EGYPT = "ZombieEgyptZombossGroup"
TELEPORT_ANIMATIONS = ("POPANIM_EFFECTS_ZOMBOSS_TELEPORTATION_BALL",
                      "POPANIM_EFFECTS_ZOMBOSS_TELEPORT_BALL_EXIT")
ANIMATION_IDS = TELEPORT_ANIMATIONS + ("POPANIM_EFFECTS_ZOMBOSS_DAMAGE_CHUNKS",)
ENGINE = "lib/armeabi/libSrc.so"
ART_HOOKS = (0xBB3828, 0xBB3940, 0xBBA050, 0xBBD0A4, 0xBE7060)
ART_LOOKUP = 0xE45D08
PATCH_ASSET = "assets/reconstruction/aster-zomboss-art.patch"


def alias_id(resource_id):
    return resource_id.replace("ZOMBOSS", "EGYBOSS")


def resource_path(resource):
    return "\\".join(resource["path"]).upper()


def append_aligned(pool, data):
    offset = len(pool)
    pool.extend(data)
    pool.extend(bytes(-len(data) % 4096))
    return offset


def install_boss_art(original, animation_ids):
    bundle = Bundle(original)
    manifest_index, manifest_path, manifest = bundle.manifest()
    groups = {g["id"]: g for g in manifest["groups"]}

    def add_resource(group, resource, **updates):
        entry = deepcopy(resource)
        entry.update(updates, slot=manifest["slot_count"])
        manifest["slot_count"] += 1
        groups[group]["resources"].append(entry)
        return entry

    common = EGYPT + "_Common"
    common_index = group_index(bundle, common)
    donor_common = group_index(bundle, DONOR + "_Common")
    animations = {r["id"]: r for r in manifest_group(manifest, DONOR + "_Common")}
    donor_files = dict(bundle.files(donor_common))
    donor_data = section(bundle, donor_common)
    files = bundle.files(common_index)
    resident = bytearray(section(bundle, common_index))
    used_images = set()
    for old_id in animation_ids:
        source = animations[old_id]
        path = resource_path(source)
        kind, offset, size = donor_files[path]
        if kind != 0:
            raise ValueError("Expected a resident PAM animation")
        art = donor_data[offset:offset + size]
        index = PamIndex(art)
        changed = bytearray(art)
        for image in index.images:
            name = image["name"]
            prefix, separator, image_id = name.rpartition("|")
            used_images.add(image_id)
            rename = (prefix + separator + alias_id(image_id)).encode("ascii")
            name_bytes = name.encode("ascii")
            if len(rename) != len(name_bytes) or rename == name_bytes:
                raise ValueError(f"Unexpected PAM image name: {name}")
            end = image["off"]
            if changed[end - len(rename):end] != name_bytes:
                raise ValueError("PAM image index does not match the animation")
            changed[end - len(rename):end] = rename
        # Timelines and event labels stay byte-for-byte identical.
        if bytes(changed[index.sprites[0]["start"]:]) != art[index.sprites[0]["start"]:]:
            raise ValueError("Zomboss animation timeline changed")
        copy = add_resource(common, source, id=alias_id(old_id),
                            path=source["path"][:-1] + ["aster_" + source["path"][-1]])
        files.append((resource_path(copy), (0, append_aligned(resident, changed), size)))
    replace_section(bundle, common_index, sorted(files), resident)

    target_group = EGYPT + "_1536"
    donor_group = DONOR + "_1536"
    target = group_index(bundle, target_group)
    donor = group_index(bundle, donor_group)
    resources = manifest_group(manifest, donor_group)
    atlas, = (r for r in resources if r.get("atlas"))
    copies = {r["id"]: r for r in resources if r.get("parent") == atlas["id"] and r["id"] in used_images}
    if copies.keys() != used_images:
        raise ValueError(f"Missing stock Zomboss sprites: {sorted(used_images - copies.keys())}")
    atlas_path = "aster_egypt_zomboss_teleport_1536"
    atlas_id = "ATLASIMAGE_ATLAS_" + atlas_path.upper()
    add_resource(target_group, atlas, id=atlas_id, path=["atlases", atlas_path])
    for sprite in copies.values():
        add_resource(target_group, sprite, id=alias_id(sprite["id"]), parent=atlas_id,
                     path=sprite["path"][:-1] + ["aster_" + sprite["path"][-1]])

    info = dict(bundle.files(donor))[resource_path(atlas) + ".PTX"]
    _, offset, size, texture, _, _, width, height = info
    gpu = bytearray(texture_section(bundle.payloads[target]))
    texture_bytes = texture_section(bundle.payloads[donor])[offset:offset + size]
    atlas_offset = append_aligned(gpu, texture_bytes)
    if len(texture_bytes) != size:
        raise ValueError("Truncated stock teleport atlas")
    count, first = struct.unpack_from("<II", bundle.infos[target], 196)
    _, donor_first = struct.unpack_from("<II", bundle.infos[donor], 196)
    new_first = len(bundle.textures)
    bundle.textures.extend(deepcopy(bundle.textures[first:first + count] +
                                    [bundle.textures[donor_first + texture]]))
    struct.pack_into("<II", bundle.infos[target], 196, count + 1, new_first)
    files = bundle.files(target)
    files.append((resource_path({"path": ["atlases", atlas_path]}) + ".PTX",
                  (1, atlas_offset, size, count, 0, 0, width, height)))
    replace_section(bundle, target, sorted(files), section(bundle, target), gpu)
    bundle.replace_manifest(manifest_index, manifest_path, manifest)
    return bundle, {common_index, target, manifest_index}


def archive_spans(archive):
    first_offset = archive.groups[0]["fields"][0]
    spans = [(0, first_offset)]
    cursor = first_offset
    for group in archive.groups:
        offset, size = group["fields"][:2]
        if offset != cursor:
            raise ValueError("The resource archive has an unexpected group layout")
        spans.append((offset, size))
        cursor += size
    if cursor != len(archive.data):
        raise ValueError("Unexpected bytes after the last resource group")
    return spans


def encode_bundle_patch(original):
    teleport_only, _ = install_boss_art(original, TELEPORT_ANIMATIONS)
    complete, changed_groups = install_boss_art(original, ANIMATION_IDS)
    sources = [Bundle(original), Bundle(teleport_only.build())]
    target = Bundle(complete.build())
    group_names = [group["ID"] for group in target.groups]
    for source in sources:
        if [group["ID"] for group in source.groups] != group_names:
            raise ValueError("The resource archive has different groups")
    changed = {0, *(index + 1 for index in changed_groups)}
    parts = [struct.pack(">4sIII", b"AZB2", len(target.data), len(changed), len(sources)),
             sha256(target.data).digest()]
    for source in sources:
        parts.extend((struct.pack(">I", len(source.data)), sha256(source.data).digest()))
    source_spans = [archive_spans(source) for source in sources]
    for index, (offset, size) in enumerate(archive_spans(target)):
        data = target.data[offset:offset + size]
        for source, spans in zip(sources, source_spans, strict=True):
            old_offset, old_size = spans[index]
            if index in changed:
                parts.append(struct.pack(">II", old_offset, old_size))
            elif source.data[old_offset:old_offset + old_size] != data:
                raise ValueError(f"Unrelated resources changed: {group_names[index - 1]}")
        if index in changed:
            parts.extend((struct.pack(">I", size), data))
    return zlib.compress(b"".join(parts), level=9)


def patch_engine(original, ndk, output):
    elf = ELFFile(BytesIO(original))
    index, segment = [(i, s) for i, s in enumerate(elf.iter_segments())
                      if s["p_type"] == "PT_LOAD"][-1]
    if segment["p_flags"] != 5 or segment["p_offset"] + segment["p_filesz"] != len(original):
        raise ValueError("Unexpected executable segment")
    engine = bytearray(original)
    engine.extend(bytes(-len(engine) % 4))
    address = segment["p_vaddr"] + len(engine) - segment["p_offset"]
    obj = output / "zomboss-art.elf"
    layout = output / "zomboss-art.ld"
    layout.write_text(f"""ENTRY(asterZombossArt)
SECTIONS {{
    . = {address}; .payload : {{ *(.text*) *(.rodata*) }}
    /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }}
}}
""", encoding="ascii")
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    subprocess.run([clang, *FLAGS, "-nostdlib", "-static", "-Wl,--no-undefined",
                    "-Wl,-T," + str(layout), ROOT / "src/zomboss-art/zomboss_art.cpp", "-o", obj],
                   check=True)
    with obj.open("rb") as stream:
        payload = ELFFile(stream)
        code = payload.get_section_by_name(".payload")
        if code["sh_addr"] != address:
            raise ValueError("Unexpected Zomboss helper address")
        for section_info in payload.iter_sections():
            if section_info.name != ".payload" and section_info["sh_flags"] & 2 and section_info["sh_size"]:
                raise ValueError(f"Unexpected Zomboss helper section: {section_info.name}")
        (symbol,) = payload.get_section_by_name(".symtab").get_symbol_by_name("asterZombossArt")
        engine.extend(code.data())
    engine.extend(bytes(-len(engine) % 4))
    stub = segment["p_vaddr"] + len(engine) - segment["p_offset"]
    arm = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    engine.extend(bytes(arm.asm(f"""
        mov r2,r1
        mov r1,r0
        adr r0,base_anchor
        ldr ip,[r0]
        sub r0,r0,ip
        b #{symbol["st_value"]:#x}
    base_anchor: .word {stub + 24:#x}
    """, stub)[0]))
    for site in ART_HOOKS:
        offset = file_offset(elf, site)
        if original[offset:offset + 4] != branch(site, ART_LOOKUP, True):
            raise ValueError(f"Unexpected stock animation call at {site:#x}")
        engine[offset:offset + 4] = branch(site, stub, True)
    size = len(engine) - segment["p_offset"]
    struct.pack_into("<II", engine, elf["e_phoff"] + index * elf["e_phentsize"] + 16, size, size)
    return bytes(engine)


def insert_update(smali):
    anchor = ("    invoke-static {p0}, Lcom/popcap/pvz2cthd/AsterLuckyTreasureArt;"
              "->apply(Landroid/content/Context;)V\n")
    hook = anchor.replace("AsterLuckyTreasureArt", "AsterZombossArt")
    if smali.count(anchor) != 1:
        raise ValueError("Unexpected resource bootstrap")
    return smali.replace(anchor, anchor + "\n" + hook)


def allow_installed_update(smali):
    start = smali.index(".method public static ensureBaseline(Landroid/content/Context;)V")
    end = smali.index(".end method", start)
    method = smali[start:end]
    anchor = "    if-eqz v13, :cond_55\n"
    if method.count(anchor) != 1:
        raise ValueError("Unexpected resource baseline layout")
    check = (
        "\n    invoke-static {p0, v1, v7}, Lcom/popcap/pvz2cthd/AsterZombossArt;"
        "->matchesPatchedArchive(Landroid/content/Context;Ljava/io/File;Ljava/lang/String;)Z\n"
        "    move-result v13\n"
        "    if-nez v13, :cond_55\n"
    )
    return smali[:start] + method.replace(anchor, anchor + check) + smali[end:]


def build_dex(sdk, output):
    classes = output / "zomboss-art-java"
    classes.mkdir(exist_ok=True)
    android = sdk / "platforms/android-34/android.jar"
    package = "com/popcap/pvz2cthd"
    names = ("AsterLuckyTreasureArt", "AsterZombossArt")
    subprocess.run(["javac", "-source", "8", "-target", "8", "-Xlint:-options", "-bootclasspath",
                    android, "-d", classes, *(ROOT / "src/bootstrap-extra" / package / f"{n}.java"
                                              for n in names)], check=True)
    subprocess.run(["java", "-cp", sdk / "build-tools/34.0.0/lib/d8.jar", "com.android.tools.r8.D8",
                    "--min-api", "21", "--lib", android, "--output", classes,
                    *(classes / package / f"{n}.class" for n in names),
                    *sorted((classes / package).glob("AsterZombossArt$*.class"))], check=True)
    return (classes / "classes.dex").read_bytes()


def build(base, zombie1, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        native = patch_engine(apk.read(ENGINE), ndk, output)
        apktool = ROOT.parent / "tools/apktool.jar"
        boot = rebuild_bootstrap(apk.read(BOOTSTRAP), output / "bootstrap", {}, apktool,
                                 transform=insert_update)
        baseline = rebuild_bootstrap(apk.read("classes7.dex"), output / "baseline", {}, apktool,
                                     transform=allow_installed_update,
                                     class_path="com/popcap/pvz2cthd/AsterRgbaPilot.smali")
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 331, 329, prefix="A")
    result = output / "PvZ2-Unline-Aster-A331-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: native, BOOTSTRAP: boot, "classes7.dex": baseline,
                    "classes9.dex": build_dex(sdk, output),
                    "AndroidManifest.xml": manifest}, sdk, result, signing,
             extra_entries={PATCH_ASSET: encode_bundle_patch(zombie1.read_bytes())})
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "zombie1", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
