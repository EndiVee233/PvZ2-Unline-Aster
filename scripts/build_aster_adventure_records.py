"""Build the native adventure records candidate against Aster A250."""

import argparse
from io import BytesIO
import os
from pathlib import Path
import re
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
MAP_LEVEL_CALLS = (0x9DF1C8, 0x9E4704, 0x9E857C)
LAUNCH_LEVEL = 0x354360
BOARD_LOAD_CALL, BOARD_LOAD = 0x350570, 0x1A2AF70
BOARD_READY_CALL, BOARD_UPDATE_DONE = 0x2297EC, 0x229520
STAR_CHOICE, STAR_CHOSEN = 0x225FF4, 0x2260A8
STAR_MODULE_GATE, STAR_MODULE_LOCKED, STAR_MODULE_ENABLED = 0x90221C, 0x902348, 0x902244
STAR_RESULT_TITLE = 0x7E5568
STAR_RIBBON_ART, STAR_RIBBON_EMPTY, STAR_RIBBON_GOLD = 0x805DB0, 0x805FB0, 0x805FF8
LEVEL_MENU_DRAW, POP_GRAPHICS = 0x7F3934, 0x116D764
LEVEL_MENU_PANEL_CALL, DRAW_DIALOG_PANEL = 0x7F3B38, 0x7F3470
BEGIN_BATTLE_ENTRY, BEGIN_BATTLE_TARGET = 0x2261A8, 0x17813A4
GAME_POLL, GAME_POLL_TARGET = 0x1A15808, 0x1A4995C
START_BUTTON_EVENT, DISPATCH_EVENT = 0x926D08, 0x21DF78
BOARD_TOUCH_CALLS, BOARD_TOUCH = (0x1A30114, 0x1A3013C, 0x1A30164), 0x1A2E16C
TITLE_TEXT, TRANSLATE_TEXT = 0x205544, 0xD07BB4
BOARD_MESSAGE_DRAW, BOARD_MESSAGE_TARGET = 0x46D890, 0x1A30074
FLAGS = [
    "--target=armv7a-linux-androideabi24", "-marm", "-march=armv7-a",
    "-mfloat-abi=softfp", "-mfpu=vfpv3-d16", "-Os", "-std=c++17",
    "-Wall", "-Wextra", "-Werror", "-fPIC", "-ffreestanding", "-fno-builtin",
    "-fno-stack-protector", "-fno-exceptions", "-fno-rtti",
    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
]


def payload(ndk, output, address, state_address, battle_tools, social_levels):
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    obj, linked, layout = (output / f"adventure-records.{ext}" for ext in ("o", "elf", "ld"))
    defines = ["-DASTER_WSA_BATTLE_TOOLS"] if battle_tools else []
    if social_levels:
        defines.append("-DASTER_SOCIAL_LEVELS")
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


def patch_native(native, ndk, output, battle_tools=False, social_levels=False):
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
    body, state_size, symbols = payload(ndk, output, address, state_address, battle_tools, social_levels)
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
    def guard(name):
        return f"""push {{r0-r3,ip,lr}}
        {helper(name, "r0")}
        cmp r0,#0
        pop {{r0-r3,ip,lr}}
        bxne lr
    """

    view_tick = guard("asterAdventureUpdateView") if social_levels else ""
    tick = stub(f"""{view_tick}
        push {{r0-r3,ip,lr}}
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
    changes = [
        (START_CALL, branch(START_CALL, SET_PHASE, True), branch(START_CALL, begin, True)),
        (UPDATE, struct.pack("<I", UPDATE_PROLOGUE), branch(UPDATE, tick)),
        (WIN_CALL, branch(WIN_CALL, WIN, True), branch(WIN_CALL, win, True)),
        (DRAW_CALL, branch(DRAW_CALL, DRAW, True), branch(DRAW_CALL, draw, True)),
    ]
    if social_levels:
        choose = stub(f"""push {{r4-r7,lr}}
            sub sp,sp,#12
            str r3,[sp]
            ldr r4,[sp,#32]
            ldr r5,[sp,#36]
            str r4,[sp,#4]
            str r5,[sp,#8]
            mov r3,r2
            mov r2,r1
            {helper("asterAdventureChoose", "r0")}
            add sp,sp,#12
            pop {{r4-r7,pc}}
        """)
        load = stub(f"""push {{r4,lr}}
            mov r4,r0
            bl #{BOARD_LOAD}
            push {{r0-r3,ip,lr}}
            {helper("asterAdventureViewLoaded", "r4")}
            pop {{r0-r3,ip,lr}}
            pop {{r4,pc}}
        """)
        poll = stub(f"""push {{r0-r3,ip,lr}}
            {helper("asterAdventureSocialFrame", "r0")}
            pop {{r0-r3,ip,lr}}
            b #{GAME_POLL_TARGET}
        """)
        ready = stub(f"""push {{r0-r3,ip,lr}}
            mov r2,r1
            {helper("asterAdventureEnterView", "r0")}
            cmp r0,#0
            pop {{r0-r3,ip,lr}}
            bne #{BOARD_UPDATE_DONE}
            b #{SET_PHASE}
        """)
        no_battle = stub(f"""{guard("asterAdventureViewFrozen")}
            b #{BEGIN_BATTLE_TARGET}
        """)
        view_button = stub(f"""push {{r0-r3,ip,lr}}
            mov r3,r5
            mov r2,r1
            {helper("asterAdventureViewButton", "r0")}
            pop {{r0-r3,ip,pc}}
        """)
        title_text = stub(f"""push {{r0-r3,ip,lr}}
            mov r3,sl
            mov r2,r1
            {helper("asterAdventureTranslateTitle", "r0")}
            pop {{r0-r3,ip,pc}}
        """)
        board_message = stub(f"""{guard("asterAdventureSuppressMessages")}
            b #{BOARD_MESSAGE_TARGET}
        """)
        initial_star = stub(f"""push {{r0-r3,ip,lr}}
            mov r2,r0
            {helper("asterAdventureSelectChallenge", "r8")}
            cmp r0,#0
            pop {{r0-r3,ip,lr}}
            bne #{STAR_CHOSEN}
            mov r5,r0
            b #{STAR_CHOICE + 4}
        """)
        # Explicit menu selections have already passed the menu's unlock gate.
        # Retain the stock main-level and world gates for all other launches.
        star_module = stub(f"""push {{r0-r3,ip,lr}}
            {helper("asterAdventureSelectedStarModule", "r0")}
            cmp r0,#0
            pop {{r0-r3,ip,lr}}
            bne #{STAR_MODULE_ENABLED}
            cmp r0,#0
            beq #{STAR_MODULE_LOCKED}
            b #{STAR_MODULE_GATE + 4}
        """)
        star_title = stub(f"""push {{r0-r3,ip,lr}}
            {helper("asterAdventureAllStarsTitle", "r5")}
            cmp r0,#1
            pop {{r0-r3,ip,lr}}
            b #{STAR_RESULT_TITLE + 4}
        """)
        star_ribbon = stub(f"""push {{r0-r3,ip,lr}}
            mov r2,r8
            {helper("asterAdventureOtherStarArt", "r6")}
            cmp r0,#0
            pop {{r0-r3,ip,lr}}
            beq #{STAR_RIBBON_EMPTY}
            bgt #{STAR_RIBBON_GOLD}
            ldr r3,[r6,#0xa4]
            b #{STAR_RIBBON_ART + 4}
        """)
        menu_draw = stub(f"""push {{r0-r3,ip,lr}}
            mov r2,r7
            {helper("asterAdventureDrawMenu", "r6")}
            pop {{r0-r3,ip,lr}}
            b #{POP_GRAPHICS}
        """)
        panel_draw = stub(f"""push {{r0-r3,ip,lr}}
            mov r3,r2
            mov r2,r1
            {helper("asterAdventureDrawMenuPanel", "r0")}
            pop {{r0-r3,ip,pc}}
        """)
        for site in MAP_LEVEL_CALLS:
            changes.append((site, branch(site, LAUNCH_LEVEL, True), branch(site, choose, True)))
        for site in BOARD_TOUCH_CALLS:
            changes.append((site, branch(site, BOARD_TOUCH, True),
                            branch(site, symbols["asterAdventureViewTouch"], True)))
        changes.extend((
            (BOARD_LOAD_CALL, branch(BOARD_LOAD_CALL, BOARD_LOAD, True), branch(BOARD_LOAD_CALL, load, True)),
            (BOARD_READY_CALL, branch(BOARD_READY_CALL, SET_PHASE, True), branch(BOARD_READY_CALL, ready, True)),
            (BEGIN_BATTLE_ENTRY, branch(BEGIN_BATTLE_ENTRY, BEGIN_BATTLE_TARGET),
             branch(BEGIN_BATTLE_ENTRY, no_battle)),
            (START_BUTTON_EVENT, branch(START_BUTTON_EVENT, DISPATCH_EVENT, True),
             branch(START_BUTTON_EVENT, view_button, True)),
            (TITLE_TEXT, branch(TITLE_TEXT, TRANSLATE_TEXT, True), branch(TITLE_TEXT, title_text, True)),
            (BOARD_MESSAGE_DRAW, branch(BOARD_MESSAGE_DRAW, BOARD_MESSAGE_TARGET),
             branch(BOARD_MESSAGE_DRAW, board_message)),
            (STAR_CHOICE, struct.pack("<I", 0xE1A05000), branch(STAR_CHOICE, initial_star)),
            (STAR_MODULE_GATE, struct.pack("<I", 0x0A000049), branch(STAR_MODULE_GATE, star_module)),
            (STAR_RESULT_TITLE, struct.pack("<I", 0xE3530002), branch(STAR_RESULT_TITLE, star_title)),
            (STAR_RIBBON_ART, struct.pack("<I", 0xE59630A4), branch(STAR_RIBBON_ART, star_ribbon)),
            (LEVEL_MENU_DRAW, branch(LEVEL_MENU_DRAW, POP_GRAPHICS, True),
             branch(LEVEL_MENU_DRAW, menu_draw, True)),
            (LEVEL_MENU_PANEL_CALL, branch(LEVEL_MENU_PANEL_CALL, DRAW_DIALOG_PANEL, True),
             branch(LEVEL_MENU_PANEL_CALL, panel_draw, True)),
            (GAME_POLL, branch(GAME_POLL, GAME_POLL_TARGET), branch(GAME_POLL, poll)),
        ))
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


def social_dex(output, sdk):
    output.mkdir(exist_ok=True)
    android = sdk / "platforms/android-34/android.jar"
    package = ROOT / "src/bootstrap-extra/com/popcap/pvz2cthd"
    sources = [package / (name + ".java") for name in ("AdventureFormationRecord", "AdventureSocial")]
    classes = output / "classes"
    classes.mkdir(exist_ok=True)
    subprocess.run(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8",
                    "-classpath", android, "-sourcepath", ROOT / "src/bootstrap-extra",
                    "-implicit:none", "-d", classes, *sources], check=True)
    jar = output / "social.jar"
    with ZipFile(jar, "w") as archive:
        for name in ("AdventureFormationRecord", "AdventureSocial"):
            for item in sorted((classes / "com/popcap/pvz2cthd").glob(name + "*.class")):
                archive.write(item, item.relative_to(classes).as_posix())
    subprocess.run(["java", "-Xmx384m", "-cp", sdk / "build-tools/34.0.0/lib/d8.jar",
                    "com.android.tools.r8.D8", "--min-api", "24", "--lib", android,
                    "--output", output, jar], check=True)
    return (output / "classes.dex").read_bytes()


def hook_social_frame(original, output):
    output.mkdir(exist_ok=True)
    apktool = ROOT.parent / "tools/apktool.jar"
    subprocess.run(["javac", "-cp", apktool, "-d", output, ROOT / "scripts/RepairDex.java"], check=True)
    cli = ["java", "-Xmx384m", "-cp", str(apktool) + os.pathsep + str(output), "RepairDex"]
    original_dex = output / "input.dex"
    original_dex.write_bytes(original)
    smali = output / "smali"
    subprocess.run([*cli, "decode", original_dex, smali], check=True)
    renderer = smali / "com/popcap/SexyAppFramework/AndroidSurfaceView$AndroidRenderer.smali"
    text = renderer.read_text(encoding="utf-8")
    entry = "    invoke-static {}, Lcom/popcap/pvz2cthd/PresetEditor;->frame()V"
    if text.count(entry) != 1:
        raise ValueError("Missing existing game renderer frame callback")
    hook = "    invoke-static {}, Lcom/popcap/pvz2cthd/AdventureSocial;->frame()V"
    renderer.write_text(text.replace(entry, entry + "\n\n" + hook), encoding="utf-8")
    rebuilt = output / "renderer.dex"
    subprocess.run([*cli, "encode", smali, rebuilt], check=True)
    return rebuilt.read_bytes()


def build(base, output, sdk, ndk, signing=None, wsa_test=False, wsa_battle_tools=False,
          social_levels=False):
    if wsa_battle_tools and not wsa_test:
        raise ValueError("Battle tools are available only in a WSA test build")
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A250-{abi}.apk" for abi in ARM_ENGINES}
    with ZipFile(sources["ARM32"]) as arm32, ZipFile(sources["ARM64"]) as arm64:
        original = arm32.read(ARM_ENGINES["ARM32"])
        if original != arm64.read(ARM_ENGINES["ARM64"]):
            raise ValueError("A250 engines must share the same ARM32 code")
    patched = patch_native(original, ndk, output, wsa_battle_tools, social_levels)
    (output / "libSrc-adventure-records.so").write_bytes(patched)
    if not signing:
        return
    version = 272 if social_levels else 251
    companion_dex = social_dex(output / "social-dex", sdk) if social_levels else None
    architectures = ("ARM32",) if wsa_test else ARM_ENGINES
    for abi in architectures:
        member = ARM_ENGINES[abi]
        with ZipFile(sources[abi]) as apk:
            manifest = manifest_version(apk.read("AndroidManifest.xml"), version, 250, prefix="A")
            excluded = ([name for name in apk.namelist() if name.startswith("assets/pvz2data.zip.")]
                        if wsa_test else [])
            changes = {member: patched, "AndroidManifest.xml": manifest}
            extra_entries = {}
            if companion_dex is not None:
                changes["classes.dex"] = hook_social_frame(apk.read("classes.dex"), output / f"renderer-{abi}")
                last_dex = max(int(match[1] or "1") for name in apk.namelist()
                               if (match := re.fullmatch(r"classes(\d*)\.dex", name)))
                friends = ROOT / "src/adventure-records/friends.json"
                extra_entries = {f"classes{last_dex + 1}.dex": companion_dex,
                                 "assets/adventure/friends.json": friends.read_bytes()}
        if wsa_test and len(excluded) != 3:
            raise ValueError("The WSA candidate expects three already extracted resource parts")
        label = f"{abi}-WSA-existing-data" if wsa_test else abi
        if wsa_battle_tools:
            label += "-battle-tools"
        target = output / f"PvZ2-Unline-Aster-A{version}-{label}.apk"
        pack_apk(sources[abi], changes, sdk, target, signing, extra_entries=extra_entries, excluded=excluded)
        print(target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "ndk"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--signing", type=Path)
    parser.add_argument("--wsa-test", action="store_true")
    parser.add_argument("--wsa-battle-tools", action="store_true")
    parser.add_argument("--social-levels", action="store_true")
    build(**vars(parser.parse_args()))
