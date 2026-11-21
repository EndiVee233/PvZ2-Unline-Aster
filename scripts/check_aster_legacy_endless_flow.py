"""Exercise the patched ARM entry points with a synthetic board and modal."""
import argparse
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R9

from build_aster_legacy_endless_flow import (
    APPEND_PLANT_ID, APPEND_PLANT_NAME, APP_SLOT, ASSIGN_PLANT_NAMES, BEGIN_BATTLE,
    BUILD_CHOOSER_PACKETS, BUILD_RUN_PACKETS,
    BUILD_OPENING_PANEL, BUILD_REWARD_PANEL, CONFIRM, COPY_INTRO_PLANTS, COPY_PLANT_IDS,
    CURRENT_PROGRESS, DANGER_ROOM_GRASS, DANGER_ROOM_INTRO_TYPE, DESTROY_PLANT_NAMES,
    DRAW_OPENING_BACKGROUND, DRAW_TILED_IMAGE, EGYPT_LEVEL, FIND_LEVEL_MODULE, FLIP_REWARD,
    GENERATE_REWARDS, INTRO_CONFIRM, NAME_FOR_PLANT_ID, OPENING_ACCEPT, OPENING_REWARDS,
    EGYPT_WAVE_PROPERTIES, FILL_RECT, FIND_DANGER_PROPERTIES, HAS_PROFILE_FLAG, INTERN_WIDE_NAME,
    OPEN_SEED_CHOOSER, OPENING_DIM, PLANT_REGISTRY, REGISTER_PLANT_ID, RELEASE_STRING,
    RESOLVE_UI_IMAGE, RESTORE_CAMPAIGN_SELECTION, SAVE_PROGRESS, SAVE_REWARD_SELECTION,
    CHECK_OFFER_CAPACITY, HIDE_GAMEPLAY_HUD, MARK_OFFER_GENERATED, OPENING_OFFER_GATE,
    BUILD_REWARD_TITLE, CONTINUATION_REWARD_TITLE, SEED_BANK_MODULE, TRANSLATE_WIDE_TEXT, patch,
    ATTACH_STATS_CONTENT, BUILD_REWARD_CONFIRM, CHECK_FESTIVAL_FLOOR_LIMIT, CHECK_PAID_REWARD,
    DIALOG_ADD_CHILD, FESTIVAL_PROGRESS, HAS_PAID_REWARD, MAP_PROGRESS_CALLS,
    REWARD_OFFER_COUNT, REWARD_OFFER_COUNT_CALLS,
    ACTIVITY_ENDLESS_LEVEL, ADD_BOARD_POWERUP, SHOW_BATTLE_POWERUPS, SHOW_POWERUP_HOLDER,
    BUILD_CHECKPOINT_LEVEL_NAME, LOAD_WIN_REWARD_PROGRESS, SELECT_EVENT_MILESTONE_REWARD,
    CHECK_DANGER_ROOM_DROP, CHECK_OTHER_REWARD_EXCLUSIONS, SET_WIDGET_VISIBLE,
    STORE_WAVE_METER_PROGRESS, SHOW_EVENT_VICTORY_SCORE, CHECK_REWARD_FADE_FLAG,
    START_CHOOSER_PREVIEW, PLAY_PREVIEW_GROAN, POST_AUDIO_EVENT,
    CHECK_VICTORY_MILESTONE, CONTINUE_AFTER_VICTORY, CHECK_SUN_PURCHASE_INPUT,
    CHECK_SUN_PURCHASE_DRAW, CHECKPOINT_HEADER, CHECKPOINT_HEADER_CALLS, CHECKPOINT_SELECT_PROFILE,
    ACTIVITY_CHECKPOINT_CALL_FLAGS, ACTIVITY_CHECKPOINT_CONTEXT, FESTIVAL_ROOMS, PROFILE_MANAGER_SLOT,
    ATTACH_WIN_RESULT, SHOW_RESULT_WIDGET, FINISH_WIN_REWARD, ACTIVITY_SUN_PLANTS,
    FLOOR_SUMMARY_STATEMENT_SITES, SHOW_BATTLE_STATEMENT,
)

NATIVE_RESULT_UPDATE = 0x1a2bf74


def run_cases(engine, base, version):
    elf = ELFFile(BytesIO(engine))
    emu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    emu.mem_map(base, 0x2000000)
    for segment in elf.iter_segments():
        if segment["p_type"] == "PT_LOAD":
            emu.mem_write(base + segment["p_vaddr"], segment.data())

    app_pointer, app, board, modules, intro, widget, type_info, level = (
        range(base + 0x2000000, base + 0x2008000, 0x1000)
    )
    stack = base + 0x2009000
    stop = stack + 4
    emu.mem_map(app_pointer, 0xa000)
    calls = []
    native_accept_state = 3
    cases = 0
    active_site = None
    statement_continuations = dict(FLOOR_SUMMARY_STATEMENT_SITES)
    have_seed_bank = True
    plant_ids = [12, 23, -1, 44]
    seed_bank = level + 0x380
    copied_ids = level + 0x420
    plant_data = level + 0x480
    plant_name_list = level + 0x580
    board_vtable = level + 0x600
    seed_properties = level + 0x700
    stock_whitelist = (level + 0x750, level + 0x754, level + 0x758)
    run_whitelist = (plant_name_list, plant_name_list + 12, plant_name_list + 16)
    move_board = 0x225ee0  # Intercepted synthetic vtable slot.
    grass_image = level + 0x790
    preload_grass = grass_image
    run_ids = level + 0x800
    native_weak_target = widget
    reward_ids = level + 0x850
    paint_rectangle = level + 0xc00
    trace_flip_coordinates = False
    profile_has_flag = True
    profile_manager = app_pointer + 0x200
    checkpoint = stack + 0x200
    checkpoint_room = stack + 0x400
    checkpoint_found = True
    expected_native_checkpoint_flag = 0
    detach_board_on_result = False

    def put(address, value):
        emu.mem_write(address, struct.pack("<I", value & 0xffffffff))

    def get(address):
        return struct.unpack("<I", emu.mem_read(address, 4))[0]

    def set_vector(address, values):
        emu.mem_write(address, struct.pack("<III", *values))

    def get_vector(address):
        return struct.unpack("<III", emu.mem_read(address, 12))

    def mock_return(value=0):
        emu.reg_write(UC_ARM_REG_R0, value)
        emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))

    def hook(_, address, _size, _data):
        relative = address - base
        arg = emu.reg_read(UC_ARM_REG_R0)
        if relative == BEGIN_BATTLE + 4:
            assert arg == board
            calls.append("battle")
            emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 24)
            mock_return()
        elif relative == DANGER_ROOM_INTRO_TYPE:
            mock_return(type_info)
        elif relative == FIND_LEVEL_MODULE:
            assert arg == modules and emu.reg_read(UC_ARM_REG_R1) == type_info
            mock_return(intro if has_intro else 0)
        elif relative == 0x2bc544:
            assert arg == intro
            calls.append("accept")
            put(board + 0xc0, native_accept_state)
            mock_return()
        elif relative == OPEN_SEED_CHOOSER + (4 if version >= 220 else 0):
            assert arg == intro and emu.reg_read(UC_ARM_REG_R1) == 0
            assert emu.mem_read(modules + 0x40, 1) == b"\x01"
            calls.append("chooser")
            if version >= 220:
                emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 16)
            mock_return()
        elif relative == CHECKPOINT_HEADER and version >= 220:
            assert emu.reg_read(UC_ARM_REG_R1) == checkpoint
            assert emu.reg_read(UC_ARM_REG_R2) == expected_native_checkpoint_flag
            calls.append("read checkpoint header")
            mock_return(int(checkpoint_found))
        elif relative == move_board:
            assert arg == board and emu.reg_read(UC_ARM_REG_R1) == 557
            assert emu.reg_read(UC_ARM_REG_R2) == 0
            calls.append("preview origin")
            mock_return()
        elif relative == BUILD_CHOOSER_PACKETS + 4:
            assert arg == widget
            active_whitelist = get_vector(seed_properties + 0x30)
            assert active_whitelist in (stock_whitelist, run_whitelist)
            calls.append("filtered chooser" if active_whitelist == run_whitelist else "stock chooser")
            emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 36)
            mock_return()
        elif relative == 0x11d74b4:
            mock_return(level + 0x880)
        elif relative == 0x1da034:
            mock_return(native_weak_target)
        elif relative == REGISTER_PLANT_ID:
            assert arg == base + PLANT_REGISTRY
            name_pointer = get(emu.reg_read(UC_ARM_REG_R1))
            mock_return({plant_data + 24: 12, plant_data + 40: 23,
                         plant_data + 56: 44, plant_data + 72: 71}.get(name_pointer, -1))
        elif relative == APPEND_PLANT_ID:
            first, last, _ = get_vector(arg)
            if first == 0:
                first = last = run_ids
            put(last, get(emu.reg_read(UC_ARM_REG_R1)))
            set_vector(arg, (first, last + 4, first + 24))
            mock_return()
        elif relative == BUILD_RUN_PACKETS:
            assert arg == widget
            first, last, _ = get_vector(emu.reg_read(UC_ARM_REG_R1))
            calls.append(("run chooser", [get(p) for p in range(first, last, 4)]))
            mock_return()
        elif relative == 0x14c2e94:
            assert arg == run_ids
            # BLX immediate enters the Thumb-state stub.
            emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))
        elif relative == SAVE_PROGRESS:
            assert arg == widget
            first, last, _ = get_vector(widget + 0xe8)
            calls.append(("save", [get(p) for p in range(first, last, 4)]))
            mock_return()
        elif relative == HAS_PROFILE_FLAG:
            calls.append("profile selection")
            mock_return(int(profile_has_flag))
        elif relative in (INTERN_WIDE_NAME, TRANSLATE_WIDE_TEXT):
            pointer = emu.reg_read(UC_ARM_REG_R1)
            chars = []
            while value := get(pointer):
                chars.append(chr(value))
                pointer += 4
            calls.append("".join(chars))
            mock_return()
        elif relative in (0x112f868, 0x1166c30):
            mock_return()
        elif relative == FILL_RECT:
            assert get(stack) == 720
            calls.append("fill")
            mock_return()
        elif relative in (0x2d5030, 0x2d5024, 0x2d53c0, 0x2d4b20, 0x2cef20, 0x2c2b30, 0x2c2a44,
                          CHECK_FESTIVAL_FLOOR_LIMIT + 4, SELECT_EVENT_MILESTONE_REWARD + 4,
                          STORE_WAVE_METER_PROGRESS + 4, CHECK_OTHER_REWARD_EXCLUSIONS,
                          CHECK_DANGER_ROOM_DROP + 4, CHECK_VICTORY_MILESTONE + 4,
                          CONTINUE_AFTER_VICTORY, CHECK_SUN_PURCHASE_INPUT + 4,
                          CHECK_SUN_PURCHASE_DRAW + 4, 0x93dc60, 0x93dfc0, 0xcd7d08):
            calls.append(relative)
            emu.reg_write(UC_ARM_REG_PC, stop)
        elif relative == SHOW_EVENT_VICTORY_SCORE + 4:
            assert arg == widget
            calls.append("event victory score")
            emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 36)
            mock_return()
        elif relative == SHOW_RESULT_WIDGET and version >= 222:
            assert arg == app
            put(app + 0x1398, widget)
            if detach_board_on_result:
                put(app + 0x6bc, 0)
            calls.append("attach win result")
            mock_return()
        elif relative == FINISH_WIN_REWARD and version >= 223:
            calls.append("finish reward without score event")
            assert get(widget + 0x100) == get(widget + 0xf4) == 1
            emu.reg_write(UC_ARM_REG_PC, base + ATTACH_WIN_RESULT + 4)
        elif relative == SHOW_BATTLE_STATEMENT and version >= 224:
            assert arg == app
            calls.append(("open battle statement", emu.reg_read(UC_ARM_REG_R1)))
            mock_return()
        elif version >= 225 and relative == statement_continuations.get(active_site):
            calls.append(("continue with visible statistics", relative))
            emu.reg_write(UC_ARM_REG_PC, base + active_site + 4)
        elif relative == START_CHOOSER_PREVIEW + 4:
            assert arg == intro
            calls.append("start preview")
            emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 36)
            mock_return()
        elif relative == POST_AUDIO_EVENT:
            calls.append("preview groan")
            mock_return()
        elif relative == 0x13152bc:
            mock_return()
        elif relative == 0xcd93b0:
            assert arg == widget and emu.reg_read(UC_ARM_REG_R1) == 0
            calls.append(("acknowledge victory", get(widget + 0xf4)))
            mock_return()
        elif relative == 0x2bfc10:
            assert arg == widget
            calls.append("prepare wave configuration")
            mock_return()
        elif relative == RESOLVE_UI_IMAGE:
            assert arg == base + DANGER_ROOM_GRASS
            calls.append("resolve grass")
            mock_return(preload_grass)
        elif relative == DRAW_TILED_IMAGE:
            assert arg == widget
            if version >= 213:
                rectangle = emu.reg_read(UC_ARM_REG_R1)
                assert bytes(emu.mem_read(rectangle, 16)) == struct.pack("<4i", 0, 0, 1280, 720)
            calls.append(("draw", emu.reg_read(UC_ARM_REG_R2)))
            mock_return()
        elif relative == COPY_PLANT_IDS:
            calls.append("copy ids")
            for index, plant_id in enumerate(plant_ids):
                put(copied_ids + index * 4, plant_id)
            put(arg, copied_ids)
            put(arg + 4, copied_ids + len(plant_ids) * 4)
            put(arg + 8, copied_ids + 0x40)
            mock_return(arg)
        elif relative == SEED_BANK_MODULE:
            assert arg == modules
            mock_return(seed_bank if have_seed_bank else 0)
        elif relative == NAME_FOR_PLANT_ID:
            assert emu.reg_read(UC_ARM_REG_R1) == base + PLANT_REGISTRY
            plant_id = emu.reg_read(UC_ARM_REG_R2)
            name = {12: b"sunflower", 23: b"peashooter", 44: b"reward_alias",
                    2: b"peashooter", 6: b"cabbagepult"}.get(plant_id, b"")
            put(plant_data, len(name))
            emu.mem_write(plant_data + 12, name + b"\0")
            put(arg, plant_data + 12)
            mock_return(arg)
        elif relative == APPEND_PLANT_NAME:
            string = get(emu.reg_read(UC_ARM_REG_R1))
            name = bytes(emu.mem_read(string, get(string - 12))).decode()
            calls.append(name)
            if not get(arg):
                put(arg, plant_name_list)
                put(arg + 4, plant_name_list)
            put(arg + 4, get(arg + 4) + 4)
            mock_return()
        elif relative == ASSIGN_PLANT_NAMES:
            assert arg == seed_bank + 0x18
            calls.append("assign roster")
            mock_return(arg)
        elif relative in (RELEASE_STRING, DESTROY_PLANT_NAMES):
            mock_return()
        elif relative in (BUILD_OPENING_PANEL, CONFIRM):
            assert arg == widget
            calls.append("panel" if relative == BUILD_OPENING_PANEL else "confirm")
            mock_return()
        elif relative in (GENERATE_REWARDS, BUILD_REWARD_PANEL):
            assert arg == widget
            calls.append("generate rewards" if relative == GENERATE_REWARDS else "reward panel")
            if relative == BUILD_REWARD_PANEL and version >= 217:
                put(widget + 0x194, level + 0x200)
            mock_return()
        elif relative == SET_WIDGET_VISIBLE:
            assert arg == widget and get(widget + 0x194) != 0
            assert emu.reg_read(UC_ARM_REG_R1) == 1
            emu.mem_write(widget + 0x4c, b"\x01")
            calls.append("show reward panel")
            mock_return()
        elif relative == FLIP_REWARD + 4:
            assert arg == widget
            calls.append((emu.reg_read(UC_ARM_REG_R1), emu.reg_read(UC_ARM_REG_R2))
                         if trace_flip_coordinates else "flip")
            emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 36)
            mock_return()
        elif relative == FESTIVAL_PROGRESS:
            calls.append("festival key")
            mock_return()
        elif relative == REWARD_OFFER_COUNT:
            calls.append("stock offer count")
            mock_return(6)
        elif relative == HAS_PAID_REWARD:
            calls.append("stock paid offer")
            mock_return()
        elif relative == DIALOG_ADD_CHILD:
            calls.append("attach content")
            mock_return()
        elif relative == ADD_BOARD_POWERUP:
            assert arg == widget
            assert get(emu.reg_read(UC_ARM_REG_R1)) == plant_data
            assert emu.reg_read(UC_ARM_REG_R2) == (0 if version >= 216 else 1)
            calls.append("register Tactical Cucumber")
            mock_return()
        elif relative == SHOW_POWERUP_HOLDER:
            calls.append("show powerups")
            mock_return()
        elif relative == 0x14ed0e0:
            name = bytes(emu.mem_read(emu.reg_read(UC_ARM_REG_R1), 40)).split(b"\0", 1)[0]
            if name == b"poweruptacticalcuke":
                put(arg, plant_data)
            elif name == b"sunflower" and version >= 220:
                put(arg, plant_data + 24)
            elif name in (EGYPT_LEVEL.encode(), ACTIVITY_ENDLESS_LEVEL.encode()):
                calls.append(name.decode())
            else:
                assert name == b"egypt" or version >= 220 and name.decode() in {
                    room.replace("_dangerroom", "") for room in FESTIVAL_ROOMS}
                calls.append(name.decode() + " key")
            mock_return()
        elif relative == CURRENT_PROGRESS + 4:
            calls.append("original key")
            emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 16)
            mock_return()

    emu.hook_add(UC_HOOK_CODE, hook)
    put(base + APP_SLOT, app_pointer)
    put(app_pointer, app)
    put(app + 0x6bc, board)
    put(board + 0xc4, level)
    put(board + 0x938, modules)
    put(board, board_vtable)
    put(board + 0x994, -557)
    put(board_vtable + 0x40, base + move_board)
    set_vector(seed_properties + 0x30, stock_whitelist)
    set_vector(seed_bank + 0x18, run_whitelist)
    for index, address in enumerate((plant_data + 24, plant_data + 40, plant_data + 56)):
        put(plant_name_list + index * 4, address)
    put(stack, 720)
    emu.mem_write(paint_rectangle, struct.pack("<4i", 0, 0, 1280, 720))
    stock_wave_name = level + 0x8c0
    emu.mem_write(stock_wave_name, "DefaultDangerRoomProps\0".encode("utf-32-le"))

    def invoke(addr, arg, expected, r2=0, *, r1=None, meter_bits=None, equal=True):
        nonlocal cases, active_site
        active_site = addr
        calls.clear()
        emu.reg_write(UC_ARM_REG_R0, arg)
        emu.reg_write(UC_ARM_REG_R2, r2)
        emu.reg_write(UC_ARM_REG_R1, paint_rectangle if version >= 214 and addr == DRAW_OPENING_BACKGROUND
                      else stock_wave_name)
        if r1 is not None:
            emu.reg_write(UC_ARM_REG_R1, r1)
        emu.reg_write(UC_ARM_REG_R3, 1280 if addr == OPENING_DIM else base + 0x2bc544)
        if addr == CHECK_FESTIVAL_FLOOR_LIMIT:
            emu.reg_write(UC_ARM_REG_R1, 1)
            emu.reg_write(UC_ARM_REG_R3, 2)
        emu.reg_write(UC_ARM_REG_LR, stop)
        emu.reg_write(UC_ARM_REG_SP, stack)
        for register in (UC_ARM_REG_R4, UC_ARM_REG_R8, UC_ARM_REG_R9):
            emu.reg_write(register, widget)
        if meter_bits is not None:
            emu.reg_write(UC_ARM_REG_R9, meter_bits)
        if addr in (SELECT_EVENT_MILESTONE_REWARD, CHECK_DANGER_ROOM_DROP, CHECK_VICTORY_MILESTONE,
                    CHECK_SUN_PURCHASE_INPUT, CHECK_SUN_PURCHASE_DRAW):
            cpsr = emu.reg_read(UC_ARM_REG_CPSR) & ~(1 << 30)
            emu.reg_write(UC_ARM_REG_CPSR, cpsr | ((1 << 30) if equal else 0))
        emu.reg_write(UC_ARM_REG_R5, 6)
        emu.reg_write(UC_ARM_REG_R6, widget if addr == BUILD_REWARD_TITLE else 7)
        if addr in (MARK_OFFER_GENERATED, CHECK_OFFER_CAPACITY):
            emu.reg_write(UC_ARM_REG_R3, 2)
        if addr == OPENING_OFFER_GATE:
            emu.reg_write(UC_ARM_REG_R3, r2)
        # Call sites return to the next instruction within their containing function.
        call_sites = (OPENING_ACCEPT, INTRO_CONFIRM, OPENING_REWARDS, COPY_INTRO_PLANTS,
                      DRAW_OPENING_BACKGROUND, OPENING_DIM, FIND_DANGER_PROPERTIES,
                      SAVE_REWARD_SELECTION, RESTORE_CAMPAIGN_SELECTION, BUILD_REWARD_TITLE,
                      *MAP_PROGRESS_CALLS, *REWARD_OFFER_COUNT_CALLS, ATTACH_STATS_CONTENT,
                      BUILD_REWARD_CONFIRM, CHECK_PAID_REWARD, SHOW_BATTLE_POWERUPS,
                      BUILD_CHECKPOINT_LEVEL_NAME, LOAD_WIN_REWARD_PROGRESS, CHECK_REWARD_FADE_FLAG,
                      PLAY_PREVIEW_GROAN, *CHECKPOINT_HEADER_CALLS, CHECKPOINT_SELECT_PROFILE,
                      *ACTIVITY_CHECKPOINT_CALL_FLAGS, ATTACH_WIN_RESULT,
                      *(site for site, _ in FLOOR_SUMMARY_STATEMENT_SITES))
        end = base + addr + 4 if addr in call_sites else stop
        emu.emu_start(base + addr, end, count=2500)
        assert emu.reg_read(UC_ARM_REG_PC) == end, (hex(addr), calls)
        assert emu.reg_read(UC_ARM_REG_SP) == stack
        assert calls == expected, (hex(addr), calls, expected)
        cases += 1

    emu.mem_write(level, EGYPT_LEVEL.encode() + b"\0")
    has_intro = True
    put(intro + 0x34, widget)
    invoke(CURRENT_PROGRESS, intro, ["egypt key"])
    invoke(INTRO_CONFIRM, widget, ["panel"])
    put(widget + 0x1b0, 1)
    invoke(INTRO_CONFIRM, widget, [])
    invoke(BEGIN_BATTLE, board, [])
    put(widget + 0xd4, 2)
    invoke(BEGIN_BATTLE, board, [])
    has_intro = False
    invoke(BEGIN_BATTLE, board, ["battle"])
    has_intro = True
    put(intro + 0x34, 0)
    card_refresh = [("run chooser", [12, 23, 44])] if version >= 213 else []
    invoke(OPENING_ACCEPT, intro, ["accept", "preview origin", *card_refresh, "chooser"])
    assert emu.mem_read(modules + 0x40, 1) == b"\x01"
    invoke(OPENING_ACCEPT, intro, ["accept"])
    put(board + 0x938, 0)
    invoke(BEGIN_BATTLE, board, ["battle"])
    invoke(OPENING_ACCEPT, intro, ["accept"])
    put(board + 0x938, modules)
    put(modules + 0x40, 1)
    invoke(OPENING_ACCEPT, intro, ["accept"])
    put(modules + 0x40, 0)
    for native_accept_state in (1, 4, 5):
        invoke(OPENING_ACCEPT, intro, ["accept"])
    invoke(OPENING_REWARDS, widget, ["generate rewards"])
    assert emu.mem_read(widget + 0x4c, 1) == b"\x00"
    invoke(FLIP_REWARD, widget, [])
    put(widget + 0x170, level + 0x100)
    put(widget + 0x174, level + 0x118)
    show_reward = ["show reward panel"] if version >= 217 else []
    invoke(OPENING_REWARDS, widget, ["generate rewards", "reward panel", *show_reward])
    put(widget + 0x194, level + 0x200)
    put(widget + 0xdc, 2)
    emu.mem_write(widget + 0x4c, b"\x00")
    invoke(OPENING_REWARDS, widget, ["generate rewards", *show_reward])
    assert emu.mem_read(widget + 0x4c, 1) == bytes([version >= 217])
    invoke(FLIP_REWARD, widget, ["flip"])
    invoke(COPY_INTRO_PLANTS, widget, ["copy ids", "sunflower", "peashooter", "reward_alias", "assign roster"])
    have_seed_bank = False
    invoke(COPY_INTRO_PLANTS, widget, ["copy ids"])
    have_seed_bank = True
    plant_ids = []
    invoke(COPY_INTRO_PLANTS, widget, ["copy ids"])
    plant_ids = [-1]
    invoke(COPY_INTRO_PLANTS, widget, ["copy ids"])
    put(widget + 0x174, seed_properties)
    invoke(BUILD_CHOOSER_PACKETS, widget, card_refresh or ["filtered chooser"])
    assert get_vector(seed_properties + 0x30) == stock_whitelist
    set_vector(seed_bank + 0x18, (0, 0, 0))
    invoke(BUILD_CHOOSER_PACKETS, widget, ["stock chooser"])
    set_vector(seed_bank + 0x18, run_whitelist)
    if version == 212:
        invoke(DRAW_OPENING_BACKGROUND, widget, ["resolve grass", ("draw", grass_image)])
        invoke(DRAW_OPENING_BACKGROUND, widget, [("draw", grass_image)], r2=grass_image)
        preload_grass = 0
        invoke(DRAW_OPENING_BACKGROUND, widget, ["resolve grass", ("draw", 0)])
    elif version == 213:
        invoke(OPENING_DIM, widget, ["resolve grass", ("draw", grass_image)])
        preload_grass = 0
        invoke(OPENING_DIM, widget, ["resolve grass", "fill"])
    else:
        put(widget + 0x1b0, 1)
        invoke(DRAW_OPENING_BACKGROUND, widget, ["resolve grass", ("draw", grass_image)])
        assert emu.mem_read(widget + 0x1d5, 1) == b"\x02"
        preload_grass = 0
        invoke(DRAW_OPENING_BACKGROUND, widget, ["resolve grass", ("draw", 0)])
        assert emu.mem_read(widget + 0x1d5, 1) == b"\x01"
        put(widget + 0x1b0, 0)
        invoke(DRAW_OPENING_BACKGROUND, widget, [("draw", grass_image)], r2=grass_image)
        invoke(OPENING_DIM, widget, [])
    if version >= 213:
        invoke(FIND_DANGER_PROPERTIES, widget, [EGYPT_WAVE_PROPERTIES])
        invoke(RESTORE_CAMPAIGN_SELECTION, widget, [])
        assert emu.reg_read(UC_ARM_REG_R0) == 0
        offers = level + 0x950
        set_vector(widget + 0x170, (offers, offers + 12, offers + 12))
        set_vector(widget + 0xe8, (reward_ids, reward_ids + 4, reward_ids + 24))
        put(reward_ids, 12)
        native_weak_target = level + 0xa40
        put(native_weak_target + 4, plant_data + 72)
        for i, (selected, locked) in enumerate(((0, 0), (1, 1), (1, 0))):
            offer = level + 0xb00 + i * 0x40
            put(offers + i * 4, offer)
            put(offer + 8, 1)
            emu.mem_write(offer + 0x30, bytes([selected, 0, locked]))
        invoke(SAVE_REWARD_SELECTION, widget, [("save", [12, 71])])
        invoke(SAVE_REWARD_SELECTION, widget, [("save", [12, 71])])
    if version >= 214:
        for floor in (1, 2, 12):
            put(widget + 0xdc, floor)
            put(widget + 0xf8, floor - 1)
            invoke(OPENING_OFFER_GATE, widget, [0x2d5030])
            assert emu.reg_read(UC_ARM_REG_R6) == 1
            invoke(MARK_OFFER_GENERATED, widget, [0x2d4b20])
            assert get(widget + 0xf8) == floor - 1
            invoke(SAVE_REWARD_SELECTION, widget, [("save", [12, 71])])
            assert get(widget + 0xf8) == floor
            invoke(OPENING_OFFER_GATE, widget, [0x2d53c0])
            invoke(CHECK_OFFER_CAPACITY, widget, [0x2cef20])
            first_activity_floor = floor == 1 and version == 214
            assert emu.reg_read(UC_ARM_REG_R5) == (6 if first_activity_floor else 1)
            assert emu.reg_read(UC_ARM_REG_R2) == (9 if first_activity_floor else 2)
            invoke(BUILD_REWARD_TITLE, widget,
                   ["DefaultDangerRoomProps" if first_activity_floor else CONTINUATION_REWARD_TITLE])
        invoke(HIDE_GAMEPLAY_HUD, widget, ["prepare wave configuration", 0x2c2b30])
        put(widget + 0x88, 1)
        invoke(HIDE_GAMEPLAY_HUD, widget, [0x2c2b30])
    if version >= 215:
        for addr in MAP_PROGRESS_CALLS:
            invoke(addr, intro, ["egypt key"])
        for addr in REWARD_OFFER_COUNT_CALLS:
            invoke(addr, widget, [])
            assert emu.reg_read(UC_ARM_REG_R0) == 4
        invoke(CHECK_PAID_REWARD, widget, [])
        assert emu.reg_read(UC_ARM_REG_R0) == 1
        invoke(CHECK_FESTIVAL_FLOOR_LIMIT, widget, [CHECK_FESTIVAL_FLOOR_LIMIT + 4])
        assert emu.reg_read(UC_ARM_REG_CPSR) & (1 << 30)
        put(widget + 0xcc, 0x100)
        put(widget + 0xd0, 0x3f800000)
        invoke(ATTACH_STATS_CONTENT, widget, ["attach content"])
        assert get(widget + 0xcc) == get(widget + 0xd0) == 0
        invoke(BUILD_REWARD_CONFIRM, widget, ["确定"])
        invoke(SHOW_BATTLE_POWERUPS, widget, ["register Tactical Cucumber", "show powerups"])
        invoke(SHOW_BATTLE_POWERUPS, 0, ["show powerups"])
        trace_flip_coordinates = True
        put(widget + 0x194, 1)
        put(widget + 0xb4, 0)
        put(widget + 0x1d0, 1)
        for i, x in enumerate((100, 300, 500)):
            offer = level + 0xb00 + i * 0x40
            for offset, value in ((0x1c, x), (0x20, 150), (0x24, 200), (0x28, 200)):
                put(offer + offset, value)
            emu.mem_write(offer + 0x30, bytes([i == 0, 0, i == 2]))
        invoke(FLIP_REWARD, widget, [(200, 250), (350, 250)], r1=350, r2=250)
        invoke(FLIP_REWARD, widget, [(150, 250)], r1=150, r2=250)
        invoke(FLIP_REWARD, widget, [(550, 250)], r1=550, r2=250)
        invoke(FLIP_REWARD, widget, [(350, 90)], r1=350, r2=90)
        trace_flip_coordinates = False
    if version >= 216:
        invoke(LOAD_WIN_REWARD_PROGRESS, intro, ["egypt key"])
        invoke(SELECT_EVENT_MILESTONE_REWARD, widget, [SELECT_EVENT_MILESTONE_REWARD + 4])
        invoke(SELECT_EVENT_MILESTONE_REWARD, widget, [SELECT_EVENT_MILESTONE_REWARD + 4], equal=False)
        activity_level = level + 0xd00
        emu.mem_write(activity_level, ACTIVITY_ENDLESS_LEVEL.encode() + b"\0")
        invoke(BUILD_CHECKPOINT_LEVEL_NAME, widget, [EGYPT_LEVEL], r1=activity_level)
        for supplied, clamped in ((0xc0000000, 0), (0x42480000, 0x42480000), (0x42fa0000, 0x42c80000)):
            invoke(STORE_WAVE_METER_PROGRESS, widget, [STORE_WAVE_METER_PROGRESS + 4], meter_bits=supplied)
            assert get(widget + 0xf0) == clamped
    if version >= 217:
        for equal in (False, True):
            invoke(CHECK_DANGER_ROOM_DROP, widget, [CHECK_OTHER_REWARD_EXCLUSIONS], equal=equal)
            assert emu.reg_read(UC_ARM_REG_R0) == widget
    if version >= 218:
        invoke(SHOW_EVENT_VICTORY_SCORE, widget, [])
        profile_has_flag = False
        for floor in (1, 2):
            put(widget + 0xdc, floor)
            invoke(CHECK_REWARD_FADE_FLAG, intro, [], r1=9)
            assert emu.reg_read(UC_ARM_REG_R0) == 1
        profile_has_flag = True
        invoke(START_CHOOSER_PREVIEW, intro, ["start preview"])
        invoke(PLAY_PREVIEW_GROAN, intro, ["preview groan"])
    if version >= 219:
        for floor in (1, 5):
            put(widget + 0x118, 1)
            invoke(SHOW_EVENT_VICTORY_SCORE, widget, [], r1=floor)
            assert get(widget + 0x100) == floor and get(widget + 0xf4) == 1
            assert get(widget + 0x118) == 0
            invoke(NATIVE_RESULT_UPDATE, widget, [("acknowledge victory", 1)])
            invoke(NATIVE_RESULT_UPDATE, widget, [])
            invoke(CHECK_VICTORY_MILESTONE, widget, [CONTINUE_AFTER_VICTORY], equal=floor == 5)
        invoke(CHECK_SUN_PURCHASE_INPUT, widget, [0x93dc60], equal=False)
        invoke(CHECK_SUN_PURCHASE_DRAW, widget, [CHECK_SUN_PURCHASE_DRAW + 4], equal=False)
    emu.mem_write(level, b"egypt_dangerroom_festival\0")
    if version >= 219:
        invoke(CHECK_SUN_PURCHASE_INPUT, widget, [CHECK_SUN_PURCHASE_INPUT + 4], equal=False)
        invoke(CHECK_SUN_PURCHASE_INPUT, widget, [0x93dc60])
        invoke(CHECK_SUN_PURCHASE_DRAW, widget, [0x93dfc0], equal=False)
        invoke(CHECK_SUN_PURCHASE_DRAW, widget, [CHECK_SUN_PURCHASE_DRAW + 4])
    put(intro + 0x34, widget)
    invoke(CURRENT_PROGRESS, intro, ["original key"])
    invoke(INTRO_CONFIRM, widget, ["confirm"])
    invoke(BEGIN_BATTLE, board, ["battle"])
    invoke(OPENING_ACCEPT, intro, ["accept"])
    put(widget + 0x194, 0)
    invoke(OPENING_REWARDS, widget, ["generate rewards"])
    invoke(FLIP_REWARD, widget, ["flip"])
    plant_ids = [12, 23]
    invoke(COPY_INTRO_PLANTS, widget, ["copy ids"])
    invoke(BUILD_CHOOSER_PACKETS, widget, ["stock chooser"])
    if version == 212:
        invoke(DRAW_OPENING_BACKGROUND, widget, [("draw", 0)])
    else:
        invoke(OPENING_DIM, widget, ["fill"])
        invoke(FIND_DANGER_PROPERTIES, widget, ["DefaultDangerRoomProps"])
        invoke(RESTORE_CAMPAIGN_SELECTION, widget, ["profile selection"])
        set_vector(widget + 0xe8, (reward_ids, reward_ids + 4, reward_ids + 24))
        invoke(SAVE_REWARD_SELECTION, widget, [("save", [12])])
    if version >= 214:
        invoke(OPENING_OFFER_GATE, widget, [0x2d53c0])
        invoke(OPENING_OFFER_GATE, widget, [0x2d5024], r2=1)
        invoke(MARK_OFFER_GENERATED, widget, [0x2d4b20])
        assert get(widget + 0xf8) == 2
        invoke(CHECK_OFFER_CAPACITY, widget, [0x2cef20])
        assert emu.reg_read(UC_ARM_REG_R2) == 9
        invoke(HIDE_GAMEPLAY_HUD, widget, [0x2c2a44])
        invoke(BUILD_REWARD_TITLE, widget, ["DefaultDangerRoomProps"])
    if version >= 215:
        for addr in MAP_PROGRESS_CALLS:
            invoke(addr, intro, ["festival key"])
        for addr in REWARD_OFFER_COUNT_CALLS:
            invoke(addr, widget, ["stock offer count"])
            assert emu.reg_read(UC_ARM_REG_R0) == 6
        invoke(CHECK_PAID_REWARD, widget, ["stock paid offer"])
        invoke(CHECK_FESTIVAL_FLOOR_LIMIT, widget, [CHECK_FESTIVAL_FLOOR_LIMIT + 4])
        assert not emu.reg_read(UC_ARM_REG_CPSR) & (1 << 30)
        put(widget + 0xcc, 0x100)
        put(widget + 0xd0, 0x3f800000)
        invoke(ATTACH_STATS_CONTENT, widget, ["attach content"])
        assert get(widget + 0xcc) == 0x100 and get(widget + 0xd0) == 0x3f800000
        invoke(BUILD_REWARD_CONFIRM, widget, ["DefaultDangerRoomProps"])
        invoke(SHOW_BATTLE_POWERUPS, widget, ["show powerups"])
        emu.mem_write(level, ACTIVITY_ENDLESS_LEVEL.encode() + b"\0")
        put(intro + 0x34, 0)
        put(widget + 0x1b0, 0)
        activity_key = ["festival_level_endless key"] if version >= 220 else ["original key"]
        invoke(CURRENT_PROGRESS, intro, activity_key)
        invoke(INTRO_CONFIRM, widget, ["panel"])
        put(intro + 0x34, widget)
        invoke(BEGIN_BATTLE, board, [])
        put(widget + 0x194, 0)
        visibility = ["show reward panel"] if version >= 222 else []
        invoke(OPENING_REWARDS, widget, ["generate rewards", "reward panel", *visibility])
        invoke(REWARD_OFFER_COUNT_CALLS[0], widget, [])
        assert emu.reg_read(UC_ARM_REG_R0) == 6
        put(widget + 0x1d8, 6)
        invoke(CHECK_OFFER_CAPACITY, widget, [0x2cef20])
        assert emu.reg_read(UC_ARM_REG_R5) == 5
        assert emu.reg_read(UC_ARM_REG_R2) == 2
        put(widget + 0xdc, 1)
        put(widget + 0xf8, 0)
        invoke(OPENING_OFFER_GATE, widget, [0x2d5030])
        put(widget + 0xdc, 2)
        invoke(OPENING_OFFER_GATE, widget, [0x2d5030 if version >= 222 else 0x2d53c0])
        if version >= 222:
            put(widget + 0xf8, 2)
            invoke(OPENING_OFFER_GATE, widget, [0x2d53c0])
            for count in (1, 3, 5, 6):
                put(widget + 0x1d8, count)
                invoke(CHECK_OFFER_CAPACITY, widget, [0x2cef20])
                assert emu.reg_read(UC_ARM_REG_R5) == min(count, 5)
            put(widget + 0x174, get(widget + 0x170))
            invoke(OPENING_REWARDS, widget, ["generate rewards"])
            invoke(SHOW_BATTLE_POWERUPS, widget, ["register Tactical Cucumber", "show powerups"])
    if version >= 216:
        invoke(LOAD_WIN_REWARD_PROGRESS, intro, activity_key if version >= 220 else ["festival key"])
        invoke(SELECT_EVENT_MILESTONE_REWARD, widget, [0xcd7d08])
        invoke(SELECT_EVENT_MILESTONE_REWARD, widget, [SELECT_EVENT_MILESTONE_REWARD + 4], equal=False)
        invoke(BUILD_CHECKPOINT_LEVEL_NAME, widget, [ACTIVITY_ENDLESS_LEVEL], r1=activity_level)
        invoke(STORE_WAVE_METER_PROGRESS, widget, [STORE_WAVE_METER_PROGRESS + 4], meter_bits=0x42fa0000)
        assert get(widget + 0xf0) == 0x42fa0000
    if version >= 217:
        invoke(CHECK_DANGER_ROOM_DROP, widget,
               [CHECK_OTHER_REWARD_EXCLUSIONS if version >= 222 else CHECK_DANGER_ROOM_DROP + 4], equal=False)
        invoke(CHECK_DANGER_ROOM_DROP, widget, [CHECK_OTHER_REWARD_EXCLUSIONS], equal=True)
    if version >= 218:
        invoke(SHOW_EVENT_VICTORY_SCORE, widget, [] if version >= 222 else ["event victory score"])
        profile_has_flag = False
        invoke(CHECK_REWARD_FADE_FLAG, intro, ["profile selection"], r1=9)
        assert emu.reg_read(UC_ARM_REG_R0) == 0
        invoke(START_CHOOSER_PREVIEW, intro, [])
        invoke(PLAY_PREVIEW_GROAN, intro, [])
        if version >= 220:
            invoke(OPEN_SEED_CHOOSER, intro, [], r1=0)
        put(intro + 0x34, 0)
        put(modules + 0x40, int(version >= 220))
        native_accept_state = 3
        native_weak_target = widget
        invoke(OPENING_ACCEPT, intro, ["accept", "preview origin", *card_refresh, "chooser"])
        invoke(START_CHOOSER_PREVIEW, intro, ["start preview"])
        invoke(PLAY_PREVIEW_GROAN, intro, ["preview groan"])
        invoke(BEGIN_BATTLE, board, ["battle"])
    if version >= 219:
        invoke(CHECK_VICTORY_MILESTONE, widget,
               [CONTINUE_AFTER_VICTORY if version >= 222 else CHECK_VICTORY_MILESTONE + 4])
        invoke(CHECK_VICTORY_MILESTONE, widget, [CONTINUE_AFTER_VICTORY], equal=False)
        invoke(CHECK_SUN_PURCHASE_INPUT, widget, [0x93dc60], equal=False)
        invoke(CHECK_SUN_PURCHASE_DRAW, widget, [CHECK_SUN_PURCHASE_DRAW + 4], equal=False)
    if version >= 222:
        # Only successful floors in the two restored modes use the hidden handoff.
        for room in (ACTIVITY_ENDLESS_LEVEL, EGYPT_LEVEL, FESTIVAL_ROOMS[0]):
            emu.mem_write(level, room.encode() + b"\0")
            put(widget + 0x100, 0)
            put(widget + 0xf4, 0)
            put(widget + 0x118, 9)
            floor_win = room != FESTIVAL_ROOMS[0]
            detach_board_on_result = version >= 223 and floor_win
            score_event_skipped = ["finish reward without score event"] if detach_board_on_result else []
            invoke(ATTACH_WIN_RESULT, app, ["attach win result", *score_event_skipped])
            if detach_board_on_result:
                assert not get(app + 0x6bc)
                put(app + 0x6bc, board)
            detach_board_on_result = False
            if room == FESTIVAL_ROOMS[0]:
                assert get(widget + 0x100) == get(widget + 0xf4) == 0
                assert get(widget + 0x118) == 9
                invoke(SHOW_EVENT_VICTORY_SCORE, widget, ["event victory score"])
            else:
                assert get(widget + 0x100) == get(widget + 0xf4) == 1
                assert get(widget + 0x118) == 0
                invoke(SHOW_EVENT_VICTORY_SCORE, widget, [], r1=2)
                assert get(widget + 0x100) == 2
                invoke(NATIVE_RESULT_UPDATE, widget, [("acknowledge victory", 1)])
                invoke(NATIVE_RESULT_UPDATE, widget, [])
        emu.mem_write(level, ACTIVITY_ENDLESS_LEVEL.encode() + b"\0")
        plant_ids = [plant_id for _, plant_id in ACTIVITY_SUN_PLANTS] + [44]
        invoke(COPY_INTRO_PLANTS, widget, ["copy ids", "reward_alias", "peashooter", "cabbagepult", "assign roster"])
        plant_ids = [2, 6, 44]
        invoke(COPY_INTRO_PLANTS, widget, ["copy ids", "peashooter", "cabbagepult", "reward_alias", "assign roster"])
        plant_ids = []
        invoke(COPY_INTRO_PLANTS, widget, ["copy ids", "peashooter", "cabbagepult", "assign roster"])
        put(reward_ids, 1)
        set_vector(widget + 0xe8, (reward_ids, reward_ids + 4, reward_ids + 24))
        invoke(SAVE_REWARD_SELECTION, widget, [("save", [2, 6])])
        invoke(SAVE_REWARD_SELECTION, widget, [("save", [2, 6])])
    elif version >= 220:
        # Activity restores its starter for existing runs as well as fresh runs.
        plant_ids = [23, 44]
        invoke(COPY_INTRO_PLANTS, widget, ["copy ids", "peashooter", "reward_alias", "sunflower", "assign roster"])
        plant_ids = [12, 23, 44]
        invoke(COPY_INTRO_PLANTS, widget, ["copy ids", "sunflower", "peashooter", "reward_alias", "assign roster"])
    if version >= 224:
        for site, continuation in FLOOR_SUMMARY_STATEMENT_SITES:
            for room in (EGYPT_LEVEL, ACTIVITY_ENDLESS_LEVEL, FESTIVAL_ROOMS[0], "egypt1"):
                emu.mem_write(level, room.encode() + b"\0")
                restored_room = room in (EGYPT_LEVEL, ACTIVITY_ENDLESS_LEVEL)
                if restored_room:
                    expected = [("continue with visible statistics", continuation)] if version >= 225 else []
                else:
                    expected = [("open battle statement", 1)]
                invoke(site, app, expected, r1=1)
                invoke(site, app, [("open battle statement", 0)], r1=0)
            put(app + 0x6bc, 0)
            invoke(site, app, [("open battle statement", 1)], r1=1)
            put(app + 0x6bc, board)
    if version >= 225:
        emu.mem_write(level, ACTIVITY_ENDLESS_LEVEL.encode() + b"\0")
        put(widget + 0x1b0, 1)
        preload_grass = grass_image
        invoke(DRAW_OPENING_BACKGROUND, widget, [("draw", grass_image)], r2=grass_image)
        invoke(DRAW_OPENING_BACKGROUND, widget, ["resolve grass", ("draw", grass_image)])
        assert emu.mem_read(widget + 0x1d5, 1) == b"\x02"
        preload_grass = 0
        invoke(DRAW_OPENING_BACKGROUND, widget, ["resolve grass", ("draw", 0)])
        invoke(OPENING_DIM, widget, [])
    if version >= 226:
        emu.mem_write(level, ACTIVITY_ENDLESS_LEVEL.encode() + b"\0")
        put(widget + 0xcc, 0x3d371001)
        put(widget + 0xd0, 0x3f7fb600)
        invoke(ATTACH_STATS_CONTENT, widget, ["attach content"])
        assert get(widget + 0xcc) == 0x3d370001
        assert not get(widget + 0xd0)
    if version >= 220:
        for room in FESTIVAL_ROOMS:
            emu.mem_write(level, room.encode() + b"\0")
            progress_key = [room.replace("_dangerroom", "") + " key"]
            invoke(CURRENT_PROGRESS, intro, progress_key)
            for addr in (*MAP_PROGRESS_CALLS, LOAD_WIN_REWARD_PROGRESS):
                invoke(addr, intro, progress_key)
        put(checkpoint + 4, checkpoint_room)
        put(base + PROFILE_MANAGER_SLOT, profile_manager)
        for reader in CHECKPOINT_HEADER_CALLS:
            for active_owner, checkpoint_owner, active_room, saved_room, expected in (
                (4, 4, EGYPT_LEVEL, EGYPT_LEVEL, 1),
                (4, 4, ACTIVITY_ENDLESS_LEVEL, EGYPT_LEVEL, 0),
                (4, 4, EGYPT_LEVEL, ACTIVITY_ENDLESS_LEVEL, 0),
                (4, 7, EGYPT_LEVEL, EGYPT_LEVEL, 0),
                (7, 7, ACTIVITY_ENDLESS_LEVEL, ACTIVITY_ENDLESS_LEVEL, 1),
                (7, 4, None, EGYPT_LEVEL, 0),
                (4, 4, None, EGYPT_LEVEL, 1),
                (-1, -1, None, EGYPT_LEVEL, 0),
                (4, 4, EGYPT_LEVEL, EGYPT_LEVEL + "_2", 0),
            ):
                put(profile_manager + 0x74, active_owner)
                put(checkpoint + 0x18, checkpoint_owner)
                put(app + 0x6bc, board if active_room else 0)
                if active_room:
                    emu.mem_write(level, active_room.encode() + b"\0")
                emu.mem_write(checkpoint_room, saved_room.encode() + b"\0")
                invoke(reader, widget, ["read checkpoint header"], r1=checkpoint)
                assert emu.reg_read(UC_ARM_REG_R0) == expected
                assert get(profile_manager + 0x74) == active_owner & 0xffffffff
            checkpoint_found = False
            invoke(reader, widget, ["read checkpoint header"], r1=checkpoint)
            assert emu.reg_read(UC_ARM_REG_R0) == 0
            checkpoint_found = True
        invoke(CHECKPOINT_SELECT_PROFILE, profile_manager, [])
    if version >= 221:
        for site in ACTIVITY_CHECKPOINT_CALL_FLAGS:
            invoke(site, widget, [])
            assert emu.reg_read(UC_ARM_REG_R1) == ACTIVITY_CHECKPOINT_CONTEXT
        expected_native_checkpoint_flag = 1
        for reader in CHECKPOINT_HEADER_CALLS:
            put(app + 0x6bc, 0)
            for active_owner, stored_owner, room, expected in (
                (4, 4, EGYPT_LEVEL, 0),
                (4, 4, ACTIVITY_ENDLESS_LEVEL, 1),
                (4, 7, ACTIVITY_ENDLESS_LEVEL, 0),
                (7, 7, FESTIVAL_ROOMS[0], 0),
                (7, 7, ACTIVITY_ENDLESS_LEVEL + "_2", 0),
            ):
                emu.mem_write(checkpoint_room, room.encode() + b"\0")
                put(profile_manager + 0x74, active_owner)
                put(checkpoint + 0x18, stored_owner)
                invoke(reader, widget, ["read checkpoint header"], r1=checkpoint, r2=ACTIVITY_CHECKPOINT_CONTEXT)
                assert emu.reg_read(UC_ARM_REG_R0) == expected
    return cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path, help="A206 ARM32 APK")
    parser.add_argument("--version", type=int, choices=range(212, 228), default=227)
    args = parser.parse_args()
    with ZipFile(args.apk) as apk:
        patched = patch(apk.read("lib/armeabi/libSrc.so"), args.version)
    cases = sum(run_cases(patched, guest_base, args.version) for guest_base in (0x10000000, 0x70000000))
    print(f"{cases} ARM call-site checks passed at two guest bases")
