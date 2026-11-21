"""Link the pickup setting into the existing A227 ARM engine."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch

ROOT = Path(__file__).resolve().parents[1]


def patch_native(native, ndk, output, *, world_resources=False, mount_campaign=False, guard_chooser_resume=False):
    output.mkdir(parents=True, exist_ok=True)
    elf = ELFFile(BytesIO(native))
    loads = [(i, s) for i, s in enumerate(elf.iter_segments()) if s["p_type"] == "PT_LOAD"]
    (code_index, code), (state_index, state) = loads[-2:]
    assert (code["p_flags"], state["p_flags"]) == (5, 6)
    assert code["p_filesz"] == code["p_memsz"] and state["p_filesz"] <= state["p_memsz"]
    text_start = (code["p_vaddr"] + code["p_filesz"] + 15) & ~15
    variables_start = (state["p_vaddr"] + state["p_memsz"] + 15) & ~15

    tools = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    flags = ["--target=armv7a-linux-androideabi24", "-marm", "-march=armv7-a", "-mfloat-abi=softfp",
             "-mfpu=vfpv3-d16", "-Os", "-fPIC", "-ffreestanding", "-fno-builtin",
             "-fno-stack-protector", "-fno-exceptions", "-fno-rtti", "-fno-unwind-tables",
             "-fno-asynchronous-unwind-tables"]
    obj, linked, ld = (output / ("auto-pickup." + suffix) for suffix in ("o", "elf", "ld"))
    subprocess.run([tools / "clang++.exe", *flags, "-c", ROOT / "src/auto-pickup/auto_pickup.cpp",
                    "-o", obj], check=True)
    with obj.open("rb") as handle:
        for section in ELFFile(handle).iter_sections():
            if section["sh_type"] == "SHT_REL" and "exidx" not in section.name:
                assert all(r["r_info_type"] != 2 for r in section.iter_relocations()), section.name
    ld.write_text(f"""ENTRY(asterPickupUpdate)
SECTIONS {{
    . = {text_start}; .payload : {{ *(.text*) *(.rodata*) }}
    . = {variables_start}; .runtime : {{ *(.data*) *(.bss*) *(COMMON) *(.got*) }}
    /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }}
}}""", encoding="ascii")
    subprocess.run([tools / "clang++.exe", *flags, "-nostdlib", "-static", "-no-pie",
                    "-Wl,--no-undefined", "-Wl,-T," + str(ld), obj, "-o", linked], check=True)
    with linked.open("rb") as handle:
        helper = ELFFile(handle)
        body, variables = (helper.get_section_by_name(n) for n in (".payload", ".runtime"))
        assert variables["sh_addr"] == variables_start
        payload = bytearray(bytes(body["sh_addr"] - text_start) + body.data())
        data = variables.data() if variables["sh_type"] != "SHT_NOBITS" else bytes(variables["sh_size"])
        symbols = {s.name: s["st_value"] for s in helper.get_section_by_name(".symtab").iter_symbols()
                   if s.name.startswith("aster")}

    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    get_base = "adr r0, basepoint\nldr ip, [r0]\nsub r0, r0, ip"
    hooks = {}

    def wrap(site, expected, source, link=False):
        assert struct.unpack_from("<I", native, file_offset(elf, site))[0] == expected, hex(site)
        payload.extend(bytes(-len(payload) % 4))
        address = text_start + len(payload)
        encoded = bytearray(assembler.asm(source + "\nbasepoint: .word 0x11223344", address)[0])
        assert encoded[-4:] == struct.pack("<I", 0x11223344)
        struct.pack_into("<I", encoded, len(encoded) - 4, address + len(encoded) - 4)
        payload.extend(encoded)
        hooks[site] = (address, branch(site, address, link))

    wrap(0x8e6114, 0xeb45278d, f"""
        push {{r0-r4,lr}}
        mov r1,r4
        {get_base}
        bl #{symbols["asterPickupSettings"]}
        pop {{r0-r4,lr}}
        b #{0x8e6114 + 8 + 4 * 0x45278d}
    """, True)
    wrap(0x8e8884, 0xea451dba, f"""
        push {{r0-r4,lr}}
        mov r2,r1
        mov r1,r0
        {get_base}
        bl #{symbols["asterPickupClick"]}
        cmp r0,#2
        moveq r1,#9
        streq r1,[sp,#4]
        beq stock_click
        cmp r0,#0
        pop {{r0-r4,lr}}
        bxne lr
        b #{0x8e8884 + 8 + 4 * 0x451dba}
        stock_click: pop {{r0-r4,lr}}
        b #{0x8e8884 + 8 + 4 * 0x451dba}
    """)
    wrap(0x8e7868, 0xeb4521d4, f"""
        push {{r0-r4,lr}}
        mov r1,r0
        {get_base}
        bl #{symbols["asterPickupTitle"]}
        cmp r0,#0
        pop {{r0-r4,lr}}
        bxne lr
        b #{0x8e7868 + 8 + 4 * 0x4521d4}
    """, True)
    wrap(0x8e7b34, 0xeb45212d, f"""
        push {{r0-r4,lr}}
        mov r2,r1
        mov r1,r0
        {get_base}
        bl #{symbols["asterPickupRows"]}
        cmp r0,#0
        pop {{r0-r4,lr}}
        beq #{0x8e7b34 + 8 + 4 * 0x45212d}
        b #0x8e7be4
    """, True)
    for vtable, update in ((0x178b860, 0x289004), (0x178ae38, 0x27811c), (0x178a870, 0x27811c)):
        assert struct.unpack_from("<I", native, file_offset(elf, vtable + 0xac))[0] == update
        assert struct.unpack_from("<I", native, file_offset(elf, vtable + 0xe4))[0] == 0x27b584
    # Native Sun::Update calls this base method before its own collection
    # check. Plant Food uses the same method directly.
    wrap(0x27811c, 0xe92d4878, f"""
        push {{r0-r4,lr}}
        mov r1,r0
        {get_base}
        bl #{symbols["asterPickupUpdate"]}
        pop {{r0-r4,lr}}
        .word 0xe92d4878
        b #0x278120
    """)

    if world_resources:
        world_entry = 0x415048
        world_prologue = 0xe92d4ff0
        original_world = text_start + ((len(payload) + 3) & ~3)
        payload.extend(bytes(-len(payload) % 4))
        payload.extend(struct.pack("<I", world_prologue))
        payload.extend(branch(original_world + 4, world_entry + 4))
        wrap(world_entry, world_prologue, f"""
            push {{r4,lr}}
            mov r2,r1
            mov r1,r0
            movw r3,#{original_world & 65535}
            movt r3,#{original_world >> 16}
            {get_base}
            bl #{symbols["asterLocalWorldAvailable"]}
            pop {{r4,pc}}
        """)
    if mount_campaign:
        egypt_mount = 0x95d4ec
        expected = struct.unpack("<I", branch(egypt_mount, 0x11c1964, True))[0]
        wrap(egypt_mount, expected, f"""
            push {{r4,lr}}
            sub sp,sp,#16
            str r3,[sp]
            ldr r4,[sp,#24]
            str r4,[sp,#4]
            ldr r4,[sp,#28]
            str r4,[sp,#8]
            mov r3,r2
            mov r2,r1
            mov r1,r0
            {get_base}
            bl #{symbols["asterMountCampaignWorlds"]}
            mov r0,#0
            add sp,sp,#16
            pop {{r4,pc}}
        """, True)
    if guard_chooser_resume:
        # The restore callback needs the primary button and the packet rows
        # built with it. An unbuilt chooser has no controls to restore.
        wrap(0x89f8d4, 0xe5d3204e, f"""
            cmp r3,#0
            bne initialized
            push {{r0-r4,lr}}
            {get_base}
            bl #{symbols["asterIdentifyEmptyFestivalCheckpoint"]}
            pop {{r0-r4,lr}}
            b #0x89fa34
        initialized:
            ldrb r2,[r3,#0x4e]
            b #0x89f8d8
        """)
        for site in (0x894498, 0x894790):
            owner_check = 0x1781edc
            expected = struct.unpack("<I", branch(site, owner_check, True))[0]
            wrap(site, expected, f"""
                push {{r4,lr}}
                sub sp,sp,#8
                movw r4,#{owner_check & 65535}
                movt r4,#{owner_check >> 16}
                str r4,[sp]
                mov r3,r2
                mov r2,r1
                mov r1,r0
                {get_base}
                bl #{symbols["asterAllowFestivalCheckpoint"]}
                add sp,sp,#8
                pop {{r4,pc}}
            """, True)
        wrap(0x2261e4, 0xe5d43988, f"""
            push {{r0-r4,lr}}
            mov r1,r4
            {get_base}
            bl #{symbols["asterFestivalBattleReady"]}
            pop {{r0-r4,lr}}
            ldrb r3,[r4,#0x988]
            b #0x2261e8
        """)

    old_rw = state["p_offset"]
    old_rw_end = old_rw + state["p_filesz"]
    code_offset = code["p_offset"] + text_start - code["p_vaddr"]
    code_end = code_offset + len(payload)
    assert not any(native[code["p_offset"] + code["p_filesz"]:old_rw])
    assert text_start + len(payload) < state["p_vaddr"]
    new_rw = max(old_rw, (code_end + 4095) & ~4095)
    variables_offset = new_rw + variables_start - state["p_vaddr"]
    shift = new_rw - old_rw
    extra = variables_offset + len(data) - (new_rw + state["p_filesz"])
    result = bytearray(native[:old_rw] + bytes(shift) + native[old_rw:old_rw_end]
                       + bytes(extra) + native[old_rw_end:])
    result[code_offset:code_end] = payload
    result[variables_offset:variables_offset + len(data)] = data
    for site, (_, patch) in hooks.items():
        offset = file_offset(elf, site)
        result[offset:offset + 4] = patch
    if world_resources:
        gift = file_offset(elf, 0x226238)
        assert native[gift:gift + 4] == branch(0x226238, 0x410ddc)
        # Skip the cash Sun/Plant Food gift after the caller restores registers.
        struct.pack_into("<I", result, gift, 0xe12fff1e)
        if not mount_campaign:
            effect = file_offset(elf, 0x16f9408)
            old_effect = b"POPANIM_EFFECTS_FROSTBITE_CHILL_PLANT\0"
            new_effect = b"POPANIM_EFFECTS_ASTERCOLD_CHILL_PLANT\0"
            assert native[effect:effect + len(old_effect)] == old_effect
            result[effect:effect + len(old_effect)] = new_effect

    program_headers = elf["e_phoff"]
    stride = elf["e_phentsize"]
    text_size = text_start + len(payload) - code["p_vaddr"]
    variables_size = variables_start + len(data) - state["p_vaddr"]
    struct.pack_into("<II", result, program_headers + code_index * stride + 16, text_size, text_size)
    struct.pack_into("<I", result, program_headers + state_index * stride + 4, new_rw)
    struct.pack_into("<II", result, program_headers + state_index * stride + 16, variables_size, variables_size)

    def relocate(offset):
        return offset + (shift if offset >= old_rw else 0) + (extra if offset >= old_rw_end else 0)

    sections_start = relocate(elf["e_shoff"])
    struct.pack_into("<I", result, 32, sections_start)
    for index, section in enumerate(elf.iter_sections()):
        struct.pack_into("<I", result, sections_start + index * elf["e_shentsize"] + 16,
                         relocate(section["sh_offset"]))
    report = {"symbols": symbols, "hooks": {site: target for site, (target, _) in hooks.items()},
              "sha256": sha256(result).hexdigest()}
    (output / "auto-pickup.json").write_text(json.dumps(report, indent=2) + "\n", encoding="ascii")
    return bytes(result)
