"""Run the P1 ARM hooks against synthetic local PvP profiles."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
import sys

from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R3, UC_ARM_REG_R4,
                               UC_ARM_REG_R7, UC_ARM_REG_SP)

from check_offline_pvp_v76_focused import Definitions

DAVE = 0x70000007
SHOP = 0x71000001
START = int(datetime(2026, 11, 24, tzinfo=timezone.utc).timestamp())
DAY = 86400
HIDDEN = 0x7f7fffff


def f32(number):
    return struct.unpack("<I", struct.pack("<f", number))[0]


def check(folder):
    sys.meta_path.insert(0, Definitions())
    import check_offline_pvp_arm as core
    from check_offline_pvp_v48_arm import SessionEngine
    from check_offline_pvp_v60_arm import board, result, return_map
    from check_offline_pvp_v81_arm import GarrisonEngine
    from check_offline_pvp_v93_focused import crc, key

    core.OUT = folder
    base, manager, end = core.BASE, core.M, core.END
    mktime = end + 0x1e8000
    clock = manager + 0x5000
    map_control = manager + 0x18000

    class Fixture(GarrisonEngine):
        def __init__(self, day=START + 1800):
            super().__init__()
            self.now = day
            self.tm = self.alloc(48)
            self.put(base + 0x1822b1c, mktime)
            self.put(clock + 0x24, f32(100))
            self.fixed_clock = True
            self.timers = []
            self.narratives = []
            self.redrawn = 0

        def hook(self, emu, address, size, data):
            off = address - base
            if address == end + 0x300:
                return SessionEngine.hook(self, emu, address, size, data)
            r0, r1 = [emu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1)]
            value = 0
            if off == 0x147854:
                t = datetime.fromtimestamp(self.now, timezone.utc)
                emu.mem_write(self.tm, struct.pack("<11i", t.second, t.minute, t.hour, t.day,
                                                   t.month - 1, t.year - 1900, 0, 0, 0, 0, 0))
                value = self.tm
            elif address == mktime:
                second, minute, hour, day, month, year, *_ = struct.unpack("<11i", emu.mem_read(r0, 44))
                if self.payload_range[0] <= emu.reg_read(UC_ARM_REG_LR) < self.payload_range[1]:
                    assert self.get(r0 + 32) == 0xffffffff
                start = datetime(year + 1900 + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
                value = int((start + timedelta(days=day - 1, hours=hour, minutes=minute,
                                               seconds=second)).timestamp())
            elif off == 0x1f7380 and self.fixed_clock:
                value = clock
            elif off == 0x2af780:
                self.narratives.append(self.txt(self.get(r1)))
            elif off == 0x14e9b0c:
                self.put(r0, self.get(r1))
            elif off == 0x10449b8:
                value = 42  # deliberately different from the local fee
            elif off == 0x100a864:
                self.redrawn += 1
            elif off == 0x109a1c0:
                emu.reg_write(UC_ARM_REG_PC, end)
                return
            elif off in (0x107b668, 0x100cf20):
                self.timers.append(r0 if off == 0x100cf20 else emu.reg_read(UC_ARM_REG_R7))
                emu.reg_write(UC_ARM_REG_PC, end)
                return
            elif off == 0x1072aa4:
                self.timers.append((self.get(manager + 0x6c), self.get(manager + 0x74)))
                # The trampoline already ran the native nine-register prologue.
                emu.reg_write(UC_ARM_REG_SP, emu.reg_read(UC_ARM_REG_SP) + 36)
            else:
                return super().hook(emu, address, size, data)
            emu.reg_write(UC_ARM_REG_R0, value)
            emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))

        def state(self):
            return base + self.exports["_ZL14economyRuntime"] + 16

        def store(self):
            self.run("_ZL11saveEconomyjR7Economy", self.state())
            assert self.u.reg_read(UC_ARM_REG_R0) == 1

        def visitor(self):
            matches = [p for p in self.residents() if self.get(p) == DAVE]
            assert len(matches) <= 1
            return matches[0] if matches else 0

        def visitor_seconds(self):
            self.u.reg_write(UC_ARM_REG_R4, self.visitor())
            self.stub(0x100cf10)
            return self.timers[-1]

        def entry_timer(self):
            self.u.reg_write(UC_ARM_REG_R3, manager)
            self.stub(0x107b664)
            return self.timers[-1]

        def title(self, record):
            address = self.get(record + 16)
            return bytes(self.u.mem_read(address, 4 * self.get(address - 12))).decode("utf-32-le")

    visitor = Fixture()
    visitor.enter()
    visitor.run("offlineGarden")
    assert visitor.visitor_seconds() == DAY - 1800
    slot = tuple(visitor.get(visitor.visitor() + o) for o in (28, 32))
    assert sum(tuple(visitor.get(p + o) for o in (28, 32)) == slot for p in visitor.residents()) == 1
    visitor.now = START + DAY - 1
    assert visitor.visitor_seconds() == 1
    visitor.now += 1
    assert visitor.visitor_seconds() == 0
    funds = visitor.get(manager + 4)
    visitor.stub(0x1042fe8, manager, DAVE, 1, 0)
    assert visitor.get(manager + 4) == funds and not visitor.loads
    visitor.run("offlineGarden")
    assert not visitor.visitor()
    visitor.now = START + 2 * DAY + 1
    visitor.run("offlineGarden")
    assert visitor.visitor_seconds() == DAY - 1
    assert visitor.get(visitor.state() + 216) == 0

    # Simulate persisted result state for the first and sixth victories. Use
    # the real installed narrative acknowledgement and recovery transitions.
    for wins, resumed_at, still_visible in ((1, START + 3600, True), (6, START + 3600, False),
                                            (6, START + DAY + 1, False)):
        before = Fixture()
        before.enter()
        before.run("offlineGarden")
        target = before.get(before.state() + 2924)
        for offset, value in ((216, wins), (332, 1), (336, 0), (340, wins),
                              (2928, int(wins != 6)), (2932, int(wins == 6))):
            before.put(before.state() + offset, value)
        before.store()
        restart = Fixture(resumed_at)
        restart.copy_state(before)
        restart.enter()
        restart.run("offlineGarden")
        assert restart.visitor()
        assert restart.get(restart.state() + 2924) == target
        restart.put(manager + 0x7000 + 0x1358, manager + 0x17200)
        restart.run("offlineDaveNarrative", map_control)
        restart.run("offlineDaveNarrative", map_control)
        assert restart.narratives == [f"MAP_PVPEVILDAVID_SUCCESS_{wins}_INTRO"]
        replacement = next(n for n in restart.files if n.endswith(".neighbors"))
        original = bytes(restart.files[replacement])
        restart.failwrite = True
        restart.stub(0x10090c4, map_control)
        assert restart.visitor() and bytes(restart.files[replacement]) == original
        restart.failwrite = False
        restart.run("offlineDaveNarrative", map_control)
        restart.stub(0x10090c4, map_control)
        assert bool(restart.visitor()) == still_visible and restart.redrawn == 1
        assert restart.get(restart.state() + 336) == 1
        next_roster = bytes(restart.files[replacement])
        assert (next_roster == original) == still_visible
        assert sum(restart.get(p) == target for p in restart.residents()) == int(not still_visible)
        restart.stub(0x10090c4, map_control)
        restart.run("offlineGarden")
        assert bytes(restart.files[replacement]) == next_roster

    lab = Fixture()
    lab.enter()
    assert lab.entry_timer() == HIDDEN
    lab.put(lab.state() + 324, 1)
    lab.put(lab.state() + 328, lab.now + 90)
    lab.put(lab.state() + 296, 1)
    lab.put(lab.state() + 300, lab.now + 180)
    assert lab.entry_timer() == f32(280)
    card, graphic = lab.alloc(0x200), lab.alloc(4)
    lab.put(manager + 0x6c, 2)
    lab.put(manager + 0x74, f32(440))
    for category, expected in ((4, (4, f32(280))), (7, (7, f32(190))), (2, (2, f32(440)))):
        lab.put(card + 0x1fc, category)
        lab.stub(0x1072aa0, card, graphic)
        assert lab.timers[-1] == expected
        assert (lab.get(manager + 0x6c), lab.get(manager + 0x74)) == (2, f32(440))
    lab.put(lab.state() + 196, 2)
    lab.put(lab.state() + 200, lab.now + 340)
    assert lab.entry_timer() == f32(440)
    lab.put(lab.state() + 200, 0)
    lab.put(lab.state() + 196, 0)
    lab.put(lab.state() + 328, lab.now + 240)
    assert lab.entry_timer() == f32(340)
    lab.put(lab.state() + 328, lab.now + 90)
    lab.now += 90
    assert lab.entry_timer() == f32(190)  # research expired, evolution still has 90 seconds
    lab.now += 90
    assert lab.entry_timer() == HIDDEN
    lab.now -= 180
    lab.put(core.PM + 0x74, 43)
    assert lab.entry_timer() == HIDDEN

    research = Fixture()
    research.enter()
    research.put(research.state() + 12, 10000)
    research.store()
    research.run("_ZL12applyEconomyjPh", manager)
    page = research.research_ui(1)
    research.click_research(page)
    assert research.entry_timer() != HIDDEN
    reopened = Fixture(research.now + 1)
    reopened.copy_state(research)
    reopened.enter()
    assert reopened.entry_timer() != HIDDEN
    research.click_research(page)
    SessionEngine.confirm(research, research.research_timer)
    assert research.entry_timer() == HIDDEN

    seed = Fixture()
    seed.enter()
    record = bytearray(seed.files[key(seed)])
    struct.pack_into("<I", record, 460, 7)
    district_shops = "offlineBusinessUsesOwnName" in seed.exports
    if district_shops:
        struct.pack_into("<I", record, 2936, 0x0f)
    for stars in (1, 2, 3):
        shop = Fixture()
        shop.files = {key(seed): crc(bytearray(record))}
        shop.enter()
        shop.run("offlineGarden")
        expected_titles = ["空置的小屋"] * 4 if district_shops else ["热狗店 · 空置的小屋", "商店 · 空置的小屋"]
        assert [shop.title(p) for p in shop.shops()] == expected_titles
        if district_shops:
            shop.string(core.PROFILE + 0x58, "WSA fixture", True)
        assert [shop.get(shop.shops()[0] + i) for i in (24, 28, 32, 36, 40, 44)] == [0, 2000, 0, 2000, 0, 0]
        shop.fixed_clock = False
        for _ in range(3):
            shop.train()
        shop.advance(91)
        shop.run("offlineTrainingTick", shop.get(manager + 0x20))
        funds = shop.get(manager + 4)
        shop.scout_shop(0)
        board(shop)
        assert shop.get(manager + 4) == funds
        widget = shop.alloc(0x140)
        shop.u.reg_write(UC_ARM_REG_R4, widget)
        shop.stub(0x109a1a8, manager)
        assert shop.get(widget + 0xfc) == 300
        shop.run("offlineAttackPreviewCost", manager)
        assert shop.u.reg_read(UC_ARM_REG_R0) == 1
        for _ in range(2):
            shop.stub(0x1042fe8, manager, SHOP, 2, 0)
        assert shop.get(manager + 4) == funds - 1 and shop.starts == 1
        shop.run(0x1030a50, manager + 0x14300, 2)
        shop.deaths(0)
        for _ in range(2):
            result(shop, stars, SHOP)
        assert shop.get(manager + 4) == funds - 1 + stars * 100 and shop.owned() == int(stars == 3)
        return_map(shop)
        shop.reset_map()
        if stars == 3:
            assert shop.title(shop.shops()[0]) == ("WSA fixture" if district_shops else "热狗店 · 自己")
            if district_shops:
                shop.run("offlineBusinessUsesOwnName", shop.shops()[0])
                assert shop.u.reg_read(UC_ARM_REG_R0) == 1
            shop.advance(180)
            shop.run("offlineTrainingTick", shop.get(manager + 0x20))
            own = shop.shops()[0]
            assert [shop.get(own + i) for i in (24, 28, 32, 36, 40, 44)] == [1, 2000, 2, 2000, 20, 40]
            wallet = shop.get(manager + 4), shop.get(manager + 8)
            for _ in range(2):
                shop.run("offlineBusinessChest", map_control, own)
            assert (shop.get(manager + 4), shop.get(manager + 8)) == (wallet[0] + 2, wallet[1] + 1)
            shop.put(core.PM + 0x74, 43)
            shop.enter()
            shop.run("offlineGarden")
            assert not shop.shops() and shop.owned() == 0
    print("P1 ARM checked native Dave countdown/ack, expiry/restart, lab card/lobby countdown and shop quotes/fees/capture/rent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    check(parser.parse_args().folder)
