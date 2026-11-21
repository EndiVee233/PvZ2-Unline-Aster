"""Build A248 with viewport-aware cannon aiming and seamless Sky City scroll."""
import argparse
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_skycity_cover import APP_SLOT, ARM_ENGINES
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


AIM_EDGE = 0xC84848
LASER_EDGE = 0xC80108
SKY_PERIOD = 0x3337CC
SKY_FIRST_TILE = 0x334E44
SKY_OLD_TILES = 0x334E48
SKY_AFTER_TILES = 0x334EB0
DRAW_IMAGE = 0x11694C8
DRAW_IMAGE_MIRRORED = 0x1169870


def patch_native(native, reference):
    elf = ELFFile(BytesIO(native))
    stock = ELFFile(BytesIO(reference))
    loads = [(i, seg) for i, seg in enumerate(elf.iter_segments()) if seg["p_type"] == "PT_LOAD"]
    (index, code), (_, data) = loads[-2:]
    if code["p_flags"] != 5 or code["p_filesz"] != code["p_memsz"]:
        raise ValueError("Expected final executable load segment")
    size = (code["p_filesz"] + 15) & ~15
    address = code["p_vaddr"] + size
    offset = code["p_offset"] + size
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    result = bytearray(native)
    payload = bytearray()

    def emit(source):
        start = address + len(payload)
        payload.extend(assembler.asm(source, start)[0])
        return start

    def redirect(site, expected, target, link=True):
        pos = file_offset(elf, site)
        original = file_offset(stock, site)
        op = bytes(assembler.asm(expected, site)[0])
        if native[pos:pos + 4] != op or reference[original:original + 4] != op:
            raise ValueError(f"Unexpected 1.7.5 instruction at {site:#x}")
        result[pos:pos + 4] = branch(site, target, link)

    # Native touch positions use screen pixels divided by the current scale.
    # Keep the stock minimum reach and leave the spawn rectangle intact.
    right_edge = emit(f"""
        adr r1,basepoint
        ldr ip,[r1]
        sub r1,r1,ip
        ldr ip,app_slot
        ldr r1,[r1,ip]
        ldr r1,[r1]
        ldr ip,[r1,#0x690]
        cmp ip,#0
        bxle lr
        ldr r1,[r1,#0x524]
        cmp r1,#0
        bxle lr
        vpush {{d0}}
        vmov s0,r1
        vmov s1,ip
        vcvt.f32.s32 s0,s0
        vdiv.f32 s0,s0,s1
        vcvt.s32.f32 s1,s0
        vmov r1,s1
        vcvt.f32.s32 s1,s1
        vcmp.f32 s0,s1
        vmrs apsr_nzcv,fpscr
        addgt r1,r1,#1
        vpop {{d0}}
        cmp r1,r0
        movge r0,r1
        bx lr
        app_slot: .word {APP_SLOT}
        basepoint: .word 0
    """)
    struct.pack_into("<I", payload, len(payload) - 4, address + len(payload) - 4)
    aim = emit(f"""
        push {{r0,r1,r3,lr}}
        add r0,r2,r1
        bl #{right_edge}
        mov r2,r0
        pop {{r0,r1,r3,pc}}
    """)
    laser = emit(f"""
        add r0,r2,r0
        b #{right_edge}
    """)
    redirect(AIM_EDGE, "add r2,r2,r1", aim)
    redirect(LASER_EDGE, "add r0,r2,r0", laser)

    # Alternating normal and mirrored tiles join matching image edges. A
    # two-tile scroll period keeps the orientation continuous at wraparound.
    period = emit("""
        ldr r0,[r4,#0x28]
        lsl r0,r0,#1
        bx lr
    """)
    redirect(SKY_PERIOD, "ldr r0,[r4,#0x28]", period)

    # Choose the first tile intersecting the graphics clip rectangle. Native
    # image drawing applies the origin and clip, including on the mirrored path.
    tiles = emit(f"""
        push {{r4-r11,lr}}
        sub sp,sp,#4
        mov r4,r0
        mov r5,r1
        mov r6,r2
        mov r7,r3
        ldr r8,[r5,#0x28]
        ldr r9,[r4,#0x28]
        cmp r8,#0
        ble done
        cmp r9,#0
        ble done
        ldr r11,[r4,#0x20]
        vldr s0,[r4,#8]
        vcvt.s32.f32 s0,s0
        vmov r0,s0
        sub r11,r11,r0
        add r9,r9,r11
        mov r10,#0
        previous:
        cmp r6,r11
        subgt r6,r6,r8
        eorgt r10,r10,#1
        bgt previous
        next:
        add r0,r6,r8
        cmp r0,r11
        movle r6,r0
        eorle r10,r10,#1
        ble next
        draw:
        mov r0,r4
        mov r1,r5
        mov r2,r6
        mov r3,r7
        cmp r10,#0
        strne r10,[sp]
        bne mirror
        bl #{DRAW_IMAGE}
        b advance
        mirror:
        bl #{DRAW_IMAGE_MIRRORED}
        advance:
        add r6,r6,r8
        eor r10,r10,#1
        cmp r6,r9
        blt draw
        done:
        add sp,sp,#4
        pop {{r4-r11,pc}}
    """)
    redirect(SKY_FIRST_TILE, f"bl #{DRAW_IMAGE}", tiles)
    redirect(SKY_OLD_TILES, "mov r0,r4", SKY_AFTER_TILES, link=False)

    end = offset + len(payload)
    if (end > data["p_offset"] or address + len(payload) > data["p_vaddr"]
            or any(native[code["p_offset"] + code["p_filesz"]:end])):
        raise ValueError("No free executable segment padding for Sky City changes")
    result[offset:end] = payload
    phdr = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", result, phdr + 16, size + len(payload), size + len(payload))
    return bytes(result)


def build(base, reference, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A247-{abi}.apk" for abi in ARM_ENGINES}
    with (ZipFile(sources["ARM32"]) as arm32, ZipFile(sources["ARM64"]) as arm64,
          ZipFile(reference) as donor):
        original = arm32.read(ARM_ENGINES["ARM32"])
        if original != arm64.read(ARM_ENGINES["ARM64"]):
            raise ValueError("A247 engines must share the same ARM32 code")
        patched = patch_native(original, donor.read(ARM_ENGINES["ARM32"]))
    for abi, member in ARM_ENGINES.items():
        with ZipFile(sources[abi]) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 248, 247, prefix="A")
        target = output / f"PvZ2-Unline-Aster-A248-{abi}.apk"
        pack_apk(sources[abi], {member: patched, "AndroidManifest.xml": manifest}, sdk, target, signing)
        print(target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "reference", "output", "sdk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
