"""Build A305 ARM32 from A303 with state-aware collectible input guards."""
import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch

ROOT = Path(__file__).resolve().parents[1]
ENGINE = "lib/armeabi/libSrc.so"
A303_ENGINE = "ff311cb31c7aae52e88a24ec93f7daa4cf71f451c4f05f9f40cbfb23a88f424a"
BASE_UPDATE = 0x27811c
AUTO_PICKUP = 0x1a681e0
PROGRAMMATIC_PICKUP = 0x27b558
TOUCH_PICKUP = 0x27b584


def compile_payload(ndk, output, start):
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    source = ROOT / "src/auto-pickup/collectible_access.cpp"
    script = output / "collectible-access.ld"
    binary = output / "collectible-access.elf"
    script.write_text(f"""ENTRY(asterAllowProgrammaticPickup)
SECTIONS {{
    . = {start};
    .payload : {{ *(.text*) *(.rodata*) }}
    /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }}
}}
""", encoding="ascii")
    subprocess.run([clang, "--target=armv7a-linux-androideabi24", "-marm", "-Os", "-fPIC",
                    "-ffreestanding", "-fno-stack-protector", "-fno-exceptions",
                    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-nostdlib", "-static",
                    "-Wl,--no-undefined", "-Wl,-T," + str(script), source, "-o", binary],
                   check=True)
    with binary.open("rb") as handle:
        elf = ELFFile(handle)
        code = elf.get_section_by_name(".payload")
        if code["sh_addr"] != start or any(
                s["sh_size"] and ((s["sh_flags"] & 3) == 3 or s["sh_type"] in ("SHT_REL", "SHT_RELA"))
                for s in elf.iter_sections()):
            raise ValueError("Collectible guard must be self-contained and read-only")
        symbols = {s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
        return bytearray(code.data()), symbols


def patch_native(native, ndk, output):
    if sha256(native).hexdigest() != A303_ENGINE:
        raise ValueError("The collectible fix expects the A303 ARM32 guest engine")
    elf = ELFFile(BytesIO(native))
    loads = [(i, s) for i, s in enumerate(elf.iter_segments()) if s["p_type"] == "PT_LOAD"]
    (code_index, code), (state_index, state) = loads[-2:]
    if (code["p_flags"], state["p_flags"]) != (5, 6) or code["p_filesz"] != code["p_memsz"]:
        raise ValueError("Unexpected guest segments")
    start = (code["p_vaddr"] + code["p_filesz"] + 15) & ~15
    payload, symbols = compile_payload(ndk, output, start)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    replacements = {}

    def redirect(site, expected, address):
        offset = file_offset(elf, site)
        if native[offset:offset+4] != expected:
            raise ValueError(f"Unexpected instruction at {site:#x}")
        replacements[offset] = branch(site, address)

    def guard(site, expected, accept, reject, *, touch=False):
        payload.extend(bytes(-len(payload) % 4))
        address = start + len(payload)
        prepare = "ldr r2,[r1,#0x28]" if touch else ""
        symbol = "asterAllowPickupTouch" if touch else "asterAllowProgrammaticPickup"
        encoded = bytes(assembler.asm(f"""
            push {{r0-r4,lr}}
            {prepare}
            mov r1,r0
            adr r0,basepoint
            ldr ip,[r0]
            sub r0,r0,ip
            bl #{symbols[symbol]}
            cmp r0,#0
            pop {{r0-r4,lr}}
            beq blocked
            {accept}
        blocked:
            {reject}
        basepoint: .word 0
        """, address)[0])
        payload.extend(encoded[:-4])
        payload.extend(struct.pack("<I", address + len(encoded) - 4))
        redirect(site, expected, address)

    # Skip just the existing automatic pickup callback for protected items.
    # Keep updating the collectible so its motion and normal lifetime continue.
    guard(BASE_UPDATE, branch(BASE_UPDATE, AUTO_PICKUP), f"b #{AUTO_PICKUP}",
          "push {r3-r6,fp,lr}\nb #0x278120")
    guard(PROGRAMMATIC_PICKUP, struct.pack("<I", 0xe52db004),
          "str fp,[sp,#-4]!\nb #0x27b55c", "bx lr")
    guard(TOUCH_PICKUP, struct.pack("<I", 0xe92d4bf0),
          "push {r4-r9,fp,lr}\nb #0x27b588", "mov r0,#0\nbx lr", touch=True)
    # ArenaBattleModule uses the independent reserved pickup at 0x27dc0c.

    # The existing automatic picker matches exact vtables. Its guarded update
    # has already excluded armed bombs, so route the converted subclass to sun.
    classify_sun = 0x1a654c0
    address = start + len(payload)
    payload.extend(bytes(assembler.asm("""
        cmp r0,r1
        beq #0x1a654e8
        movw r1,#0x64d0
        movt r1,#0x17f
        cmp r0,r1
        beq #0x1a654e8
        b #0x1a654c8
    """, address)[0]))
    redirect(classify_sun, struct.pack("<I", 0xe1500001), address)

    old_state = state["p_offset"]
    old_end = code["p_offset"] + code["p_filesz"]
    code_end = code["p_offset"] + start - code["p_vaddr"] + len(payload)
    alignment = state["p_align"]
    growth = (max(0, code_end - old_state) + alignment - 1) & -alignment
    if start + len(payload) >= state["p_vaddr"] or any(native[old_end:old_state]):
        raise ValueError("Collectible guards exceed the executable segment gap")
    result = bytearray(native[:old_state] + bytes(growth) + native[old_state:])
    result[code_end-len(payload):code_end] = payload
    for offset, value in replacements.items():
        result[offset:offset+4] = value
    headers, header_size = elf["e_phoff"], elf["e_phentsize"]
    size = code_end - code["p_offset"]
    struct.pack_into("<II", result, headers + code_index * header_size + 16, size, size)
    struct.pack_into("<I", result, headers + state_index * header_size + 4, old_state + growth)
    sections = elf["e_shoff"]
    if sections >= old_state:
        sections += growth
    struct.pack_into("<I", result, 32, sections)
    for index, section in enumerate(elf.iter_sections()):
        offset = section["sh_offset"]
        if offset >= old_state:
            struct.pack_into("<I", result, sections + index * elf["e_shentsize"] + 16, offset + growth)
    return result


def build(base, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_native(apk.read(ENGINE), ndk, output)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 305, 303, prefix="A")
    (output / "libSrc.so").write_bytes(engine)
    if signing:
        final = output / "PvZ2-Unline-Aster-A305-ARM32-WSA-existing-data.apk"
        pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, final, signing)
        print(final)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "output", "sdk", "ndk"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--signing", type=Path)
    build(**vars(parser.parse_args()))
