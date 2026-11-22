"""Build the A303 ARM32 WSA candidate from the existing A302 test APK."""
import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from shutil import copyfile
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_auto_pickup import patch_native as patch_sign_in
from prepare_aster_pvp_feedback import NEW_STATE, ROOT, compile_payload, file_offset
from prepare_profile_memory import branch


ENGINE = "lib/armeabi/libSrc.so"
A302_ENGINE = "ed562d9fc10acc9065a2015af7ba07cee7edc746f8c02d06efbfe5478da13fdb"


def patch_pvp(native, sdk, headers, output):
    elf = ELFFile(BytesIO(native))
    loads = [(i, segment) for i, segment in enumerate(elf.iter_segments())
             if segment["p_type"] == "PT_LOAD"]
    (code_index, code), (state_index, state) = loads[-2:]
    if (code["p_flags"], state["p_flags"]) != (5, 6):
        raise ValueError("Missing A302 PvP code and state segments")
    start = (code["p_vaddr"] + code["p_filesz"] + 15) & ~15
    compiled = compile_payload(sdk, ROOT / "src", headers, output, start, NEW_STATE, archived=False)
    with compiled.open("rb") as handle:
        guest = ELFFile(handle)
        payload = bytearray(guest.get_section_by_name(".payload").data())
        runtime = guest.get_section_by_name(".runtime").data()
        symbols = {s.name: s["st_value"] for s in guest.get_section_by_name(".symtab").iter_symbols()}
    runtime_offset = file_offset(elf, NEW_STATE, len(runtime))
    if native[runtime_offset:runtime_offset + len(runtime)] != runtime:
        raise ValueError("P0 must use the current A302 PvP runtime without changing its storage")

    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    replacements = {}

    def redirect(site, old, target, link=False):
        offset = file_offset(elf, site)
        if native[offset:offset + 4] != old:
            raise ValueError(f"Unexpected A302 instruction at {site:#x}")
        replacements[offset] = branch(site, target, link)

    def wrapper(site, old, source):
        origin = start + len(payload)
        code_bytes = bytes(assembler.asm(source + "\nbasepoint: .word 0", origin)[0])
        payload.extend(code_bytes[:-4])
        payload.extend(struct.pack("<I", origin + len(code_bytes) - 4))
        redirect(site, old, origin)

    # The normal and post-commit paths share the refreshed projection.
    region_site = 0x1a3a0bc
    redirect(region_site, branch(region_site, 0x1a44728, True),
             symbols["_ZL13projectGardenjPh"], True)
    redirect(0x1a38000, struct.pack("<I", 0xe92d4ff0), symbols["offlineGarden"])

    base_arg = "adr r0,basepoint\nldr ip,[r0]\nsub r0,r0,ip"
    preview = 0x109a1a8
    wrapper(preview, branch(preview, 0x1a641e0), f"""
        push {{r0-r4,lr}}
        mov r2,r0
        mov r1,r4
        {base_arg}
        bl #{symbols['offlineTutorialPreviewRewards']}
        cmp r0,#0
        pop {{r0-r4,lr}}
        bne #0x109a1c0
        b #0x1a641e0
    """)
    for site, original, register in ((0x1051244, 0xe59020c4, "r0"),
                                     (0x1051920, 0xe59e20c4, "lr")):
        wrapper(site, struct.pack("<I", original), f"""
            ldr r2,[{register},#0xc4]
            push {{r0-r4,lr}}
            mov r1,r2
            {base_arg}
            bl #{symbols['offlineTutorialResultCoins']}
            str r0,[sp,#8]
            pop {{r0-r4,lr}}
            b #{site+4}
        """)
    wrapper(0x1051da0, struct.pack("<I", 0xe3a02ffa), f"""
        push {{r0-r4,lr}}
        bl #{symbols['offlineFirstAttackCoins']}
        str r0,[sp,#8]
        pop {{r0-r4,lr}}
        b #0x1051da4
    """)

    old_state = state["p_offset"]
    code_end = code["p_offset"] + start - code["p_vaddr"] + len(payload)
    new_state = max(old_state, (code_end + 4095) & ~4095)
    if start + len(payload) >= state["p_vaddr"]:
        raise ValueError("PvP code exceeds the A302 executable range")
    if any(native[code["p_offset"] + code["p_filesz"]:old_state]):
        raise ValueError("Unexpected data in the A302 segment gap")
    growth = new_state - old_state
    result = bytearray(native[:old_state] + bytes(growth) + native[old_state:])
    result[code_end - len(payload):code_end] = payload
    for offset, value in replacements.items():
        result[offset:offset + 4] = value
    headers_at, header_size = elf["e_phoff"], elf["e_phentsize"]
    size = code_end - code["p_offset"]
    struct.pack_into("<II", result, headers_at + code_index * header_size + 16, size, size)
    struct.pack_into("<I", result, headers_at + state_index * header_size + 4, new_state)
    sections = elf["e_shoff"]
    if sections >= old_state:
        sections += growth
    struct.pack_into("<I", result, 32, sections)
    for index, section in enumerate(elf.iter_sections()):
        offset = section["sh_offset"]
        if offset >= old_state:
            struct.pack_into("<I", result, sections + index * elf["e_shentsize"] + 16, offset + growth)
    return bytes(result)


def build(base, output, sdk, ndk, pvp_headers, signing):
    output.mkdir(parents=True, exist_ok=True)
    (output / "generated").mkdir(exist_ok=True)
    copyfile(pvp_headers / "exchange-presets.json", output / "generated/exchange-presets.json")
    with ZipFile(base) as apk:
        original = apk.read(ENGINE)
        manifest = apk.read("AndroidManifest.xml")
    if sha256(original).hexdigest() != A302_ENGINE:
        raise ValueError("The P0 build expects the A302 WSA guest engine")
    engine = patch_pvp(original, sdk, pvp_headers, output)
    engine = patch_sign_in(engine, ndk, output / "sign-in", offline_sign_in=True, refresh_sign_in=True)
    (output / "libSrc.so").write_bytes(engine)
    if signing:
        final = output / "PvZ2-Unline-Aster-A303-ARM32-WSA-existing-data.apk"
        manifest = manifest_version(manifest, 303, 302, prefix="A")
        pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, final, signing)
        print(final)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for item in ("base", "output", "sdk", "ndk", "pvp-headers"):
        parser.add_argument("--" + item, required=True, type=Path)
    parser.add_argument("--signing", type=Path)
    build(**vars(parser.parse_args()))
