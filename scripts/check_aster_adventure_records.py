"""Exercise the A251 adventure hooks on ARM with bounded native service doubles."""

import argparse
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM
from unicorn.arm_const import (
    UC_ARM_REG_C1_C0_2, UC_ARM_REG_CPSR, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC,
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R6,
    UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_SP,
)

from build_aster_adventure_records import (
    BEGIN_BATTLE_ENTRY, BEGIN_BATTLE_TARGET, BOARD_LOAD, BOARD_LOAD_CALL, BOARD_READY_CALL,
    BOARD_UPDATE_DONE, DRAW, DRAW_CALL, GAME_POLL, GAME_POLL_TARGET, GOLD_TILE_SUN, INITIAL_ACTORS,
    KILL_ZOMBIES,
    BOARD_TOUCH_CALLS, BOARD_TOUCH, DISPATCH_EVENT, LAUNCH_LEVEL, MAP_LEVEL_CALLS, PLAY_NARRATIVE,
    PICKUP_CLICK, SETTINGS_CLICK,
    SET_PHASE, STAR_DESCRIPTIONS_ENABLED, STAR_DESCRIPTIONS_GATE,
    STAR_MODULE_ENABLED, STAR_MODULE_GATE, STAR_MODULE_LOCKED,
    STAR_RESULT_TITLE, STAR_RIBBON_ART, STAR_RIBBON_EMPTY, STAR_RIBBON_GOLD,
    STAR_NEXT_BUTTON, STAR_NEXT_CLICK, STAR_SHOW_CONTINUE, STAR_SHOW_NEXT, STAR_CLICK_CONTINUE,
    SHOP_SCROLLBAR_CALL, SHOP_SCROLLBAR_VISIBLE, START_BUTTON_EVENT, START_CALL,
    CHOOSER_RESTORE_CALL, CHOOSER_RESTORE, SEED_BANK_REFRESH, SEED_PACKET_DRAW_CALL, SEED_PACKET_DRAW,
    STOCK_SUN_CLOSE, STOCK_SUN_PURCHASE, SUN_BUTTON_OPEN, UPDATE, VIEWPORT_HIGH_DRAW, WIN, WIN_CALL,
)


BASE = 0x4000000
DATA = 0x8000000
RETURN = DATA
STACK = DATA + 0xf000
ARGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
APP, BOARD, STORE, PROFILE, CLOCK, GRAPHICS = (DATA + n for n in (
    0x1000, 0x2800, 0x4000, 0x4400, 0x4800, 0x4c00
))
ALIAS = DATA + 0x5000
PLANT_NODE = DATA + 0x5200
PLANT = DATA + 0x5400
TYPE = DATA + 0x5800
TYPE_NAME = DATA + 0x5a00
TYPE_CLASS = DATA + 0x5b00
BEST = DATA + 0x6000
REGISTRY = DATA + 0x8000
PLANT_STORE = DATA + 0x8100
COMMAND = "/data/data/com.pvz2unline.aster/cache/aster-battle-tools.cmd"
CLAIMED = COMMAND.removesuffix(".cmd") + ".claimed"
SOCIAL_EVENT = "/data/data/com.pvz2unline.aster/cache/aster-social-level"
SOCIAL_REPLY = "/data/data/com.pvz2unline.aster/cache/aster-social-reply"
SOCIAL_SETTING = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-content.bin"
SOCIAL_ON = struct.pack("<III", 0x31434f53, 1, 0xfffffffe)
GIFT_LEDGER = "/data/data/com.pvz2unline.aster/files/userdata/friend-sun-00000001.bin"
LOADOUT = 4884
SELF_ROW = 0x100 + 160


class Game:
    def __init__(self, output, social_enabled=True, engine=None):
        self.arm = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.arm.mem_map(BASE, 0x2000000)
        self.arm.mem_map(DATA, 0x10000)
        with (engine or output / "libSrc-adventure-records.so").open("rb") as f:
            for seg in ELFFile(f).iter_segments():
                if seg["p_type"] == "PT_LOAD" and seg["p_filesz"]:
                    self.arm.mem_write(BASE + seg["p_vaddr"], seg.data())
        with (output / "adventure-records.elf").open("rb") as f:
            self.symbols = {s.name: s["st_value"] for s in
                            ELFFile(f).get_section_by_name(".symtab").iter_symbols()}
        self.arm.reg_write(UC_ARM_REG_C1_C0_2, 0xf00000)
        self.arm.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.files = {}
        if social_enabled and "asterSocialSettingsClick" in self.symbols:
            self.files[SOCIAL_SETTING] = SOCIAL_ON
        self.descriptors = {}
        self.opens = []
        self.rectangles = []
        self.clock_labels = []
        self.renames = 0
        self.fail_rename = False
        self.stock_calls = []
        self.logs = []
        self.clears = 0
        self.put(BASE + 0x1821674, DATA + 4)
        self.put(DATA + 4, APP)
        self.put(APP + 0x6bc, BOARD)
        self.put(APP + 0x524, 1600)
        self.arm.mem_write(APP + 0x698, struct.pack("<f", 1.0))
        self.put(BASE + 0x1842b50, DATA + 0x7900)
        self.put(DATA + 0x7924, DATA + 0x7a00)
        self.put(BASE + 0x18300a4, STORE)
        self.put(BASE + 0x1830528, CLOCK)
        self.put(STORE + 0x74, 1)
        self.put(BOARD + 0xb4, 9, 5)
        self.put(BOARD + 0xc4, ALIAS)
        self.put(PLANT_STORE + 0x34, PLANT_NODE)
        self.put(PLANT_NODE + 4, PLANT_STORE + 0x30, PLANT)
        self.put(TYPE + 4, TYPE_NAME, TYPE_CLASS)
        self.arm.mem_write(TYPE_NAME, b"peashooter\x00")
        self.arm.mem_write(TYPE_CLASS, b"PlantPeashooter\x00")
        self.put(PLANT + 0xf8, 2, 1)
        for offset, value in ((0x38, 2), (0xac, 1), (0xb0, 4), (0xb4, 1), (0x16c, 0x0101),
                              (0x170, 1), (0x174, 4), (0x1c0, 0xffffffff)):
            self.put(PLANT + offset, value)
        self.arm.hook_add(UC_HOOK_CODE, self.native)

    def put(self, addr, *values):
        self.arm.mem_write(addr, struct.pack("<" + "I" * len(values), *values))

    def get(self, addr, count=1):
        return struct.unpack("<" + "I" * count, self.arm.mem_read(addr, count * 4))

    def string(self, addr):
        return bytes(self.arm.mem_read(addr, 128)).split(b"\0", 1)[0].decode("ascii")

    def execute(self, where, *args, return_from_call=False, r4=0, r5=0):
        from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5
        if isinstance(where, str):
            where = self.symbols[where]
        self.arm.reg_write(UC_ARM_REG_SP, STACK)
        self.arm.reg_write(UC_ARM_REG_LR, RETURN)
        self.arm.reg_write(UC_ARM_REG_R4, r4)
        self.arm.reg_write(UC_ARM_REG_R5, r5)
        for reg, value in zip(ARGS, args):
            self.arm.reg_write(reg, value)
        if return_from_call:
            self.arm.hook_add(UC_HOOK_CODE, self.stop, begin=BASE + where + 4, end=BASE + where + 4)
        self.arm.emu_start(BASE + where, RETURN, count=150_000)
        assert self.arm.reg_read(UC_ARM_REG_SP) == STACK
        return self.arm.reg_read(UC_ARM_REG_R0)

    def stop(self, *_):
        self.arm.emu_stop()

    def native(self, arm, address, _size, _context):
        off = address - BASE
        a, b, c, d = (arm.reg_read(reg) for reg in ARGS)
        result = 0
        if off == SET_PHASE:
            assert a == BOARD and b == 5
            self.put(a + 0xc0, b)
            self.stock_calls.append("start")
        elif off == UPDATE + 4:
            # The hook executes the original nine-register push first.
            stack = arm.reg_read(UC_ARM_REG_SP)
            assert stack == STACK - 36
            arm.reg_write(UC_ARM_REG_LR, self.get(stack + 32)[0])
            arm.reg_write(UC_ARM_REG_SP, STACK)
        elif off == WIN:
            assert a == BOARD
            self.stock_calls.append("win")
            self.put(BOARD + 0x7f4, 1)
        elif off == DRAW:
            assert (a, b) == (BOARD, GRAPHICS)
            self.stock_calls.append("draw")
        elif off == 0x207D90:
            assert (a, b, c, d) == (BOARD, 0x14, 5, TYPE)
            self.stock_calls.append("tactical-cuke")
        elif off == 0x7a98dc:
            assert a == STORE
            result = PROFILE
        elif off == 0x11d74b4:
            result = REGISTRY
        elif off == 0x20bb34:
            assert a == BOARD
        elif off == 0x11d7538:
            assert a == REGISTRY and b == 0x23
            result = PLANT_STORE
        elif off == 0x1da034:
            assert a == REGISTRY and b == PLANT + 0xf8
            result = TYPE
        elif off == 0x4b56ac:
            assert a == PLANT
            result = int(self.get(a + 0x16c)[0] & 0xffff == 0x0101)
        elif off == KILL_ZOMBIES:
            assert self.get(BOARD + 0xc0) == (5,)
            assert not self.get(BOARD + 0x8d4)[0] & 0x100
            self.clears += 1
        elif off == 0x148448:
            name = self.string(a)
            self.opens.append(name)
            if name == CLAIMED:
                assert b == 0x8800
            if b == 0x241:
                self.files[name] = b""
            if name in self.files:
                result = 3
                self.descriptors[result] = name, 0
            else:
                result = 0xffffffff
        elif off == 0x148460:
            name, pos = self.descriptors[a]
            block = self.files[name][pos:pos + min(c, 631)]
            arm.mem_write(b, block)
            result = len(block)
            self.descriptors[a] = name, pos + result
        elif off == 0x1485d4:
            name, pos = self.descriptors[a]
            result = min(c, 683)
            self.files[name] += bytes(arm.mem_read(b, result))
            self.descriptors[a] = name, pos + result
        elif off == 0x147b90:
            self.descriptors.pop(a)
        elif off == 0x1485e0:
            assert a in self.descriptors
        elif off == 0x147e6c:
            source, target = self.string(a), self.string(b)
            if target == CLAIMED:
                if source in self.files:
                    self.files[target] = self.files.pop(source)
                else:
                    result = 0xffffffff
            elif self.fail_rename:
                result = 0xffffffff
            else:
                self.files[target] = self.files.pop(source)
                if target != SOCIAL_EVENT:
                    self.renames += 1
        elif off == 0x148424:
            self.files.pop(self.string(a), None)
        elif off == 0x147adc:
            self.logs.append(self.string(c).split(" ", 1)[0])
        elif off == 0x1166c30:
            arm.mem_write(a + 0x4c, bytes(arm.mem_read(b, 16)))
        elif off == 0x1167010:
            self.rectangles.append((b, c, d, self.get(arm.reg_read(UC_ARM_REG_SP))[0]))
        elif off == 0x14ed0e0:
            self.put(a, DATA + 0x7800)
        elif off in (0x14ebf58, 0x14ea238, 0x97714c):
            pass
        elif off == 0x14eb450:
            address = DATA + 0x7b00
            data = bytearray()
            while (word := self.get(b + len(data))[0]):
                data += struct.pack("<I", word)
            arm.mem_write(address, bytes(data) + bytes(4))
            self.put(a, address)
        elif off in (0x973270, 0x97335c):
            assert a == GRAPHICS and d == DATA + 0x7a00
            label = bytes(arm.mem_read(self.get(b)[0], 24)).decode("utf-32le").split("\0", 1)[0]
            self.clock_labels.append(label)
        else:
            return
        arm.reg_write(UC_ARM_REG_R0, result)
        arm.reg_write(UC_ARM_REG_PC, arm.reg_read(UC_ARM_REG_LR))

    def time(self, seconds, step=0):
        self.arm.mem_write(CLOCK + 0x24, struct.pack("<2f", seconds, step))

    def start(self, t, level=b"egypt1", stars=0):
        self.arm.mem_write(ALIAS, level + b"\0")
        self.arm.mem_write(BOARD + 0xcc, struct.pack("<f", t))
        self.put(BOARD + 0x7f4, 0)
        self.put(BOARD + 0x7f0, (stars - 1) & 0xffffffff)
        self.put(BOARD + 0x8a0, int(bool(stars)))
        self.time(t)
        self.execute(START_CALL, BOARD, 5, r4=BOARD, return_from_call=True)

    def tick(self, seconds, step=None):
        if step is None:
            last = struct.unpack("<f", self.arm.mem_read(CLOCK + 0x24, 4))[0]
            gap = seconds - last
            step = gap if 0 < gap <= 0.25 else 0
        self.time(seconds, step)
        self.execute(UPDATE, BOARD)

    def finish(self):
        self.execute(WIN_CALL, BOARD, return_from_call=True)

    def best(self, day=1, stars=0):
        if not self.execute("asterAdventureBest", BASE, day, stars, BEST):
            return None
        return self.get(BEST, 6)

    def runs_plant_actions(self):
        action = BASE + 0x4bf3d8
        # Execute the native Plant::Update gate for a plant whose actions are active.
        self.arm.mem_write(PLANT + 0xf0, b"\1")
        self.arm.reg_write(UC_ARM_REG_R7, PLANT)
        hook = self.arm.hook_add(UC_HOOK_CODE, self.stop, begin=action, end=action)
        try:
            self.arm.emu_start(BASE + 0x4bfed0, BASE + 0x4bfef8, count=32)
            return self.arm.reg_read(UC_ARM_REG_PC) == action
        finally:
            self.arm.hook_del(hook)


def check_egypt_endless_plant_updates(output):
    game = Game(output)
    flag = BOARD + 0x7fb

    def enabled():
        return game.arm.mem_read(flag, 1)[0]

    assert not game.runs_plant_actions()
    game.start(10, b"egypt_dangerroom")
    assert enabled() == 1 and game.runs_plant_actions()
    game.arm.mem_write(flag, b"\0")
    game.tick(10.25)
    assert enabled() == 0  # Respect later changes made by the game.

    # A restored battle can reach Board::Update without calling BeginBattle.
    game = Game(output)
    game.arm.mem_write(ALIAS, b"egypt_dangerroom\0")
    game.put(BOARD + 0xc0, 3)
    game.tick(20)
    assert enabled() == 0
    game.put(BOARD + 0xc0, 4)
    game.tick(20.25)
    assert enabled() == 0
    game.put(BOARD + 0xc0, 5)
    game.arm.mem_write(BOARD + 0x8d5, b"\1")
    game.tick(20.5)
    assert enabled() == 0
    game.arm.mem_write(BOARD + 0x8d5, b"\0")
    game.tick(20.75)
    assert enabled() == 1 and game.runs_plant_actions()

    for level in (b"egypt1", b"pirate_dangerroom", b"festival_dangerroom_level_endless"):
        game.arm.mem_write(flag, b"\0")
        game.start(30, level)
        game.tick(30.25)
        assert enabled() == 0
    print("Egypt legacy Endless plant updates passed: start, restore, and mode isolation")


def main(output):
    game = Game(output)
    game.start(10)
    game.tick(10.125)
    game.tick(10.25)
    game.put(BOARD + 0x8d5, 1)
    game.tick(10.375)
    game.tick(15)
    game.put(BOARD + 0x8d5, 0)
    game.tick(15.125)
    game.tick(15.25)
    game.tick(20)
    game.tick(20.125)
    game.put(GRAPHICS + 0x4c, 13, 14, 15, 255)
    game.execute(DRAW_CALL, BOARD, GRAPHICS, return_from_call=True)
    assert len(game.rectangles) == 1 and game.clock_labels == ["0:00"]
    assert game.get(GRAPHICS + 0x4c, 4) == (13, 14, 15, 255)
    game.finish()
    assert game.best() == (3, 1, 1, 0, 625, 1)
    assert game.string(BEST + 24).startswith("peashooter")
    assert game.get(BEST + 56) == (0x01020104,)
    assert game.renames == 1
    assert not game.best(day=2) and not game.best(stars=1)
    game.finish()
    assert game.renames == 1

    game.start(30)
    for tick in (30.25, 30.5, 30.75):
        game.tick(tick)
    game.finish()
    assert game.best()[4] == 625 and game.renames == 1
    assert game.get(game.execute("asterAdventureLast", BASE) + 16)[0] == 750

    game.start(40)
    game.tick(40.25)
    game.fail_rename = True
    game.finish()
    assert game.best()[4] == 625 and not any(p.endswith(".tmp") for p in game.files)
    game.fail_rename = False
    game.start(45)
    game.tick(45.25)
    game.finish()
    assert game.best()[4] == 250 and game.renames == 2

    game.start(50, b"egypt2", stars=2)
    game.tick(50.25)
    game.finish()
    assert game.best(2, 2) == (3, 1, 2, 2, 250, 1)
    assert game.best()[4] == 250

    game.start(55, b"egypt2", stars=1)
    game.tick(55.25)
    game.arm.mem_write(BOARD + 0x7fe, b"\1")
    game.finish()
    assert not game.best(2, 1)
    game.arm.mem_write(BOARD + 0x7fe, b"\0")

    game.put(STORE + 0x74, 2)
    assert not game.best() and not game.execute("asterAdventureLast", BASE)
    game.start(60)
    game.tick(60.25)
    game.put(STORE + 0x74, 3)
    game.finish()
    assert not game.best()
    game.put(STORE + 0x74, 2)
    assert not game.best()
    game.start(70, b"egypt1_endless")
    game.tick(70.25)
    game.finish()
    assert not game.best() and game.renames == 3
    game.put(STORE + 0x74, 1)
    assert game.best()[4] == 250

    path = next(p for p in game.files if p.endswith("-1-0.run"))
    record = game.files[path]
    for version, size in ((1, LOADOUT), (2, len(record) - 8)):
        legacy = bytearray(record[:size])
        struct.pack_into("<I", legacy, 0, version)
        checksum = 0x811c9dc5
        for byte in legacy:
            checksum = ((checksum ^ byte) * 0x01000193) & 0xffffffff
        game.files[path] = bytes(legacy) + struct.pack("<I", checksum)
        assert game.best() == (version, 1, 1, 0, 250, 1)
        assert game.get(BEST + LOADOUT) == (0,)
        assert game.get(BEST + len(record) - 8) == (0xffffffff,)
    game.files[path] += b"corrupt"
    assert not game.best()
    assert game.stock_calls.count("start") == 8 and game.stock_calls.count("win") == 9
    assert game.logs.count("clear") == 5

    game = Game(output)
    game.put(DATA + 0x7924, 0)
    game.put(DATA + 0x791c, DATA + 0x7a00)
    game.start(100)
    for frame in range(1, 240):
        game.tick(100 + frame / 4)
    game.execute(DRAW_CALL, BOARD, GRAPHICS, return_from_call=True)
    assert game.clock_labels[-1] == "0:59"
    game.put(BOARD + 0x8d5, 1)
    game.tick(200, step=0.25)
    game.execute(DRAW_CALL, BOARD, GRAPHICS, return_from_call=True)
    assert game.clock_labels[-1] == "0:59"
    game.put(BOARD + 0x8d5, 0)
    # The acceleration is already part of the simulation step. Rendering and
    # a repeated callback in the same frame must not charge that step twice.
    game.tick(200.125, step=0.25)
    game.tick(200.125, step=0.25)
    game.execute(DRAW_CALL, BOARD, GRAPHICS, return_from_call=True)
    assert game.clock_labels[-1] == "1:00"
    game.finish()
    assert game.best()[4] == 60000

    print("A251 ARM checks passed: timer, HUD, native flow, formation, best time, save failure, isolation")


SCENE, DIALOG, PROPERTIES = (DATA + offset for offset in (0x9000, 0xa000, 0xa400))
WIDGETS, WIDGET_VT, APP_VT = (DATA + offset for offset in (0xa800, 0xaa00, 0xac00))
STAGE_TEXT, STAGE, LEVEL, STRING_AREA = (DATA + offset for offset in (0xb000, 0xb100, 0xb104, 0xb200))
VIEW_BUTTON, OTHER_HUD, ANCHOR = (DATA + offset for offset in (0xdc00, 0xdd00, 0xde00))
DIALOG_BUTTON = DATA + 0xe100
BANK = DATA + 0xa00
SUNFLOWER = DATA + 0x5c00


class SocialGame(Game):
    def __init__(self, output, social_enabled=True, engine=None):
        super().__init__(output, social_enabled=social_enabled, engine=engine)
        self.put(SCENE + 0x984, 13)
        self.put(BASE + 0x183049c, PLANT_STORE)
        self.put(STAGE, STAGE_TEXT)
        self.put(LEVEL, ALIAS)
        self.arm.mem_write(STAGE_TEXT, b"egypt\0")
        self.arm.mem_write(ALIAS, b"egypt1\0")
        self.wall = 100
        self.strings = 0
        self.launched = []
        self.placed = []
        self.returned = []
        self.finished_boards = 0
        self.activations = {}
        self.view_draws = []
        self.menu_buttons = {}
        self.labels = []
        self.cleared = True
        self.trophy_progress = {}
        self.earned = 0
        self.put(APP + 0x524, 1600, 1000)
        self.put(APP + 0x690, 0x3f800000)
        self.put(APP + 0x698, 0x3f800000)
        self.put(APP + 0x2c0, WIDGETS)
        self.put(APP, APP_VT)
        self.put(APP_VT + 0xa8, BASE + 0x10004)
        self.put(WIDGETS, WIDGET_VT)
        self.put(BOARD, WIDGET_VT)
        self.put(WIDGET_VT + 0x58, BASE + 0x10008)
        for slot, address in ((0x10, 0x13165b4), (0x14, 0x1315be4), (0x38, 0x1316670),
                              (0x2c, 0x1316a08), (0xac, 0x1313b68)):
            self.put(WIDGET_VT + slot, BASE + address)
        self.put(PROPERTIES + 0x1c, DATA + 0xa500, DATA + 0xa500 + 3 * 12)
        self.put(VIEW_BUTTON + 0xf4, DATA + 0xdf00)
        arm_x_y = struct.unpack("<2I", struct.pack("<2f", 100.0, 100.0))
        self.put(ANCHOR, *arm_x_y)
        self.sun_limit = 9990
        self.packets = ()

    def native(self, arm, address, size, context):
        off = address - BASE
        a, b, c, d = (arm.reg_read(reg) for reg in ARGS)
        stack = arm.reg_read(UC_ARM_REG_SP)
        out = 0
        if off == 0x147974:
            self.put(a, self.wall, 0)
        elif off == 0x147854:
            out = TYPE  # The UTC test calendar has a zero tm_gmtoff.
        elif off == STOCK_SUN_PURCHASE:
            self.stock_calls.append(("purchase-sun", a, b))
        elif off in (0x209574, 0x40fd9c, 0x410ebc):
            assert a == (BOARD if off == 0x209574 else APP)
        elif off == 0x10008:
            assert a == BOARD and b in (0, 1)
            arm.mem_write(BOARD + 0x8d5, bytes([b]))
        elif off == 0x2077e4:
            assert a == BOARD
            out = self.sun_limit
        elif off == 0x221b1c:
            assert a == BOARD and 0 < b <= 125
            self.put(BOARD + 0x12c, self.get(BOARD + 0x12c)[0] + b)
        elif off == PICKUP_CLICK:
            self.stock_calls.append(("settings-click", b))
        elif off == 0x8e7820:
            self.stock_calls.append("settings-refresh")
        elif off == 0x14ed0e0:
            address = STRING_AREA + self.strings * 128
            self.strings += 1
            arm.mem_write(address, self.string(b).encode("ascii") + b"\0")
            self.put(a, address)
        elif off == 0x14ebf58:
            pass
        elif off == 0x708f8c:
            assert a == PROFILE and c < 3
            out = bool(self.earned & (1 << c))
        elif off == 0x708104:
            assert a == PROFILE
            alias = self.string(self.get(b)[0])
            if alias in ("egypt11", "pirate10"):
                out = self.trophy_progress.get(self.get(STORE + 0x74)[0], 1)
            else:
                out = 3 if self.cleared else 1
        elif off == 0x14c1a7c:
            assert a == 0x170
            out = DIALOG
        elif off == 0x7f1b6c:
            assert a == DIALOG
            self.put(DIALOG, WIDGET_VT)
        elif off == 0x1313b68:
            assert a in (DIALOG, DIALOG_BUTTON) and b < 1600 and c < 1000
        elif off in (0x13165b4, 0x1316670, 0x1316a08, 0x1315be4):
            assert a == WIDGETS and b == DIALOG
        elif off == 0x1317158:
            assert a == WIDGETS and b == DIALOG and not self.get(WIDGETS + 0x88)[0]
            self.put(WIDGETS + 0x88, DIALOG)
        elif off == 0x1317170:
            assert a == WIDGETS and b == DIALOG and self.get(WIDGETS + 0x88)[0] == DIALOG
            self.put(WIDGETS + 0x88, 0)
        elif off == 0x10004:
            assert a == APP and b == DIALOG
            self.menu_buttons.clear()
        elif off == 0x9c0818:
            self.menu_buttons.clear()
        elif off == 0x14eb450:
            self.put(a, DATA + 0xe000)
            content = bytearray()
            while (word := self.get(b + len(content))[0]):
                content += struct.pack("<I", word)
            self.labels.append(content.decode("utf-32le"))
            arm.mem_write(DATA + 0xe000, bytes(content) + b"\0\0\0\0")
        elif off == 0x97714c:
            key = self.string(self.get(a)[0])
            assert key != "UIStartGameButton"
            out = BANK if key == "UISeedBank" and self.packets else OTHER_HUD
        elif self.packets and off == 0x20bb34:
            assert a == BOARD
            out = BANK
        elif self.packets and off == 0x895f0c:
            assert b == BANK
            self.put(a, self.packets[c], 1)
        elif self.packets and off == 0x717300:
            assert (a, self.string(self.get(b)[0]), c) == (PROFILE, "sunflower", 0)
            out = 3
        elif self.packets and off == 0x896448:
            assert (a, b, c) == (BANK, len(self.packets), 1)
            self.put(BANK + 0x11d, b)
        elif self.packets and off == 0x8962bc:
            assert (a, b) == (BANK, 1)
        elif self.packets and off == SEED_BANK_REFRESH + 4:
            assert arm.reg_read(UC_ARM_REG_SP) == STACK - 16
            arm.reg_write(UC_ARM_REG_SP, STACK)
            self.stock_calls.append("seed-bank-refresh")
        elif off == CHOOSER_RESTORE:
            assert (a, b) == (OTHER_HUD, BEST)
            self.stock_calls.append("restore-chooser-cards")
        elif self.packets and off == SEED_PACKET_DRAW:
            assert (b, c) == (GRAPHICS, TYPE)
            self.stock_calls.append(("draw-packet", self.get(a + 0x98)[0], self.get(a + 0x10c)[0]))
        elif self.packets and off == 0x8ad824:
            assert a in self.packets
            self.put(a + 0xf0, *self.get(b, 2))
        elif self.packets and off == 0x97a9c8:
            assert a in self.packets and b == 2
            self.put(a + 0x98, b)
        elif off == 0x11e13a8:
            out = REGISTRY
        elif off == 0x11e2ed8:
            assert a == REGISTRY and self.get(b, 18) == tuple(map(ord, "UIStartGameButton\0"))
            out = 7
        elif off in (0x11e153c, 0x11e14cc, 0x11e1f08):
            assert (a, b) == (REGISTRY, 7)
            out = STAGE_TEXT
        elif off == 0x9781e8:
            assert self.get(a, 2) == (7, STAGE_TEXT) and b == 1
            out = VIEW_BUTTON
        elif off == 0x926b48:
            assert a == VIEW_BUTTON and self.get(self.get(b)[0], 5) == tuple(map(ord, "返回地图\0"))
        elif off == 0x97620c:
            assert a == VIEW_BUTTON
            out = ANCHOR
        elif off == 0x9766cc:
            assert a == VIEW_BUTTON and struct.pack("<2I", b, c) == struct.pack("<2f", 100, 41)
        elif off == 0x9766f4:
            self.activations[a] = b
        elif off == 0x20b3d0:
            assert a == BOARD and b == 1
            arm.mem_write(BOARD + 0x7f9, b"\1")
        elif off == 0x20f4f8:
            assert a == BOARD and self.get(BOARD + 0x7f9)[0] & 255 == 1
            self.stock_calls.append("editor-animation")
        elif off == 0x9777e0:
            self.stock_calls.append("hud-update")
        elif off == 0x235048:
            assert b == GRAPHICS
            origin = struct.unpack("<f", arm.mem_read(b + 8, 4))[0]
            board_x = struct.unpack("<i", arm.mem_read(a + 0x2c, 4))[0]
            self.view_draws.append((a, origin, board_x))
        elif off == BOARD_TOUCH:
            self.stock_calls.append("board-touch")
        elif off == 0x926b94:
            assert (a, b) == (VIEW_BUTTON, TYPE)
            self.stock_calls.append("button-touch")
        elif off == DISPATCH_EVENT:
            self.stock_calls.append("dispatch-event")
        elif off in (0x14ea238, 0x7f1290):
            pass
        elif off == 0x7f25ec:
            _, callback, _, action, _, adapter = self.get(c, 6)
            assert (a, adapter) == (DIALOG, BASE + 0x2cc954) and d in (0, 1)
            self.menu_buttons[action] = callback - BASE
            out = DIALOG_BUTTON
            self.put(out, WIDGET_VT)
        elif off == LAUNCH_LEVEL:
            self.launched.append((a, self.string(self.get(b)[0]), self.string(self.get(c)[0]),
                                  d, *self.get(stack, 2)))
            self.put(SCENE + 0xa24, 6)
        elif off == BOARD_LOAD:
            assert a == BOARD
            self.put(SCENE + 0x984, 6)
            self.put(BOARD + 0xc0, 1)
            self.put(BOARD + 0x7f0, 0)
            self.put(BOARD + 0x8a0, 1)
        elif off == BOARD_UPDATE_DONE:
            pass
        elif off == GOLD_TILE_SUN + 4:
            assert stack == STACK - 36
            arm.reg_write(UC_ARM_REG_SP, STACK)
            self.stock_calls.append("gold-sun")
        elif off == PLAY_NARRATIVE + 4:
            assert stack == STACK - 32
            arm.reg_write(UC_ARM_REG_SP, STACK)
            self.stock_calls.append("narrative")
        elif off - 4 in INITIAL_ACTORS:
            assert stack == STACK - 36
            arm.reg_write(UC_ARM_REG_SP, STACK)
            self.stock_calls.append(off - 4)
        elif off == BEGIN_BATTLE_TARGET:
            self.stock_calls.append("begin-battle")
        elif off == SET_PHASE and b in (2, 3, 4):
            self.put(a + 0xc0, b)
            arm.mem_write(a + 0x7fb, b"\1")
        elif off == GAME_POLL_TARGET:
            pass
        elif off == 0x20cea8:
            assert b == PLANT_STORE
            alias = self.string(self.get(c)[0])
            if self.packets and alias == "sunflower":
                self.put(a, SUNFLOWER, 1)
            else:
                assert alias == "peashooter"
                self.put(a, 123, 456)
        elif off == 0x21ab00:
            assert a == BOARD and self.get(d, 2) == (123, 456)
            assert arm.mem_read(BOARD + 0x7fb, 1) == b"\0"
            self.placed.append((b, c, *self.get(stack, 6)))
            out = PLANT
        elif off == 0x352498:
            assert self.finished_boards and self.get(BOARD + 0xc0) == (9,)
            self.returned.append((a, b, c, d))
        elif off == 0x226770:
            assert a == BOARD and self.get(a + 0x7f4) == (7,)
            self.put(a + 0xc0, 9)
            self.finished_boards += 1
        elif self.packets and off == 0x1d9bb4:
            self.put(a, c, d)
        elif self.packets and off == 0x1da034 and b not in (PLANT + 0xf8, RETURN):
            ident, _ = self.get(b, 2)
            out = ident if ident in (*self.packets, SUNFLOWER) else TYPE
        elif off in (0x1da034, 0x1d9bb4) and b not in (PLANT + 0xf8, RETURN):
            out = TYPE if off == 0x1da034 else 0
        else:
            return super().native(arm, address, size, context)
        arm.reg_write(UC_ARM_REG_R0, out)
        arm.reg_write(UC_ARM_REG_PC, arm.reg_read(UC_ARM_REG_LR))

    def choose(self, alias=b"egypt1", site=MAP_LEVEL_CALLS[0]):
        self.arm.mem_write(ALIAS, alias + b"\0")
        self.put(STACK, 1, 1)
        self.execute(site, SCENE, STAGE, LEVEL, 0xffffffff, return_from_call=True)
        msg = self.files.pop(SOCIAL_EVENT, None)
        return struct.unpack("<4I", msg) if msg else None

    def update_menu(self):
        self.wall += 1
        self.execute(GAME_POLL, BASE, BEST, 256)

    def click(self, action):
        self.execute(self.menu_buttons[action], action)
        self.update_menu()

    def reply(self, msg, action, record=b""):
        self.files[SOCIAL_REPLY] = struct.pack("<4I", *msg[:3], action) + record
        self.update_menu()


def check_social_levels(output):
    game = SocialGame(output)
    game.packets = tuple(DATA + 0x200 * (i + 1) for i in range(3))
    first, empty, third = game.packets
    game.put(BANK, BASE + 0x17c00e0)
    game.put(BANK + 8, 0x1234, 0x5678)
    game.put(BANK + 0x11d, 3)
    for packet in game.packets:
        game.put(packet, BASE + 0x17c05f0)
        game.put(packet + 0x40, 0x1234, 0x5678)
    game.put(SUNFLOWER + 4, SUNFLOWER + 0x20)
    game.arm.mem_write(SUNFLOWER + 0x20, b"sunflower\0")
    game.put(first + 0xf0, SUNFLOWER, 1)
    game.put(first + 0x138, 0xffffffff, 0xffffffff)
    game.put(third + 0xf0, 123, 456)
    game.put(third + 0x138, 4, 2)
    game.start(10)
    game.execute(0x79BB90, BOARD, 0x14, 5, TYPE, return_from_call=True)
    assert game.stock_calls[-1] == "tactical-cuke"
    # An end-of-battle state change cannot overwrite the selected loadout.
    game.put(first + 0xf0, 0, 0)
    game.tick(10.25)
    game.finish()
    record = next(raw for name, raw in game.files.items() if name.endswith("-1-0.run"))
    assert struct.unpack_from("<I", record, len(record) - 8) == (1,)
    size, *cards = struct.unpack_from("<I32sI32sI32sI", record, LOADOUT)
    assert size == 3 and cards == [
        b"sunflower".ljust(32, b"\0"), 3, bytes(32), 0, b"peashooter".ljust(32, b"\0"), 4
    ]
    assert SOCIAL_EVENT not in game.files
    assert game.choose(b"egypt1_endless") is None
    assert game.launched.pop()[2] == "egypt1_endless"

    menu = game.choose()
    assert menu[1:] == (1, 1, 1) and not game.launched
    game.update_menu()
    assert game.get(WIDGETS + 0x88) == (DIALOG,) and not game.get(APP + 0x1370)[0]
    assert SELF_ROW in game.menu_buttons and "1  我" in game.labels
    elapsed = struct.unpack_from("<I", record, 16)[0]
    scores = struct.pack("<I", 2)
    for friend_id, name, time in ((1, "离线好友", elapsed), (2, "后排好友", elapsed + 1000)):
        scores += struct.pack("<IIII", friend_id, 0, time, 0xFFFFFFFF) + name.encode("utf-32le").ljust(160, b"\0")
    game.reply(menu, 4, scores)
    assert [label for label in game.labels[-30:] if "  " in label][-3:] == [
        "1  离线好友", "2  我", "3  后排好友"
    ]
    game.click(0x100)
    assert SOCIAL_EVENT not in game.files
    game.click(5)
    assert struct.unpack("<4I", game.files.pop(SOCIAL_EVENT)) == (*menu[:3], 0x100)
    game.reply((menu[0] + 1, *menu[1:]), 2, record)
    assert not game.launched
    game.reply(menu, 2, record[:-1])
    assert not game.launched
    game.reply(menu, 2, record)
    assert game.launched.pop() == (SCENE, "egypt", "egypt1", 0xffffffff, 1, 1)
    game.execute(BOARD_LOAD_CALL, BOARD, LEVEL, 0xffffffff, return_from_call=True)
    assert game.get(BOARD + 0x7f0) == (0xffffffff,) and game.get(BOARD + 0x8a0) == (0,)
    assert not game.placed and SOCIAL_EVENT not in game.files
    assert not game.execute("asterAdventureViewFrozen", BASE, BOARD)
    game.execute(BOARD_READY_CALL, BOARD, 3, return_from_call=True)
    assert game.get(BOARD + 0xc0) == (4,)
    assert game.get(BOARD + 0x2c) == (312,)
    matrix = BEST
    for width, scale, zoom, origin in ((1600, 1, 1.2, 312), (1784, 1.38, 1.2, 220),
                                        (730, 1, 1.04, -123), (2560, 1.8, 1.2, 401)):
        game.put(APP + 0x524, width)
        game.arm.mem_write(APP + 0x690, struct.pack("<f", scale))
        game.arm.mem_write(GRAPHICS + 8, struct.pack("<f", origin))
        original = (zoom, 0, width * (1 - zoom), 0, zoom, -20, 0, 0, 1)
        game.arm.mem_write(matrix, struct.pack("<9f", *original))
        game.execute("asterAdventureDrawFormationCamera", BASE, BOARD, GRAPHICS, matrix)
        _, drawn, board_x = game.view_draws[-1]
        assert abs((drawn + 488 * scale) * zoom + original[2] - width / 2) < .001
        assert board_x == 312 + int(drawn - origin)
        assert struct.unpack("<f", game.arm.mem_read(GRAPHICS + 8, 4))[0] == origin
        assert game.get(BOARD + 0x2c) == (312,)
        game.execute("asterAdventureDrawFormationCamera", BASE, TYPE, GRAPHICS, matrix)
        assert game.view_draws[-1][:2] == (TYPE, origin)
        assert bytes(game.arm.mem_read(matrix, 36)) == struct.pack("<9f", *original)

    # An artwork edge takes precedence if a perfectly centered lawn would
    # expose a gap, even though the frame can fit at another horizontal offset.
    game.put(APP + 0x524, 1400)
    game.put(BOARD + 0x34, 1200)
    game.put(BOARD + 0x994, 0)
    game.arm.mem_write(APP + 0x690, struct.pack("<f", 1))
    game.arm.mem_write(GRAPHICS + 8, struct.pack("<f", 0))
    game.arm.mem_write(matrix, struct.pack("<9f", 1.2, 0, 0, 0, 1.2, -20, 0, 0, 1))
    game.execute("asterAdventureDrawFormationCamera", BASE, BOARD, GRAPHICS, matrix)
    assert game.view_draws[-1][1] == 0
    game.put(BOARD + 0x34, 0)
    game.put(APP + 0x524, 1600)
    game.arm.mem_write(GRAPHICS + 8, struct.pack("<f", -53))
    game.execute(VIEWPORT_HIGH_DRAW, BOARD, GRAPHICS)
    assert game.view_draws[-1] == (BOARD, 312, 677)
    game.view_draws.clear()
    game.execute(VIEWPORT_HIGH_DRAW, TYPE, GRAPHICS)
    assert game.view_draws[0][:2] == (TYPE, -53)
    assert not game.runs_plant_actions()
    game.execute(GOLD_TILE_SUN, TYPE, 50)
    assert "gold-sun" not in game.stock_calls
    game.execute(PLAY_NARRATIVE, TYPE, ALIAS, TYPE, ALIAS)
    assert "narrative" not in game.stock_calls
    for site in INITIAL_ACTORS:
        game.execute(site, TYPE)
        assert site not in game.stock_calls
    assert game.placed == [(4, 1, 0, 1, 2, 0, 1, 1)]
    assert SOCIAL_EVENT not in game.files
    assert game.activations == {VIEW_BUTTON: 1, OTHER_HUD: 0, BANK: 1}
    assert game.get(first + 0xf0, 2) == (SUNFLOWER, 1)
    assert game.get(empty + 0xf0, 2) == (0, 0)
    assert game.get(third + 0xf0, 2) == (123, 456)
    for packet, grade in ((first, 3), (third, 4)):
        assert game.get(packet + 0x138, 2) == (grade, 2)
        assert game.get(packet + 0x98) == (2,)
        assert game.arm.mem_read(packet + 0x115, 1) == b"\1"
    game.execute(SEED_BANK_REFRESH, BANK)
    assert "seed-bank-refresh" not in game.stock_calls
    game.execute(CHOOSER_RESTORE_CALL, OTHER_HUD, BEST, return_from_call=True)
    assert "restore-chooser-cards" not in game.stock_calls
    game.put(first + 0x98, 3)
    game.put(first + 0x10c, 8)
    game.execute(SEED_PACKET_DRAW_CALL, first, GRAPHICS, TYPE, return_from_call=True)
    assert game.stock_calls[-1] == ("draw-packet", 2, 17)
    assert game.get(first + 0x98) == (3,) and game.get(first + 0x10c) == (8,)
    game.execute("asterAdventureTranslateTitle", BASE, BEST, ALIAS, BOARD)
    title = "离线好友的阵型 - 0分00秒 · 战术黄瓜 1次\0"
    assert game.get(game.get(BEST)[0], len(title)) == tuple(map(ord, title))
    game.tick(20)
    assert game.stock_calls[-2:] == ["editor-animation", "hud-update"]
    game.execute(BEGIN_BATTLE_ENTRY, BOARD)
    assert "begin-battle" not in game.stock_calls
    for site in BOARD_TOUCH_CALLS:
        assert game.execute(site, BASE, BOARD, ALIAS, TYPE, return_from_call=True)
        assert game.stock_calls[-1] == "button-touch"
    assert "board-touch" not in game.stock_calls
    game.execute(START_BUTTON_EVENT, 0, 0, r5=OTHER_HUD, return_from_call=True)
    assert game.stock_calls[-1] == "dispatch-event" and not game.returned
    game.execute(START_BUTTON_EVENT, 0, 0, r5=VIEW_BUTTON, return_from_call=True)
    assert not game.returned
    game.update_menu()
    assert game.returned == [(SCENE, 13, 0, 1)]
    game.put(SCENE + 0x984, 13)
    game.execute(GAME_POLL, BASE, BEST, 256)
    assert struct.unpack("<4I", game.files.pop(SOCIAL_EVENT)) == (*menu[:3], 3)
    game.execute(SEED_BANK_REFRESH, BANK)
    assert game.stock_calls[-1] == "seed-bank-refresh"
    game.execute(CHOOSER_RESTORE_CALL, OTHER_HUD, BEST, return_from_call=True)
    assert game.stock_calls[-1] == "restore-chooser-cards"
    game.execute(SEED_PACKET_DRAW_CALL, first, GRAPHICS, TYPE, return_from_call=True)
    assert game.stock_calls[-1] == ("draw-packet", 3, 8)

    own_menu = game.choose()
    game.update_menu()
    assert SELF_ROW in game.menu_buttons and 5 in game.menu_buttons
    game.click(17)
    assert SELF_ROW not in game.menu_buttons and 5 not in game.menu_buttons
    game.click(16)
    faster = struct.pack("<I", 4)
    rows = ((1, 0, "一号", 20), (2, 1, "星级好友", 25), (3, 0, "二号", 30), (4, 0, "三号", 40))
    for friend_id, stars, name, time in rows:
        faster += struct.pack("<IIII", friend_id, stars, time, 0xFFFFFFFF) + name.encode("utf-32le").ljust(160, b"\0")
    game.reply(own_menu, 4, faster)
    assert SELF_ROW not in game.menu_buttons and 4 in game.menu_buttons
    game.click(4)
    assert SELF_ROW in game.menu_buttons and "4  我" in game.labels
    game.click(SELF_ROW)
    game.click(5)
    assert SOCIAL_EVENT not in game.files and SOCIAL_REPLY not in game.files
    assert game.launched.pop() == (SCENE, "egypt", "egypt1", 0xffffffff, 1, 1)
    game.execute(BOARD_LOAD_CALL, BOARD, LEVEL, 0xffffffff, return_from_call=True)
    game.execute(BOARD_READY_CALL, BOARD, 3, return_from_call=True)
    assert game.placed == [(4, 1, 0, 1, 2, 0, 1, 1)] * 2
    assert game.activations[BANK] == 1
    assert game.get(first + 0xf0, 2) == (SUNFLOWER, 1)
    assert game.get(third + 0x138, 2) == (4, 2)
    game.execute("asterAdventureTranslateTitle", BASE, BEST, ALIAS, BOARD)
    title = "我的阵型 - 0分00秒 · 战术黄瓜 1次\0"
    assert game.get(game.get(BEST)[0], len(title)) == tuple(map(ord, title))
    game.execute(START_BUTTON_EVENT, 0, 0, r5=VIEW_BUTTON, return_from_call=True)
    game.update_menu()
    game.put(SCENE + 0x984, 13)
    game.update_menu()
    assert struct.unpack("<4I", game.files.pop(SOCIAL_EVENT)) == (*own_menu[:3], 3)
    assert next(raw for name, raw in game.files.items() if name.endswith("-1-0.run")) == record

    game.execute(BEGIN_BATTLE_ENTRY, BOARD)
    assert game.stock_calls.count("begin-battle") == 1
    game.arm.mem_write(BOARD + 0x7fb, b"\1")
    game.start(20.25)
    game.tick(20.5)
    assert game.runs_plant_actions()
    game.execute(GOLD_TILE_SUN, TYPE, 50)
    assert game.stock_calls[-1] == "gold-sun"
    game.execute(PLAY_NARRATIVE, TYPE, ALIAS, TYPE, ALIAS)
    assert game.stock_calls[-1] == "narrative"
    for site in INITIAL_ACTORS:
        game.execute(site, TYPE)
        assert game.stock_calls[-1] == site
    game.execute("asterAdventureViewTouch", BASE, BOARD, ALIAS, TYPE)
    assert game.stock_calls[-1] == "board-touch"

    for tier in range(4):
        game.put(SCENE + 0x984, 13)
        menu = game.choose(b"egypt2", MAP_LEVEL_CALLS[1])
        game.update_menu()
        game.click(16 + tier)
        game.click(2)
        assert game.launched.pop()[2] == "egypt2" and len(game.placed) == 2
        game.put(BOARD + 0x8a0, 1)
        assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        assert game.get(BOARD + 0x7f0) == ((tier - 1) & 0xffffffff,)
        assert game.get(BOARD + 0x8a0) == (int(bool(tier)),)
        game.put(SCENE + 0x984, 6)
        game.wall += 40
        game.update_menu()
        assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        game.put(SCENE + 0x984, 13)
        game.update_menu()
        assert not game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
    game.put(SCENE + 0x984, 13)
    game.choose(site=MAP_LEVEL_CALLS[2])
    game.update_menu()
    game.click(19)
    assert 2 in game.menu_buttons
    game.put(STORE + 0x74, 2)
    game.update_menu()
    assert not game.launched and not game.menu_buttons
    print("Social ARM checks passed: joint ranking, paging, self/friend preview, native star selection and profile isolation")


def check_world_trophy(output):
    game = SocialGame(output)
    game.cleared = False

    def star_module_target(main_cleared=0):
        # Start at the native branch after the current level's completion check.
        stops = (STAR_MODULE_GATE + 4, STAR_MODULE_ENABLED, STAR_MODULE_LOCKED)
        hooks = [game.arm.hook_add(UC_HOOK_CODE, game.stop, begin=BASE + offset, end=BASE + offset)
                 for offset in stops]
        try:
            game.execute(STAR_MODULE_GATE, main_cleared)
            return game.arm.reg_read(UC_ARM_REG_PC) - BASE
        finally:
            for hook in hooks:
                game.arm.hook_del(hook)

    for progress in (1, 2):
        game.trophy_progress[1] = progress
        assert game.choose() is None
        assert game.launched.pop()[2] == "egypt1" and not game.menu_buttons
        game.put(BOARD + 0x7f0, 2)
        game.put(BOARD + 0x8a0, 1)
        assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        assert game.get(BOARD + 0x7f0) == (0xffffffff,) and game.get(BOARD + 0x8a0) == (0,)
    assert star_module_target() == STAR_MODULE_LOCKED
    assert star_module_target(main_cleared=1) == STAR_MODULE_GATE + 4

    game.trophy_progress[1] = 3
    for day, tier in ((1, 1), (2, 3)):
        game.choose(f"egypt{day}".encode())
        game.update_menu()
        game.click(16 + tier)
        game.click(2)
        assert game.launched.pop()[2] == f"egypt{day}"
        assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        assert game.get(BOARD + 0x7f0) == (tier - 1,)
        assert star_module_target() == STAR_MODULE_ENABLED
        game.put(STORE + 0x74, 2)
        assert star_module_target() == STAR_MODULE_LOCKED
        game.put(STORE + 0x74, 1)
        game.arm.mem_write(ALIAS, b"egypt11\0")
        assert star_module_target() == STAR_MODULE_LOCKED

    game.put(STORE + 0x74, 2)
    assert game.choose() is None
    assert game.launched.pop()[2] == "egypt1" and not game.menu_buttons
    game.put(STORE + 0x74, 1)
    game.choose()
    game.update_menu()
    game.click(2)
    assert game.launched.pop()[2] == "egypt1"
    assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
    assert star_module_target() == STAR_MODULE_LOCKED
    print("Egypt World Trophy checks passed: claimed vs pending, both levels, native goal setup, account isolation")


def check_star_dialogs(output):
    game = SocialGame(output)

    def setup(index, mode, mask):
        game.earned = mask
        game.put(BOARD + 0x7f0, index)
        game.put(DIALOG + 0x44, 3, index, mode)
        game.put(DIALOG + 0xa0, 3, index, mode)

    def ribbon(slot):
        game.arm.reg_write(UC_ARM_REG_R6, DIALOG)
        game.arm.reg_write(UC_ARM_REG_R8, slot)
        targets = (STAR_RIBBON_ART + 4, STAR_RIBBON_EMPTY, STAR_RIBBON_GOLD)
        hooks = [game.arm.hook_add(UC_HOOK_CODE, game.stop, begin=BASE + address, end=BASE + address)
                 for address in targets]
        try:
            game.execute(STAR_RIBBON_ART)
            return game.arm.reg_read(UC_ARM_REG_PC) - BASE
        finally:
            for hook in hooks:
                game.arm.hook_del(hook)

    def all_stars_title(index):
        game.execute(STAR_RESULT_TITLE, 0, 0, 0, index, r5=DIALOG, return_from_call=True)
        return bool(game.arm.reg_read(UC_ARM_REG_CPSR) & (1 << 30))

    setup(2, 3, 0b001)
    assert [ribbon(i) for i in range(3)] == [STAR_RIBBON_GOLD, STAR_RIBBON_EMPTY, STAR_RIBBON_ART + 4]
    setup(2, 1, 0b101)
    assert ribbon(1) == STAR_RIBBON_EMPTY and not all_stars_title(2)
    setup(1, 1, 0b101)
    assert ribbon(2) == STAR_RIBBON_GOLD and all_stars_title(1)
    setup(2, 2, 0b111)
    assert all_stars_title(2)
    game.arm.mem_write(ALIAS, b"tutorial4\0")
    setup(2, 1, 0b001)
    assert ribbon(1) == STAR_RIBBON_ART + 4 and all_stars_title(2)
    print("Star dialog checks passed: out-of-order ribbons, completion titles and stock fallback")

def check_star_advance(output, engine=None):
    for index, earned, mode, next_index in (
            (0, 0, 1, 1), (0, 0b001, 1, 1), (0, 0b011, 1, 2),
            (2, 0b101, 1, 1), (1, 0b110, 2, 0), (2, 0b011, 1, -1),
            (1, 0b101, 1, -1), (0, 0, 0, -2), (0, 0, 3, -2)):
        game = SocialGame(output, engine=engine)
        game.choose(b"egypt2")
        game.update_menu()
        game.click(17 + index)
        game.click(2)
        game.put(SCENE + 0x984, 6)
        assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        game.earned = earned
        page = DIALOG + 0x240
        game.put(page, 4)
        game.put(page + 0x44, 3, index, mode)
        game.put(DIALOG + 0xe0, page, page + 0x88, page + 0x88, 0)

        def branch_target(site, targets, **registers):
            hooks = [game.arm.hook_add(UC_HOOK_CODE, game.stop, begin=BASE + addr,
                                       end=BASE + addr) for addr in targets]
            try:
                game.execute(site, **registers)
                return game.arm.reg_read(UC_ARM_REG_PC) - BASE
            finally:
                for hook in hooks:
                    game.arm.hook_del(hook)

        game.arm.reg_write(UC_ARM_REG_R9, page)
        draw = branch_target(STAR_NEXT_BUTTON, (STAR_NEXT_BUTTON + 4, STAR_SHOW_CONTINUE, STAR_SHOW_NEXT))
        assert draw == { -2: STAR_NEXT_BUTTON + 4, -1: STAR_SHOW_CONTINUE }.get(next_index, STAR_SHOW_NEXT)
        click = branch_target(STAR_NEXT_CLICK, (STAR_NEXT_CLICK + 4, STAR_CLICK_CONTINUE), r5=DIALOG)
        assert click == (STAR_CLICK_CONTINUE if next_index == -1 else STAR_NEXT_CLICK + 4)
        assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        assert game.get(BOARD + 0x7f0) == (next_index if next_index >= 0 else index,)
        assert game.earned == earned
    print("Next star checks passed: first missing, skip earned, wrap, all earned, retry and intro")


def check_campaign_levels(output):
    catalog = json.loads((output / "adventure-levels.json").read_bytes())
    for level in ("pirate1", "iceage1", "lostcity3"):
        assert catalog[level][1:] == [3, True]
    for level in ("egypt8", "skycity9", "skycity_challenge_fish_a", "skycity_challenge_pooyan_a"):
        assert catalog[level][1:] == [1, False]
    assert "egypt_dangerroom" not in catalog

    game = SocialGame(output)
    game.arm.mem_write(STAGE_TEXT, b"pirate\0")
    game.cleared = False
    assert game.choose(b"pirate8", MAP_LEVEL_CALLS[1]) is None
    assert game.launched.pop() == (SCENE, "pirate", "pirate8", 0xffffffff, 1, 1)
    game.update_menu()
    assert not game.menu_buttons and SOCIAL_EVENT not in game.files
    game.trophy_progress[1] = 3
    msg = game.choose(b"pirate8", MAP_LEVEL_CALLS[1])
    assert msg[2] == catalog["pirate8"][0]
    game.update_menu()
    game.click(19)
    game.click(2)
    assert game.launched.pop()[1:3] == ("pirate", "pirate8")
    assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
    assert game.get(BOARD + 0x7f0) == (2,) and game.get(BOARD + 0x8a0) == (1,)
    from unicorn.arm_const import UC_ARM_REG_FP
    descriptions_branches = (STAR_DESCRIPTIONS_ENABLED, STAR_DESCRIPTIONS_GATE + 4)
    for address in descriptions_branches:
        game.arm.hook_add(UC_HOOK_CODE, game.stop, begin=BASE + address, end=BASE + address)
    game.arm.reg_write(UC_ARM_REG_FP, STACK + 0x40)
    for query, expected in ((BOARD + 0xc4, STAR_DESCRIPTIONS_ENABLED),
                            (STAGE, STAR_DESCRIPTIONS_GATE + 4)):
        game.put(STACK + 4, query)
        game.arm.reg_write(UC_ARM_REG_CPSR, game.arm.reg_read(UC_ARM_REG_CPSR) | (1 << 30))
        game.execute(STAR_DESCRIPTIONS_GATE)
        assert game.arm.reg_read(UC_ARM_REG_PC) - BASE == expected

    game = SocialGame(output)
    game.cleared = False
    msg = game.choose(b"egypt8")
    game.update_menu()
    scores = struct.pack("<IIIII", 1, 1, 1, 12000, 0xFFFFFFFF) + b"A\0\0\0".ljust(160, b"\0")
    game.reply(msg, 4, scores)
    assert game.menu_buttons.keys() >= {1, 2, 17, 0x100}
    assert not game.menu_buttons.keys() & {5, 16, 18, 19}
    game.click(2)
    assert game.launched.pop()[1:3] == ("egypt", "egypt8")
    game.put(PROPERTIES + 0x20, DATA + 0xa500 + 12)
    assert game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
    assert game.get(BOARD + 0x7f0) == (0,) and game.get(BOARD + 0x8a0) == (1,)
    game.start(10, b"egypt8", stars=1)
    game.tick(10.25)
    game.execute(DRAW_CALL, BOARD, GRAPHICS, return_from_call=True)
    assert not game.rectangles
    game.finish()
    assert game.best(catalog["egypt8"][0], stars=1)[5] == 0
    assert not game.best(stars=1)
    print(f"Campaign checks passed: {len(catalog)} levels, single-star launch, preview gates and record isolation")


def check_social_settings(output):
    game = SocialGame(output, social_enabled=False)
    assert game.choose() is None and game.launched.pop()[2] == "egypt1"
    assert not game.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
    game.start(10)
    game.tick(10.5)
    game.execute(DRAW_CALL, BOARD, GRAPHICS, return_from_call=True)
    game.finish()
    assert not game.rectangles and not game.best()

    game.execute(SETTINGS_CLICK, DIALOG, 1050)
    assert game.stock_calls[-1] == ("settings-click", 1050)
    game.execute(SETTINGS_CLICK, DIALOG, 1060)
    assert game.stock_calls[-1] == ("settings-click", 9)
    game.execute(SETTINGS_CLICK, DIALOG, 1062)
    assert game.stock_calls[-1] == "settings-refresh"
    assert game.files[SOCIAL_SETTING] == SOCIAL_ON
    assert game.choose()[1:] == (1, 1, 1)
    game.update_menu()
    game.click(1)
    game.start(20)
    game.tick(20.25)
    game.finish()
    assert game.best()[4] == 250

    reopened = SocialGame(output, social_enabled=False)
    reopened.files.update(game.files)
    assert reopened.choose()[1:] == (1, 1, 1)
    game.execute(SETTINGS_CLICK, DIALOG, 1061)
    assert game.files[SOCIAL_SETTING] == struct.pack("<III", 0x31434f53, 0, 0xffffffff)
    assert game.choose() is None and game.launched.pop()[2] == "egypt1"
    assert game.best()[4] == 250
    for data in (game.files[SOCIAL_SETTING], SOCIAL_ON + b"invalid"):
        reopened = SocialGame(output, social_enabled=False)
        reopened.files[SOCIAL_SETTING] = data
        assert reopened.choose() is None and reopened.launched.pop()[2] == "egypt1"
    print("Social settings checks passed: default stock flow, persistence, opt-out and existing records")


def check_friend_sun(output):
    class SunGame(SocialGame):
        shop, stock_tab, products, node = (DATA + i for i in (0x10000, 0x10200, 0x10400, 0x10600))

        def __init__(self, output, **options):
            super().__init__(output, **options)
            self.arm.mem_map(DATA + 0x10000, 0x10000)
            self.controls = {}
            self.next_control = DATA + 0x11000
            self.put(WIDGET_VT + 0x8c, BASE + 0x1313b1c)

        def native(self, arm, address, size, context):
            off = address - BASE
            a, b, c, _ = (arm.reg_read(reg) for reg in ARGS)
            result = 0
            if off == STOCK_SUN_PURCHASE:
                self.stock_calls.append(("purchase-sun", a, b))
                self.put(APP + 0x12cc, self.shop)
                self.put(self.shop, WIDGET_VT, self.node)
                self.put(self.shop + 0xc4, b, self.products)
                self.put(self.node + 8, self.stock_tab)
                self.put(self.stock_tab, BASE + 0x17b8d20)
                self.put(BASE + 0x17b8d20 + 0x8c, BASE + 0x1313b1c)
                self.put(self.stock_tab + 0x28, 350, 60, 130, 62)
                self.put(self.products, WIDGET_VT)
                self.put(self.products + 0x28, 130, 113, 610, 380)
                self.put(self.products + 0x4c, 1)
                self.put(BOARD + 0x8d5, 1)
            elif off == STOCK_SUN_CLOSE + 4:
                assert a == APP and not self.controls
                self.put(APP + 0x12cc, 0)
                self.put(BOARD + 0x8d5, 0)
                stack = arm.reg_read(UC_ARM_REG_SP)
                arm.reg_write(UC_ARM_REG_LR, self.get(stack + 20)[0])
                arm.reg_write(UC_ARM_REG_SP, stack + 24)
            elif off == 0x14c1a7c and a == 0x1f8:
                while True:
                    result = self.next_control
                    self.next_control += 0x200
                    if self.next_control >= DATA + 0x20000:
                        self.next_control = DATA + 0x11000
                    if result not in self.controls:
                        break
            elif off == 0x7e8db4:
                self.put(a, WIDGET_VT)
                self.controls[a] = b, c
            elif off in (0x112f868, 0x7e9028, 0x7e90dc):
                pass
            elif off == 0x10004 and b in self.controls:
                del self.controls[b]
            elif off in (0x1313b68, 0x13165b4, 0x1315be4) and (a in self.controls or b in self.controls):
                pass
            elif off == 0x1313b1c:
                self.put(a + 0x4c, b)
            elif off == SHOP_SCROLLBAR_VISIBLE:
                result = 1
            else:
                return super().native(arm, address, size, context)
            arm.reg_write(UC_ARM_REG_R0, result)
            arm.reg_write(UC_ARM_REG_PC, arm.reg_read(UC_ARM_REG_LR))

        def click(self, action):
            listener = next(listener for key, listener in self.controls.values() if key == action)
            function = self.get(self.get(listener)[0] + 8)[0]
            self.execute(function - BASE, listener, action)
            self.update_menu()

        def actions(self):
            return {action for action, _ in self.controls.values() if action}

    def open_gifts(game, friend_ids):
        game.execute(SUN_BUTTON_OPEN, APP, 1, return_from_call=True)
        game.update_menu()
        request = struct.unpack("<4I", game.files.pop(SOCIAL_EVENT))
        assert request[1:] == (1, 1, 5)
        roster = struct.pack("<I", len(friend_ids)) + b"".join(
            struct.pack("<II", id_, 0xFFFFFFFF) + "离线好友".encode("utf-32le").ljust(160, b"\0")
            for id_ in friend_ids)
        game.wall += 1
        game.reply(request, 5, roster)
        assert game.get(APP + 0x12cc) == (game.shop,)
        assert game.get(game.products + 0x4c) == (0,)
        assert game.arm.mem_read(BOARD + 0x8d5, 1) == b"\1"

    off = SunGame(output, social_enabled=False)
    off.start(10)
    off.execute(SUN_BUTTON_OPEN, APP, 1, return_from_call=True)
    assert off.stock_calls[-1] == ("purchase-sun", APP, 1) and not off.menu_buttons

    game = SunGame(output)
    game.wall = 1_700_000_000
    game.start(10)
    game.put(BOARD + 0x12c, 75)
    open_gifts(game, [12, 15, 17, 19, 21, 25])
    assert set(range(16, 22)) <= game.actions()
    game.click(2)
    assert game.actions() == {1, 2} and game.get(game.products + 0x4c) == (1,)
    assert game.execute(SHOP_SCROLLBAR_CALL, game.products, return_from_call=True) == 1
    game.click(1)
    assert set(range(16, 22)) <= game.actions()
    assert game.execute(SHOP_SCROLLBAR_CALL, game.products, return_from_call=True) == 0
    assert game.stock_calls.count(("purchase-sun", APP, 1)) == 1
    game.click(16)
    game.fail_rename = True
    game.click(3)
    assert game.get(BOARD + 0x12c) == (75,) and GIFT_LEDGER not in game.files
    game.fail_rename = False
    game.sun_limit = 90
    game.click(3)
    assert game.get(BOARD + 0x12c) == (75,) and GIFT_LEDGER not in game.files
    game.sun_limit = 9990
    game.click(3)
    assert game.get(BOARD + 0x12c) == (100,) and not game.controls
    assert game.arm.mem_read(BOARD + 0x8d5, 1) == b"\0"
    assert struct.unpack("<8I", game.files[GIFT_LEDGER])[2:4] == (1, 12)
    game.tick(10.25)
    game.finish()
    assert not game.best()

    reopened = SunGame(output)
    reopened.files.update(game.files)
    reopened.wall = game.wall
    reopened.start(20)
    reopened.put(BOARD + 0x12c, 75)
    open_gifts(reopened, [12, 15, 17, 19, 21, 25])
    for action in range(16, 20):
        reopened.click(action)
    reopened.click(20)
    reopened.click(3)
    assert reopened.get(BOARD + 0x12c) == (175,)
    assert struct.unpack("<8I", reopened.files[GIFT_LEDGER])[2:] == (5, 12, 15, 17, 19, 21)
    open_gifts(reopened, [25])
    assert reopened.actions() == {1, 2}
    reopened.click(2)
    assert reopened.get(reopened.products + 0x4c) == (1,)
    reopened.execute(STOCK_SUN_CLOSE, APP)
    reopened.wall += 86400
    open_gifts(reopened, [12])
    reopened.click(16)
    reopened.click(3)
    assert reopened.get(BOARD + 0x12c) == (200,)
    assert struct.unpack("<8I", reopened.files[GIFT_LEDGER])[2:4] == (1, 12)

    open_gifts(reopened, list(range(20, 28)))
    reopened.click(16)
    reopened.click(5)
    reopened.click(17)
    reopened.click(3)
    assert reopened.get(BOARD + 0x12c) == (250,)
    assert struct.unpack("<8I", reopened.files[GIFT_LEDGER])[2:6] == (3, 12, 20, 27)
    print("Friend sun checks passed: six cards, paging, daily cap, stock purchase and assisted records")


def check_battle_tools(output):
    game = Game(output)
    game.files[COMMAND] = b"R"
    game.start(10)
    assert COMMAND not in game.files
    game.tick(10.25)
    assert game.clears == 0
    game.files[COMMAND] = b"C\n"
    game.tick(10.75)
    assert game.clears == 0 and COMMAND not in game.files and CLAIMED not in game.files
    game.files[COMMAND] = b"C"
    game.tick(11.25)
    game.tick(11.5)
    assert game.clears == 1
    game.files[COMMAND] = b"R"
    game.tick(11.75)
    game.tick(12.25)
    assert game.clears == 2
    game.tick(12.75)
    assert game.clears == 3
    game.put(BOARD + 0x8d5, 1)
    game.files[COMMAND] = b"S"
    game.tick(13.75)
    assert game.clears == 3
    game.put(BOARD + 0x8d5, 0)
    game.tick(14.0)
    game.tick(14.25)
    assert game.clears == 3
    game.finish()
    assisted = next(p for p in game.files if "adventure-test-" in p)
    assert struct.unpack_from("<6I", game.files[assisted])[5] == 1
    assert SOCIAL_EVENT not in game.files
    assert not game.best() and not game.execute("asterAdventureLast", BASE)

    game.start(20)
    game.tick(20.25)
    game.finish()
    assert game.clears == 3 and game.best()[4] == 250
    game.start(30, b"egypt1_endless")
    game.files[COMMAND] = b"C"
    game.tick(30.25)
    assert game.clears == 3
    game.start(40, b"egypt2")
    game.tick(40.25)
    assert game.clears == 3 and COMMAND not in game.files
    print("A251 WSA battle-tools checks passed: one-shot, repeat, stop, pause, stage and save isolation")


def check_user_redemption_entry(output):
    from build_aster_adventure_records import SHOP_CODE_CARD, SHOP_CODE_SKIP

    for enabled in (False, True):
        game = Game(output, social_enabled=enabled)
        assert game.execute("asterUserHasCodeEntry", BASE) == enabled
        destination = SHOP_CODE_SKIP if enabled else SHOP_CODE_CARD + 4
        game.arm.hook_add(UC_HOOK_CODE, game.stop, begin=BASE + destination, end=BASE + destination)
        result = game.execute(SHOP_CODE_CARD, 123)
        assert game.arm.reg_read(UC_ARM_REG_PC) == BASE + destination
        assert result == (123 if enabled else 304)
    print("User gift-code entry checks passed: hide the shop card on opt-in, keep the stock card on opt-out")


def check_user_map_dispatch(output):
    from build_aster_adventure_records import (USER_MAP_DRAW_SLOT, USER_MAP_HIT_SLOT, USER_MAP_TOUCH_SLOT,
                                               USER_MAP_NO_HIT, USER_MAP_NO_TOUCH, USER_MAP_OVERLAY_SLOT)

    game = Game(output, social_enabled=True)
    game.put(BASE + game.symbols["_ZN12_GLOBAL__N_14userE"], STAGE)
    # This other map widget must still miss instead of claiming the touch.
    other_hit, = game.get(BASE + 0x17C7EF4)
    assert other_hit == USER_MAP_NO_HIT and game.execute(other_hit, BOARD, 123, 456) == 0
    assert game.execute(USER_MAP_NO_TOUCH, BOARD, 123, 456, 1) == 0
    draw, hit, touch = (game.get(BASE + slot)[0]
                        for slot in (USER_MAP_DRAW_SLOT, USER_MAP_HIT_SLOT, USER_MAP_TOUCH_SLOT))
    assert draw != USER_MAP_NO_HIT and hit != USER_MAP_NO_HIT and touch != USER_MAP_NO_TOUCH
    assert game.execute(hit, BOARD, 123, 456) == 0
    assert game.execute(touch, BOARD, 123, 456, 1) == 0
    entries = []

    def record_draw(arm, address, size, context):
        entries.append(tuple(arm.reg_read(reg) for reg in ARGS[:3]))

    draw_target = BASE + game.symbols["asterUserDraw"]
    game.arm.hook_add(UC_HOOK_CODE, record_draw, begin=draw_target, end=draw_target)
    game.execute(draw, BOARD, 123)
    game.execute(game.get(BASE + USER_MAP_OVERLAY_SLOT)[0], BOARD + 16, 456)
    assert entries == [(BASE, BOARD, 123), (BASE, BOARD, 456)]
    print("User button vtable hooks preserve the other world-map hit test")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--battle-tools", action="store_true")
    parser.add_argument("--social-levels", action="store_true")
    parser.add_argument("--star-advance-engine", type=Path)
    args = parser.parse_args()
    if args.star_advance_engine:
        check_star_advance(args.output, args.star_advance_engine)
        raise SystemExit(0)
    main(args.output)
    check_egypt_endless_plant_updates(args.output)
    if args.social_levels:
        check_social_levels(args.output)
        check_world_trophy(args.output)
        check_star_dialogs(args.output)
        if "asterAdventureNextStar" in Game(args.output).symbols:
            check_star_advance(args.output)
        check_campaign_levels(args.output)
        check_social_settings(args.output)
        check_friend_sun(args.output)
        check_user_redemption_entry(args.output)
        check_user_map_dispatch(args.output)
    if args.battle_tools:
        check_battle_tools(args.output)
