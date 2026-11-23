"""Remove retired overlays and correct coin flights on the A328 guest."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile
import zlib

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_hud_pickup import BOOTSTRAP, ROOT
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from merge_legacy_pvp_resources import Bundle, u32
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch
from rebuild_bootstrap_dex import rebuild_bootstrap


ENGINE = "lib/armeabi/libSrc.so"
BASE_GUEST = "f68d59a228fb4dd11283bb2d26fcb690aa44938ed3ee7f89ef1962872aecf841"
TRANSPARENT_ASTC = bytes.fromhex("fcfdffffffffffff0000000000000000")


def patch_guest(engine):
    if sha256(engine).hexdigest() != BASE_GUEST:
        raise ValueError("Expected the A328 guest engine")
    elf = ELFFile(BytesIO(engine))
    index, segment = [(i, s) for i, s in enumerate(elf.iter_segments()) if s["p_type"] == "PT_LOAD"][-1]
    if segment["p_flags"] != 5 or segment["p_offset"] + segment["p_filesz"] != len(engine):
        raise ValueError("Unexpected executable tail")
    result = bytearray(engine)

    def write(site, original, replacement):
        offset = file_offset(elf, site)
        if result[offset:offset + 4] != original:
            raise ValueError(f"Unexpected word at {site:#x}")
        result[offset:offset + 4] = replacement

    # The plant exchange builds its tabs in order: Stars, Coins, Gold Beans.
    write(0xE52200, struct.pack("<I", 0xE3550003), struct.pack("<I", 0xE3550002))
    # Remove the older treasure drawer's Lucky action (widget ID 12).
    write(0xA392FC, branch(0xA392FC, 0xA39310), branch(0xA392FC, 0xA39358))
    # When a lane qualifies for the mower offer, leave through the existing
    # no-offer exit before pausing the board or setting the pending lane.
    write(0x4310E0, struct.pack("<I", 0xE3A01000), branch(0x4310E0, 0x4310EC))

    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def append_stub(instructions, has_base_anchor=False):
        result.extend(bytes(-len(result) % 4))
        address = segment["p_vaddr"] + len(result) - segment["p_offset"]
        code = bytearray(assembler.asm(instructions, address)[0])
        if has_base_anchor:
            struct.pack_into("<I", code, len(code) - 4, address + len(code) - 4)
        result.extend(code)
        return address

    # All store navigation requests go through this native queue entry. Reject the
    # exact "leaf" destination before committing the pending page or transition.
    entry = 0x35288C
    stub = append_stub(f"""
        ldr ip,[r1]
        push {{r2,r3}}
        ldr r2,[ip,#-12]
        cmp r2,#4
        ldreq r2,[ip]
        movweq r3,#0x656c
        movteq r3,#0x6661
        cmpeq r2,r3
        pop {{r2,r3}}
        bxeq lr
        .word 0xe92d48f0
        b #{entry + 4:#x}
    """)
    write(entry, struct.pack("<I", 0xE92D48F0), branch(entry, stub))

    # The bank returns its screen anchor in the caller's stack frame. Convert
    # it through the live camera before the native collectible tween starts.
    # Keep the original tween, award and draw order for every collectible.
    flight = 0x22C768
    tween = 0x2792EC
    stub = append_stub(f"""
        push {{r0-r4,lr}}
        adr r4, base_anchor
        ldr ip,[r4]
        sub r4,r4,ip
        ldr ip,[r0]
        sub ip,ip,r4
        movw r3,#0xa870
        movt r3,#0x0178
        cmp ip,r3
        bne finish
        ldr ip,app_slot
        ldr ip,[r4,ip]
        ldr ip,[ip]
        cmp ip,#0
        beq finish
        add ip,ip,#0x690
        vldr s2,[ip]
        vcmp.f32 s2,#0.0
        vmrs apsr_nzcv,fpscr
        ble finish

        sub sp,sp,#16
        vstr s2,[sp,#8]
        ldr r0,[r11,#-0x3c]
        ldr r1,[r11,#-0x38]
        ldr r2,[r7,#0x2c]
        ldr r3,[r7,#0x30]
        sub r0,r0,r2
        sub r1,r1,r3
        strd r0,r1,[sp]
        mov r0,r4
        mov r1,r7
        mov r2,sp
        bl #0x1a2d590
        ldr ip,[sp,#24]
        vldr s0,[sp]
        vldr s1,[sp,#4]
        vldr s2,[sp,#8]
        vcvt.f32.s32 s0,s0
        vcvt.f32.s32 s1,s1
        vdiv.f32 s0,s0,s2
        vdiv.f32 s1,s1,s2
        vstr s0,[ip]
        vstr s1,[ip,#4]
        add sp,sp,#16
    finish:
        pop {{r0-r4,lr}}
        b #{tween:#x}
    app_slot: .word 0x1821674
    base_anchor: .word 0
    """, has_base_anchor=True)
    write(flight, branch(flight, tween, True), branch(flight, stub, True))
    size = len(result) - segment["p_offset"]
    struct.pack_into("<II", result, elf["e_phoff"] + index * elf["e_phentsize"] + 16, size, size)
    return bytes(result)


def texture_patch(original, group_name, retired_prefix):
    """Erase blocks used by Lucky alone while retaining shared atlas boundaries."""
    bundle = Bundle(original)
    group, = (i for i, g in enumerate(bundle.groups) if g["ID"] == group_name)
    payload = bundle.payloads[group]
    files = dict(bundle.files(group))
    if u32(payload, 16) & 1 == 0:
        raise ValueError("Expected compressed texture allocation")
    packed_start, packed_size, unpacked_size = struct.unpack_from("<III", payload, 40)
    before = payload[packed_start:packed_start + packed_size]
    data = bytearray(zlib.decompress(before))
    if len(data) != unpacked_size:
        raise ValueError("Unexpected texture allocation length")

    group_manifest, = (g for g in bundle.manifest()[2]["groups"] if g["id"] == group_name)
    resources = group_manifest["resources"]
    parents = {r["parent"] for r in resources if r["id"].startswith(retired_prefix)}
    if not parents:
        raise ValueError("Missing Lucky Treasure sprites")
    for atlas in (r for r in resources if r["id"] in parents):
        name = "\\".join(atlas["path"]).upper() + ".PTX"
        _, start, length, texture, _, _, width, height = files[name]
        texture += u32(bundle.infos[group], 200)
        edge = 5
        stride = (width + edge - 1) // edge
        if u32(bundle.textures[texture], 12) != 161 or length != stride * ((height + edge - 1) // edge) * 16:
            raise ValueError("Unexpected Lucky Treasure ASTC atlas")
        lucky, retained = set(), set()
        for sprite in (r for r in resources if r.get("parent") == atlas["id"]):
            x, y, w, h = (sprite[key] for key in ("ax", "ay", "aw", "ah"))
            blocks = lucky if sprite["id"].startswith(retired_prefix) else retained
            blocks.update(row * stride + column
                          for row in range(y // edge, (y + h + edge - 1) // edge)
                          for column in range(x // edge, (x + w + edge - 1) // edge))
        for block in lucky - retained:
            offset = start + block * 16
            data[offset:offset + 16] = TRANSPARENT_ASTC
    after = zlib.compress(data, level=9)
    if len(after) > packed_size:
        raise ValueError("Replacement crosses the existing texture allocation")
    after = after.ljust(packed_size, b"\0")
    absolute = bundle.groups[group]["fields"][0] + packed_start
    assert original[absolute:absolute + packed_size] == before
    return struct.pack(">5I", len(original), absolute, packed_size, zlib.crc32(before),
                       zlib.crc32(after)) + after


def launch_art_update(smali):
    anchor = "    invoke-direct {p0}, Lcom/popcap/pvz2cthd/BootActivity;->applyPvpSkillResource()V\n"
    hook = ("    invoke-static {p0}, Lcom/popcap/pvz2cthd/AsterLuckyTreasureArt;"
            "->apply(Landroid/content/Context;)V\n")
    if smali.count(anchor) != 1:
        raise ValueError("Unexpected bootstrap flow")
    return smali.replace(anchor, anchor + "\n" + hook)


def build_art_dex(sdk, output):
    classes = output / "lucky-art-classes"
    classes.mkdir(exist_ok=True)
    android = sdk / "platforms/android-34/android.jar"
    class_path = "com/popcap/pvz2cthd/AsterLuckyTreasureArt"
    subprocess.run(["javac", "-source", "8", "-target", "8", "-Xlint:-options",
                    "-bootclasspath", android, "-d", classes,
                    ROOT / "src/bootstrap-extra" / f"{class_path}.java"], check=True)
    subprocess.run(["java", "-cp", sdk / "build-tools/34.0.0/lib/d8.jar", "com.android.tools.r8.D8",
                    "--min-api", "21", "--lib", android, "--output", classes,
                    classes / f"{class_path}.class"], check=True)
    return (classes / "classes.dex").read_bytes()


def build(base, uicommon, uiactive, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        assert "classes9.dex" not in apk.namelist()
        native = patch_guest(apk.read(ENGINE))
        boot = rebuild_bootstrap(apk.read(BOOTSTRAP), output / "bootstrap", {},
                                 ROOT.parent / "tools/apktool.jar", transform=launch_art_update)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 329, 328, prefix="A")
    result = output / "PvZ2-Unline-Aster-A329-ARM32-WSA-existing-data.apk"
    extras = {
        "assets/reconstruction/aster-lucky-art-uicommon.patch":
            texture_patch(uicommon.read_bytes(), "GoldCan_1536", "IMAGE_EFFECTS_GOLDCAN"),
        "assets/reconstruction/aster-lucky-art-uiactive.patch":
            texture_patch(uiactive.read_bytes(), "UI_Store_1536", "IMAGE_UI_STORE_GOLDCAN"),
        "classes9.dex": build_art_dex(sdk, output),
    }
    pack_apk(base, {ENGINE: native, BOOTSTRAP: boot, "AndroidManifest.xml": manifest},
             sdk, result, signing, extra_entries=extras)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "uicommon", "uiactive", "output", "sdk", "signing"):
        parser.add_argument("--" + name, required=True, type=Path)
    build(**vars(parser.parse_args()))
