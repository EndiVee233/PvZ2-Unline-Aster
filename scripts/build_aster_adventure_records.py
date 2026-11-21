"""Build the native adventure records candidate against Aster A250."""

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
START_CALL = 0x226200
SET_PHASE = 0x224554
UPDATE = 0x22930C
UPDATE_PROLOGUE = 0xE92D4FF0
WIN_CALL = 0x2299AC
WIN = 0x227E9C
DRAW_CALL = 0x23AA00
DRAW = 0x1A30020
KILL_ZOMBIES = 0x85D8D8
FLAGS = [
    "--target=armv7a-linux-androideabi24", "-marm", "-march=armv7-a",
    "-mfloat-abi=softfp", "-mfpu=vfpv3-d16", "-Os", "-std=c++17",
    "-Wall", "-Wextra", "-Werror", "-fPIC", "-ffreestanding", "-fno-builtin",
    "-fno-stack-protector", "-fno-exceptions", "-fno-rtti",
    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
]


def payload(ndk, output, address, state_address, battle_tools):
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    obj, linked, layout = (output / f"adventure-records.{ext}" for ext in ("o", "elf", "ld"))
    defines = ["-DASTER_WSA_BATTLE_TOOLS"] if battle_tools else []
    subprocess.run([clang, *FLAGS, *defines, "-c", ROOT / "src/adventure-records/adventure_records.cpp",
                    "-o", obj], check=True)
    layout.write_text(f"""ENTRY(asterAdventureStart)
SECTIONS {{
    . = {address}; .payload : {{ *(.text*) *(.rodata*) }}
    . = {state_address}; .runtime (NOLOAD) : {{ *(.bss*) *(COMMON) }}
    /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }}
}}
""", encoding="ascii")
    subprocess.run([clang, "--target=armv7a-linux-androideabi24", "-nostdlib", "-static",
                    "-Wl,--no-undefined",
                    "-Wl,-T," + str(layout), obj, "-o", linked], check=True)
    with linked.open("rb") as handle:
        elf = ELFFile(handle)
        code, state = (elf.get_section_by_name(n) for n in (".payload", ".runtime"))
        if (code["sh_addr"] != address or state["sh_addr"] != state_address
                or state["sh_type"] != "SHT_NOBITS"
                or any(s["sh_size"] for s in elf.iter_sections()
                       if s.name.startswith((".rel", ".data", ".got")))):
            raise ValueError("Adventure records payload needs relocatable code and zero-init state")
        symbols = {s.name: s["st_value"] for s in elf.get_section_by_name(".symtab").iter_symbols()}
        return bytearray(code.data()), state["sh_size"], symbols


def patch_native(native, ndk, output, battle_tools=False):
    elf = ELFFile(BytesIO(native))
    loads = [(i, seg) for i, seg in enumerate(elf.iter_segments()) if seg["p_type"] == "PT_LOAD"]
    (code_index, code), (state_index, state) = loads[-2:]
    if ((code["p_flags"], state["p_flags"]) != (5, 6) or code["p_filesz"] != code["p_memsz"]):
        raise ValueError("Missing A250 executable and state segments")
    start = (code["p_filesz"] + 15) & ~15
    address = code["p_vaddr"] + start
    offset = code["p_offset"] + start
    state_address = (state["p_vaddr"] + state["p_memsz"] + 15) & ~15
    if battle_tools:
        kill = file_offset(elf, KILL_ZOMBIES)
        if struct.unpack_from("<4I", native, kill) != (0xE92D4FF0, 0xE59F5164, 0xE28DB020, 0xE24DD05C):
            raise ValueError("A250 native zombie-clearing routine changed")
    body, state_size, symbols = payload(ndk, output, address, state_address, battle_tools)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def stub(source):
        body.extend(bytes(-len(body) % 4))
        origin = address + len(body)
        compiled = bytearray(assembler.asm(source + "\nbasepoint: .word 0", origin)[0])
        struct.pack_into("<I", compiled, len(compiled) - 4, origin + len(compiled) - 4)
        body.extend(compiled)
        return origin

    def helper(name, board):
        return f"""mov r1,{board}
            adr r0,basepoint
            ldr ip,[r0]
            sub r0,r0,ip
            bl #{symbols[name]}
        """

    # Board::BeginBattle has set m_levelStartTime. Keep the regular phase
    # transition and only start our stopwatch when the resulting phase is live.
    begin = stub(f"""push {{r4,lr}}
        mov r4,r0
        bl #{SET_PHASE}
        push {{r0-r3,ip,lr}}
        {helper("asterAdventureStart", "r4")}
        pop {{r0-r3,ip,lr}}
        pop {{r4,pc}}
    """)
    tick = stub(f"""push {{r0-r3,ip,lr}}
        {helper("asterAdventureTick", "r0")}
        pop {{r0-r3,ip,lr}}
        .word {UPDATE_PROLOGUE}
        b #{UPDATE+4}
    """)
    # This is the module-driven win call from Board::Update. The separate
    # debug win route into the same native routine stays outside this hook.
    win = stub(f"""push {{r0-r3,ip,lr}}
        {helper("asterAdventureWin", "r0")}
        pop {{r0-r3,ip,lr}}
        b #{WIN}
    """)
    # Draw after the existing viewport wrapper restores its world transform.
    draw = stub(f"""push {{r4-r6,lr}}
        mov r4,r0
        mov r5,r1
        bl #{DRAW}
        mov r2,r5
        {helper("asterAdventureDrawClock", "r4")}
        pop {{r4-r6,pc}}
    """)
    changes = (
        (START_CALL, branch(START_CALL, SET_PHASE, True), branch(START_CALL, begin, True)),
        (UPDATE, struct.pack("<I", UPDATE_PROLOGUE), branch(UPDATE, tick)),
        (WIN_CALL, branch(WIN_CALL, WIN, True), branch(WIN_CALL, win, True)),
        (DRAW_CALL, branch(DRAW_CALL, DRAW, True), branch(DRAW_CALL, draw, True)),
    )
    result = bytearray(native)
    for site, expected, replacement in changes:
        pos = file_offset(elf, site)
        if native[pos:pos + 4] != expected:
            raise ValueError(f"Unexpected engine instruction at {site:#x}")
        result[pos:pos + 4] = replacement
    end = offset + len(body)
    phdr, stride = elf["e_phoff"], elf["e_phentsize"]
    old_state_offset = state["p_offset"]
    if any(native[code["p_offset"] + code["p_filesz"]:min(end, old_state_offset)]):
        raise ValueError("Existing content occupies the executable padding")
    if end > old_state_offset:
        # The final writable load has no section table or other program
        # segment behind it. Increase the file gap by whole load pages.
        if (elf["e_shoff"] >= old_state_offset or any(
            i != state_index and s["p_offset"] + s["p_filesz"] > old_state_offset
            for i, s in enumerate(elf.iter_segments())
        )):
            raise ValueError("Cannot move shared writable data in this ELF")
        alignment = state["p_align"]
        extra = (end - old_state_offset + alignment - 1) // alignment * alignment
        if (code["p_vaddr"] + end - code["p_offset"] + alignment - 1) // alignment * alignment > state["p_vaddr"]:
            raise ValueError("Adventure payload overlaps the writable virtual segment")
        result[old_state_offset:old_state_offset] = bytes(extra)
        struct.pack_into("<I", result, phdr + state_index * stride + 4, old_state_offset + extra)
    result[offset:end] = body
    size = start + len(body)
    struct.pack_into("<II", result, phdr + code_index * stride + 16, size, size)
    struct.pack_into("<I", result, phdr + state_index * stride + 20,
                     state_address + state_size - state["p_vaddr"])
    return bytes(result)


def build(base, output, sdk, ndk, signing=None, wsa_test=False, wsa_battle_tools=False):
    if wsa_battle_tools and not wsa_test:
        raise ValueError("Battle tools are available only in a WSA test build")
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A250-{abi}.apk" for abi in ARM_ENGINES}
    with ZipFile(sources["ARM32"]) as arm32, ZipFile(sources["ARM64"]) as arm64:
        original = arm32.read(ARM_ENGINES["ARM32"])
        if original != arm64.read(ARM_ENGINES["ARM64"]):
            raise ValueError("A250 engines must share the same ARM32 code")
    patched = patch_native(original, ndk, output, wsa_battle_tools)
    (output / "libSrc-adventure-records.so").write_bytes(patched)
    if not signing:
        return
    architectures = ("ARM32",) if wsa_test else ARM_ENGINES
    for abi in architectures:
        member = ARM_ENGINES[abi]
        with ZipFile(sources[abi]) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 251, 250, prefix="A")
            excluded = ([name for name in apk.namelist() if name.startswith("assets/pvz2data.zip.")]
                        if wsa_test else [])
        if wsa_test and len(excluded) != 3:
            raise ValueError("The WSA candidate expects three already extracted resource parts")
        label = f"{abi}-WSA-existing-data" if wsa_test else abi
        if wsa_battle_tools:
            label += "-battle-tools"
        target = output / f"PvZ2-Unline-Aster-A251-{label}.apk"
        pack_apk(sources[abi], {member: patched, "AndroidManifest.xml": manifest}, sdk, target,
                 signing, excluded=excluded)
        print(target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "ndk"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--signing", type=Path)
    parser.add_argument("--wsa-test", action="store_true")
    parser.add_argument("--wsa-battle-tools", action="store_true")
    build(**vars(parser.parse_args()))
