"""Execute Aster's installed pickup gates, timer and desktop shortcut dispatch."""
import argparse
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC,
                               UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP)


def check(engine, base):
    vm = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    vm.reg_write(UC_ARM_REG_C1_C0_2, 0xf << 20)
    vm.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    vm.mem_map(base, 0x1c00000)
    with engine.open("rb") as handle:
        for segment in ELFFile(handle).iter_segments():
            if segment["p_type"] == "PT_LOAD":
                vm.mem_write(base + segment["p_vaddr"], segment.data())

    mem = 0x6000000
    vm.mem_map(mem, 0x10000)
    holder, app, board, driver, item, touch, name, dispatcher, listener, rect, table = (
        mem + i * 0x1000 for i in range(11)
    )
    modal, cast, rectangle, stop = mem + 0xc000, mem + 0xc004, mem + 0xc008, mem + 0xc00c
    missing_view_setting = mem + 0xc010
    clock = mem + 0xd000
    stack = mem + 0xff00

    def put(address, word):
        vm.mem_write(address, struct.pack("<I", word))

    def get(address):
        return struct.unpack("<I", vm.mem_read(address, 4))[0]

    def level(label):
        vm.mem_write(name, label.encode("ascii") + b"\0")

    put(base + 0x1821674, holder)
    put(holder, app)
    put(base + 0x18216bc, holder)
    put(base + 0x1822ebc, missing_view_setting)
    put(app, table)
    put(table + 0x12c, modal)
    put(app + 0x690, 0x3f800000)
    put(app + 0x6bc, board)
    put(driver + 0x44, app)
    put(board + 0xc0, 4)
    put(board + 0xc4, name)
    put(board + 0x93c, dispatcher)
    put(dispatcher, listener)
    put(dispatcher + 4, listener + 0x48)
    put(listener + 12, item)
    put(item + 8, item)
    put(item + 12, 1)
    put(item + 0x160, 0x3f000000)  # 0.5 second pickup deadline
    put(clock + 0x24, 0x3f800000)
    auto_enabled = base + 0x1b048dc
    vm.mem_write(base + 0x1b048ec, b"\x01")  # settings already loaded
    vm.mem_write(auto_enabled, b"\x01")
    vm.mem_write(rect, struct.pack("<4I", 100, 200, 40, 40))

    def fixture(kind, flagged=False):
        vtable = base + kind
        assert get(vtable + 0xe4) == 0x27b584
        put(item, vtable)
        put(vtable + 0xe4, base + 0x27b584)  # emulate ELF pointer relocation
        put(vtable + 0x10, cast)
        put(vtable + 0x90, rectangle)
        put(item + 0x94, 0)
        put(item + 0x168, int(flagged))
        put(item + 0x16c, 0)
        put(item + 0x8c, 0x40 if flagged else 0)

    events = []
    expected_terminal = stop
    def on_code(vm, pc, size, _):
        off = pc - base
        r0, r1, r2, r3 = (vm.reg_read(r) for r in
                          (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
        if pc == stop:
            vm.emu_stop()
            return
        if off == 0x1a681e0:
            assert r0 == item
            events.append("automatic")
            return
        if off == 0x278120:
            assert vm.reg_read(UC_ARM_REG_SP) == stack - 24
            events.append("stock update")
            vm.reg_write(UC_ARM_REG_SP, stack)
            vm.reg_write(UC_ARM_REG_PC, stop)
            return
        if off == 0x27b3fc:
            assert r0 == item
            events.append("collect")
            put(item + 0x94, 1)
            result = 0
        elif off == 0x27d950:
            assert r0 == item and r1 == 1
            events.append("reserved by AI")
            vm.emu_stop()
            return
        elif pc == expected_terminal:
            vm.emu_stop()
            return
        elif off == 0x1f7380:
            result = clock
        elif off == 0x147adc:
            result = 0
        elif pc == modal:
            result = 0
        elif pc == missing_view_setting:
            result = 0xffffffff
        elif pc == cast:
            result = int(r0 == item and r1 == base + 0x27c56c)
        elif pc == rectangle:
            result = rect
        elif off in (0x27c56c, 0x11d74b4):
            result = base + off
        elif off == 0x1d9bb4:
            put(r0, r2)
            put(r0 + 4, r3)
            result = 0
        elif off == 0x1da034:
            result = get(r1)
        elif off == 0x15dec20:
            result = struct.unpack("<I", struct.pack("<f", r0))[0]
        elif off in (0x15dee64, 0x15deccc):
            assert r1 == 0x3f800000
            result = r0
        elif off == 0x15df0f8:
            result = int(struct.unpack("<f", struct.pack("<I", r0))[0])
        else:
            return
        vm.reg_write(UC_ARM_REG_R0, result)
        vm.reg_write(UC_ARM_REG_PC, vm.reg_read(UC_ARM_REG_LR))

    vm.hook_add(UC_HOOK_CODE, on_code)

    def run(site, *args, terminal=stop):
        nonlocal expected_terminal
        events.clear()
        expected_terminal = terminal
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            vm.reg_write(reg, value)
        vm.reg_write(UC_ARM_REG_LR, stop)
        vm.reg_write(UC_ARM_REG_SP, stack)
        vm.emu_start(base + site, 0, count=12000)
        assert vm.reg_read(UC_ARM_REG_PC) == terminal, hex(vm.reg_read(UC_ARM_REG_PC))
        if terminal == stop:
            assert vm.reg_read(UC_ARM_REG_SP) == stack
        return tuple(events)

    def point(x, y, phase):
        put(touch + 8, x)
        put(touch + 12, y)
        put(touch + 0x28, phase)

    def attempt(path):
        put(item + 0x94, 0)
        if path == "auto":
            return run(0x27811c, item)
        if path == "programmatic":
            return run(0x27b558, item)
        if path in ("A key", "hover"):
            point(29 if path == "A key" else 120, 220, 0)
            return run(0x1a010a4, base, driver, touch, 6 if path == "A key" else 5)
        point(50 if path == "miss" else 120, 220, 1 if path == "drag" else 0)
        return run(0x27b584, item, touch)

    paths = ("auto", "programmatic", "A key", "hover", "drag", "click", "miss")

    def check_paths(kind, label, allowed):
        level(label)
        for path in paths:
            if path == "auto":
                expected = ("automatic", "collect", "stock update") if path in allowed else ("stock update",)
            else:
                expected = ("collect",) if path in allowed else ()
            assert attempt(path) == expected, (hex(base), hex(kind), label, path, events, expected)
            assert get(item + 0x94) == int(path in allowed)

    def matrix(kind, label, allowed, *, flagged=False):
        put(base + kind + 0xe4, 0x27b584)
        fixture(kind, flagged)
        check_paths(kind, label, allowed)

    ordinary_paths = set(paths) - {"miss"}
    bomb = 0x17f64d0
    fixture(bomb)
    # Run the native state writes and shared flag setter. Art and animation
    # setup follow these instructions and are outside this input fixture.
    run(0xe212a0, item, terminal=base + 0xe212c4)
    assert get(item + 0x16c) == 1 and get(item + 0x8c) & 0x40
    check_paths(bomb, "future_minigame", {"click"})
    run(0xe21c1c, item, terminal=base + 0xe21c38)
    assert get(item) == base + bomb and get(item + 0x16c) == 0 and not (get(item + 0x8c) & 0x40)
    check_paths(bomb, "future_minigame", ordinary_paths)
    vm.mem_write(auto_enabled, b"\x00")
    assert attempt("auto") == ("automatic", "stock update") and get(item + 0x94) == 0
    vm.mem_write(auto_enabled, b"\x01")

    sun = 0x178b860
    matrix(sun, "future_minigame", {"click"}, flagged=True)
    run(0x288e88, item, 0, terminal=base + 0x288eb4)
    assert get(item + 0x168) == 0
    check_paths(sun, "future_minigame", ordinary_paths)
    matrix(0x178a870, "arena_battle_test", set(paths) - {"miss"}, flagged=True)
    matrix(0x178ae38, "egypt1", set(paths) - {"miss"})
    for label, site in (("arena_battle_test", 0x108bb08),
                        ("ARENA_BATTLE_ATTACK_TUTORIAL", 0x10a42c0)):
        matrix(0x178ae38, label, set())
        # The regular and tutorial AI call their original reserved pickup
        # directly. Stop where the native reservation changes item state.
        assert run(site, item, 1, terminal=base + 0x27d950) == ("reserved by AI",)
    print(f"57 pickup cases, native sun-bomb transitions and 2 AI reservations passed at {base:#x}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    args = parser.parse_args()
    for base in (0x10000000, 0x70000000):
        check(args.engine, base)
