"""Exercise the A251 adventure hooks on ARM with bounded native service doubles."""

import argparse
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM
from unicorn.arm_const import (
    UC_ARM_REG_C1_C0_2, UC_ARM_REG_CPSR, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC,
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R6,
    UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_SP,
)

from build_aster_adventure_records import (
    BEGIN_BATTLE_ENTRY, BEGIN_BATTLE_TARGET, BOARD_LOAD, BOARD_LOAD_CALL, BOARD_READY_CALL,
    BOARD_UPDATE_DONE, DRAW, DRAW_CALL, GAME_POLL, GAME_POLL_TARGET, KILL_ZOMBIES,
    BOARD_TOUCH_CALLS, BOARD_TOUCH, DISPATCH_EVENT, LAUNCH_LEVEL, MAP_LEVEL_CALLS,
    SET_PHASE, STAR_MODULE_ENABLED, STAR_MODULE_GATE, STAR_MODULE_LOCKED,
    STAR_RESULT_TITLE, STAR_RIBBON_ART, STAR_RIBBON_EMPTY, STAR_RIBBON_GOLD,
    START_BUTTON_EVENT, START_CALL, UPDATE, WIN, WIN_CALL,
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


class Game:
    def __init__(self, output):
        self.arm = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.arm.mem_map(BASE, 0x2000000)
        self.arm.mem_map(DATA, 0x10000)
        with (output / "libSrc-adventure-records.so").open("rb") as f:
            for seg in ELFFile(f).iter_segments():
                if seg["p_type"] == "PT_LOAD" and seg["p_filesz"]:
                    self.arm.mem_write(BASE + seg["p_vaddr"], seg.data())
        with (output / "adventure-records.elf").open("rb") as f:
            self.symbols = {s.name: s["st_value"] for s in
                            ELFFile(f).get_section_by_name(".symtab").iter_symbols()}
        self.arm.reg_write(UC_ARM_REG_C1_C0_2, 0xf00000)
        self.arm.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.files = {}
        self.descriptors = {}
        self.opens = []
        self.rectangles = []
        self.renames = 0
        self.fail_rename = False
        self.stock_calls = []
        self.logs = []
        self.clears = 0
        self.put(BASE + 0x1821674, DATA + 4)
        self.put(DATA + 4, APP)
        self.put(APP + 0x6bc, BOARD)
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
        elif off == 0x7a98dc:
            assert a == STORE
            result = PROFILE
        elif off == 0x11d74b4:
            result = REGISTRY
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
        else:
            return
        arm.reg_write(UC_ARM_REG_R0, result)
        arm.reg_write(UC_ARM_REG_PC, arm.reg_read(UC_ARM_REG_LR))

    def time(self, seconds):
        self.arm.mem_write(CLOCK + 0x24, struct.pack("<f", seconds))

    def start(self, t, level=b"egypt1", stars=0):
        self.arm.mem_write(ALIAS, level + b"\0")
        self.arm.mem_write(BOARD + 0xcc, struct.pack("<f", t))
        self.put(BOARD + 0x7f4, 0)
        self.put(BOARD + 0x7f0, (stars - 1) & 0xffffffff)
        self.put(BOARD + 0x8a0, int(bool(stars)))
        self.time(t)
        self.execute(START_CALL, BOARD, 5, r4=BOARD, return_from_call=True)

    def tick(self, seconds):
        self.time(seconds)
        self.execute(UPDATE, BOARD)

    def finish(self):
        self.execute(WIN_CALL, BOARD, return_from_call=True)

    def best(self, day=1, stars=0):
        if not self.execute("asterAdventureBest", BASE, day, stars, BEST):
            return None
        return self.get(BEST, 6)


def check_egypt_endless_plant_updates(output):
    game = Game(output)
    flag = BOARD + 0x7fb

    def enabled():
        return game.arm.mem_read(flag, 1)[0]

    def runs_plant_actions():
        action = BASE + 0x4bf3d8
        # Execute the native Plant::Update gate for a plant whose actions are active.
        game.arm.mem_write(PLANT + 0xf0, b"\1")
        game.arm.reg_write(UC_ARM_REG_R7, PLANT)
        hook = game.arm.hook_add(UC_HOOK_CODE, game.stop, begin=action, end=action)
        try:
            game.arm.emu_start(BASE + 0x4bfed0, BASE + 0x4bfef8, count=32)
            return game.arm.reg_read(UC_ARM_REG_PC) == action
        finally:
            game.arm.hook_del(hook)

    assert not runs_plant_actions()
    game.start(10, b"egypt_dangerroom")
    assert enabled() == 1 and runs_plant_actions()
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
    assert enabled() == 1 and runs_plant_actions()

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
    assert len(game.rectangles) > 10
    assert game.get(GRAPHICS + 0x4c, 4) == (13, 14, 15, 255)
    game.finish()
    assert game.best() == (1, 1, 1, 0, 500, 1)
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
    assert game.best()[4] == 500 and game.renames == 1
    assert game.get(game.execute("asterAdventureLast", BASE) + 16)[0] == 750

    game.start(40)
    game.tick(40.25)
    game.fail_rename = True
    game.finish()
    assert game.best()[4] == 500 and not any(p.endswith(".tmp") for p in game.files)
    game.fail_rename = False
    game.start(45)
    game.tick(45.25)
    game.finish()
    assert game.best()[4] == 250 and game.renames == 2

    game.start(50, b"egypt2", stars=2)
    game.tick(50.25)
    game.finish()
    assert game.best(2, 2) == (1, 1, 2, 2, 250, 1)
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
    game.files[path] += b"corrupt"
    assert not game.best()
    assert game.stock_calls.count("start") == 8 and game.stock_calls.count("win") == 9
    assert game.logs.count("clear") == 5
    print("A251 ARM checks passed: timer, HUD, native flow, formation, best time, save failure, isolation")


SCENE, DIALOG, PROPERTIES = (DATA + offset for offset in (0x9000, 0xa000, 0xa400))
WIDGETS, WIDGET_VT, APP_VT = (DATA + offset for offset in (0xa800, 0xaa00, 0xac00))
STAGE_TEXT, STAGE, LEVEL, STRING_AREA = (DATA + offset for offset in (0xb000, 0xb100, 0xb104, 0xb200))
VIEW_BUTTON, OTHER_HUD, ANCHOR = (DATA + offset for offset in (0xdc00, 0xdd00, 0xde00))


class SocialGame(Game):
    def __init__(self, output):
        super().__init__(output)
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
        self.menu_buttons = {}
        self.cleared = True
        self.trophy_progress = {}
        self.earned = 0
        self.put(APP + 0x524, 1600, 1000)
        self.put(APP + 0x698, 0x3f800000)
        self.put(APP + 0x2c0, WIDGETS)
        self.put(APP, APP_VT)
        self.put(APP_VT + 0xa8, BASE + 0x10004)
        self.put(WIDGETS, WIDGET_VT)
        for slot, address in ((0x10, 0x13165b4), (0x14, 0x1315be4), (0x38, 0x1316670),
                              (0x2c, 0x1316a08), (0xac, 0x1313b68)):
            self.put(WIDGET_VT + slot, BASE + address)
        self.put(PROPERTIES + 0x1c, DATA + 0xa500, DATA + 0xa500 + 3 * 12)
        self.put(VIEW_BUTTON + 0xf4, DATA + 0xdf00)
        arm_x_y = struct.unpack("<2I", struct.pack("<2f", 100.0, 100.0))
        self.put(ANCHOR, *arm_x_y)

    def native(self, arm, address, size, context):
        off = address - BASE
        a, b, c, d = (arm.reg_read(reg) for reg in ARGS)
        stack = arm.reg_read(UC_ARM_REG_SP)
        out = 0
        if off == 0x147974:
            self.put(a, self.wall, 0)
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
            assert alias in {"egypt1", "egypt2", "egypt11"}
            if alias == "egypt11":
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
            assert a == DIALOG and b < 1600 and c < 1000
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
            arm.mem_write(DATA + 0xe000, bytes(content) + b"\0\0\0\0")
        elif off == 0x97714c:
            key = self.string(self.get(a)[0])
            assert key != "UIStartGameButton"
            out = OTHER_HUD
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
            out = DATA + 0xe100
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
        elif off == BEGIN_BATTLE_TARGET:
            self.stock_calls.append("begin-battle")
        elif off == SET_PHASE and b in (2, 3, 4):
            self.put(a + 0xc0, b)
        elif off == GAME_POLL_TARGET:
            pass
        elif off == 0x20cea8:
            assert b == PLANT_STORE and self.string(self.get(c)[0]) == "peashooter"
            self.put(a, 123, 456)
        elif off == 0x21ab00:
            assert a == BOARD and self.get(d, 2) == (123, 456)
            self.placed.append((b, c, *self.get(stack, 6)))
            out = PLANT
        elif off == 0x352498:
            assert self.finished_boards and self.get(BOARD + 0xc0) == (9,)
            self.returned.append((a, b, c, d))
        elif off == 0x226770:
            assert a == BOARD and self.get(a + 0x7f4) == (7,)
            self.put(a + 0xc0, 9)
            self.finished_boards += 1
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
    game.start(10)
    game.tick(10.25)
    game.finish()
    record = next(raw for name, raw in game.files.items() if name.endswith("-1-0.run"))
    assert SOCIAL_EVENT not in game.files
    assert game.choose(b"egypt1_endless") is None
    assert game.launched.pop()[2] == "egypt1_endless"

    menu = game.choose()
    assert menu[1:] == (1, 1, 1) and not game.launched
    game.update_menu()
    assert game.get(WIDGETS + 0x88) == (DIALOG,) and not game.get(APP + 0x1370)[0]
    elapsed = struct.unpack_from("<I", record, 16)[0]
    scores = struct.pack("<III", 1, 0, elapsed) + "离线好友".encode("utf-32le").ljust(160, b"\0")
    game.reply(menu, 4, scores)
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
    assert game.placed == [(4, 1, 0, 1, 2, 0, 1, 1)]
    assert SOCIAL_EVENT not in game.files
    assert game.activations == {VIEW_BUTTON: 1, OTHER_HUD: 0}
    game.execute("asterAdventureTranslateTitle", BASE, BEST, ALIAS, BOARD)
    title = "离线好友的阵型 - 0分00秒\0"
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
    game.execute(BEGIN_BATTLE_ENTRY, BOARD)
    assert game.stock_calls.count("begin-battle") == 1
    game.execute("asterAdventureViewTouch", BASE, BOARD, ALIAS, TYPE)
    assert game.stock_calls[-1] == "board-touch"

    for tier in range(4):
        game.put(SCENE + 0x984, 13)
        menu = game.choose(b"egypt2", MAP_LEVEL_CALLS[1])
        game.update_menu()
        game.click(16 + tier)
        game.click(2)
        assert game.launched.pop()[2] == "egypt2" and len(game.placed) == 1
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
    game.cleared = False
    game.choose(site=MAP_LEVEL_CALLS[2])
    game.update_menu()
    game.click(19)
    assert 2 not in game.menu_buttons
    game.put(STORE + 0x74, 2)
    game.update_menu()
    assert not game.launched and not game.menu_buttons
    print("Social ARM checks passed: offline scores, preview placement and cleanup, native star selection, locked levels and profile isolation")


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
        game.choose()
        game.update_menu()
        game.click(19)
        assert 2 not in game.menu_buttons
        game.click(1)
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
    game.choose()
    game.update_menu()
    game.click(19)
    assert 2 not in game.menu_buttons
    assert not game.launched
    game.click(1)
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
    game.arm.mem_write(ALIAS, b"pirate1\0")
    setup(2, 1, 0b001)
    assert ribbon(1) == STAR_RIBBON_ART + 4 and all_stars_title(2)
    print("Star dialog checks passed: out-of-order ribbons, completion titles and stock fallback")


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--battle-tools", action="store_true")
    parser.add_argument("--social-levels", action="store_true")
    args = parser.parse_args()
    main(args.output)
    check_egypt_endless_plant_updates(args.output)
    if args.social_levels:
        check_social_levels(args.output)
        check_world_trophy(args.output)
        check_star_dialogs(args.output)
    if args.battle_tools:
        check_battle_tools(args.output)
