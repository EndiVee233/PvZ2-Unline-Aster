"""Check the native sign-in calendar and grants against the original Toolbox."""
import argparse
from calendar import monthrange
from datetime import date
from io import BytesIO
import json
import struct
from zipfile import ZipFile
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm_const import (
    UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_SP,
)


RETURN = 0x09001000
STACK = 0x09100000
MANAGER, PLAYER, OTHER, HOLDER, APP, TM, OBJECTS = (STACK + n * 0x1000 for n in range(1, 8))
EPOCH = date(1970, 1, 1)
WIDE_STRINGS = 0x09200000


def read_word(emu, address):
    return struct.unpack("<I", emu.mem_read(address, 4))[0]


def write_word(emu, address, value):
    emu.mem_write(address, struct.pack("<I", value))


def read_string(emu, address):
    return bytes(emu.mem_read(address, 32)).split(b"\0", 1)[0].decode("ascii")


def verify(engine, report, base, pool, plants):
    emu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    emu.reg_write(UC_ARM_REG_FPEXC, 1 << 30)
    emu.mem_map(base, 0x2000000)
    for segment in ELFFile(BytesIO(engine)).iter_segments():
        if segment["p_type"] == "PT_LOAD":
            emu.mem_write(base + segment["p_vaddr"], segment.data())
    emu.mem_map(RETURN, 0x1000)
    emu.mem_map(STACK, 0x10000)
    emu.mem_map(WIDE_STRINGS, 0x40000)
    write_word(emu, base + 0x18300a4, MANAGER)
    write_word(emu, base + 0x1821674, HOLDER)
    write_word(emu, HOLDER, APP)
    write_word(emu, MANAGER + 0x74, 10)
    active = PLAYER
    clock = date(2028, 2, 25)
    shown = 0
    awards = []
    labels = []
    draw_calls = []
    wide_strings = {}
    next_string = WIDE_STRINGS + 12
    strings = {}
    tile = OBJECTS + 0x800
    shard_balance = OBJECTS + 0x900
    aliases = {plant["code"] for plant in plants.values()}

    def intercept(uc, address, _size, _data):
        site = address - base
        arg = uc.reg_read(UC_ARM_REG_R0)
        if site == 0x147824:
            result = (clock - EPOCH).days * 86400
        elif site == 0x147854:
            day = date.fromordinal(EPOCH.toordinal() + read_word(uc, arg) // 86400)
            uc.mem_write(TM, struct.pack("<6I", 0, 0, 0, day.day, day.month - 1, day.year - 1900))
            result = TM
        elif site == 0x1df738:
            result = MANAGER
        elif site == 0x7a98dc:
            assert arg == MANAGER
            result = active
        elif site == 0x4184f8:
            nonlocal shown
            assert arg == APP
            shown += 1
            result = 1
        elif site == 0x14ed0e0:
            name = read_string(uc, uc.reg_read(UC_ARM_REG_R1))
            assert name in aliases and name not in strings
            strings[name] = OBJECTS + len(strings) * 32
            uc.mem_write(strings[name], name.encode("ascii") + b"\0")
            write_word(uc, arg, strings[name])
            result = arg
        elif site == 0xf6347c:
            assert arg == tile and uc.reg_read(UC_ARM_REG_R2) == 1
            assert struct.unpack("<3I", uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 12))[1:] == (9, 0)
            result = 0
        elif site == 0x14ea6fc:
            assert arg == tile + 0xc8
            address, length = (uc.reg_read(reg) for reg in (UC_ARM_REG_R1, UC_ARM_REG_R2))
            labels.append(bytes(uc.mem_read(address, length * 4)).decode("utf-32-le"))
            write_word(uc, arg, OBJECTS)
            result = arg
        elif site == 0x14eb450:
            nonlocal next_string
            address = uc.reg_read(UC_ARM_REG_R1)
            codepoints = []
            while (unit := read_word(uc, address + 4 * len(codepoints))):
                codepoints.append(unit)
            wide_strings[next_string] = "".join(map(chr, codepoints))
            write_word(uc, arg, next_string)
            next_string += 4 * len(codepoints) + 16
            result = arg
        elif site == 0x14ea238:
            del wide_strings[arg + 12]
            result = 0
        elif site == 0x13af2d0:
            sp = uc.reg_read(UC_ARM_REG_SP)
            entry = read_word(uc, read_word(uc, sp + 4))
            draw_calls.append(wide_strings.get(entry, labels[-1]))
            result = 0
        elif site in (0x729ebc, 0x746164, 0x745220):
            assert arg == active
            assert uc.mem_read(active + 0x3a4, 1) == b"\1"
            first = uc.reg_read(UC_ARM_REG_R1)
            if site == 0x729ebc:
                awards.append((read_string(uc, read_word(uc, first)), uc.reg_read(UC_ARM_REG_R2)))
            elif site == 0x746164:
                awards.append(("gold", first))
            else:
                assert uc.reg_read(UC_ARM_REG_R2) == 0
                awards.append(("diamonds", first))
            result = 0
        elif site in (0xf68f5c, 0xf69068):
            uc.emu_stop()
            return
        else:
            return
        uc.reg_write(UC_ARM_REG_R0, result)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    emu.hook_add(UC_HOOK_CODE, intercept)

    def run(offset, arg=0, second=0, third=0):
        emu.reg_write(UC_ARM_REG_SP, STACK + 0x8000)
        emu.reg_write(UC_ARM_REG_LR, RETURN)
        emu.reg_write(UC_ARM_REG_R0, arg)
        emu.reg_write(UC_ARM_REG_R1, second)
        emu.reg_write(UC_ARM_REG_R2, third)
        emu.emu_start(base + offset, RETURN, count=10000)
        assert emu.reg_read(UC_ARM_REG_PC) in (RETURN, base + 0xf68f5c, base + 0xf69068)
        return emu.reg_read(UC_ARM_REG_R0)

    def open_panel():
        run(report["symbols"]["asterDailySignOpen"], base)
        config = run(report["symbols"]["asterDailySignConfig"], base)
        start = read_word(emu, config + 0x14)
        end = read_word(emu, config + 0x18)
        assert read_word(emu, config + 0x0c) == clock.month
        return start, (end - start) // 12

    def claim(entry, player=None):
        emu.reg_write(UC_ARM_REG_R4, active if player is None else player)
        emu.reg_write(UC_ARM_REG_R6, entry)
        run(0xf68f58, entry)

    def expected_day():
        month = max(0, min(11, (clock.year - 2026) * 12 + clock.month - 6))
        return pool[month][clock.day - 1]

    def expected_awards():
        day = expected_day()
        return [(plants[day["plant"]]["code"], day["num"]), ("gold", day["gold"]), ("diamonds", day["dia"])]

    def check_tile(entry, *, claimed=False):
        day = expected_day()
        alias, kind, amount = struct.unpack("<3I", emu.mem_read(entry, 12))
        assert (read_string(emu, alias), kind, amount) == (plants[day["plant"]]["code"], 5, day["num"])
        run(report["symbols"]["asterDailySignTile"], base, tile, entry)
        write_word(emu, tile + 0xd8, clock.day - 1)
        write_word(emu, tile + 0x34, 120)
        draw_regs, draw_stack = OBJECTS + 0xa00, OBJECTS + 0xb00
        emu.mem_write(draw_regs, struct.pack("<IIffI", APP, 0, 0, 14, tile))
        emu.mem_write(draw_stack, struct.pack("<f4I", 100, tile + 0xc8, 1, 0, 0))
        run(report["symbols"]["asterDailySignDraw"], base, draw_regs, draw_stack)
        status = "已领" if claimed else "可领"
        assert draw_calls == [
            f'{clock.day}日 {status}', day["plant"], f'碎片 ×{day["num"]}',
            f'金币 {day["gold"]}', f'钻石 {day["dia"]}',
        ]
        draw_calls.clear()
        labels.clear()

    first, length = open_panel()
    today_entry = first + (clock.day - 1) * 12
    assert shown == 1 and length == 29 and read_word(emu, PLAYER + 0x3a0) == 25
    check_tile(today_entry)
    claim(today_entry)
    claim(today_entry)
    assert awards == expected_awards()
    check_tile(today_entry, claimed=True)
    assert emu.mem_read(PLAYER + 0x3c8, 1) == b"\1"
    open_panel()
    assert read_word(emu, PLAYER + 0x3a0) == 25 and emu.mem_read(PLAYER + 0x3a4, 1) == b"\1"

    clock = date(2028, 2, 26)
    claim(today_entry)
    assert len(awards) == 3
    open_panel()
    assert read_word(emu, PLAYER + 0x3a0) == 26
    claim(today_entry)
    assert len(awards) == 3
    today_entry += 12
    claim(today_entry)
    assert len(awards) == 6 and awards[-3:] == expected_awards()

    active = OTHER
    write_word(emu, MANAGER + 0x74, 11)
    claim(today_entry, PLAYER)
    claim(today_entry)
    assert len(awards) == 6
    open_panel()
    assert read_word(emu, OTHER + 0x3a0) == 26
    assert read_word(emu, PLAYER + 0x3a0) == 26
    write_word(emu, OTHER + 0x98, 0x7fffffff)
    claim(today_entry)
    assert len(awards) == 6 and emu.mem_read(OTHER + 0x3a4, 1) == b"\0"
    write_word(emu, OTHER + 0x98, 100)
    write_word(emu, OTHER + 0xa0, 0x7fffffff)
    claim(today_entry)
    assert len(awards) == 6
    write_word(emu, OTHER + 0xa0, 0)
    write_word(emu, OTHER + 0x208, shard_balance)
    write_word(emu, OTHER + 0x20c, shard_balance + 8)
    # Choose the active native ID by the original plant registry.
    write_word(emu, shard_balance, plants[expected_day()["plant"]]["order"])
    write_word(emu, shard_balance + 4, 0x7fffffff)
    claim(today_entry)
    assert len(awards) == 6
    write_word(emu, shard_balance + 4, 0)
    claim(today_entry)
    assert len(awards) == 9 and awards[-3:] == expected_awards()

    clock = date(2028, 2, 25)
    old_shown = shown
    run(report["symbols"]["asterDailySignOpen"], base)
    assert shown == old_shown
    clock = date(2028, 3, 1)
    _, length = open_panel()
    assert length == 31 and read_word(emu, OTHER + 0x3a0) == 1
    assert emu.mem_read(OTHER + 0x3a4, 1) == b"\0"

    # Use fresh state to compare every playable date, plus both table bounds.
    write_word(emu, OTHER + 0x3b4, 0)
    for offset in range(-1, 13):
        year, month = divmod(2026 * 12 + 5 + offset, 12)
        month += 1
        days = monthrange(year, month)[1]
        for day in range(1, days + 1):
            clock = date(year, month, day)
            first, length = open_panel()
            assert length == days and read_word(emu, OTHER + 0x3a0) == day
            entry = first + (day - 1) * 12
            check_tile(entry)
            awards.clear()
            claim(entry)
            assert awards == expected_awards(), clock


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("native_report", type=Path)
    parser.add_argument("reference", type=Path, help="directory containing the original Toolbox JSON files")
    args = parser.parse_args()
    with ZipFile(args.apk) as apk:
        engine = apk.read("lib/armeabi/libSrc.so")
    report = json.loads(args.native_report.read_text())
    pool = json.loads((args.reference / "rewards_pool_old.json").read_bytes())
    registry = json.loads((args.reference / "plants.json").read_bytes())
    plants = {plant["name"]: plant for plant in registry.values()}
    for base in (0x10000000, 0x70000000):
        verify(engine, report, base, pool, plants)
    print("Daily sign-in display and all 3 native grants match the Toolbox at both guest bases")
