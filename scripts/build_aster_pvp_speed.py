"""Build A337 with a 3x fast-forward setting on PvP boards."""

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


A336_ENGINE = "2348b7dbc9d9eb8ca62a8e9a29d385852d425d8814d415bf09b569afa6397a8f"
SPEED_FAST_TARGET = 0x8F37A0
SPEED_TARGET_READY = 0x8F37A8
FEEDBACK_READ_RATE = 0x1AD5AF4
LAWN_APP_GOT = 0x1821674
# pvpMusicGrass in the installed payload identifies the four PvP board aliases.
IS_PVP_BOARD_LEVEL = 0x1AE45E0


def patch_guest(engine):
    if sha256(engine).hexdigest() != A336_ENGINE:
        raise ValueError("Expected the A336 ARM32 guest engine")

    elf = ELFFile(BytesIO(engine))
    index, tail = [(i, segment) for i, segment in enumerate(elf.iter_segments())
                   if segment["p_type"] == "PT_LOAD"][-1]
    if (tail["p_flags"] != 5 or tail["p_offset"] + tail["p_filesz"] != len(engine)
            or tail["p_filesz"] != tail["p_memsz"]):
        raise ValueError("Unexpected A336 executable tail")

    offset = (len(engine) + 15) & ~15
    address = tail["p_vaddr"] + offset - tail["p_offset"]
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    patched = bytearray(engine)
    patched.extend(bytes(offset - len(patched)))

    def hook(site, expected, assembly, *, relative_literal=None):
        file = file_offset(elf, site)
        if patched[file:file + 4] != struct.pack("<I", expected):
            raise ValueError(f"Unexpected speed instruction at {site:#x}")
        target = address + len(patched) - offset
        code = bytearray(assembler.asm(assembly, target)[0])
        if relative_literal is not None:
            literal = len(code) - 4
            struct.pack_into("<i", code, literal, relative_literal - (target + literal))
        patched.extend(code)
        patched[file:file + 4] = bytes(assembler.asm(f"bne #{target}", site)[0])

    # SpeedChange takes this path only when the current speed is 1x.
    # The original release-to-1x branch and speed event remain in use.
    hook(SPEED_FAST_TARGET, 0x13A04101, f"""
        mov r4,#0x40000000
        adr r0,app_slot_delta
        ldr r1,[r0]
        ldr r0,[r0,r1]
        cmp r0,#0
        ldrne r0,[r0]
        cmp r0,#0
        ldrne r0,[r0,#0x6bc]
        cmp r0,#0
        beq ready
        ldr r0,[r0,#0xc4]
        bl #{IS_PVP_BOARD_LEVEL}
        cmp r0,#0
        orrne r4,r4,#0x00400000
    ready:
        b #{SPEED_TARGET_READY}
    app_slot_delta:
        .word 0
    """, relative_literal=LAWN_APP_GOT)

    hook(FEEDBACK_READ_RATE, 0x15910030, """
        ldr r0,[r1,#0x30]
        eor r2,r0,#0x00400000
        cmp r2,#0x40000000
        moveq r0,#0x40000000
        bx lr
    """)

    segment_size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, segment_size, segment_size)
    return bytes(patched)


def build(base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_guest(apk.read(ENGINE))
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 337, 336, prefix="A")
    result = output / "PvZ2-Unline-Aster-A337-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "output", "sdk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
