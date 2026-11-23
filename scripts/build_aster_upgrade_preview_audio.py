"""Build A336 with scoped Wwise cleanup for the plant upgrade preview."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_star_difficulty import ENGINE
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A335_ENGINE = "a283b73f7b4a37684906c75e65f43c432ef8d220fb1a07d43ed9465f59a0d4aa"
UNREGISTER_EMITTER = 0x13645C8
STOP_ALL_ON_EMITTER = 0x152A3C4
LAWN_APP_GOT = 0x1821674
PLANT_UPGRADE_DIALOG = 0x128C
POST_EMITTER_EVENT = 0x23F268
POST_PLANT_FOOD_SOUND = 0x4BE45C
CHANGE_PREVIEW_PLANT = 0x81B1EC
RELEASE_PREVIEW_GROUPS = 0x41C660
CHANGE_PREVIEW_GRADE = 0x817974
CLOSE_UPGRADE_DIALOG = 0x3FF63C


def patch_guest(engine):
    if sha256(engine).hexdigest() != A335_ENGINE:
        raise ValueError("Expected the A335 ARM32 guest engine")

    elf = ELFFile(BytesIO(engine))
    loads = [(i, segment) for i, segment in enumerate(elf.iter_segments())
             if segment["p_type"] == "PT_LOAD"]
    (state_index, state), (index, tail) = loads[-2:]
    preview_food = state["p_vaddr"] + state["p_memsz"]
    if (tail["p_flags"] != 5 or tail["p_offset"] + tail["p_filesz"] != len(engine)
            or tail["p_filesz"] != tail["p_memsz"] or state["p_flags"] != 6
            or preview_food % 4 or preview_food + 4 > tail["p_vaddr"]):
        raise ValueError("Unexpected A335 preview audio load segments")

    offset = (len(engine) + 15) & ~15
    address = tail["p_vaddr"] + offset - tail["p_offset"]
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    patched = bytearray(engine)
    code = bytearray()

    def emit(assembly, *relative_targets):
        entry = address + len(code)
        code.extend(bytes(assembler.asm(assembly, entry)[0]))
        for index, target in enumerate(relative_targets):
            literal = len(code) - 4 * (len(relative_targets) - index)
            struct.pack_into("<I", code, literal, (target - address - literal) & 0xFFFFFFFF)
        return entry

    def hook(site, expected, assembly, *relative_targets, link=False):
        file = file_offset(elf, site)
        if patched[file:file + 4] != expected:
            raise ValueError(f"Unexpected preview audio instruction at {site:#x}")
        patched[file:file + 4] = branch(site, emit(assembly, *relative_targets), link)

    # The activation and the animated charge share the preview plant's emitter.
    stop_preview_food = emit(f"""
        adr ip,state_anchor
        ldr r3,[ip]
        add ip,ip,r3
        ldr r0,[ip]
        mov r1,#0
        str r1,[ip]
        cmp r0,#0
        bxeq lr
        b #{STOP_ALL_ON_EMITTER}
    state_anchor:
        .word 0
    """, preview_food)

    require_preview = f"""
        adr ip,app_slot_delta
        ldr r3,[ip]
        ldr ip,[ip,r3]
        cmp ip,#0
        beq skip_cleanup
        ldr ip,[ip]
        cmp ip,#0
        beq skip_cleanup
        movw r3,#{PLANT_UPGRADE_DIALOG}
        ldr ip,[ip,r3]
        cmp ip,#0
        beq skip_cleanup
    """

    hook(POST_PLANT_FOOD_SOUND, branch(POST_PLANT_FOOD_SOUND, POST_EMITTER_EVENT, True), f"""
        cmp r0,#0
        cmnne r0,#1
        beq skip_cleanup
        {require_preview}
        adr ip,state_anchor
        ldr r3,[ip]
        str r0,[ip,r3]
    skip_cleanup:
        b #{POST_EMITTER_EVENT}
    state_anchor:
        .word 0
    app_slot_delta:
        .word 0
    """, preview_food, LAWN_APP_GOT, link=True)

    # Stop Plant Food before the preview resets its board or audio banks.
    stop_first = f"""
        push {{r0-r3,ip,lr}}
        bl #{stop_preview_food}
        pop {{r0-r3,ip,lr}}
    """
    hook(CHANGE_PREVIEW_PLANT, branch(CHANGE_PREVIEW_PLANT, RELEASE_PREVIEW_GROUPS, True),
         stop_first + f"b #{RELEASE_PREVIEW_GROUPS}", link=True)
    hook(CHANGE_PREVIEW_GRADE, struct.pack("<I", 0xE59630C0),
         stop_first + f"ldr r3,[r6,#0xc0]\nb #{CHANGE_PREVIEW_GRADE + 4}")
    hook(CLOSE_UPGRADE_DIALOG, struct.pack("<I", 0xE92D4878),
         stop_first + f".word 0xe92d4878\nb #{CLOSE_UPGRADE_DIALOG + 4}")

    # Other preview voices can outlive a Wwise game object too. Stop them on that
    # object before unregistering it. Zero and the wildcard ID are never targeted.
    hook(UNREGISTER_EMITTER, struct.pack("<I", 0xE52DB004), f"""
        cmp r1,#0
        cmnne r1,#1
        beq skip_cleanup
        adr ip,state_anchor
        ldr r3,[ip]
        add ip,ip,r3
        ldr r3,[ip]
        cmp r1,r3
        moveq r3,#0
        streq r3,[ip]
        {require_preview}
        push {{r0,r1,r2,lr}}
        mov r0,r1
        bl #{STOP_ALL_ON_EMITTER}
        pop {{r0,r1,r2,lr}}
    skip_cleanup:
        str fp,[sp,#-4]!
        b #{UNREGISTER_EMITTER + 4}
    state_anchor:
        .word 0
    app_slot_delta:
        .word 0
    """, preview_food, LAWN_APP_GOT)

    patched.extend(bytes(offset - len(engine)))
    patched.extend(code)
    segment_size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, segment_size, segment_size)
    state_header = elf["e_phoff"] + state_index * elf["e_phentsize"]
    struct.pack_into("<I", patched, state_header + 20, state["p_memsz"] + 4)
    return bytes(patched)


def build(base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_guest(apk.read(ENGINE))
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 336, 335, prefix="A")
    result = output / "PvZ2-Unline-Aster-A336-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "output", "sdk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
