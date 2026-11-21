"""Route the Sky City world map background through Aster's title cover draw."""
import argparse
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


SKY_DRAW = 0x97427C
ORIGINAL_DRAW = 0xD056DC
TITLE_COVER = 0x1A05014
APP_SLOT = 0x1821674
ARM_ENGINES = {
    "ARM32": "lib/armeabi/libSrc.so",
    "ARM64": "assets/guest_libs/libSrc_a32.so",
}


def patch_native(native):
    elf = ELFFile(BytesIO(native))
    at = lambda address: file_offset(elf, address)
    # World map's skycity branch and the two title draw stubs in A244.
    for site, target in (
        (0x9DD600, 0x974054),
        (SKY_DRAW, ORIGINAL_DRAW),
        (0x462A00, 0x1A2B314),
        (0x95E3BC, 0x1A2B358),
        (0x1A2B348, TITLE_COVER),
        (0x1A2B38C, TITLE_COVER),
    ):
        if native[at(site):at(site) + 4] != branch(site, target, True):
            raise ValueError(f"Unexpected Aster draw site {site:#x}")
    app_literal = struct.unpack_from("<I", native, at(0x974374))[0]
    if app_literal + 0x9740B8 != APP_SLOT:
        raise ValueError("Sky City background viewport source changed")

    loads = [(i, seg) for i, seg in enumerate(elf.iter_segments()) if seg["p_type"] == "PT_LOAD"]
    (index, code), (_, data) = loads[-2:]
    if code["p_flags"] != 5 or code["p_filesz"] != code["p_memsz"]:
        raise ValueError("Expected final executable load segment")
    aligned_size = (code["p_filesz"] + 15) & ~15
    address = code["p_vaddr"] + aligned_size
    offset = code["p_offset"] + aligned_size
    # The stock draw has already set the graphics origin to (0, 0) and
    # cleared the full viewport. Pass the same dimensions to the title helper.
    wrapper = bytearray(Ks(KS_ARCH_ARM, KS_MODE_ARM).asm(f"""
        push {{r4,lr}}
        sub sp,sp,#16
        mov r2,r1
        mov r1,r0
        adr r0,basepoint
        ldr r4,[r0]
        sub r0,r0,r4
        ldr r4,app_slot
        ldr r4,[r0,r4]
        ldr r4,[r4]
        mov r3,#0
        str r3,[sp]
        ldr ip,[r4,#0x524]
        str ip,[sp,#4]
        ldr ip,[r4,#0x528]
        str ip,[sp,#8]
        bl #{TITLE_COVER}
        add sp,sp,#16
        pop {{r4,pc}}
        app_slot: .word {APP_SLOT}
        basepoint: .word 0
    """, address)[0])
    struct.pack_into("<I", wrapper, len(wrapper) - 4, address + len(wrapper) - 4)
    end = offset + len(wrapper)
    if (end > data["p_offset"] or address + len(wrapper) > data["p_vaddr"]
            or any(native[code["p_offset"] + code["p_filesz"]:end])):
        raise ValueError("No free executable segment padding for Sky City cover")

    result = bytearray(native)
    result[offset:end] = wrapper
    draw_offset = at(SKY_DRAW)
    result[draw_offset:draw_offset + 4] = branch(SKY_DRAW, address, True)
    phdr = elf["e_phoff"] + index * elf["e_phentsize"]
    new_size = aligned_size + len(wrapper)
    struct.pack_into("<II", result, phdr + 16, new_size, new_size)
    return bytes(result)


def build(base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    source = {abi: base / f"PvZ2-Unline-Aster-A244-{abi}.apk" for abi in ARM_ENGINES}
    with ZipFile(source["ARM32"]) as arm32, ZipFile(source["ARM64"]) as arm64:
        original = arm32.read(ARM_ENGINES["ARM32"])
        if original != arm64.read(ARM_ENGINES["ARM64"]):
            raise ValueError("A244 engines must share the same ARM32 code")
    patched = patch_native(original)
    for abi, member in ARM_ENGINES.items():
        with ZipFile(source[abi]) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 245, 244, prefix="A")
        target = output / f"PvZ2-Unline-Aster-A245-{abi}.apk"
        pack_apk(source[abi], {member: patched, "AndroidManifest.xml": manifest}, sdk, target, signing)
        print(target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
