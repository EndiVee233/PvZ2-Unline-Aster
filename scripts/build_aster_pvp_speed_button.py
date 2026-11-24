"""Build A338 with the native three-speed button in the PvP HUD."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, create_plan, rebuild_dynamic_bootstrap
from build_aster_legacy_endless_gameplay import Bundle, alias_data, replace_rton
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_star_difficulty import ENGINE
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A337_ENGINE = "d8e6795329203402a767ec72d649dd2ea1fdec858981d67024e8c9339acb76c2"
LAYOUTS = ("IPAD", "IPHONE", "IPHONE5", "IPHONESTRETCH")
ARENA_SPEED_EVENT = 0x10A23AC
DISPATCH_FLOAT_EVENT = 0x7DE8A0
FEEDBACK_RATE = 0x1AD5A9C
FEEDBACK_CHANGED = 0x1AD5AFC


def restore_arena_widget(document):
    objects = document["objects"]
    regular = alias_data(objects, "UIChangeSpeedButton")
    arena = alias_data(objects, "UIArenaChangeSpeedButton")
    for button in (regular, arena):
        if (button["Class"], button["SizeFromImage"]) != ("SpeedChange", "IMAGE_UI_HUD_INGAME_SPEED"):
            raise ValueError("Unexpected speed widget in the A337 HUD")
    arena.update(Class="ArenaChangeSpeedButton", SizeFromImage="IMAGE_UI_HUD_INGAME_ARENA_CHANGE_SPEED")


def patch_layouts(dynamic):
    bundle = Bundle(dynamic)
    for layout in LAYOUTS:
        replace_rton(bundle, rf"PACKAGES\UI_{layout}.RTON", restore_arena_widget, allow_growth=True)
    return bundle.build()


def patch_guest(engine):
    if sha256(engine).hexdigest() != A337_ENGINE:
        raise ValueError("Expected the A337 ARM32 guest engine")

    elf = ELFFile(BytesIO(engine))
    index, tail = [(i, segment) for i, segment in enumerate(elf.iter_segments())
                   if segment["p_type"] == "PT_LOAD"][-1]
    if (tail["p_flags"] != 5 or tail["p_offset"] + tail["p_filesz"] != len(engine)
            or tail["p_filesz"] != tail["p_memsz"]):
        raise ValueError("Unexpected A337 executable tail")

    site = file_offset(elf, ARENA_SPEED_EVENT)
    if engine[site:site + 4] != branch(ARENA_SPEED_EVENT, DISPATCH_FLOAT_EVENT, True):
        raise ValueError("Unexpected ArenaChangeSpeedButton dispatch")

    # Keep the original three-stage counter, art and speed event. Its dispatch
    # also uses the Aster cue when entering or leaving fast-forward.
    offset = (len(engine) + 15) & ~15
    address = tail["p_vaddr"] + offset - tail["p_offset"]
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code = bytearray(assembler.asm(f"""
        push {{r0-r2,r4,r5,lr}}
        adr r4,load_bias_anchor
        ldr r5,[r4]
        sub r4,r4,r5
        mov r0,r4
        bl #{FEEDBACK_RATE}
        mov r5,r0
        ldmia sp,{{r0-r2}}
        bl #{DISPATCH_FLOAT_EVENT}
        str r0,[sp]
        mov r0,r4
        mov r1,r5
        bl #{FEEDBACK_CHANGED}
        pop {{r0-r2,r4,r5,pc}}
    load_bias_anchor:
        .word 0
    """, address)[0])
    struct.pack_into("<I", code, len(code) - 4, address + len(code) - 4)

    patched = bytearray(engine)
    patched[site:site + 4] = branch(ARENA_SPEED_EVENT, address, True)
    patched.extend(bytes(offset - len(patched)))
    patched.extend(code)
    segment_size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, segment_size, segment_size)
    return bytes(patched)


def build(base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_guest(apk.read(ENGINE))
        original = apk.read(ASSET)
        dynamic = patch_layouts(original)
        plan = create_plan(dynamic, output, rgba_atlases=1)
        bootstrap = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / "bootstrap", original, dynamic)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 338, 337, prefix="A")
    result = output / "PvZ2-Unline-Aster-A338-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, ASSET: dynamic, PLAN: plan, BOOTSTRAP: bootstrap,
                    "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "output", "sdk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
