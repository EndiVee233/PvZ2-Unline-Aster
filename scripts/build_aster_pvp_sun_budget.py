"""Build A341 with one PvP formation sun budget for editing and matching."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import struct
import subprocess
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_adventure_records import FLAGS, ROOT
from build_aster_pvp_feedback import catalogue_dex, pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_star_difficulty import ENGINE
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A340_ENGINE = "0827a1a081410ca19c7268ad5029c06f35c077078c91a4fffb2545e44537400a"
EDITOR_PLANTS = 0x1AE7140
MATCHING_PLANTS = 0x1AE7F20
PLANT_COUNT = 85
CATALOGUE_DEX = "classes6.dex"


def plant_costs(engine, elf):
    """Read editor aliases and prices from the installed matching catalogue."""
    editor = file_offset(elf, EDITOR_PLANTS)
    matching = file_offset(elf, MATCHING_PLANTS)
    costs = {}
    for i in range(PLANT_COUNT):
        plant, sun, tier, role, _ = struct.unpack_from("<5I", engine, matching + i * 20)
        if plant in costs or sun > 1000 or not 1 <= tier <= 4 or role > 2:
            raise ValueError("Unexpected native plant prices")
        costs[plant] = (sun, tier)
    result = {}
    for i in range(PLANT_COUNT):
        plant, tier, name = struct.unpack_from("<II32s", engine, editor + i * 40)
        alias = name.split(b"\0", 1)[0].decode("ascii")
        if not re.fullmatch(r"[a-z0-9_]+", alias) or alias in result or plant not in costs:
            raise ValueError("Unexpected native editor plant alias")
        sun, expected_tier = costs[plant]
        if tier != expected_tier:
            raise ValueError("The editor and matching plant catalogues differ")
        result[alias] = sun
    return result


def patch_guest(engine, ndk, output):
    if sha256(engine).hexdigest() != A340_ENGINE:
        raise ValueError("Expected the A340 ARM32 guest engine")
    elf = ELFFile(BytesIO(engine))
    state, code = (elf.get_segment(index) for index in (7, 8))
    if (state["p_flags"] != 6 or code["p_flags"] != 5
            or code["p_memsz"] != code["p_filesz"]
            or code["p_offset"] + code["p_filesz"] != len(engine)):
        raise ValueError("Unexpected A340 load segments")
    state_at = (state["p_vaddr"] + state["p_memsz"] + 15) & -16
    code_at = (code["p_vaddr"] + code["p_memsz"] + 15) & -16
    (output / "preset_plant_costs.inc").write_text(
        "".join(f'    {{"{alias}", {sun}}},\n' for alias, sun in plant_costs(engine, elf).items()),
        encoding="ascii")
    linker = output / "pvp-budget.ld"
    linked = output / "pvp-budget.elf"
    linker.write_text(f"""ENTRY(presetBudgetLimit)
SECTIONS {{
    . = {state_at}; .runtime (NOLOAD) : {{ *(.bss*) *(COMMON) }}
    . = {code_at}; .payload : {{ *(.text*) *(.rodata*) }}
    .initialized : {{ *(.data*) *(.got*) }}
    /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.notes*) *(.note*) *(.comment*) }}
}}
ASSERT(SIZEOF(.initialized) == 0, "PvP budget state must be zero-initialized")
""", encoding="ascii")
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    subprocess.run([clang, *FLAGS, "-I", output, "-nostdlib", "-static", "-Wl,--no-undefined",
                    "-Wl,-T," + str(linker), ROOT / "src/offline-pvp/preset_budget.cpp", "-o", linked], check=True)
    with linked.open("rb") as handle:
        helper = ELFFile(handle)
        body = bytearray(helper.get_section_by_name(".payload").data())
        state_end = state_at + helper.get_section_by_name(".runtime")["sh_size"]
        symbols = {s.name: s["st_value"] for s in helper.get_section_by_name(".symtab").iter_symbols()
                   if s.name.startswith("presetBudget")}
    if state_end > code["p_vaddr"]:
        raise ValueError("PvP budget state overlaps the executable segment")

    patched = bytearray(engine)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    base_arg = "adr r0,anchor\nldr ip,[r0]\nsub r0,r0,ip"

    def hook(site, expected, instructions, *, linked_call=False, anchor=False):
        pos = file_offset(elf, site)
        if isinstance(expected, int):
            expected = struct.pack("<I", expected)
        if patched[pos:pos + 4] != expected:
            raise ValueError(f"Unexpected A340 PvP instruction at {site:#x}")
        body.extend(bytes(-len(body) % 4))
        address = code_at + len(body)
        suffix = "\nanchor: .word 0" if anchor else ""
        stub = bytearray(assembler.asm(instructions + suffix, address)[0])
        if anchor:
            struct.pack_into("<I", stub, len(stub) - 4, address + len(stub) - 4)
        body.extend(stub)
        patched[pos:pos + 4] = branch(site, address, linked_call)

    hook(0x1AD92F0, 0xE59A0130, f"""
        push {{r0-r4,lr}}
        mov r0,r8
        mov r1,sl
        bl #{symbols['presetBudgetRefresh']}
        pop {{r0-r4,lr}}
        b #0x1ad9308
    """)
    hook(0x108C384, branch(0x108C384, 0x22BFD0, True), f"""
        push {{r0-r4,lr}}
        mov r2,r1
        mov r1,r0
        {base_arg}
        bl #{symbols['presetBudgetCanPlace']}
        cmp r0,#0
        pop {{r0-r4,lr}}
        bxeq lr
        b #0x22bfd0
    """, anchor=True, linked_call=True)
    hook(0x1AD7B20, branch(0x1AD7B20, 0x1AD7B38, True), f"""
        push {{r0-r4,lr}}
        bl #{symbols['presetBudgetCanSave']}
        cmp r0,#0
        pop {{r0-r4,lr}}
        bxeq lr
        b #0x1ad7b38
    """, linked_call=True)

    # The catalogue can supply one extra word. The original decoder still
    # receives its exact expected size and validates every candidate itself.
    hook(0x1AD7E64, 0xE3550000, f"""
        push {{r0-r4,lr}}
        mov r0,r5
        mov r1,r3
        bl #{symbols['presetBudgetCatalogue']}
        str r0,[sp,#12]
        pop {{r0-r4,lr}}
        cmp r5,#0
        b #0x1ad7e68
    """)

    # Existing frozen neighbors are read with allowDisabled. Lowering the
    # online limit must not invalidate their whole saved roster.
    hook(0x1AE2D14, 0xE301257D, f"""
        ldr r2,[fp,#8]
        cmp r2,#0
        movwne r2,#20001
        bne #0x1ae2d18
        push {{r0-r4,lr}}
        bl #{symbols['presetBudgetLimit']}
        add r0,r0,#1
        str r0,[sp,#8]
        pop {{r0-r4,lr}}
        b #0x1ae2d18
    """)

    for site, register, opcode in ((0x1AC6E14, 3, 0xE301357C), (0x1AC6F64, 0, 0xE301057C)):
        hook(site, opcode, f"""
            push {{r0-r4,lr}}
            bl #{symbols['presetBudgetLimit']}
            str r0,[sp,#{register * 4}]
            pop {{r0-r4,lr}}
            b #{site + 4}
        """)

    patched.extend(bytes(code_at - code["p_vaddr"] - code["p_filesz"]))
    patched.extend(body)
    size = len(patched) - code["p_offset"]
    header, stride = elf["e_phoff"], elf["e_phentsize"]
    struct.pack_into("<I", patched, header + 7 * stride + 20, state_end - state["p_vaddr"])
    struct.pack_into("<II", patched, header + 8 * stride + 16, size, size)
    return bytes(patched)


def build(base, output, ndk, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_guest(apk.read(ENGINE), ndk, output)
        dex = catalogue_dex(apk.read(CATALOGUE_DEX), sdk, output / "java",
                            prefixes=("GithubPresetCatalog", "PresetEditor"))
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 341, 340, prefix="A")
    result = output / "PvZ2-Unline-Aster-A341-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest, CATALOGUE_DEX: dex}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "output", "ndk", "sdk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
