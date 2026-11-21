"""Exercise the A251 adventure hooks on ARM with bounded native service doubles."""

import argparse
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM
from unicorn.arm_const import (
    UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
    UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
)

from build_aster_adventure_records import (
    DRAW, DRAW_CALL, KILL_ZOMBIES, SET_PHASE, START_CALL, UPDATE, WIN, WIN_CALL,
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
        for offset, value in ((0xac, 1), (0xb0, 4), (0xb4, 1), (0x16c, 0x0101),
                              (0x170, 2), (0x174, 4), (0x1c0, 0xffffffff)):
            self.put(PLANT + offset, value)
        self.arm.hook_add(UC_HOOK_CODE, self.native)

    def put(self, addr, *values):
        self.arm.mem_write(addr, struct.pack("<" + "I" * len(values), *values))

    def get(self, addr, count=1):
        return struct.unpack("<" + "I" * count, self.arm.mem_read(addr, count * 4))

    def string(self, addr):
        return bytes(self.arm.mem_read(addr, 128)).split(b"\0", 1)[0].decode("ascii")

    def execute(self, where, *args, return_from_call=False, r4=0):
        from unicorn.arm_const import UC_ARM_REG_R4
        if isinstance(where, str):
            where = self.symbols[where]
        self.arm.reg_write(UC_ARM_REG_SP, STACK)
        self.arm.reg_write(UC_ARM_REG_LR, RETURN)
        self.arm.reg_write(UC_ARM_REG_R4, r4)
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
    args = parser.parse_args()
    main(args.output)
    if args.battle_tools:
        check_battle_tools(args.output)
