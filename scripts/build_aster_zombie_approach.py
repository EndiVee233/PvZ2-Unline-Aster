"""Enable the native off-board zombie speed condition in Aster A351."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A350_ENGINE = "4adf1e70ec5fe576f74ebf0f12b2ee75d59a4195567f3ae65bb2bcae3000e1de"
SPAWN_INIT = 0x2168D8
ENTRANCE_FADE = 0x1A68A1C
APP_HOLDER = 0x1821674
GAME_CLOCK = 0x1F7380
CONDITION_CHANGED = 0xA4AF6C
APPROACH_CONDITION = 6


def patch_guest(engine):
    if sha256(engine).hexdigest() != A350_ENGINE:
        raise ValueError("Expected the A350 shared guest")
    elf = ELFFile(BytesIO(engine))
    index, tail = [(i, segment) for i, segment in enumerate(elf.iter_segments())
                   if segment["p_type"] == "PT_LOAD"][-1]
    if (tail["p_flags"] != 5 or tail["p_memsz"] != tail["p_filesz"]
            or tail["p_offset"] + tail["p_filesz"] != len(engine)):
        raise ValueError("Unexpected A350 engine code segment")

    padding = -len(engine) % 4
    stub = tail["p_vaddr"] + tail["p_filesz"] + padding
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    # The common spawn path runs before callers finish placing the zombie.
    # Its signed spawn index uses values below -1 for special placements.
    # Stock Zombie::Update clears condition 6 at x <= 792 before moving.
    # The condition tracker doubles the existing movement rate while bit 6
    # is set, then refreshes the rig on each condition transition.
    code = bytearray(assembler.asm(f"""
        push {{r4,r5,r6,lr}}
        mov r4,r2
        bl #{ENTRANCE_FADE}
        cmn r4,#1
        blt done
        ldrb r0,[sl,#0x60]
        cmp r0,#0
        bne done

        adr r0,app_offset
        ldr r1,[r0]
        ldr r0,[r0,r1]
        cmp r0,#0
        ldrne r0,[r0]
        cmp r0,#0
        beq done
        ldr r1,[r0,#0x6bc]
        cmp r1,r7
        bne done
        ldr r1,[r7,#0xc0]
        sub r1,r1,#4
        cmp r1,#1
        bhi done

        @ The PvP board uses arena-prefixed level names for manual deployment.
        ldr r0,[r7,#0xc4]
        cmp r0,#0
        beq done
        ldrb r1,[r0]
        cmp r1,#97
        ldrbeq r1,[r0,#1]
        cmpeq r1,#114
        ldrbeq r1,[r0,#2]
        cmpeq r1,#101
        ldrbeq r1,[r0,#3]
        cmpeq r1,#110
        ldrbeq r1,[r0,#4]
        cmpeq r1,#97
        ldrbeq r1,[r0,#5]
        cmpeq r1,#95
        beq done

        ldr r0,[sl,#0x240]
        tst r0,#(1 << {APPROACH_CONDITION})
        bne done
        ldr r5,[sl,#0x248]
        ldr r1,[sl,#0x24c]
        cmp r5,#0
        beq done
        sub r1,r1,r5
        cmp r1,#(16 * ({APPROACH_CONDITION} + 1))
        blo done
        ldr r0,[sl,#0x84]
        cmp r0,#0
        beq done
        bl #{GAME_CLOCK}
        ldr r0,[r0,#0x24]
        movw r1,#0xffff
        movt r1,#0x7f7f
        str r0,[r5,#(16 * {APPROACH_CONDITION})]
        str r1,[r5,#(16 * {APPROACH_CONDITION} + 4)]
        ldr r0,[sl,#0x240]
        orr r0,r0,#(1 << {APPROACH_CONDITION})
        str r0,[sl,#0x240]
        ldr r0,[sl,#0x264]
        orr r0,r0,#2
        str r0,[sl,#0x264]
        mov r0,sl
        mov r1,#{APPROACH_CONDITION}
        bl #{CONDITION_CHANGED}
    done:
        pop {{r4,r5,r6,pc}}
    app_offset:
        .word 0
    """, stub)[0])
    struct.pack_into("<i", code, len(code) - 4, APP_HOLDER - (stub + len(code) - 4))

    patched = bytearray(engine)
    offset = file_offset(elf, SPAWN_INIT)
    if engine[offset:offset + 4] != branch(SPAWN_INIT, ENTRANCE_FADE, True):
        raise ValueError("Unexpected zombie entrance fade hook")
    patched[offset:offset + 4] = branch(SPAWN_INIT, stub, True)
    patched.extend(bytes(padding) + code)
    size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, size, size)
    return bytes(patched)


def build(base, output, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_guest(apk.read(engine)),
            MANIFEST: manifest_version(apk.read(MANIFEST), 351, 350, prefix="A"),
        }
    pack_apk(base, updates, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
