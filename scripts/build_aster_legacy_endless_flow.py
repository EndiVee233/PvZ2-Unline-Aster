"""Use the original Egypt card pool and keep the native opening dialogue active."""
import argparse
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_egypt_lawn_fix import APP_SLOT, EGYPT_LEVEL
from build_aster_legacy_endless_gameplay import (
    ACTIVITY_STARTER, ACTIVITY_STARTERS, ACTIVITY_SUN_PLANTS, BOOTSTRAP, ROOT, patch_egypt_waves,
)
from build_aster_pvp_feedback import pack_apk
from build_aster_rgba_background_pilot import ASSET, PLAN, create_plan
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch
from rebuild_bootstrap_dex import rebuild_bootstrap


ENGINE = "9598651815024fcdd5872a3c0beb6f469979424968076a7cb08014dda29082bb"
CURRENT_PROGRESS = 0x40add4
FESTIVAL_PROGRESS = 0x40af08
MAP_PROGRESS_CALLS = (0x2c3394, 0x2c3678, 0x2c3b7c, 0x2c3ecc, 0x2c5e0c)
LOAD_WIN_REWARD_PROGRESS = 0x997648
CHECK_DANGER_ROOM_DROP = 0x99838c
CHECK_OTHER_REWARD_EXCLUSIONS = 0x9989d4
SELECT_EVENT_MILESTONE_REWARD = 0xcd6b70
SHOW_EVENT_VICTORY_SCORE = 0xcd6a28
ATTACH_WIN_RESULT = 0x9977c0
SHOW_RESULT_WIDGET = 0x40324c
FINISH_WIN_REWARD = 0x9978d4
FLOOR_SUMMARY_STATEMENT_SITES = ((0x2d04a8, 0x2d010c), (0x2d0684, 0x2d022c))
SHOW_BATTLE_STATEMENT = 0x4111d0
CHECK_VICTORY_MILESTONE = 0xcd9430
CONTINUE_AFTER_VICTORY = 0xcd9744
CHECK_SUN_PURCHASE_INPUT = 0x93dc40
CHECK_SUN_PURCHASE_DRAW = 0x93e170
CHECK_REWARD_FADE_FLAG = 0x2d679c
BUILD_CHECKPOINT_LEVEL_NAME = 0x2c3dd4
STORE_WAVE_METER_PROGRESS = 0x9bf30c
CHECK_FESTIVAL_FLOOR_LIMIT = 0x2c5500
INTRO_CONFIRM = 0x2bcdac
CONFIRM = 0x2ced7c
BUILD_OPENING_PANEL = 0x2cfbe0
BEGIN_BATTLE = 0x2261a8
OPENING_ACCEPT = 0x2bb630
DANGER_ROOM_INTRO_TYPE = 0x2bbbbc
FIND_LEVEL_MODULE = 0x43af38
OPENING_REWARDS = 0x2d5038
GENERATE_REWARDS = 0x2d4164
BUILD_REWARD_PANEL = 0x2d1544
SET_WIDGET_VISIBLE = 0x1313b1c
FLIP_REWARD = 0x2d0fb8
OPEN_SEED_CHOOSER = 0x8fdf00
START_CHOOSER_PREVIEW = 0x8fee50
PLAY_PREVIEW_GROAN = 0x8fafa4
POST_AUDIO_EVENT = 0x1ecd30
COPY_INTRO_PLANTS = 0x2bc648
COPY_PLANT_IDS = 0x20ab94
SEED_BANK_MODULE = 0x20b958
PLANT_REGISTRY = 0x1830470
NAME_FOR_PLANT_ID = 0x49792c
APPEND_PLANT_NAME = 0x1ed488
ASSIGN_PLANT_NAMES = 0x267fd4
DESTROY_PLANT_NAMES = 0x24ae54
RELEASE_STRING = 0x14ebf58
BUILD_CHOOSER_PACKETS = 0x8a530c
DRAW_OPENING_BACKGROUND = 0x2d2350
DRAW_TILED_IMAGE = 0x972e70
RESOLVE_UI_IMAGE = 0x1dd8f0
DANGER_ROOM_GRASS = 0x18321e0
SAVE_REWARD_SELECTION = 0x2ceeb8
SAVE_PROGRESS = 0x2ced24
REGISTER_PLANT_ID = 0x4978b8
APPEND_PLANT_ID = 0x2d6e10
BUILD_RUN_PACKETS = 0x8a3f98
RESTORE_CAMPAIGN_SELECTION = 0x8a5de4
HAS_PROFILE_FLAG = 0x709898
OPENING_DIM = 0x2d23a0
FILL_RECT = 0x1167010
FIND_DANGER_PROPERTIES = 0x2c2ed4
INTERN_WIDE_NAME = 0x11e2ed8
EGYPT_WAVE_PROPERTIES = "AsterEgyptLegacyDangerRoomProps"
OPENING_OFFER_GATE = 0x2d5020
MARK_OFFER_GENERATED = 0x2d4b1c
CHECK_OFFER_CAPACITY = 0x2cef1c
HIDE_GAMEPLAY_HUD = 0x2c2a40
BUILD_REWARD_TITLE = 0x2d1608
TRANSLATE_WIDE_TEXT = 0xd080f0
CONTINUATION_REWARD_TITLE = "选择一张卡片加入你的阵容！"
ACTIVITY_ENDLESS_LEVEL = "festival_dangerroom_level_endless"
FESTIVAL_ROOMS = tuple(f"festival_dangerroom_level_{stage}"
                      for stage in ("one", "two", "three", "four", "endless"))
FESTIVAL_KEYS = tuple(range(0x16f3d30, 0x16f3da8, 0x18))
CHECKPOINT_HEADER = 0x894078
CHECKPOINT_HEADER_CALLS = (0x894498, 0x894790)
CHECKPOINT_SELECT_PROFILE = 0x894890
PROFILE_MANAGER_SLOT = 0x18300a4
ACTIVITY_CHECKPOINT_CONTEXT = 2
ACTIVITY_CHECKPOINT_CALL_FLAGS = (0xe08e50, 0xe08ef0)
REWARD_OFFER_COUNT = 0x2cd298
REWARD_OFFER_COUNT_CALLS = (0x2d46b8, 0x2d48a0)
ATTACH_STATS_CONTENT = 0x2cfc28
DIALOG_ADD_CHILD = 0x7f15e8
BUILD_REWARD_CONFIRM = 0x2d1c94
CHECK_PAID_REWARD = 0x2d4ed4
HAS_PAID_REWARD = 0x7697c4
SHOW_BATTLE_POWERUPS = 0x225890
SHOW_POWERUP_HOLDER = 0x7842e4
ADD_BOARD_POWERUP = 0x784d24


def patch(engine, version=227):
    if sha256(engine).hexdigest() != ENGINE:
        raise ValueError("Expected the A206 guest engine")
    elf = ELFFile(BytesIO(engine))
    loads = [(i, s) for i, s in enumerate(elf.iter_segments()) if s["p_type"] == "PT_LOAD"]
    # A210 no longer fits in the injected RX segment's file padding. The
    # original RX segment has unused padding before its following RW segment.
    (index, rx), (_, rw) = loads[:2] if version >= 210 else loads[-2:]
    if rx["p_flags"] != 5 or rw["p_flags"] != 6 or rx["p_filesz"] != rx["p_memsz"]:
        raise ValueError("Unexpected guest payload segments")
    used = (rx["p_filesz"] + 15) & ~15
    start = rx["p_vaddr"] + used
    asm = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    egypt_key_data = 'egypt_key:\n.asciz "egypt"'

    # Keep explicit event-menu selections when no Endless board owns the call.
    board_key_lookup = "bl find_board_progress_key\nmov r1, r0" if version >= 220 else "bl egypt_board"
    key_parameter = "" if version >= 220 else (
        "bl get_egypt_key" if version >= 213 else "adr r1, egypt_key")
    key_code = f"""
    payload_start:
        push {{r0-r3,r4,lr}}
        {board_key_lookup}
        cmp r0, #0
        {'strne r1, [sp, #4]' if version >= 220 else ''}
        pop {{r0-r3,r4,lr}}
        beq festival_key
        push {{r4,lr}}
        sub sp, sp, #8
        mov r4, r0
        {key_parameter}
        mov r2, sp
        blx #0x14ed0e0
        mov r0, r4
        add sp, sp, #8
        pop {{r4,pc}}
    festival_key:
        push {{r4,r5,fp,lr}}
        b #{CURRENT_PROGRESS + 4}
    """
    if version not in range(207, 228):
        raise ValueError("Expected A207 through A227")
    reward_board = "reward_board" if version >= 215 else "egypt_board"
    floor_rewards_board = reward_board if version >= 222 else "egypt_board"
    # Registering the widget prepares its background. The opening panel must
    # also construct the native buttons before auto-confirm can be suspended.
    legacy_action = "bxne lr" if version == 207 else f"""
        beq original_confirm
        ldr ip, [r0, #0x1b0]
        cmp ip, #0
        bxne lr
        {'mov ip, #0; strb ip, [r0, #0x1d5]' if version >= 214 else ''}
        b #{BUILD_OPENING_PANEL}
    original_confirm:
    """
    intro_code = f"""
    intro_entry:
        push {{r0-r3,r4,lr}}
        bl {reward_board}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        {legacy_action}
        b #{CONFIRM}
    """
    # Case 3 of Board::SetState normally starts battle immediately. While the
    # native intro owns the modal, defer all attempts to enter battle. Its
    # affirmative action releases the modal before dispatching this callback.
    prepare_pan = "bl position_for_preview" if version >= 212 else ""
    refresh_cards = "bl refresh_run_packets" if version >= 213 else ""
    after_accept = f"""
        mov r1, #1
        strb r1, [r2, #0x40]
        {prepare_pan}
        {refresh_cards}
        mov r0, r5
        mov r1, #0
        pop {{r4-r6,lr}}
        b #{OPEN_SEED_CHOOSER}
    """ if version >= 211 else f"""
        pop {{r4-r6,lr}}
        b #{BEGIN_BATTLE}
    """
    battle_code = f"""
    begin_battle:
        push {{r0-r3,r4,lr}}
        mov r4, r0
        bl {reward_board}
        cmp r0, #0
        beq begin_now
        cmp r0, r4
        bne begin_now
        ldr r4, [r4, #0x938]
        cmp r4, #0
        beq begin_now
        bl #{DANGER_ROOM_INTRO_TYPE}
        mov r1, r0
        mov r0, r4
        bl #{FIND_LEVEL_MODULE}
        cmp r0, #0
        ldrne r0, [r0, #0x34]
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        bxne lr
        b battle_prologue
    begin_now:
        pop {{r0-r3,r4,lr}}
    battle_prologue:
        push {{r4,r5,r6,r7,fp,lr}}
        b #{BEGIN_BATTLE + 4}

    opening_accept:
        push {{r0-r6,lr}}
        mov r5, r0
        bl {reward_board}
        mov r4, r0
        pop {{r0-r3}}
        cmp r4, #0
        bne accept_egypt
        pop {{r4-r6,lr}}
        bx r3
    accept_egypt:
        blx r3
        bl {reward_board}
        cmp r0, r4
        bne accept_done
        ldr r1, [r0, #0xc0]
        cmp r1, #3
        bne accept_done
        ldr r2, [r0, #0x938]
        cmp r2, #0
        ldrbne r1, [r2, #0x40]
        beq accept_done
        {'''
        push {r0-r3}
        bl activity_board
        cmp r0, #0
        pop {r0-r3}
        bne finish_accept
        ''' if version >= 220 else ''}
        cmp r1, #0
        bne accept_done
    finish_accept:
        {after_accept}
    accept_done:
        pop {{r4-r6,pc}}
    """ if version >= 209 else ""
    # Start generates offers and resets the old panel. Prepare the replacement
    # before dispatching card input, and show the parent again after a floor win.
    build_reward_panel = f"""
        bne reward_panel_ready
        mov r0, r4
        bl #{BUILD_REWARD_PANEL}
    reward_panel_ready:
        bl {floor_rewards_board}
        cmp r0, #0
        beq rewards_done
        ldr r0, [r4, #0x194]
        cmp r0, #0
        beq rewards_done
        mov r0, r4
        mov r1, #1
        bl #{SET_WIDGET_VISIBLE}
        b rewards_done
    """ if version >= 217 else f"""
        bne rewards_done
        mov r0, r4
        pop {{r4,lr}}
        b #{BUILD_REWARD_PANEL}
    """
    reward_code = f"""
    opening_rewards:
        push {{r4,lr}}
        mov r4, r0
        {'add r0, r4, #0xe8; bl ensure_activity_starter; mov r0, r4' if version >= 220 else ''}
        bl #{GENERATE_REWARDS}
        bl {reward_board}
        cmp r0, #0
        beq rewards_done
        ldr r1, [r4, #0x170]
        ldr r2, [r4, #0x174]
        cmp r1, r2
        bhs rewards_done
        ldr r0, [r4, #0x194]
        cmp r0, #0
        {build_reward_panel}
    rewards_done:
        pop {{r4,pc}}

    flip_reward:
        push {{r0-r3,r4,lr}}
        ldr r4, [r0, #0x194]
        cmp r4, #0
        bne flip_now
        bl {reward_board}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        bxne lr
        b flip_prologue
    flip_now:
        pop {{r0-r3,r4,lr}}
        {"b select_one_offer" if version >= 215 else ""}
    flip_prologue:
        push {{r4,r5,r6,r7,r8,sb,sl,fp,lr}}
        b #{FLIP_REWARD + 4}
    """ if version >= 210 else ""
    # The native accept callback has just read the saved roster, including any
    # plant added by the reward screen. Replace the chooser's transient list
    # with those aliases without changing the shared SeedBankProperties.
    roster_code = f"""
    copy_intro_plants:
        push {{r4-r8,lr}}
        sub sp, sp, #16
        mov r4, r0
        bl #{COPY_PLANT_IDS}
        {'mov r0, r4; bl ensure_activity_starter' if version >= 220 else ''}
        bl {reward_board}
        cmp r0, #0
        beq roster_done
        ldr r0, [r0, #0x938]
        cmp r0, #0
        beq roster_done
        bl #{SEED_BANK_MODULE}
        cmp r0, #0
        beq roster_done
        add r5, r0, #0x18
        ldm r4, {{r6,r7}}
        cmp r6, r7
        bhs roster_done
        adr r8, plant_registry_offset
        ldr r0, [r8]
        add r8, r8, r0
        mov r0, #0
        str r0, [sp]
        str r0, [sp, #4]
        str r0, [sp, #8]
    next_plant:
        add r0, sp, #12
        mov r1, r8
        ldr r2, [r6], #4
        bl #{NAME_FOR_PLANT_ID}
        ldr r0, [sp, #12]
        ldr r1, [r0, #-12]
        cmp r1, #0
        beq release_plant
        mov r0, sp
        add r1, sp, #12
        bl #{APPEND_PLANT_NAME}
    release_plant:
        ldr r0, [sp, #12]
        sub r0, r0, #12
        add r1, sp, #12
        blx #{RELEASE_STRING}
        cmp r6, r7
        blo next_plant
        ldr r1, [sp, #4]
        ldr r0, [sp]
        cmp r0, r1
        beq dispose_roster
        mov r0, r5
        mov r1, sp
        bl #{ASSIGN_PLANT_NAMES}
    dispose_roster:
        mov r0, sp
        bl #{DESTROY_PLANT_NAMES}
    roster_done:
        mov r0, r4
        add sp, sp, #16
        pop {{r4-r8,pc}}
    plant_registry_offset:
        .word 0
    """ if version >= 211 else ""
    # SeedChooser builds the visible packets by reading the property
    # whitelist directly, independently of the live seed-bank list. Borrow
    # the current run's vector only during that synchronous construction.
    old_chooser_code = f"""
    chooser_packets:
        push {{r0-r3,r4-r8,lr}}
        mov r4, r0
        ldr r5, [r0, #0x174]
        cmp r5, #0
        beq original_packets
        bl egypt_board
        cmp r0, #0
        beq original_packets
        ldr r0, [r0, #0x938]
        cmp r0, #0
        beq original_packets
        bl #{SEED_BANK_MODULE}
        cmp r0, #0
        beq original_packets
        add r1, r0, #0x18
        ldm r1, {{r6-r8}}
        cmp r6, r7
        bhs original_packets
        add r5, r5, #0x30
        ldm r5, {{r0-r2}}
        stm r5, {{r6-r8}}
        push {{r0-r3}}
        mov r0, r4
        bl chooser_prologue
        pop {{r0-r3}}
        stm r5, {{r0-r2}}
        pop {{r0-r3,r4-r8,pc}}
    original_packets:
        pop {{r0-r3,r4-r8,lr}}
    chooser_prologue:
        push {{r4,r5,r6,r7,r8,sb,sl,fp,lr}}
        b #{BUILD_CHOOSER_PACKETS + 4}

    position_for_preview:
        ldr r1, [r0, #0x994]
        rsb r1, r1, #0
        mov r2, #0
        ldr ip, [r0]
        ldr ip, [ip, #0x40]
        bx ip

    opening_background:
        cmp r2, #0
        bne original_background
        push {{r0-r3,r4,lr}}
        bl egypt_board
        cmp r0, #0
        beq background_done
        adr r1, grass_offset
        ldr r0, [r1]
        add r0, r0, r1
        bl #{RESOLVE_UI_IMAGE}
        str r0, [sp, #8]
    background_done:
        pop {{r0-r3,r4,lr}}
    original_background:
        b #{DRAW_TILED_IMAGE}
    grass_offset:
        .word 0
    """ if version == 212 else ""
    mark_confirmed = "ldr r0, [r4, #0xdc]\nstr r0, [r4, #0xf8]" if version >= 214 else ""
    run_code = f"""
    save_reward_selection:
        push {{r4-r8,lr}}
        sub sp, sp, #8
        mov r4, r0
        bl {reward_board}
        cmp r0, #0
        beq save_rewards
        {mark_confirmed}
        {'add r0, r4, #0xe8; bl ensure_activity_starter' if version >= 220 else ''}
        ldr r5, [r4, #0x170]
        ldr r6, [r4, #0x174]
        add r7, r4, #0xe8
    reward_loop:
        cmp r5, r6
        bhs save_rewards
        ldr r8, [r5], #4
        ldrb r0, [r8, #0x30]
        cmp r0, #0
        beq reward_loop
        ldrb r0, [r8, #0x32]
        cmp r0, #0
        bne reward_loop
        ldr r0, [r8, #8]
        cmp r0, #1
        bne reward_loop
        add r8, r8, #0x10
        bl #0x11d74b4
        mov r1, r8
        bl #0x1da034
        cmp r0, #0
        beq reward_loop
        add r1, r0, #4
        bl plant_id_for_alias
        cmp r0, #0
        blt reward_loop
        ldm r7, {{r1,r2}}
    check_reward_id:
        cmp r1, r2
        bhs add_reward_id
        ldr r3, [r1], #4
        cmp r3, r0
        beq reward_loop
        b check_reward_id
    add_reward_id:
        str r0, [sp]
        mov r0, r7
        mov r1, sp
        bl #{APPEND_PLANT_ID}
        b reward_loop
    save_rewards:
        mov r0, r4
        add sp, sp, #8
        pop {{r4-r8,lr}}
        b #{SAVE_PROGRESS}

    plant_id_for_alias:
        adr r0, plant_registry_offset
        ldr r2, [r0]
        add r0, r0, r2
        b #{REGISTER_PLANT_ID}

    refresh_run_packets:
        push {{r4,lr}}
        bl current_seed_bank
        cmp r0, #0
        beq refresh_done
        add r4, r0, #0x30
        bl #0x11d74b4
        mov r1, r4
        bl #0x1da034
        cmp r0, #0
        beq refresh_done
        bl chooser_packets
    refresh_done:
        pop {{r4,pc}}

    current_seed_bank:
        push {{r4,lr}}
        bl {reward_board}
        cmp r0, #0
        ldrne r0, [r0, #0x938]
        cmp r0, #0
        pop {{r4,lr}}
        bne #{SEED_BANK_MODULE}
        bx lr

    chooser_packets:
        push {{r0-r3,r4-r8,lr}}
        mov r4, r0
        bl current_seed_bank
        cmp r0, #0
        beq original_packets
        add r0, r0, #0x18
        ldm r0, {{r5,r6}}
        cmp r5, r6
        bhs original_packets
        sub sp, sp, #16
        mov r0, #0
        str r0, [sp]
        str r0, [sp, #4]
        str r0, [sp, #8]
    chooser_plant_id:
        mov r1, r5
        bl plant_id_for_alias
        cmp r0, #0
        blt chooser_next_plant
        str r0, [sp, #12]
        mov r0, sp
        add r1, sp, #12
        bl #{APPEND_PLANT_ID}
    chooser_next_plant:
        add r5, r5, #4
        cmp r5, r6
        blo chooser_plant_id
        mov r0, r4
        mov r1, sp
        bl #{BUILD_RUN_PACKETS}
        ldr r0, [sp]
        cmp r0, #0
        beq chooser_dispose_done
        blx #0x14c2e94
    chooser_dispose_done:
        add sp, sp, #16
        pop {{r0-r3,r4-r8,pc}}
    original_packets:
        pop {{r0-r3,r4-r8,lr}}
        push {{r4,r5,r6,r7,r8,sb,sl,fp,lr}}
        b #{BUILD_CHOOSER_PACKETS + 4}

    restore_campaign_selection:
        push {{r0-r3,r4,lr}}
        bl {reward_board}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        beq #{HAS_PROFILE_FLAG}
        mov r0, #0
        bx lr

    position_for_preview:
        ldr r1, [r0, #0x994]
        rsb r1, r1, #0
        mov r2, #0
        ldr ip, [r0]
        ldr ip, [ip, #0x40]
        bx ip

    """ if version >= 213 else ""
    old_dim_code = f"""
    opening_dim:
        push {{r0-r6,lr}}
        bl egypt_board
        cmp r0, #0
        beq fill_original
        adr r1, grass_offset
        ldr r0, [r1]
        add r0, r0, r1
        bl #{RESOLVE_UI_IMAGE}
        cmp r0, #0
        beq fill_original
        mov r5, r0
        sub sp, sp, #16
        mov r4, sp
        mov r0, r4
        mov r1, #1
        bl #0x112f868
        ldr r0, [sp, #16]
        mov r1, r4
        bl #0x1166c30
        mov r1, #0
        str r1, [r4]
        str r1, [r4, #4]
        ldr r2, [sp, #28]
        str r2, [r4, #8]
        ldr r2, [sp, #48]
        str r2, [r4, #12]
        ldr r0, [sp, #16]
        mov r1, r4
        mov r2, r5
        mov r3, #0x3f800000
        bl #{DRAW_TILED_IMAGE}
        add sp, sp, #16
        pop {{r0-r6,pc}}
    fill_original:
        pop {{r0-r6,lr}}
        b #{FILL_RECT}
    """ if version == 213 else ""
    single_reward_limit = """
        mov r6, #0
        mov r5, #1
    """ if version >= 215 else """
        ldr r2, [r0, #0xdc]
        cmp r2, #1
        ble stock_offer_capacity
        mov r6, #0
        mov r5, #1
    """
    reward_title_gate = "" if version >= 215 else """
        ldr r2, [r6, #0xdc]
        cmp r2, #1
    """
    title_address = "adr" if version >= 215 else "adrgt"
    activity_offer_gate = """
        push {r0-r3,r4,lr}
        bl activity_board
        cmp r0, #0
        pop {r0-r3,r4,lr}
        beq stock_offer_gate
        ldr r2, [r4, #0xdc]
        cmp r2, #1
        bne #0x2d53c0
        ldr r3, [r4, #0xf8]
        b compare_offer_floor
    """ if 215 <= version < 222 else ""
    stats_board = reward_board if version >= 225 else "egypt_board"
    next_floor_code = f"""
    opening_offer_gate:
        push {{r0-r3,r4,lr}}
        bl {floor_rewards_board}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        {'beq activity_or_stock_offer' if 215 <= version < 222 else 'beq stock_offer_gate'}
        ldr r2, [r4, #0xdc]
        ldr r3, [r4, #0xf8]
    compare_offer_floor:
        cmp r2, r3
        ble #0x2d53c0
        mov r6, #1
        b #0x2d5030
    activity_or_stock_offer:
        {activity_offer_gate}
    stock_offer_gate:
        cmp r3, #0
        beq #0x2d53c0
        b #0x2d5024

    mark_offer_generated:
        push {{r0-r4,lr}}
        bl {reward_board}
        cmp r0, #0
        pop {{r0-r4,lr}}
        streq r3, [sb, #0xf8]
        b #0x2d4b20

    check_offer_capacity:
        push {{r0-r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r4,lr}}
        {"beq activity_offer_capacity" if version >= 215 else "beq stock_offer_capacity"}
        {single_reward_limit}
    stock_offer_capacity:
        add r2, r3, r6
        b #0x2cef20

    preserve_gameplay_hud:
        push {{r0-r3,r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        ldr r2, [r4, #0x84]
        beq #0x2c2a44
        ldr r3, [r4, #0x88]
        cmp r2, r3
        bne #0x2c2b30
        mov r0, r4
        bl #0x2bfc10
        b #0x2c2b30

    stats_background:
        push {{r0-r6,lr}}
        ldr r4, [r8, #0x1b0]
        cmp r4, #0
        beq draw_background
        bl {stats_board}
        cmp r0, #0
        beq draw_background
        ldr r5, [sp, #8]
        cmp r5, #0
        bne color_background
        adr r1, grass_offset
        ldr r0, [r1]
        add r0, r0, r1
        bl #{RESOLVE_UI_IMAGE}
        mov r5, r0
    color_background:
        str r5, [sp, #8]
        cmp r5, #0
        moveq r0, #1
        movne r0, #2
        strb r0, [r8, #0x1d5]
        beq draw_background
        sub sp, sp, #16
        mov r0, sp
        mov r1, #1
        bl #0x112f868
        ldr r0, [sp, #16]
        mov r1, sp
        bl #0x1166c30
        add sp, sp, #16
    draw_background:
        pop {{r0-r6,lr}}
        b #{DRAW_TILED_IMAGE}

    opening_dim:
        push {{r0-r3,r4,lr}}
        bl {stats_board}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        beq #{FILL_RECT}
        bx lr

    reward_title:
        push {{r0-r3,r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        beq #{TRANSLATE_WIDE_TEXT}
        {reward_title_gate}
        {title_address} r1, next_floor_title
        b #{TRANSLATE_WIDE_TEXT}
    next_floor_title:
        .word {','.join(map(str, map(ord, CONTINUATION_REWARD_TITLE + chr(0))))}
        {"grass_offset: .word 0" if version >= 218 else ""}
    """ if version >= 214 else ""
    map_room_code = f"""
    select_one_offer:
        push {{r0-r8,lr}}
        bl egypt_board
        cmp r0, #0
        beq flip_with_original_coords
        ldm sp, {{r4-r6}}
        ldr r1, [r4, #0xb4]
        cmp r1, #0
        bne flip_with_original_coords
        ldr r1, [r4, #0x1d0]
        cmp r1, #1
        bne flip_with_original_coords
        ldr r1, [r4, #0x170]
        ldr r2, [r4, #0x174]
        mov r7, #0
        mov r8, #0
    locate_offers:
        cmp r1, r2
        bhs replace_offer
        ldr r0, [r1], #4
        ldrb r3, [r0, #0x30]
        cmp r3, #0
        movne r7, r0
        ldrb r3, [r0, #0x32]
        cmp r3, #0
        bne locate_offers
        ldr r3, [r0, #0x1c]
        sub r3, r5, r3
        ldr ip, [r0, #0x24]
        cmp r3, ip
        bhs locate_offers
        ldr r3, [r0, #0x20]
        sub r3, r6, r3
        ldr ip, [r0, #0x28]
        cmp r3, ip
        movlo r8, r0
        b locate_offers
    replace_offer:
        cmp r7, #0
        beq flip_with_original_coords
        cmp r8, #0
        beq flip_with_original_coords
        cmp r7, r8
        beq flip_with_original_coords
        ldr r1, [r7, #0x1c]
        ldr r2, [r7, #0x20]
        ldr r3, [r7, #0x24]
        add r1, r1, r3, asr #1
        ldr r3, [r7, #0x28]
        add r2, r2, r3, asr #1
        mov r0, r4
        bl flip_prologue
    flip_with_original_coords:
        pop {{r0-r8,lr}}
        b flip_prologue

    map_progress:
        push {{r0-r3,r4,lr}}
        bl {'find_board_progress_key' if version >= 220 else 'egypt_board'}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        bne #{CURRENT_PROGRESS}
        b #{FESTIVAL_PROGRESS}

    map_offer_count:
        push {{r0-r3,r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        movne r0, #4
        bxne lr
        push {{r0-r3,r4,lr}}
        bl activity_board
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        movne r0, #6
        bxne lr
        b #{REWARD_OFFER_COUNT}

    activity_offer_capacity:
        push {{r0-r4,lr}}
        bl activity_board
        cmp r0, #0
        pop {{r0-r4,lr}}
        {'''
        beq stock_offer_capacity
        ldr r5, [r0, #0x1d8]
        cmp r5, #5
        movgt r5, #5
        mov r6, #0
        ''' if version >= 222 else '''
        movne r5, #5
        movne r6, #0
        '''}
        b stock_offer_capacity

    check_floor_limit:
        push {{r0-r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r4,lr}}
        movne r1, r3
        cmp r3, r1
        b #{CHECK_FESTIVAL_FLOOR_LIMIT + 4}

    attach_stats_content:
        push {{r0-r3,r4,lr}}
        bl {reward_board if version >= 226 else "egypt_board"}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        @ The dialog otherwise draws its own full-screen black backdrop.
        movne ip, #0
        strbne ip, [r0, #0xcd]
        strne ip, [r0, #0xd0]
        b #{DIALOG_ADD_CHILD}

    show_battle_powerups:
        push {{r0-r3,r4,lr}}
        bl {floor_rewards_board}
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        beq #{SHOW_POWERUP_HOLDER}
        cmp r0, #0
        beq #{SHOW_POWERUP_HOLDER}
        push {{r4,lr}}
        sub sp, sp, #16
        mov r4, r0
        mov r0, sp
        adr r1, tactical_cuke_name
        add r2, sp, #4
        blx #0x14ed0e0
        mov r0, r4
        mov r1, sp
        mov r2, #{0 if version >= 216 else 1}
        bl #{ADD_BOARD_POWERUP}
        ldr r0, [sp]
        add r1, sp, #8
        sub r0, r0, #12
        blx #{RELEASE_STRING}
        add sp, sp, #16
        pop {{r4,lr}}
        b #{SHOW_POWERUP_HOLDER}

    map_reward_confirm:
        push {{r0-r3,r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        adrne r1, confirm_label
        b #{TRANSLATE_WIDE_TEXT}

    skip_paid_offer:
        push {{r0-r3,r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        movne r0, #1
        bxne lr
        b #{HAS_PAID_REWARD}

    confirm_label:
        .word 0x786e, 0x5b9a, 0
    tactical_cuke_name:
        .word {','.join(hex(word) for word in struct.unpack("<5I", b"poweruptacticalcuke" + bytes(1)))}
    """ if version >= 215 else ""
    win_reward_code = f"""
    select_event_milestone:
        bne #{SELECT_EVENT_MILESTONE_REWARD + 4}
        push {{r0-r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r4,lr}}
        bne #{SELECT_EVENT_MILESTONE_REWARD + 4}
        b #0xcd7d08

    checkpoint_level_name:
        push {{r4,lr}}
        push {{r0-r3}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r3}}
        {'''
        beq build_checkpoint_name
        bl get_egypt_level
    build_checkpoint_name:
        ''' if version >= 220 else 'adrne r1, egypt_level'}
        blx #0x14ed0e0
        pop {{r4,pc}}

    clamp_wave_meter_progress:
        push {{r0-r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r4,lr}}
        beq store_meter_progress
        cmp sb, #0
        movmi sb, #0
        mov ip, #0x42000000
        add ip, ip, #0xc80000
        cmp sb, ip
        movhi sb, ip
    store_meter_progress:
        str sb, [r0, #0xf0]
        b #{STORE_WAVE_METER_PROGRESS + 4}
    """ if version >= 216 else ""
    # Skip the event-only reward exclusion for the Egypt map room. Keep the
    # remaining native checks, collectable placement, and pickup callbacks.
    legacy_drop_code = f"""
    check_danger_room_drop:
        beq #{CHECK_OTHER_REWARD_EXCLUSIONS}
        push {{r0-r4,lr}}
        bl {floor_rewards_board}
        cmp r0, #0
        pop {{r0-r4,lr}}
        bne #{CHECK_OTHER_REWARD_EXCLUSIONS}
        b #{CHECK_DANGER_ROOM_DROP + 4}
    """ if version >= 217 else ""
    # The event score panel subscribes separately from the floor checkpoint.
    # The fade check normally skips animation until the first confirmed reward.
    legacy_victory = f"""
        beq original_event_victory_score
    stage_floor_continuation:
        cmp r1, #1
        movlt r1, #1
        str r1, [r0, #0x100]
        mov r2, #0
        str r2, [r0, #0x118]
        mov r2, #1
        str r2, [r0, #0xf4]
        bx lr
    original_event_victory_score:
    """ if version >= 219 else "bxne lr"
    # Advance on the result widget's next update, after the event dispatcher
    # releases the board. Use the same continuation as a stock non-milestone.
    legacy_continue_code = f"""
    check_victory_milestone:
        bne #{CONTINUE_AFTER_VICTORY}
        push {{r0-r4,lr}}
        bl {floor_rewards_board}
        cmp r0, #0
        pop {{r0-r4,lr}}
        bne #{CONTINUE_AFTER_VICTORY}
        b #{CHECK_VICTORY_MILESTONE + 4}
    """ if version >= 219 else ""
    # The sun bank checks IsDangerRoom independently in draw and hit testing.
    # Continue through the original feature, affordability and input checks.
    sun_purchase_code = f"""
    check_sun_purchase_input:
        beq #0x93dc60
        push {{r0-r4,lr}}
        bl {reward_board}
        cmp r0, #0
        pop {{r0-r4,lr}}
        bne #0x93dc60
        b #{CHECK_SUN_PURCHASE_INPUT + 4}

    check_sun_purchase_draw:
        beq #{CHECK_SUN_PURCHASE_DRAW + 4}
        push {{r0-r4,lr}}
        bl {reward_board}
        cmp r0, #0
        pop {{r0-r4,lr}}
        bne #{CHECK_SUN_PURCHASE_DRAW + 4}
        b #0x93dfc0
    """ if version >= 219 else ""
    legacy_transition_code = f"""
    show_event_victory_score:
        push {{r0-r4,lr}}
        bl {floor_rewards_board}
        cmp r0, #0
        pop {{r0-r4,lr}}
        {legacy_victory}
        push {{r4,r5,r6,r7,r8,sb,sl,fp,lr}}
        b #{SHOW_EVENT_VICTORY_SCORE + 4}

    check_reward_fade_flag:
        push {{r0-r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r4,lr}}
        movne r0, #1
        bxne lr
        b #{HAS_PROFILE_FLAG}
    """ if version >= 218 else ""
    # The activity can request the inherited chooser timeline while the
    # reward dialog still covers the board. Keep its preview and cue behind
    # the same modal boundary as the existing BeginBattle gate.
    activity_transition_code = f"""
    {'open_activity_chooser:' if version >= 220 else ''}
        {'''
        push {r0-r4,lr}
        bl activity_reward_modal
        cmp r0, #0
        pop {r0-r4,lr}
        bxne lr
        push {r4,r5,fp,lr}
        b #0x8fdf04
        ''' if version >= 220 else ''}

    start_chooser_preview:
        push {{r0-r4,lr}}
        bl activity_reward_modal
        cmp r0, #0
        pop {{r0-r4,lr}}
        bxne lr
        push {{r4,r5,r6,r7,r8,sb,sl,fp,lr}}
        b #{START_CHOOSER_PREVIEW + 4}

    play_preview_groan:
        push {{r0-r4,lr}}
        bl activity_reward_modal
        cmp r0, #0
        pop {{r0-r4,lr}}
        bxne lr
        b #{POST_AUDIO_EVENT}

    activity_reward_modal:
        push {{r4,lr}}
        bl activity_board
        cmp r0, #0
        ldrne r4, [r0, #0x938]
        moveq r4, #0
        cmp r4, #0
        moveq r0, #0
        popeq {{r4,pc}}
        bl #{DANGER_ROOM_INTRO_TYPE}
        mov r1, r0
        mov r0, r4
        bl #{FIND_LEVEL_MODULE}
        cmp r0, #0
        ldrne r0, [r0, #0x34]
        pop {{r4,pc}}
    """ if version >= 218 else ""
    checkpoint_saved_registers = "r4-r6" if version >= 221 else "r4"
    prefix_check = f"""
        adr r0, activity_level
        mov ip, #{len("festival_dangerroom_level_")}
    read_festival_prefix:
        ldrb r2, [r0], #1
        ldrb r3, [r1], #1
        cmp r2, r3
        bne no_progress_key
        subs ip, ip, #1
        bne read_festival_prefix
    """ if version >= 221 else """
        adr r0, festival_prefix
    read_festival_prefix:
        ldrb r2, [r0], #1
        cmp r2, #0
        beq festival_suffix
        ldrb r3, [r1], #1
        cmp r2, r3
        beq read_festival_prefix
        b no_progress_key
    """
    activity_roster = f"""
    ensure_activity_starter:
        push {{r4-r8,lr}}
        mov r4, r0
        bl activity_board
        cmp r0, #0
        popeq {{r4-r8,pc}}
        ldm r4, {{r5,r6}}
        mov r7, r5
        mov r8, #0
    next_activity_packet:
        cmp r5, r6
        bhs add_activity_starters
        ldr r0, [r5], #4
        adr r1, activity_no_sun
    check_activity_packet:
        ldrh r2, [r1], #2
        cmp r2, #0
        beq keep_activity_packet
        cmp r0, r2
        bne check_activity_packet
        b next_activity_packet
    keep_activity_packet:
        cmp r0, #{ACTIVITY_STARTERS[0][1]}
        orreq r8, r8, #1
        cmp r0, #{ACTIVITY_STARTERS[1][1]}
        orreq r8, r8, #2
        str r0, [r7], #4
        b next_activity_packet
    add_activity_starters:
        str r7, [r4, #4]
        sub sp, sp, #8
        tst r8, #1
        bne second_activity_starter
        mov r2, #{ACTIVITY_STARTERS[0][1]}
        bl append_activity_packet
    second_activity_starter:
        tst r8, #2
        bne activity_roster_done
        mov r2, #{ACTIVITY_STARTERS[1][1]}
        bl append_activity_packet
    activity_roster_done:
        add sp, sp, #8
        pop {{r4-r8,pc}}
    append_activity_packet:
        mov r0, r4
        mov r1, sp
        str r2, [sp]
        b #{APPEND_PLANT_ID}
    """ if version >= 222 else f"""
    ensure_activity_starter:
        push {{r4-r6,lr}}
        mov r4, r0
        bl activity_board
        cmp r0, #0
        popeq {{r4-r6,pc}}
        sub sp, sp, #16
        mov r0, sp
        adr r1, activity_starter
        add r2, sp, #4
        blx #0x14ed0e0
        mov r1, sp
        bl plant_id_for_alias
        mov r5, r0
        ldr r0, [sp]
        add r1, sp, #4
        sub r0, r0, #12
        blx #{RELEASE_STRING}
        cmp r5, #0
        blt starter_done
        ldm r4, {{r0,r6}}
    find_starter_id:
        cmp r0, r6
        bhs append_starter_id
        ldr r1, [r0], #4
        cmp r1, r5
        bne find_starter_id
        b starter_done
    append_starter_id:
        mov r0, r4
        mov r1, sp
        str r5, [sp]
        bl #{APPEND_PLANT_ID}
    starter_done:
        add sp, sp, #16
        pop {{r4-r6,pc}}
    """
    roster_data = (f'activity_no_sun: .short {",".join(str(i) for _, i in ACTIVITY_SUN_PLANTS)},0'
                   if version >= 222 else f'activity_starter: .asciz "{ACTIVITY_STARTER}"')
    progress_isolation_code = f"""
    .align 2
    find_board_progress_key:
        push {{r4-r6,lr}}
        bl egypt_board
        cmp r0, #0
        beq find_festival_key
        bl get_egypt_key
        mov r0, r1
        pop {{r4-r6,pc}}
    find_festival_key:
        bl current_board_name
        cmp r1, #0
        beq no_progress_key
        {prefix_check}
    festival_suffix:
        mov r4, r1
        adr r5, festival_keys
        mov r6, r5
    next_progress_room:
        ldr r3, [r6], #4
        cmp r3, #0
        beq no_progress_key
        add r3, r5, r3
        add r0, r3, #{len("festival_level_")}
        mov r1, r4
        bl room_names_match
        cmp r0, #0
        beq next_progress_room
        mov r0, r3
        pop {{r4-r6,pc}}
    no_progress_key:
        mov r0, #0
        pop {{r4-r6,pc}}

    room_names_match:
        ldrb r2, [r0], #1
        ldrb ip, [r1], #1
        cmp r2, ip
        movne r0, #0
        bxne lr
        cmp r2, #0
        bne room_names_match
        mov r0, #1
        bx lr

    read_owned_checkpoint:
        push {{{checkpoint_saved_registers},lr}}
        mov r4, r1
        {f'''
        mov r5, r2
        cmp r2, #{ACTIVITY_CHECKPOINT_CONTEXT}
        moveq r2, #1
        ''' if version >= 221 else ''}
        bl #{CHECKPOINT_HEADER}
        cmp r0, #0
        popeq {{{checkpoint_saved_registers},pc}}
        adr r0, profile_manager_offset
        ldr r1, [r0]
        ldr r0, [r0, r1]
        cmp r0, #0
        beq deny_checkpoint
        ldr r1, [r0, #0x74]
        ldr r2, [r4, #0x18]
        cmn r1, #1
        beq deny_checkpoint
        cmp r1, r2
        bne deny_checkpoint
        {f'''
        cmp r5, #{ACTIVITY_CHECKPOINT_CONTEXT}
        adreq r1, activity_level
        beq compare_checkpoint_room
        ''' if version >= 221 else ''}
        bl find_board_progress_key
        cmp r0, #0
        moveq r0, #1
        popeq {{{checkpoint_saved_registers},pc}}
        bl current_board_name
    compare_checkpoint_room:
        ldr r0, [r4, #4]
        cmp r0, #0
        beq deny_checkpoint
        pop {{{checkpoint_saved_registers},lr}}
        b room_names_match
    deny_checkpoint:
        mov r0, #0
        pop {{{checkpoint_saved_registers},pc}}

    {activity_roster}

    .align 2
    {roster_data if version >= 222 else ''}
    profile_manager_offset: .word 0
    festival_keys: .space {4 * (len(FESTIVAL_KEYS) + 1)}
    {f'activity_level: .asciz "{ACTIVITY_ENDLESS_LEVEL}"' if version >= 221
     else 'festival_prefix: .asciz "festival_dangerroom_level_"'}
    {roster_data if version < 222 else ''}
    .align 2
    """ if version >= 220 else ""
    grass_data = "grass_offset: .word 0" if version < 218 else ""
    wave_code = f"""
    {grass_data}

    find_wave_properties:
        push {{r0-r3,r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r0-r3,r4,lr}}
        adrne r1, wave_properties_name
        b #{INTERN_WIDE_NAME}
    wave_properties_name:
        .word {','.join(map(str, map(ord, EGYPT_WAVE_PROPERTIES + chr(0))))}
    """ if version >= 213 else ""
    activity_predicates = f"""
    reward_board:
        push {{r4,lr}}
        bl egypt_board
        cmp r0, #0
        pop {{r4,lr}}
        bxne lr
    activity_board:
        adr r2, activity_level
        b find_named_board
    """ if version >= 215 else ""
    activity_level_data = f"""
    activity_level:
        .asciz "{ACTIVITY_ENDLESS_LEVEL}"
    """ if 215 <= version < 221 else ""
    predicate = f"""
    {activity_predicates}
    egypt_board:
        adr r2, egypt_level
    find_named_board:
        {'''
        push {r2,lr}
        bl current_board_name
        pop {r2,lr}
        cmp r1, #0
        beq different
        b compare
    current_board_name:
        mov r1, #0
        ''' if version >= 220 else ''}
        adr ip, app_slot_offset
        ldr r3, [ip]
        ldr r3, [ip, r3]
        cmp r3, #0
        beq different
        ldr r3, [r3]
        cmp r3, #0
        beq different
        ldr r0, [r3, #0x6bc]
        cmp r0, #0
        beq different
        ldr r1, [r0, #0xc4]
        {'bx lr' if version >= 220 else ''}
        cmp r1, #0
        beq different
    compare:
        ldrb r3, [r1], #1
        ldrb ip, [r2], #1
        cmp r3, ip
        bne different
        cmp r3, #0
        bne compare
        bx lr
    different:
        mov r0, #0
        bx lr
    {'''get_egypt_key:
        adr r1, egypt_key
        bx lr''' if version >= 213 else ''}
    {'''get_egypt_level:
        adr r1, egypt_level
        bx lr''' if version >= 220 else ''}
    app_slot_offset:
        .word 0
    {egypt_key_data}
    {activity_level_data}
    egypt_level:
        .asciz "{EGYPT_LEVEL}"
    """
    labels = ["intro_entry", "app_slot_offset"]
    if version >= 209:
        labels.extend(("begin_battle", "opening_accept"))
    if version >= 210:
        labels.extend(("opening_rewards", "flip_reward"))
    if version >= 211:
        labels.extend(("copy_intro_plants", "plant_registry_offset"))
    if version == 212:
        labels.extend(("chooser_packets", "opening_background", "grass_offset"))
    if version >= 213:
        labels.extend(("chooser_packets", "grass_offset", "opening_dim", "save_reward_selection",
                       "restore_campaign_selection", "find_wave_properties"))
    if version >= 214:
        labels.extend(("opening_offer_gate", "mark_offer_generated", "check_offer_capacity",
                       "preserve_gameplay_hud", "stats_background", "reward_title"))
    if version >= 215:
        labels.extend(("map_progress", "map_offer_count", "check_floor_limit", "attach_stats_content",
                       "map_reward_confirm", "skip_paid_offer", "show_battle_powerups"))
    if version >= 216:
        labels.extend(("select_event_milestone", "checkpoint_level_name", "clamp_wave_meter_progress"))
    if version >= 217:
        labels.append("check_danger_room_drop")
    if version >= 218:
        labels.extend(("show_event_victory_score", "check_reward_fade_flag",
                       "start_chooser_preview", "play_preview_groan"))
    if version >= 219:
        labels.extend(("check_victory_milestone", "check_sun_purchase_input", "check_sun_purchase_draw"))
    if version >= 220:
        labels.extend(("open_activity_chooser", "read_owned_checkpoint", "profile_manager_offset",
                       "festival_keys"))
    if version >= 222:
        labels.extend(("reward_board", "stage_floor_continuation"))
    # Keystone resolves these offsets from the same instruction stream. The
    # table is packaging metadata and is removed before writing the payload.
    table = "\n".join(f".word {label} - payload_start" for label in labels)
    source = (key_code + intro_code + battle_code + reward_code + roster_code + old_chooser_code +
              run_code + old_dim_code + next_floor_code + map_room_code + win_reward_code +
              legacy_drop_code + legacy_transition_code + legacy_continue_code + sun_purchase_code +
              activity_transition_code + wave_code + progress_isolation_code + predicate + table)
    payload = bytearray(asm.asm(source, start)[0])
    table_start = len(payload) - 4 * len(labels)
    entries = dict(zip(labels, struct.unpack_from("<" + "I" * len(labels), payload, table_start)))
    del payload[table_start:]
    anchor = entries["app_slot_offset"]
    struct.pack_into("<i", payload, anchor, APP_SLOT - start - anchor)
    if version >= 220:
        anchor = entries["profile_manager_offset"]
        struct.pack_into("<i", payload, anchor, PROFILE_MANAGER_SLOT - start - anchor)
        anchor = entries["festival_keys"]
        for key_index, (name, addr) in enumerate(zip(FESTIVAL_ROOMS, FESTIVAL_KEYS, strict=True)):
            key = name.replace("_dangerroom", "").encode() + bytes(1)
            offset = file_offset(elf, addr, len(key))
            if engine[offset:offset + len(key)] != key:
                raise ValueError("Unexpected native Festival progress key")
            struct.pack_into("<i", payload, anchor + key_index * 4, addr - start - anchor)
    if version >= 211:
        anchor = entries["plant_registry_offset"]
        struct.pack_into("<i", payload, anchor, PLANT_REGISTRY - start - anchor)
    if version >= 212:
        anchor = entries["grass_offset"]
        struct.pack_into("<i", payload, anchor, DANGER_ROOM_GRASS - start - anchor)
    physical = rx["p_offset"] + used
    end = physical + len(payload)
    if end > rw["p_offset"] or start + len(payload) > rw["p_vaddr"] or any(engine[physical:end]):
        raise ValueError("Insufficient free executable space in the guest")

    updated = bytearray(engine)
    if version >= 222:
        result_index, result_rx = loads[-2]
        next_rw = loads[-1][1]
        if (result_index == index or result_rx["p_flags"] != 5 or next_rw["p_flags"] != 6 or
                result_rx["p_filesz"] != result_rx["p_memsz"]):
            raise ValueError("Missing the second executable padding for floor transitions")
        result_used = (result_rx["p_filesz"] + 15) & ~15
        result_entry = result_rx["p_vaddr"] + result_used
        result_offset = result_rx["p_offset"] + result_used
        attach_original_then_continue = f"""
            push {{r4,lr}}
            mov r4, r0
            bl #{SHOW_RESULT_WIDGET}
            bl #{start + entries["reward_board"]}
            cmp r0, #0
            popeq {{r4,pc}}
            add r4, r4, #0x1300
            ldr r0, [r4, #0x98]
            mov r1, #1
            pop {{r4,lr}}
            cmp r0, #0
            bne #{start + entries["stage_floor_continuation"]}
            bx lr
        """
        # Classify the victorious board before mounting anything. For the restored
        # modes complete the native reward state and its cleanup without the
        # score event's listeners. The widget's next update still performs the
        # existing deferred acknowledgement after reward cleanup.
        attach_without_score_event = f"""
            push {{r0-r4,lr}}
            bl #{start + entries["reward_board"]}
            cmp r0, #0
            pop {{r0-r4,lr}}
            beq #{SHOW_RESULT_WIDGET}
            push {{r4,lr}}
            mov r4, r0
            bl #{SHOW_RESULT_WIDGET}
            add r4, r4, #0x1300
            ldr r0, [r4, #0x98]
            cmp r0, #0
            popeq {{r4,pc}}
            mov r1, #1
            bl #{start + entries["stage_floor_continuation"]}
            pop {{r4,lr}}
            b #{FINISH_WIN_REWARD}
        """
        result_code = bytes(asm.asm(attach_without_score_event if version >= 223
                                    else attach_original_then_continue, result_entry)[0])
        statement_entries = {}
        for site, continuation in FLOOR_SUMMARY_STATEMENT_SITES if version >= 224 else ():
            if version == 224 and statement_entries:
                statement_entries[site] = statement_entry
                continue
            statement_entry = result_entry + len(result_code)
            statement_entries[site] = statement_entry
            # The stock path hides the statistics and card widget after it
            # mounts the statement. Resume after both operations together.
            on_skip = f"bne #{continuation}" if version >= 225 else "bxne lr"
            statement_code = f"""
                cmp r1, #1
                bne #{SHOW_BATTLE_STATEMENT}
                push {{r0-r4,lr}}
                bl #{start + entries["reward_board"]}
                cmp r0, #0
                pop {{r0-r4,lr}}
                {on_skip}
                b #{SHOW_BATTLE_STATEMENT}
            """
            result_code += bytes(asm.asm(statement_code, statement_entry)[0])
        result_end = result_offset + len(result_code)
        if (result_end > next_rw["p_offset"] or result_entry + len(result_code) > next_rw["p_vaddr"] or
                any(engine[result_offset:result_end])):
            raise ValueError("Insufficient padding for the floor result hook")
        updated[result_offset:result_end] = result_code
        header = elf["e_phoff"] + result_index * elf["e_phentsize"] + 16
        result_size = result_used + len(result_code)
        struct.pack_into("<II", updated, header, result_size, result_size)
    patches = [
        (CURRENT_PROGRESS, struct.pack("<I", 0xe92d4830), start, False),
        (INTRO_CONFIRM, branch(INTRO_CONFIRM, CONFIRM, True), start + entries["intro_entry"], True),
    ]
    if version >= 209:
        patches.extend((
            (BEGIN_BATTLE, struct.pack("<I", 0xe92d48f0), start + entries["begin_battle"], False),
            (OPENING_ACCEPT, struct.pack("<I", 0xe12fff33), start + entries["opening_accept"], True),
        ))
    if version >= 213:
        for site, original, name in (
            (SAVE_REWARD_SELECTION, SAVE_PROGRESS, "save_reward_selection"),
            (RESTORE_CAMPAIGN_SELECTION, HAS_PROFILE_FLAG, "restore_campaign_selection"),
            (OPENING_DIM, FILL_RECT, "opening_dim"),
            (FIND_DANGER_PROPERTIES, INTERN_WIDE_NAME, "find_wave_properties"),
        ):
            patches.append((site, branch(site, original, True), start + entries[name], True))
        patches.append((BUILD_CHOOSER_PACKETS, struct.pack("<I", 0xe92d4ff0),
                        start + entries["chooser_packets"], False))
    if version >= 214:
        patches.append((DRAW_OPENING_BACKGROUND, branch(DRAW_OPENING_BACKGROUND, DRAW_TILED_IMAGE, True),
                        start + entries["stats_background"], True))
        patches.append((BUILD_REWARD_TITLE, branch(BUILD_REWARD_TITLE, TRANSLATE_WIDE_TEXT, True),
                        start + entries["reward_title"], True))
        for site, word, name in (
            (OPENING_OFFER_GATE, 0x0a0000e6, "opening_offer_gate"),
            (MARK_OFFER_GENERATED, 0xe58930f8, "mark_offer_generated"),
            (CHECK_OFFER_CAPACITY, 0xe0832006, "check_offer_capacity"),
            (HIDE_GAMEPLAY_HUD, 0xe5942084, "preserve_gameplay_hud"),
        ):
            patches.append((site, struct.pack("<I", word), start + entries[name], False))
    if version >= 215:
        patches.append((CHECK_FESTIVAL_FLOOR_LIMIT, struct.pack("<I", 0xe1530001),
                        start + entries["check_floor_limit"], False))
        for sites, original, target in (
            (MAP_PROGRESS_CALLS, FESTIVAL_PROGRESS, "map_progress"),
            (REWARD_OFFER_COUNT_CALLS, REWARD_OFFER_COUNT, "map_offer_count"),
            ((ATTACH_STATS_CONTENT,), DIALOG_ADD_CHILD, "attach_stats_content"),
            ((BUILD_REWARD_CONFIRM,), TRANSLATE_WIDE_TEXT, "map_reward_confirm"),
            ((CHECK_PAID_REWARD,), HAS_PAID_REWARD, "skip_paid_offer"),
            ((SHOW_BATTLE_POWERUPS,), SHOW_POWERUP_HOLDER, "show_battle_powerups"),
        ):
            patches.extend((site, branch(site, original, True), start + entries[target], True)
                           for site in sites)
    if version >= 216:
        patches.extend((
            (LOAD_WIN_REWARD_PROGRESS, branch(LOAD_WIN_REWARD_PROGRESS, FESTIVAL_PROGRESS, True),
             start + entries["map_progress"], True),
            (SELECT_EVENT_MILESTONE_REWARD, struct.pack("<I", 0x0a000464),
             start + entries["select_event_milestone"], False),
            (BUILD_CHECKPOINT_LEVEL_NAME, struct.pack("<I", 0xfa48a4c1),
             start + entries["checkpoint_level_name"], True),
            (STORE_WAVE_METER_PROGRESS, struct.pack("<I", 0xe58090f0),
             start + entries["clamp_wave_meter_progress"], False),
        ))
    if version >= 217:
        patches.append((CHECK_DANGER_ROOM_DROP, struct.pack("<I", 0x0a000190),
                        start + entries["check_danger_room_drop"], False))
    if version >= 218:
        patches.extend((
            (SHOW_EVENT_VICTORY_SCORE, struct.pack("<I", 0xe92d4ff0),
             start + entries["show_event_victory_score"], False),
            (CHECK_REWARD_FADE_FLAG, branch(CHECK_REWARD_FADE_FLAG, HAS_PROFILE_FLAG, True),
             start + entries["check_reward_fade_flag"], True),
            (START_CHOOSER_PREVIEW, struct.pack("<I", 0xe92d4ff0),
             start + entries["start_chooser_preview"], False),
            (PLAY_PREVIEW_GROAN, branch(PLAY_PREVIEW_GROAN, POST_AUDIO_EVENT, True),
             start + entries["play_preview_groan"], True),
        ))
    if version >= 219:
        for site, original, name in (
            (CHECK_VICTORY_MILESTONE, 0x1a0000c3, "check_victory_milestone"),
            (CHECK_SUN_PURCHASE_INPUT, 0x0a000006, "check_sun_purchase_input"),
            (CHECK_SUN_PURCHASE_DRAW, 0x1affff92, "check_sun_purchase_draw"),
        ):
            patches.append((site, struct.pack("<I", original), start + entries[name], False))
    if version >= 220:
        patches.append((OPEN_SEED_CHOOSER, struct.pack("<I", 0xe92d4830),
                        start + entries["open_activity_chooser"], False))
        patches.extend((site, branch(site, CHECKPOINT_HEADER, True),
                        start + entries["read_owned_checkpoint"], True)
                       for site in CHECKPOINT_HEADER_CALLS)
    if version >= 222:
        patches.append((ATTACH_WIN_RESULT, branch(ATTACH_WIN_RESULT, SHOW_RESULT_WIDGET, True),
                        result_entry, True))
    if version >= 224:
        patches.extend((site, branch(site, SHOW_BATTLE_STATEMENT, True), target, True)
                       for site, target in statement_entries.items())
    if version >= 210:
        patches.extend((
            (OPENING_REWARDS, branch(OPENING_REWARDS, GENERATE_REWARDS, True), start + entries["opening_rewards"], True),
            (FLIP_REWARD, struct.pack("<I", 0xe92d4ff0), start + entries["flip_reward"], False),
        ))
    if version >= 211:
        patches.append((COPY_INTRO_PLANTS, branch(COPY_INTRO_PLANTS, COPY_PLANT_IDS, True),
                        start + entries["copy_intro_plants"], True))
    if version == 212:
        patches.extend((
            (BUILD_CHOOSER_PACKETS, struct.pack("<I", 0xe92d4ff0), start + entries["chooser_packets"], False),
            (DRAW_OPENING_BACKGROUND, branch(DRAW_OPENING_BACKGROUND, DRAW_TILED_IMAGE, True),
             start + entries["opening_background"], True),
        ))
    for site, original, target, link in patches:
        offset = file_offset(elf, site, 4)
        if engine[offset:offset + 4] != original:
            raise ValueError(f"Unexpected instruction at {site:#x}")
        updated[offset:offset + 4] = branch(site, target, link)
    if version >= 220:
        offset = file_offset(elf, CHECKPOINT_SELECT_PROFILE, 4)
        if engine[offset:offset + 4] != branch(CHECKPOINT_SELECT_PROFILE, 0x7aa9f4, True):
            raise ValueError("Unexpected checkpoint profile selector")
        struct.pack_into("<I", updated, offset, 0xe1a00000)
    if version >= 221:
        # Both branches share the native internal-save flag. Carry the explicit
        # entry context through the preliminary check and the actual resume.
        for site in ACTIVITY_CHECKPOINT_CALL_FLAGS:
            offset = file_offset(elf, site, 4)
            if struct.unpack_from("<I", engine, offset)[0] != 0xe3a01001:
                raise ValueError(f"Unexpected activity checkpoint argument at {site:#x}")
            struct.pack_into("<I", updated, offset, 0xe3a01000 | ACTIVITY_CHECKPOINT_CONTEXT)
    updated[physical:end] = payload
    header = elf["e_phoff"] + index * elf["e_phentsize"] + 16
    struct.pack_into("<II", updated, header, used + len(payload), used + len(payload))
    return bytes(updated)


def build(base, output, sdk, jdk, signing, version, iris_data):
    output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(jdk / "bin") + os.pathsep + os.environ["PATH"]
    reference = None
    resources = None
    for abi, member in (("ARM32", "lib/armeabi/libSrc.so"), ("ARM64", "assets/guest_libs/libSrc_a32.so")):
        source = base / f"PvZ2-Unline-Aster-A206-{abi}.apk"
        with ZipFile(source) as apk:
            engine = apk.read(member)
            manifest = manifest_version(apk.read("AndroidManifest.xml"), version, 206, prefix="A")
            if version >= 213:
                dynamic = apk.read(ASSET)
                dex = apk.read(BOOTSTRAP)
        if reference is None:
            reference = engine
            updated = patch(engine, version)
        elif engine != reference:
            raise ValueError("ARM64 guest engine differs from ARM32")
        final = output / f"PvZ2-Unline-Aster-A{version}-{abi}.apk"
        changes = {member: updated, "AndroidManifest.xml": manifest}
        if version >= 213:
            dynamic_hash = sha256(dynamic).hexdigest()
            if resources is None:
                resources = patch_egypt_waves(dynamic, iris_data, EGYPT_WAVE_PROPERTIES,
                                             moneybag=version >= 216, activity_music=version >= 218,
                                             activity_starter=220 <= version < 222,
                                             activity_last_stand=version >= 222,
                                             activity_welcome=version >= 227)
                plan = create_plan(resources, output)
                source_hash = dynamic_hash
            elif dynamic_hash != source_hash:
                raise ValueError("ARM64 resources differ from ARM32")
            replacements = {dynamic_hash: sha256(resources).hexdigest()}
            if len(dynamic) != len(resources):
                replacements[hex(len(dynamic))] = hex(len(resources))
            dex = rebuild_bootstrap(dex, output / f"bootstrap-{abi}", replacements,
                                    ROOT.parent / "tools/apktool.jar")
            changes.update({ASSET: resources, PLAN: plan, BOOTSTRAP: dex})
        pack_apk(source, changes, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "jdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--version", type=int, choices=range(207, 228), default=227)
    parser.add_argument("--iris-data", type=Path,
                        default=ROOT / "work/feedback/A203/legacy-endless-level-data.json")
    build(**vars(parser.parse_args()))
