"""Run the A303 region callback and first-attack reward paths on the ARM guest."""
import argparse
from pathlib import Path
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R2, UC_ARM_REG_R4

from check_offline_pvp_v76_focused import Definitions


def check(folder):
    sys.meta_path.insert(0, Definitions())
    import check_offline_pvp_arm as core
    from check_offline_pvp_v81_arm import GarrisonEngine
    from check_offline_pvp_v93_focused import crc, key

    core.OUT = folder
    base, manager, player = core.BASE, core.M, core.PROFILE
    map_control = manager + 0x18000

    class Fixture(GarrisonEngine):
        def __init__(self):
            super().__init__()
            self.redraws = []
            self.models = []
            self.reward_text = None

        def hook(self, emu, address, size, data):
            offset = address - base
            if offset == 0x100a864:
                self.redraws.append([self.get(shop) for shop in self.shops()])
            if offset == 0x100a5ac:
                self.models.append([self.get(p) for p in self.shops()])
                emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))
                return
            if offset == 0x109a1c0:
                emu.reg_write(UC_ARM_REG_PC, core.END)
                return
            if offset in (0x1051248, 0x1051924, 0x1051da4):
                self.reward_text = emu.reg_read(UC_ARM_REG_R2)
                emu.reg_write(UC_ARM_REG_PC, core.END)
                return
            if offset == 0x1013a3c:
                emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))
                return
            return super().hook(emu, address, size, data)

        def region_panel(self, zone, price):
            panel = self.alloc(0x150)
            self.stub(0x10196d0, panel, map_control, 0, zone, 0)
            for offset, value in ((0xa4, 0), (0xa8, 0), (0xac, zone),
                                  (0xc0, map_control), (0x144, price)):
                self.put(panel + offset, value)
            return panel

        def shop_name(self, record):
            address = self.get(record + 16)
            return bytes(self.u.mem_read(address, 4 * self.get(address - 12))).decode("utf-32-le")

    initial = Fixture()
    initial.enter()
    raw = bytearray(initial.files[key(initial)])
    for offset, value in ((12, 26500), (16, 7), (184, 7)):
        struct.pack_into("<I", raw, offset, value)
    game = Fixture()
    game.files = {key(initial): crc(raw)}
    game.enter()
    game.run("offlineGarden")
    district_shops = "offlineBusinessUsesOwnName" in game.exports
    assert not game.shops()
    if district_shops:
        game.put(map_control + 0xa8, manager + 0x19000)
    area2 = game.region_panel(2, 10000)
    game.stub(0x100b3d8, area2, 202)
    assert game.get(manager + 4) == 16500
    second = game.redraws[-1]
    assert len(second) == (2 if district_shops else 0)
    if district_shops:
        assert game.models[-1] == second
        assert len({game.get(p + 52) for p in game.shops()}) == 2
        assert {game.get(p + 48) for p in game.shops()} == {2}
        assert all(game.shop_name(p) == "空置的小屋" for p in game.shops())
    area3 = game.region_panel(3, 16500)
    game.run("offlineBusinessAction", area3, 203)
    assert game.get(manager + 4) == 16500
    assert [game.get(p) for p in game.shops()] == second
    game.failwrite = True
    game.stub(0x100b3d8, area3, 202)
    assert game.get(manager + 4) == 16500
    assert [game.get(p) for p in game.shops()] == second
    game.failwrite = False
    game.stub(0x100b3d8, area3, 202)
    third = game.redraws[-1]
    assert game.get(manager + 4) == 0
    if district_shops:
        assert game.models[-1] == third and set(second) <= set(third)
        assert len(third) - len(second) in range(3)
    else:
        assert third == [0x71000001, 0x71000002]
    game.stub(0x100b3d8, area3, 202)
    assert game.get(manager + 4) == 0 and game.redraws[-1] == third
    if district_shops:
        restarted = Fixture()
        restarted.copy_state(game)
        restarted.enter()
        restarted.run("offlineGarden")
        assert sorted(restarted.get(p) for p in restarted.shops()) == sorted(third)
        # Reuse the actual ARM allocator with fresh profile IDs.
        layouts = set()
        totals = {zone: set() for zone in range(2, 7)}
        plots = (0b11100, 0b100011, 0b111000000, 0b111000000000, 0b111000000000000)
        layout = game.alloc(len(raw))
        initializer = game.exports["_ZL23initializeDistrictShopsR7Economy"]
        for user_id in range(100, 132):
            game.put(layout + 8, user_id)
            game.run(initializer, layout)
            mask = game.get(layout + 2936)
            layouts.add(mask)
            for zone, plot_mask in enumerate(plots, 2):
                totals[zone].add((mask & plot_mask).bit_count())
        assert len(layouts) > 16 and totals[2] == {2}
        assert all(totals[zone] == {0, 1, 2} for zone in range(3, 7))

        # Migrate a v18 wallet containing the two original occupied shops.
        legacy = bytearray(raw[:2936])
        for offset, value in ((4, 18), (412, 3), (460, 7)):
            struct.pack_into("<I", legacy, offset, value)
        migrated = Fixture()
        migrated.files = {key(initial): crc(legacy)}
        migrated.enter()
        migrated.run("offlineGarden")
        assert migrated.owned() == 3 and migrated.get(manager + 4) == 26500
        assert {0x71000001, 0x71000002} <= {migrated.get(p) for p in migrated.shops()}
    shop = game.shops()[0]
    assert game.click(shop) == (3, game.get(shop + 48), game.get(shop + 52))
    game.scout_shop(0)
    assert len(game.loads) == 1 and game.get(manager + 4) == 0
    game.put(core.PM + 0x74, 43)
    game.put(manager + 0x20, 0)
    game.enter()
    game.run("offlineGarden")
    assert not game.shops(), ([(game.get(p), game.get(p + 48), game.get(p + 52)) for p in game.shops()],
                              struct.unpack_from("<I", game.files[key(game)], 460)[0])

    tutorial = Fixture()
    holder, app, board, widget = (tutorial.alloc(size) for size in (8, 0x1500, 0xc00, 0x138))
    tutorial.put(base + 0x1821674, holder)
    tutorial.put(holder, app)
    tutorial.put(app + 0x6bc, board)
    tutorial.put(app + 0x1218, 3)
    tutorial.put(manager + 0xa8, 1)
    tutorial.put(player + 0x75c, 3)
    tutorial.string(board + 0xc4, "arena_battle_attack_tutorial")
    tutorial.u.mem_write(widget + 0xec, b"\xff" * 20)
    tutorial.u.reg_write(UC_ARM_REG_R4, widget)
    tutorial.stub(0x109a1a8, manager)
    assert tutorial.get(widget + 0x118) == 1
    assert [tutorial.get(widget + i) for i in (0xf0, 0xf4, 0xf8, 0xfc)] == [0, 0, 0, 1000]
    assert tutorial.u.mem_read(widget + 0xee, 2) == b"\0\0"
    assert not tutorial.files

    tutorial.put(player + 0x75c, 7)
    tutorial.put(manager + 0xc4, 1057970944)
    tutorial.stub(0x1051244, manager)
    assert tutorial.reward_text == 1000
    tutorial.stub(0x1051da0)
    assert tutorial.reward_text == 1000 and not tutorial.files
    tutorial.put(player + 0x75c, 9)
    tutorial.stub(0x1051244, manager)
    assert tutorial.reward_text == 1057970944
    tutorial.put(player + 0x75c, 3)
    tutorial.string(board + 0xc4, "arena_plant_tutorial")
    tutorial.run("offlineTutorialPreviewRewards", widget, manager)
    assert tutorial.u.reg_read(UC_ARM_REG_R0) == 0

    tutorial.put(player + 0x75c, 9)
    tutorial.enter()
    first = bytes(tutorial.files[key(tutorial)])
    assert tutorial.get(manager + 4) == 1000
    tutorial.enter()
    assert tutorial.get(manager + 4) == 1000 and bytes(tutorial.files[key(tutorial)]) == first
    print("P0 PvP shop projection, cancellation, failed write, profile isolation and tutorial rewards passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    check(parser.parse_args().folder)
