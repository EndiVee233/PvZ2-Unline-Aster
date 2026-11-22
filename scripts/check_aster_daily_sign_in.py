"""Check the native sign-in calendar and grants against the approved civil-year table."""
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
    UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
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
    by_alias = {plant["code"]: plant["order"] for plant in plants.values()}
    keys = dict(zip(("埃及", "海盗", "西部", "功夫", "未来", "暗黑", "巨浪"),
                    ("egypt", "pirate", "cowboy", "kongfu", "future", "dark", "beach")))
    materials = {"普通医药箱": "magic_regeneration", "普通肥料": "magic_fertilizer",
                 "高级肥料": "epic_fertilizer", "精制铁桶": "epic_drum",
                 "高级火药桶": "epic_explode"}
    aliases = set(by_alias) | set(keys.values()) | set(materials.values()) | {""}
    owned = {}
    key_balances = {}
    fail_grant = False
    accessory_record = OBJECTS + 0xc00
    costume_record = OBJECTS + 0xd00
    costume_count = OBJECTS + 0xe00

    def model_grant(player, award, amount):
        awards.append((award, amount))
        if fail_grant:
            return
        if isinstance(award, int):
            write_word(emu, player + award, read_word(emu, player + award) + amount)
            return
        kind, name = award
        if kind == "key":
            key_balances[player, name] = key_balances.get((player, name), 0) + amount
        elif kind in ("plant", "costume"):
            owned.setdefault(player, set()).add((kind, name))
        elif kind == "plant-piece":
            if read_word(emu, shard_balance) != by_alias[name]:
                write_word(emu, shard_balance, by_alias[name])
                write_word(emu, shard_balance + 4, 0)
            write_word(emu, shard_balance + 4, read_word(emu, shard_balance + 4) + amount)
            write_word(emu, player + 0x208, shard_balance)
            write_word(emu, player + 0x20c, shard_balance + 8)
        elif kind == "costume-piece":
            if read_word(emu, costume_record) != by_alias[name]:
                write_word(emu, costume_count, 0)
            write_word(emu, costume_record, by_alias[name])
            write_word(emu, costume_record + 4, costume_count)
            write_word(emu, costume_count, read_word(emu, costume_count) + amount)
            write_word(emu, player + 0x3c, costume_record)
            write_word(emu, player + 0x40, costume_record + 16)
        elif kind == "material":
            if read_word(emu, accessory_record) != strings[name]:
                write_word(emu, accessory_record + 4, 0)
            write_word(emu, accessory_record, strings[name])
            write_word(emu, accessory_record + 4, read_word(emu, accessory_record + 4) + amount)
            write_word(emu, player + 0x2d8, accessory_record)
            write_word(emu, player + 0x2dc, accessory_record + 8)
        else:
            raise AssertionError(award)

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
            assert name in aliases and name not in strings, name
            strings[name] = OBJECTS + len(strings) * 32
            uc.mem_write(strings[name], name.encode("ascii") + b"\0")
            write_word(uc, arg, strings[name])
            result = arg
        elif site == 0xf6347c:
            assert arg == tile and uc.reg_read(UC_ARM_REG_R2) == 1
            _, kind, amount = struct.unpack("<3I", uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 12))
            assert kind in (0, 1, 2, 9) and amount == 0
            result = 0
        elif site == 0x7e8a28:
            desc = uc.reg_read(UC_ARM_REG_R1)
            image = bytes(uc.mem_read(read_word(uc, desc + 12), 64)).split(b"\0", 1)[0]
            assert image.startswith(b"IMAGE_")
            write_word(uc, arg + 4, 0xabcd)
            result = 0
        elif site == 0x1d9bb4:
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
        elif site in (0x708e18, 0x708890, 0x706da0):
            name = read_string(uc, read_word(uc, uc.reg_read(UC_ARM_REG_R1)))
            if site == 0x706da0:
                result = key_balances.get((arg, name), 0)
            else:
                kind = "plant" if site == 0x708e18 else "costume"
                result = int((kind, name) in owned.get(arg, set()))
        elif site in (0x746164, 0x745220, 0x729ebc, 0x744554, 0x7233ec, 0x722624,
                      0x717c24, 0x729e8c, 0x7492d4, 0x729440):
            assert arg == active
            assert uc.mem_read(active + 0x3a4, 1) == b"\1"
            first = uc.reg_read(UC_ARM_REG_R1)
            second = uc.reg_read(UC_ARM_REG_R2)
            if site in (0x746164, 0x745220):
                if site == 0x745220:
                    assert second == 0
                model_grant(arg, 0x98 if site == 0x746164 else 0xa0, first)
            else:
                name = read_string(uc, read_word(uc, first))
                if site == 0x744554:
                    assert second == 1
                    model_grant(arg, ("plant", name), 1)
                elif site == 0x722624:
                    assert second == 0
                    model_grant(arg, ("costume", name), 1)
                elif site == 0x729e8c:
                    assert second == 0 and read_word(uc, uc.reg_read(UC_ARM_REG_SP)) == 1
                    model_grant(arg, ("costume-piece", name), uc.reg_read(UC_ARM_REG_R3))
                elif site not in (0x7233ec, 0x717c24):
                    kind = {0x729ebc: "plant-piece", 0x7492d4: "key", 0x729440: "material"}[site]
                    model_grant(arg, (kind, name), second)
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

    def expected_day(*, duplicate=False):
        day = pool[clock.month - 1][clock.day - 1]
        name, amount = day["name"], day["amount"]
        if name == "金币":
            return "", 0, amount, (0x98, amount), name
        if name == "钻石":
            return "", 1, amount, (0xa0, amount), name
        if name.endswith("钥匙"):
            alias = keys[name[:-2]]
            return alias, 2, amount, (("key", alias), amount), name
        if name in materials:
            alias = materials[name]
            return alias, 9, amount, (("material", alias), amount), name + "碎片"
        for suffix, kind in (("装扮碎片", "costume-piece"), ("装扮", "costume"),
                             ("整株", "plant"), ("碎片", "plant-piece")):
            if name.endswith(suffix):
                alias = plants[name[:-len(suffix)]]["code"]
                if duplicate:
                    assert kind in ("plant", "costume")
                    kind += "-piece"
                    name = name[:-2] + ("碎片" if kind == "plant-piece" else "装扮碎片")
                    amount = 10
                return alias, 9, amount, ((kind, alias), amount), name
        raise AssertionError(day)

    def check_tile(entry, *, claimed=False, duplicate=False):
        alias, kind, amount = struct.unpack("<3I", emu.mem_read(entry, 12))
        expected_alias, expected_kind, expected_amount, _, item = expected_day(duplicate=duplicate)
        assert (read_string(emu, alias), kind, amount) == (expected_alias, expected_kind, expected_amount), clock
        run(report["symbols"]["asterDailySignTile"], base, tile, entry)
        write_word(emu, tile + 0xd8, clock.day - 1)
        write_word(emu, tile + 0x34, 120)
        draw_regs, draw_stack = OBJECTS + 0xa00, OBJECTS + 0xb00
        emu.mem_write(draw_regs, struct.pack("<IIffI", APP, 0, 0, 14, tile))
        emu.mem_write(draw_stack, struct.pack("<f4I", 100, tile + 0xc8, 1, 0, 0))
        run(report["symbols"]["asterDailySignDraw"], base, draw_regs, draw_stack)
        status = "已领" if claimed else "可领"
        assert draw_calls == [f"{clock.day}日 {status}", item, f"×{amount}"], (clock, draw_calls)
        draw_calls.clear()
        labels.clear()

    def today_entry():
        start, days = open_panel()
        assert days == monthrange(clock.year, clock.month)[1]
        assert read_word(emu, active + 0x3a0) == clock.day
        return start + (clock.day - 1) * 12

    def change_player(player, user):
        nonlocal active
        active = player
        write_word(emu, MANAGER + 0x74, user)

    clock = date(2028, 2, 28)
    first = today_entry()
    check_tile(first)
    claim(first)
    claim(first)
    assert awards == [expected_day()[3]]
    check_tile(today_entry(), claimed=True)
    assert emu.mem_read(PLAYER + 0x3c8, 1) == b"\1"

    clock = date(2028, 2, 29)
    claim(first)
    assert len(awards) == 1
    next_entry = today_entry()
    claim(first)
    assert len(awards) == 1
    claim(next_entry)
    assert awards[-1] == expected_day()[3] and len(awards) == 2

    change_player(OTHER, 11)
    claim(next_entry, PLAYER)
    claim(next_entry)
    assert len(awards) == 2
    entry = today_entry()
    write_word(emu, OTHER + 0xa0, 0x7fffffff)
    claim(entry)
    assert len(awards) == 2 and emu.mem_read(OTHER + 0x3a4, 1) == b"\0"
    write_word(emu, OTHER + 0xa0, 0)
    fail_grant = True
    claim(entry)
    assert emu.mem_read(OTHER + 0x3a4, 1) == b"\0"
    assert read_word(emu, OTHER + 0xa0) == 0
    fail_grant = False
    claim(entry)
    assert emu.mem_read(OTHER + 0x3a4, 1) == b"\1"
    assert read_word(emu, OTHER + 0xa0) == expected_day()[2]

    clock = date(2028, 2, 28)
    old_shown = shown
    run(report["symbols"]["asterDailySignOpen"], base)
    assert shown == old_shown
    clock = date(2028, 3, 1)
    claim(today_entry())
    assert awards[-1] == expected_day()[3]

    for month, day, kind, alias in [(1, 2, "plant", "wintersweet"), (11, 19, "costume", "broccoli")]:
        clock = date(2029, month, day)
        owned.setdefault(OTHER, set()).add((kind, alias))
        entry = today_entry()
        check_tile(entry, duplicate=True)
        claim(entry)
        assert awards[-1] == expected_day(duplicate=True)[3]
        owned[OTHER].clear()

    # A restored, already claimed profile must retain its marker before any award.
    clock = date(2030, 2, 28)
    write_word(emu, OTHER + 0x3b4, (clock - EPOCH).days * 86400)
    before = len(awards)
    claim(today_entry())
    assert len(awards) == before
    clock = date(2030, 3, 1)
    claim(today_entry())
    assert len(awards) == before + 1

    for year in (2032, 2033):
        for month in range(1, 13):
            for day in range(1, monthrange(year, month)[1] + 1):
                clock = date(year, month, day)
                owned[OTHER] = set()
                entry = today_entry()
                check_tile(entry)
                awards.clear()
                claim(entry)
                assert awards == [expected_day()[3]], clock

    # Shop keys use the native 99 limit and must reject a partial bundle.
    clock = date(2034, 3, 1)
    key_balances[OTHER, "egypt"] = 98
    entry = today_entry()
    awards.clear()
    claim(entry)
    assert not awards and key_balances[OTHER, "egypt"] == 98
    assert emu.mem_read(OTHER + 0x3a4, 1) == b"\0"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("native_report", type=Path)
    parser.add_argument("reference", type=Path, help="directory containing the approved civil-year table JSON files")
    args = parser.parse_args()
    with ZipFile(args.apk) as apk:
        engine = apk.read("lib/armeabi/libSrc.so")
    report = json.loads(args.native_report.read_text())
    pool = json.loads(Path(__file__).with_name("aster_sign_in_calendar_expected.json").read_bytes())
    assert [len(month) for month in pool] == [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    registry = json.loads((args.reference / "plants.json").read_bytes())
    plants = {plant["name"]: plant for plant in registry.values()}
    for base in (0x10000000, 0x70000000):
        verify(engine, report, base, pool, plants)
    print("Daily sign-in checked 366 leap and 365 common-year dates at each guest base")
