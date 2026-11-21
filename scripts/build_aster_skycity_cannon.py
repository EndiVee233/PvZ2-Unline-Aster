"""Keep Sky City Fishing mode cannon coordinates in board units."""
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


# The alternate Board constructor stores the horizontal origin in display
# pixels. Fishing touch coordinates and effect/projectile positions use board
# units. Its background blits and switch overlay have their own pixel math.
ORIGINS = (
    (0xC7EE90, "r5", "r6"),  # Aim area and laser travel limits.
    (0xC7F7A4, "r3", "r0"),  # Muzzle position used by both cannon types.
    (0xC81610, "r5", "r4"),  # Cannon rig position.
    (0xC85884, "r5", "r4"),  # Intro and special cannon effects.
)


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
    helper = bytearray(assembler.asm(f"""
        adr r1,basepoint
        ldr ip,[r1]
        sub r1,r1,ip
        ldr ip,app_slot
        ldr r1,[r1,ip]
        ldr r1,[r1]
        ldr r1,[r1,#0x690]
        cmp r1,#0
        bxle lr
        movw ip,#0
        movt ip,#0x7f80
        cmp r1,ip
        bxhs lr
        vpush {{d0}}
        vmov s0,r0
        vmov s1,r1
        vcvt.f32.s32 s0,s0
        vdiv.f32 s0,s0,s1
        vcvt.s32.f32 s0,s0
        vmov r0,s0
        vpop {{d0}}
        bx lr
        app_slot: .word {APP_SLOT}
        basepoint: .word 0
    """, address)[0])
    struct.pack_into("<I", helper, len(helper) - 4, address + len(helper) - 4)
    payload = helper
    result = bytearray(native)
    for site, board, destination in ORIGINS:
        pos = file_offset(elf, site)
        old = file_offset(stock, site)
        expected = bytes(assembler.asm(f"ldr {destination},[{board},#0x96c]", site)[0])
        if native[pos:pos + 4] != expected or reference[old:old + 4] != expected:
            raise ValueError(f"Unexpected 1.7.5 Fishing offset load at {site:#x}")
        stub = address + len(payload)
        save_result = "str r0,[sp]" if destination == "r0" else f"mov {destination},r0"
        # Preserve condition flags from the original site. Two of the loads
        # sit between a comparison and the corresponding native branch.
        payload.extend(assembler.asm(f"""
            push {{r0-r3,ip,lr}}
            mrs r2,apsr
            ldr r0,[{board},#0x96c]
            bl #{address}
            msr apsr_nzcvq,r2
            {save_result}
            pop {{r0-r3,ip,pc}}
        """, stub)[0])
        result[pos:pos + 4] = branch(site, stub, True)
    end = offset + len(payload)
    if (end > data["p_offset"] or address + len(payload) > data["p_vaddr"]
            or any(native[code["p_offset"] + code["p_filesz"]:end])):
        raise ValueError("No free executable segment padding for Fishing fix")
    result[offset:end] = payload
    phdr = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", result, phdr + 16, size + len(payload), size + len(payload))
    return bytes(result)


def build(base, reference, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A245-{abi}.apk" for abi in ARM_ENGINES}
    with (ZipFile(sources["ARM32"]) as arm32, ZipFile(sources["ARM64"]) as arm64,
          ZipFile(reference) as donor):
        original = arm32.read(ARM_ENGINES["ARM32"])
        if original != arm64.read(ARM_ENGINES["ARM64"]):
            raise ValueError("A245 engines must share the same ARM32 code")
        patched = patch_native(original, donor.read(ARM_ENGINES["ARM32"]))
    for abi, member in ARM_ENGINES.items():
        with ZipFile(sources[abi]) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 247, 245, prefix="A")
        target = output / f"PvZ2-Unline-Aster-A247-{abi}.apk"
        pack_apk(sources[abi], {member: patched, "AndroidManifest.xml": manifest}, sdk, target, signing)
        print(target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "reference", "output", "sdk", "signing"):
        parser.add_argument("--" + option, required=True, type=Path)
    build(**vars(parser.parse_args()))
