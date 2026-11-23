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
STAR_DESCRIPTIONS_GATE, STAR_DESCRIPTIONS_ENABLED = 0x7B1EB8, 0x7B1EC8
STAR_RESULT_TITLE = 0x7E5568
STAR_RIBBON_ART, STAR_RIBBON_EMPTY, STAR_RIBBON_GOLD = 0x805DB0, 0x805FB0, 0x805FF8
STAR_NEXT_BUTTON, STAR_NEXT_CLICK = 0x7E5CFC, 0x7E6BC8
STAR_SHOW_NEXT, STAR_SHOW_CONTINUE, STAR_CLICK_CONTINUE = 0x7E5D30, 0x7E62CC, 0x7E6B68
LEVEL_MENU_DRAW, POP_GRAPHICS = 0x7F3934, 0x116D764
LEVEL_MENU_PANEL_CALL, DRAW_DIALOG_PANEL = 0x7F3B38, 0x7F3470
BEGIN_BATTLE_ENTRY, BEGIN_BATTLE_TARGET = 0x2261A8, 0x17813A4
GAME_POLL, GAME_POLL_TARGET = 0x1A15808, 0x1A4995C
START_BUTTON_EVENT, DISPATCH_EVENT = 0x926D08, 0x21DF78
BOARD_TOUCH_CALLS, BOARD_TOUCH = (0x1A30114, 0x1A3013C, 0x1A30164), 0x1A2E16C
TITLE_TEXT, TRANSLATE_TEXT = 0x205544, 0xD07BB4
BOARD_MESSAGE_DRAW, BOARD_MESSAGE_TARGET = 0x46D890, 0x1A30074
VIEWPORT_NORMAL_DRAW = 0x1A64638
VIEWPORT_HIGH_DRAW = 0x1A64434
SEED_BANK_REFRESH = 0x895BD8
CHOOSER_RESTORE_CALL, CHOOSER_RESTORE = 0x8A5FEC, 0x8A0308
SEED_PACKET_DRAW_CALL, SEED_PACKET_DRAW = 0x8AE434, 0x8AB53C
GOLD_TILE_SUN = 0x3C1834
PLAY_NARRATIVE = 0x2AF780
# InitialPlantModule, InitialPlantPlacer and InitialZombiePlacer. The
# separate InitialGridItemPlacer still builds the original terrain.
INITIAL_ACTORS = (0x7CE1C8, 0x7D010C, 0x7D4C08)
SETTINGS_ROW, PICKUP_ROW = 0x8E6114, 0x1A68118
SETTINGS_CLICK, PICKUP_CLICK = 0x8E8884, 0x1A6813C
SETTINGS_TITLE, PICKUP_TITLE = 0x8E7868, 0x1A68184
SETTINGS_CHOICES, PICKUP_CHOICES = 0x8E7B34, 0x1A681B0
SETTINGS_CHOICES_DONE = 0x8E7BE4
SUN_BUTTON_OPEN, STOCK_SUN_PURCHASE = 0x93DD9C, 0x418E44
STOCK_SUN_CLOSE, SHOP_SCROLLBAR_CALL, SHOP_SCROLLBAR_VISIBLE = 0x418D18, 0x92C408, 0x1370BC0
USER_MAP_DRAW_SLOT, USER_MAP_HIT_SLOT, USER_MAP_TOUCH_SLOT = 0x17C7A9C, 0x17C7AB4, 0x17C7B1C
USER_MAP_NO_HIT, USER_MAP_NO_TOUCH = 0xA1BF74, 0xA1BBB0
USER_MAP_OVERLAY_SLOT, USER_MAP_OVERLAY_THUNK = 0x17C7B28, 0xA1C6B0
SIGN_IN_CREATE, CREATE_HUD = 0x9FF7C4, 0x9781E8
SHOP_CODE_CARD, SHOP_CODE_SKIP = 0x9361A0, 0x935EBC
FLAGS = [
    "--target=armv7a-linux-androideabi24", "-marm", "-march=armv7-a",
    "-mfloat-abi=softfp", "-mfpu=vfpv3-d16", "-Os", "-std=c++17",
    "-Wall", "-Wextra", "-Werror", "-fPIC", "-ffreestanding", "-fno-builtin",
    "-fno-stack-protector", "-fno-exceptions", "-fno-rtti",
    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
]

def star_advance_patches(stub, helper):
    button = stub(f"""push {{r0-r3,ip,lr}}
        mov r2,#0
        {helper("asterAdventureNextStar", "sb")}
        cmn r0,#1
        pop {{r0-r3,ip,lr}}
        beq #{STAR_SHOW_CONTINUE}
        movgt r4,#0
        bgt #{STAR_SHOW_NEXT}
        ldr r2,[sb,#0x48]
        b #{STAR_NEXT_BUTTON + 4}
    """)
    click = stub(f"""push {{r0-r3,ip,lr}}
        mov r2,#1
        {helper("asterAdventureNextStar", "r5")}
        cmn r0,#1
        pop {{r0-r3,ip,lr}}
        beq #{STAR_CLICK_CONTINUE}
        mov r3,#1
        b #{STAR_NEXT_CLICK + 4}
    """)
    return ((STAR_NEXT_BUTTON, 0xE5992048, button), (STAR_NEXT_CLICK, 0xE3A03001, click))


def payload(ndk, output, address, state_address, battle_tools, social_levels, social_art):
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    obj, linked, layout = (output / f"adventure-records.{ext}" for ext in ("o", "elf", "ld"))
    defines = ["-DASTER_WSA_BATTLE_TOOLS"] if battle_tools else []
    if social_levels:
        defines.extend(("-DASTER_SOCIAL_LEVELS", "-I", str(output)))
    if social_art:
        defines.append("-DASTER_SOCIAL_ART")
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


def patch_native(native, ndk, output, battle_tools=False, social_levels=False, social_art=False):
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
    body, state_size, symbols = payload(ndk, output, address, state_address,
                                        battle_tools, social_levels, social_art)
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
        user_attach = stub(f"""push {{r4,lr}}
            bl #{CREATE_HUD}
            mov r4,r0
            {helper("asterUserAttach", "r0")}
            mov r0,r4
            pop {{r4,pc}}
        """)
        changes.append((SIGN_IN_CREATE, branch(SIGN_IN_CREATE, CREATE_HUD, True),
                        branch(SIGN_IN_CREATE, user_attach, True)))
        # The original empty lottery draw also serves as the false-returning
        # hit test of another map widget. Patch only the lottery vtable.
        for site, original, symbol, arguments in (
                (USER_MAP_DRAW_SLOT, USER_MAP_NO_HIT, "asterUserDraw", "mov r2,r1"),
                (USER_MAP_TOUCH_SLOT, USER_MAP_NO_TOUCH, "asterUserTouch",
                 "sub sp,sp,#8\nstr r3,[sp]\nmov r3,r2\nmov r2,r1")):
            entry = stub(f"""push {{r4,lr}}
                {arguments}
                {helper(symbol, 'r0')}
                {'add sp,sp,#8' if site == USER_MAP_TOUCH_SLOT else ''}
                pop {{r4,pc}}
            """)
            changes.append((site, struct.pack("<I", original), struct.pack("<I", entry)))
            if site == USER_MAP_DRAW_SLOT:
                # The overlay renderer passes the secondary base at widget+16.
                overlay = stub(f"sub r0,r0,#16\nb #{entry}")
                changes.append((USER_MAP_OVERLAY_SLOT, struct.pack("<I", USER_MAP_OVERLAY_THUNK),
                                struct.pack("<I", overlay)))
        user_hit = stub(f"""push {{r4,lr}}
            mov r3,r2
            mov r2,r1
            {helper("asterUserHit", "r0")}
            pop {{r4,pc}}
        """)
        changes.append((USER_MAP_HIT_SLOT, struct.pack("<I", USER_MAP_NO_HIT), struct.pack("<I", user_hit)))
        shop_code = stub(f"""push {{r0-r3,ip,lr}}
            {helper("asterUserHasCodeEntry", "r0")}
            cmp r0,#0
            pop {{r0-r3,ip,lr}}
            bne #{SHOP_CODE_SKIP}
            mov r0,#304
            b #{SHOP_CODE_CARD + 4}
        """)
        changes.append((SHOP_CODE_CARD, struct.pack("<I", 0xE3A00E13), branch(SHOP_CODE_CARD, shop_code)))

        def four_args(name):
            return stub(f"""push {{r4,lr}}
                sub sp,sp,#8
                str r3,[sp]
                mov r3,r2
                mov r2,r1
                {helper(name, "r0")}
                add sp,sp,#8
                pop {{r4,pc}}
            """)

        borrow_cursor = stub(f"""push {{r4,lr}}
            mov r3,r5
            mov r2,r1
            {helper("asterAdventureBindBorrowCursor", "r0")}
            pop {{r4,pc}}
        """)
        for site, original, replacement in (
                (0x28F2A8, 0x229E8C, borrow_cursor),
                (0x4E751C, 0x4E719C, four_args("asterAdventurePlaceBorrowed")),
                (0x79BB90, 0x207D90, four_args("asterAdventureTacticalCuke"))):
            changes.append((site, branch(site, original, True), branch(site, replacement, True)))

        chooser_hide = stub(f"""{guard("asterBorrowDeferChooserHide")}
            .word 0xe92d48f0
            b #0x8f25d0
        """)
        changes.append((0x8F25CC, struct.pack("<I", 0xe92d48f0), branch(0x8F25CC, chooser_hide)))
        behind_chooser = stub(f"""push {{r4,lr}}
            mov r2,r1
            {helper("asterBorrowDrawBehindChooser", "r0")}
            pop {{r4,pc}}
        """)
        over_chooser = stub(f"""push {{r4,lr}}
            mov r2,r0
            ldr r1,[fp,#-0x88]
            {helper("asterBorrowDrawOverChooser", "r1")}
            pop {{r4,pc}}
        """)
        changes.extend((
            (0x8A603C, branch(0x8A603C, 0x976438, True), branch(0x8A603C, behind_chooser, True)),
            (0x8A6B00, branch(0x8A6B00, POP_GRAPHICS, True), branch(0x8A6B00, over_chooser, True)),
        ))

        # Read the completed native world matrix at the normal draw call.
        # At the high-view tail call there is no extra device transform.
        center_view = stub(f"""push {{r0-r3,ip,lr}}
            add r3,sp,#44
            mov r2,r1
            {helper("asterAdventureDrawFormationCamera", "r0")}
            pop {{r0-r3,ip,pc}}
        """)
        changes.append((VIEWPORT_NORMAL_DRAW, struct.pack("<I", 0xE12FFF32),
                        branch(VIEWPORT_NORMAL_DRAW, center_view, True)))
        high_view = stub(f"""push {{r4,lr}}
            mov r2,r1
            mov r3,#0
            {helper("asterAdventureDrawFormationCamera", "r0")}
            pop {{r4,pc}}
        """)
        changes.append((VIEWPORT_HIGH_DRAW, struct.pack("<I", 0xE12FFF12),
                        branch(VIEWPORT_HIGH_DRAW, high_view)))
        refresh = stub(f"""{guard("asterAdventureViewSeedBankRefresh")}
            .word 0xe92d4818
            b #{SEED_BANK_REFRESH + 4}
        """)
        chooser_restore = stub(f"""push {{r4,lr}}
            mov r2,r1
            {helper("asterAdventureRestoreChooserCards", "r0")}
            pop {{r4,pc}}
        """)
        seed_draw = stub(f"""push {{r4,lr}}
            mov r3,r2
            mov r2,r1
            {helper("asterAdventureDrawFormationCard", "r0")}
            pop {{r4,pc}}
        """)
        changes.extend((
            (SEED_BANK_REFRESH, struct.pack("<I", 0xe92d4818), branch(SEED_BANK_REFRESH, refresh)),
            (CHOOSER_RESTORE_CALL, branch(CHOOSER_RESTORE_CALL, CHOOSER_RESTORE, True),
             branch(CHOOSER_RESTORE_CALL, chooser_restore, True)),
            (SEED_PACKET_DRAW_CALL, branch(SEED_PACKET_DRAW_CALL, SEED_PACKET_DRAW, True),
             branch(SEED_PACKET_DRAW_CALL, seed_draw, True)),
        ))
        sun_button = stub(f"""push {{r0-r3,ip,lr}}
            mov r2,r1
            {helper("asterFriendSunOpen", "r0")}
            pop {{r0-r3,ip,pc}}
        """)
        changes.append((SUN_BUTTON_OPEN, branch(SUN_BUTTON_OPEN, STOCK_SUN_PURCHASE, True),
                        branch(SUN_BUTTON_OPEN, sun_button, True)))
        sun_close = stub(f"""push {{r0-r3,ip,lr}}
            {helper("asterFriendSunBeforeClose", "r0")}
            pop {{r0-r3,ip,lr}}
            push {{r3-r6,r11,lr}}
            b #{STOCK_SUN_CLOSE + 4}
        """)
        sun_scrollbar = stub(f"""push {{r1-r3,lr}}
            {helper("asterFriendSunShopScrollbar", "r0")}
            pop {{r1-r3,pc}}
        """)
        changes.extend((
            (STOCK_SUN_CLOSE, struct.pack("<I", 0xE92D4878), branch(STOCK_SUN_CLOSE, sun_close)),
            (SHOP_SCROLLBAR_CALL, branch(SHOP_SCROLLBAR_CALL, SHOP_SCROLLBAR_VISIBLE, True),
             branch(SHOP_SCROLLBAR_CALL, sun_scrollbar, True)),
        ))
        # Chain to A250's automatic pickup hooks for the existing settings
        # pages. Both custom rows use the game's native radio-button layout.
        settings_row = stub(f"""push {{r0-r4,lr}}
            {helper("asterSocialSettingsRow", "r4")}
            pop {{r0-r4,lr}}
            b #{PICKUP_ROW}
        """)
        settings_click = stub(f"""push {{r0-r4,lr}}
            mov r2,r1
            {helper("asterSocialSettingsClick", "r0")}
            cmp r0,#2
            moveq r1,#9
            streq r1,[sp,#4]
            beq stock_click
            cmp r0,#0
            pop {{r0-r4,lr}}
            bxne lr
            b #{PICKUP_CLICK}
            stock_click:
            pop {{r0-r4,lr}}
            b #{PICKUP_CLICK}
        """)
        settings_title = stub(f"""{guard("asterSocialSettingsTitle")}
            b #{PICKUP_TITLE}
        """)
        settings_choices = stub(f"""push {{r0-r3,ip,lr}}
            mov r2,r1
            {helper("asterSocialSettingsChoices", "r0")}
            cmp r0,#0
            pop {{r0-r3,ip,lr}}
            bne #{SETTINGS_CHOICES_DONE}
            b #{PICKUP_CHOICES}
        """)
        for site, old, new, link in (
            (SETTINGS_ROW, PICKUP_ROW, settings_row, True),
            (SETTINGS_CLICK, PICKUP_CLICK, settings_click, False),
            (SETTINGS_TITLE, PICKUP_TITLE, settings_title, True),
            (SETTINGS_CHOICES, PICKUP_CHOICES, settings_choices, True),
        ):
            changes.append((site, branch(site, old, link), branch(site, new, link)))

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
        board_message = stub(f"""{guard("asterAdventureSuppressBoardEffects")}
            b #{BOARD_MESSAGE_TARGET}
        """)
        # Keep the terrain initializer and the preview's own HUD. Only the
        # effects that add sun, dialogue or extra combatants are suspended.
        transient_effects = ((PLAY_NARRATIVE, 0xE92D4BF0),
                             *((site, 0xE92D4FF0) for site in (GOLD_TILE_SUN, *INITIAL_ACTORS)))
        for site, prologue in transient_effects:
            effect = stub(f"""{guard("asterAdventureSuppressBoardEffects")}
                .word {prologue}
                b #{site + 4}
            """)
            changes.append((site, struct.pack("<I", prologue), branch(site, effect)))
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
        # The condition dialog repeats the world unlock check before filling
        # its vector. It must use the same access decision as the active tier.
        star_descriptions = stub(f"""bne #{STAR_DESCRIPTIONS_ENABLED}
            push {{r0-r3,ip,lr}}
            ldr r1,[fp,#-0x3c]
            {helper("asterAdventureSelectedStarDescriptions", "r1")}
            cmp r0,#0
            pop {{r0-r3,ip,lr}}
            bne #{STAR_DESCRIPTIONS_ENABLED}
            b #{STAR_DESCRIPTIONS_GATE + 4}
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
        for site, original, target in star_advance_patches(stub, helper):
            changes.append((site, struct.pack("<I", original), branch(site, target)))
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
            (STAR_DESCRIPTIONS_GATE, struct.pack("<I", 0x1A000002),
             branch(STAR_DESCRIPTIONS_GATE, star_descriptions)),
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
    names = ("AdventureFormationRecord", "AdventureFriendFiles", "AdventureFriendRoster",
             "AdventureSocial", "AsterSaveBackup")
    sources = [package / (name + ".java") for name in names]
    classes = output / "classes"
    classes.mkdir(exist_ok=True)
    subprocess.run(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8",
                    "-classpath", android, "-sourcepath", ROOT / "src/bootstrap-extra",
                    "-implicit:none", "-d", classes, *sources], check=True)
    jar = output / "social.jar"
    with ZipFile(jar, "w") as archive:
        for name in names:
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
    activity = smali / "com/popcap/SexyAppFramework/SexyAppFrameworkActivity.smali"
    text = activity.read_text(encoding="utf-8")
    entry = ("    invoke-static {p0, p1, p2, p3}, Lcom/popcap/pvz2cthd/PresetEditor;->onActivityResult"
             "(Landroid/app/Activity;IILandroid/content/Intent;)Z")
    if text.count(entry) != 1:
        raise ValueError("Missing existing game document result handler")
    export = (
        entry.replace("PresetEditor", "AdventureSocial") + "\n"
        "    move-result v0\n"
        "    if-eqz v0, :aster_social_original_result\n"
        "    return-void\n"
        "    :aster_social_original_result\n\n"
    )
    activity.write_text(text.replace(entry, export + entry), encoding="utf-8")
    rebuilt = output / "renderer.dex"
    subprocess.run([*cli, "encode", smali, rebuilt], check=True)
    return rebuilt.read_bytes()


def patch_user_entry(dynamic):
    from build_aster_daily_sign_in import LAYOUTS
    from build_aster_hud_pickup import Bundle, replace_rton

    def add_user_button(document):
        sheets = {alias: entry["objdata"] for entry in document["objects"]
                  for alias in entry.get("aliases", ())}
        sign = sheets["UIWorldMapLoginRewardButton"]
        button = sign.copy()
        button.update(Class="WorldMap_LotteryButton",
                      PositionOffset={"x": sign["PositionOffset"]["x"] + 94, "y": sign["PositionOffset"]["y"]})
        document["objects"].append({"objclass": "UIWidgetSheet", "aliases": ["UIWorldMapUserButton"], "objdata": button})

    bundle = Bundle(dynamic)
    for layout in LAYOUTS:
        replace_rton(bundle, f"PACKAGES\\{layout}.RTON", add_user_button, allow_growth=True)
    return bundle.build()


def patch_friend_entry(dynamic):
    from build_aster_daily_sign_in import LAYOUTS
    from build_aster_hud_pickup import Bundle, replace_rton

    def add_friend_button(document):
        sheets = {alias: entry["objdata"] for entry in document["objects"]
                  for alias in entry.get("aliases", ())}
        user = sheets["UIWorldMapUserButton"]
        button = user.copy()
        button["PositionOffset"] = {"x": user["PositionOffset"]["x"] + 67,
                                    "y": user["PositionOffset"]["y"]}
        document["objects"].append(
            {"objclass": "UIWidgetSheet", "aliases": ["UIWorldMapFriendButton"], "objdata": button})

    bundle = Bundle(dynamic)
    for layout in LAYOUTS:
        replace_rton(bundle, f"PACKAGES\\{layout}.RTON", add_friend_button, allow_growth=True)
    return bundle.build()


def hook_save_restore(smali):
    importer = "    invoke-static {p0}, Lcom/popcap/pvz2cthd/PresetProfileImporter;->apply(Landroid/content/Context;)V"
    if smali.count(importer) != 1:
        raise ValueError("Missing bootstrap save initialization")
    restore = importer.replace("PresetProfileImporter;->apply(", "AsterSaveBackup;->applyPending(")
    return smali.replace(importer, restore + "\n\n" + importer)


def build(base, output, sdk, ndk, signing=None, wsa_test=False, wsa_battle_tools=False,
          social_levels=False, social_art=None, cn_user_apk=None):
    if wsa_battle_tools and not wsa_test:
        raise ValueError("Battle tools are available only in a WSA test build")
    if (social_art or cn_user_apk) and not social_levels:
        raise ValueError("Social sprites require the social level menu")
    output.mkdir(parents=True, exist_ok=True)
    sources = {abi: base / f"PvZ2-Unline-Aster-A250-{abi}.apk" for abi in ARM_ENGINES}
    if social_levels:
        from prepare_aster_adventure_levels import make_catalog, write_packet_anchors, write_user_plants

        catalog = make_catalog(sources["ARM32"], output)
        write_packet_anchors(sources["ARM32"], output)
        write_user_plants(sources["ARM32"], output)
    with ZipFile(sources["ARM32"]) as arm32, ZipFile(sources["ARM64"]) as arm64:
        original = arm32.read(ARM_ENGINES["ARM32"])
        if original != arm64.read(ARM_ENGINES["ARM64"]):
            raise ValueError("A250 engines must share the same ARM32 code")
    patched = patch_native(original, ndk, output, wsa_battle_tools, social_levels, bool(social_art))
    (output / "libSrc-adventure-records.so").write_bytes(patched)
    if not signing:
        return
    if social_levels:
        from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, create_plan, rebuild_dynamic_bootstrap
        from prepare_aster_social_art import add_social_art

        with ZipFile(sources["ARM32"]) as apk:
            original_dynamic = apk.read(ASSET)
        dynamic = add_social_art(patch_user_entry(original_dynamic), social_art, cn_user_apk)
        plan = create_plan(dynamic, output, rgba_atlases=1)
    version = 302 if social_levels else 251
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
            if social_levels:
                if apk.read(ASSET) != original_dynamic:
                    raise ValueError("Both architectures must start with the same dynamic bundle")
                changes.update({ASSET: dynamic, PLAN: plan,
                                BOOTSTRAP: rebuild_dynamic_bootstrap(
                                    apk.read(BOOTSTRAP), output / f"bootstrap-{abi}", original_dynamic, dynamic,
                                    transform=hook_save_restore)})
            if companion_dex is not None:
                changes["classes.dex"] = hook_social_frame(apk.read("classes.dex"), output / f"renderer-{abi}")
                last_dex = max(int(match[1] or "1") for name in apk.namelist()
                               if (match := re.fullmatch(r"classes(\d*)\.dex", name)))
                friends = ROOT / "src/adventure-records/friends.json"
                extra_entries = {f"classes{last_dex + 1}.dex": companion_dex,
                                 "assets/adventure/friends.json": friends.read_bytes(),
                                 "assets/adventure/levels.json": catalog}
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
    parser.add_argument("--social-art", type=Path, help="ZIP with the supplied 1536 social atlases")
    parser.add_argument("--cn-user-apk", type=Path, help="Local authorized Chinese 4.2.8 APK for the user panel sprites")
    build(**vars(parser.parse_args()))
