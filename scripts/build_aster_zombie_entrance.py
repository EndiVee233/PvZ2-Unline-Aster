"""Build A250 with a fade scoped to the zombie renderer."""
import argparse
from io import BytesIO
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_skycity_cover import ARM_ENGINES
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


ROOT = Path(__file__).resolve().parents[1]
SPAWN_INIT = 0x2168D8
STOCK_INIT = 0xA43A44
DRAW_RIG = 0x776B54
ZOMBIE_DRAW_SITES = (0xA48360, 0xA48760)


def compile_payload(ndk, output, text_address, state_address):
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    flags = ["--target=armv7a-linux-androideabi24", "-marm", "-march=armv7-a",
             "-mfloat-abi=softfp", "-mfpu=vfpv3-d16", "-Os", "-fPIC", "-ffreestanding",
             "-fno-builtin", "-fno-stack-protector", "-fno-exceptions", "-fno-rtti",
             "-fno-unwind-tables", "-fno-asynchronous-unwind-tables"]
    obj, linked, layout = (output / f"zombie-entrance.{ext}" for ext in ("o", "elf", "ld"))
    subprocess.run([clang, *flags, "-c", ROOT / "src/zombie-entrance/zombie_entrance.cpp",
                    "-o", obj], check=True)
    layout.write_text(f"""ENTRY(asterZombieEntrance)
SECTIONS {{
    . = {text_address}; .payload : {{ *(.text*) *(.rodata*) }}
    . = {state_address}; .runtime (NOLOAD) : {{ *(.bss*) *(COMMON) }}
    /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }}
}}""", encoding="ascii")
    subprocess.run([clang, *flags, "-nostdlib", "-static", "-no-pie", "-Wl,--no-undefined",
                    "-Wl,-T," + str(layout), obj, "-o", linked], check=True)
    with linked.open("rb") as handle:
        elf = ELFFile(handle)
        body, state = (elf.get_section_by_name(n) for n in (".payload", ".runtime"))
        if (body["sh_addr"] != text_address or state["sh_addr"] != state_address
                or state["sh_type"] != "SHT_NOBITS"
                or any(sec["sh_size"] for sec in elf.iter_sections()
                       if sec.name.startswith((".rel", ".data", ".got")))):
            raise ValueError("Entrance payload must be PIC with zero-initialized state")
        symbols = {s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
        return bytearray(body.data()), state["sh_size"], symbols


def patch_native(native, ndk, output):
    elf = ELFFile(BytesIO(native))
    loads = [(i, seg) for i, seg in enumerate(elf.iter_segments()) if seg["p_type"] == "PT_LOAD"]
    (code_index, code), (state_index, state) = loads[-2:]
    if ((code["p_flags"], state["p_flags"]) != (5, 6)
            or code["p_filesz"] != code["p_memsz"]):
        raise ValueError("Unexpected A248 executable and state segments")
    start = (code["p_filesz"] + 15) & ~15
    address = code["p_vaddr"] + start
    offset = code["p_offset"] + start
    state_address = (state["p_vaddr"] + state["p_memsz"] + 15) & ~15
    payload, state_size, symbols = compile_payload(ndk, output, address, state_address)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def wrapper(source):
        origin = address + len(payload)
        body = bytearray(assembler.asm(source + "\nbasepoint: .word 0", origin)[0])
        struct.pack_into("<I", body, len(body) - 4, origin + len(body) - 4)
        payload.extend(body)
        return origin

    # This call occurs after the zombie's BoardEntity initialization and
    # before Board appends it to the live zombies list.
    spawn = wrapper(f"""
        push {{r4,lr}}
        bl #{STOCK_INIT}
        mov r1,r7
        mov r2,sl
        adr r0,basepoint
        ldr ip,[r0]
        sub r0,r0,ip
        bl #{symbols['asterZombieEntrance']}
        pop {{r4,pc}}
    """)
    # Both base Zombie::Draw paths carry the owning zombie in r4. Route just
    # their body draw calls through the fade, leaving the shared rig unchanged.
    draw = wrapper(f"""
        push {{r4,lr}}
        sub sp,sp,#8
        str r2,[sp]
        mov r3,r1
        mov r2,r0
        mov r1,r4
        adr r0,basepoint
        ldr ip,[r0]
        sub r0,r0,ip
        bl #{symbols['asterDrawZombieEntrance']}
        add sp,sp,#8
        pop {{r4,pc}}
    """)

    result = bytearray(native)
    for site, target, hook in ((SPAWN_INIT, STOCK_INIT, spawn),
                               *((site, DRAW_RIG, draw) for site in ZOMBIE_DRAW_SITES)):
        pos = file_offset(elf, site)
        if native[pos:pos + 4] != branch(site, target, True):
            raise ValueError(f"Unexpected engine instruction at {site:#x}")
        result[pos:pos + 4] = branch(site, hook, True)

    end = offset + len(payload)
    if end > state["p_offset"] or any(native[code["p_offset"] + code["p_filesz"]:end]):
        raise ValueError("No free executable segment space for the zombie fade")
    result[offset:end] = payload
    phdr = elf["e_phoff"]
    stride = elf["e_phentsize"]
    struct.pack_into("<II", result, phdr + code_index * stride + 16, start + len(payload), start + len(payload))
    struct.pack_into("<I", result, phdr + state_index * stride + 20,
                     state_address + state_size - state["p_vaddr"])
    return bytes(result)


def build(base, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A248-{abi}.apk" for abi in ARM_ENGINES}
    with ZipFile(sources["ARM32"]) as arm32, ZipFile(sources["ARM64"]) as arm64:
        original = arm32.read(ARM_ENGINES["ARM32"])
        if original != arm64.read(ARM_ENGINES["ARM64"]):
            raise ValueError("A248 engines must share the same ARM32 code")
    patched = patch_native(original, ndk, output)
    for abi, member in ARM_ENGINES.items():
        with ZipFile(sources[abi]) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 250, 248, prefix="A")
        target = output / f"PvZ2-Unline-Aster-A250-{abi}.apk"
        pack_apk(sources[abi], {member: patched, "AndroidManifest.xml": manifest}, sdk, target, signing)
        print(target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
