"""Exercise P2 economy and matchmaking on the installed ARM32 engine."""
import argparse
from pathlib import Path
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2

from check_offline_pvp_v76_focused import Definitions


# Base level, production per hour (coins, medals), storage (coins, medals),
# next base upgrade (cost, seconds), representative trainable zombie and cost.
BASES = (
    (1, (40, 20), (2000, 2000), (150, 14400), "pvp_change", 5),
    (10, (210, 29), (56000, 3800), (10400, 74302), "pvp_gargantuar", 110),
    (19, (1000, 38), (890000, 5600), (690000, 383380), "pvp_football_mech", 900),
)
NPC = 0x70000002
SHOP_IDS = (0x71000001, 0x71000002, 0x71000003)
SHOP_LINEUPS = ((13, {2, 3, 4, 15, 16, 20, 21}), (21, {2, 5, 7, 21, 27, 42, 43, 45}),
                (15, {2, 3, 4, 5, 6, 27}))
WALLET_LIMIT = 2_000_000_000


def check_progression(make_engine):
    for level, rates, caps, (upgrade_cost, seconds), zombie, training_cost in BASES:
        engine = make_engine(level, caps[0] - 100)
        assert engine.base_stats() == (*caps, *rates)
        before = engine.balance()
        engine.train(name=zombie)
        assert engine.balance() == before - training_cost and engine.queued() == 1
        engine.train(2, zombie)
        assert engine.balance() == before and engine.queued() == 0
        engine.upgrade(1)
        assert engine.balance() == before - upgrade_cost
        assert engine.field(200) == engine.now + seconds
        engine.advance(seconds - 1)
        engine.enter()
        assert engine.field(184) == level and engine.field(196) == 1
        engine.advance(1)
        engine.enter()
        assert engine.field(184) == level + 1 and engine.field(196) == 0
        assert engine.balance() == min(caps[0], before - upgrade_cost + rates[0]*seconds//3600)

        # Months offline reach the production caps without overshooting.
        engine = make_engine(level, 0, medals=0)
        engine.advance_without_raids(365 * 86400)
        engine.enter()
        assert (engine.balance(), engine.medals()) == caps, (level, engine.balance(), engine.medals(), engine.notices)
        assert engine.field(208) == engine.field(212) == 0
        engine.advance_without_raids(86400)
        engine.enter()
        assert (engine.balance(), engine.medals()) == caps, (level, engine.balance(), engine.medals(), engine.notices)
        over = make_engine(level, caps[0]+100, medals=caps[1]+100)
        over.advance_without_raids(86400)
        over.enter()
        assert (over.balance(), over.medals()) == (caps[0]+100, caps[1]+100)


def check_battles(make_engine, battle, manager):
    for level, _, caps, *_ in BASES:
        for npc, entry_fee, shop_bit in ((NPC, 10, 0), (SHOP_IDS[0], 1, 1), (SHOP_IDS[1], 1, 2)):
            for stars in range(4):
                engine = make_engine(level, caps[0], shops=bool(shop_bit), cups=499)
                engine.run("offlineGarden")
                initial = engine.balance()
                for _ in range(3):
                    engine.train()
                assert engine.balance() == initial - 15 and engine.queued() == 3
                engine.advance(91)
                engine.run("offlineTrainingTick", engine.get(manager + 0x20))
                assert engine.held() == 3
                before, medals = engine.balance(), engine.medals()
                if shop_bit:
                    engine.scout_shop(shop_bit - 1)
                    battle.board(engine)
                else:
                    battle.scout(engine, npc)
                assert engine.balance() == before
                for _ in range(2):
                    battle.start(engine, npc)
                assert engine.balance() == before - entry_fee and engine.starts == 1
                engine.run(0x1030a50, manager + 0x14300, 2)
                engine.deaths(1)
                for _ in range(2):
                    battle.result(engine, stars, npc)
                reward = 100 * stars
                assert engine.balance() == before - entry_fee + reward
                assert engine.get(manager + 0xc4) == reward and engine.medals() == medals
                assert engine.held() == 2 and engine.windows == 1
                assert engine.owned() == (shop_bit if stars == 3 else 0)
                assert engine.field(2840) == 499 + (2*stars-1 if stars and not shop_bit else 0)
                battle.return_map(engine)
                assert engine.balance() == before - entry_fee + reward

        engine = make_engine(level, caps[0])
        engine.run("offlineGarden")
        engine.train()
        engine.advance(31)
        engine.run("offlineTrainingTick", engine.get(manager + 0x20))
        before = engine.balance()
        battle.scout(engine, NPC)
        engine.cancel()
        assert engine.balance() == before
        engine.reset_map()
        engine.put(manager + 0x7000 + 0x6bc, 0)
        engine.stub(0x1042fe8, manager, NPC, 1, 0)
        assert engine.balance() == before - 10 and engine.field(236) == 1
        restarted = make_engine(level, source=engine)
        assert restarted.balance() == before and restarted.field(224) == 0
        battle.board(engine)
        assert engine.field(236) == 2
        engine.cancel()
        assert engine.balance() == before - 10 and engine.field(224) == 0
        restarted = make_engine(level, source=engine)
        assert restarted.balance() == before - 10

    engine = make_engine(19, WALLET_LIMIT)
    engine.run("offlineGarden")
    engine.train()
    engine.advance(31)
    engine.run("offlineTrainingTick", engine.get(manager + 0x20))
    battle.scout(engine, NPC)
    battle.start(engine, NPC)
    engine.run(0x1030a50, manager + 0x14300, 0)
    engine.deaths(0)
    battle.result(engine, 3, NPC)
    assert engine.balance() == WALLET_LIMIT and engine.get(manager + 0xc4) == 15


def check_shop_storage(make_engine, claim_shop, manager):
    engine = make_engine(19, WALLET_LIMIT, medals=WALLET_LIMIT, shops=True)
    engine.run("offlineGarden")
    for _ in range(3):
        engine.train()
    engine.advance(91)
    engine.run("offlineTrainingTick", engine.get(manager + 0x20))
    for i in range(2):
        claim_shop(engine, i)
    assert engine.owned() == 3
    # Keep this fixture on the normal progression ticking path.
    engine.advance_without_raids(100 * 3600)
    engine.enter()
    for shop in engine.shops()[:2]:
        assert [engine.get(shop + offset) for offset in (24, 28, 32, 36)] == [2000]*4
    assert (engine.balance(), engine.medals()) == (WALLET_LIMIT, WALLET_LIMIT)
    first = engine.shops()[0]
    engine.run("offlineBusinessChest", manager + 0x18000, first)
    assert (engine.get(first + 32), engine.get(first + 24)) == (2000, 2000)
    engine.train()
    engine.run("offlineBusinessChest", manager + 0x18000, first)
    assert (engine.get(first + 32), engine.get(first + 24)) == (1995, 2000)
    engine.run("offlineBusinessChest", manager + 0x18000, first)
    assert (engine.balance(), engine.medals()) == (WALLET_LIMIT, WALLET_LIMIT)
    assert (engine.get(first + 32), engine.get(first + 24)) == (1995, 2000)
    assert engine.get(engine.shops()[1] + 32) == 2000


def check_shop_formations(make_engine, battle, claim_shop, manager):
    from check_aster_pvp_feedback import seal

    for index, (count, plant_types) in enumerate(SHOP_LINEUPS):
        engine = make_engine(10, 1000, shops=True)
        if index == 2 and "offlineBusinessUsesOwnName" not in engine.exports:
            continue
        world = ("pirate", "west", "egypt")[index]
        battle_name, defense_name = "arena_battle_test", "arena_plant_test"
        assert engine.resolve_definition(battle_name) == (battle_name,)
        engine.run("offlineGarden")
        engine.scout_shop(index)
        assert engine.resolve_definition(battle_name) == (f"arena_shop_{world}_battle",)
        assert engine.resolve_definition("pirate1") == ("pirate1",)
        engine.missing_definition = f"arena_shop_{world}_battle"
        assert engine.resolve_definition(battle_name) == (engine.missing_definition, battle_name)
        engine.missing_definition = None
        battle.board(engine)
        original = engine.plants()
        plants = list(struct.iter_unpack("<III", original))
        assert len(plants) == count and {plant[0] for plant in plants} == plant_types
        cells = {(row, column) for _, row, column in plants}
        def is_land(row, col):
            return row < 5 and col < 9 and (index != 0 or row not in (1, 3) or col < 5)

        assert len(cells) == count and all(is_land(row, col) for row, col in cells)
        start, end = (engine.get(manager + offset) for offset in (0x90, 0x94))
        assert {(engine.get(p), engine.get(p+4)) for p in range(start, end, 16)} == {
            (plant, 1) for plant in plant_types
        } and end - start == len(plant_types)*16
        engine.cancel()
        for _ in range(3):
            engine.train()
        engine.advance(91)
        engine.run("offlineTrainingTick", engine.get(manager + 0x20))
        claim_shop(engine, index)
        assert engine.edit(index) == 1 and engine.plants() == original
        assert engine.resolve_definition(defense_name) == (f"arena_shop_{world}_defense",)
        destination = next((row, col) for row in range(5) for col in range(9)
                           if (row, col) not in cells and is_land(row, col))
        plant = engine.get(manager + 0x84)
        if index == 0:
            engine.put(plant + 4, 1)
            engine.put(plant + 8, 7)
            engine.save()
            assert not any("-shop-" in path for path in engine.files)
        engine.put(plant + 4, destination[0])
        engine.put(plant + 8, destination[1])
        moved = engine.plants()
        engine.save()
        engine.request(3)
        restarted = make_engine(10, source=engine)
        restarted.run("offlineGarden")
        assert restarted.edit(index) == 1 and restarted.plants() == moved
        if index == 0:
            # A rectangular-board save can contain a plant on a water tile.
            path, = (p for p in engine.files if p.endswith("-shop-71000001.def"))
            envelope = bytearray(engine.files[path])
            old_formation = envelope[20:]
            struct.pack_into("<II", old_formation, 28, 1, 7)
            seal(old_formation, 20)
            envelope[20:] = old_formation
            seal(envelope, 16)
            engine.files[path] = envelope
            legacy = make_engine(10, source=engine)
            legacy.run("offlineGarden")
            assert legacy.edit(index) == 1
            relocated = list(struct.iter_unpack("<III", legacy.plants()))
            assert relocated[0] == (plants[0][0], 1, 3)
            assert relocated[1:] == plants[1:] and legacy.files[path] == envelope


def check_matching(make_engine):
    from check_aster_pvp_feedback import seed_roll

    def random_step(state):
        state ^= (state << 13) & 0xffffffff
        state ^= state >> 17
        return state ^ ((state << 5) & 0xffffffff)

    # Independent Python sampler checks the three radii and the exact boundary.
    def expected(cups, seed):
        mixed = seed ^ 0xb27159af
        mixed = (mixed ^ (mixed >> 16)) * 0x7feb352d & 0xffffffff
        mixed = (mixed ^ (mixed >> 15)) * 0x846ca68b & 0xffffffff
        rng = random_step((mixed ^ (mixed >> 16)) or 1)
        roll = rng % 100
        radius = 10 if roll < 75 else 25 if roll < 95 else 50
        center = min(cups, 500)
        return center - radius + random_step(rng) % (2*radius+1), radius

    engine = make_engine(1, 1000)
    roster, opponent = engine.alloc(24+900*17), engine.alloc(900)
    radius_seeds, edge_seeds = {}, {}
    for seed in range(1, 25001):
        sampled, radius = expected(500, seed)
        radius_seeds.setdefault(radius, seed)
        if sampled in (450, 550):
            edge_seeds.setdefault(sampled, seed)
    assert radius_seeds.keys() == {10, 25, 50} and edge_seeds.keys() == {450, 550}
    sample_seeds = sorted(set(radius_seeds.values()) | set(edge_seeds.values()))
    for cups in (499, 500, 501, 25000, WALLET_LIMIT):
        engine.set_field(2840, cups)
        for seed in sample_seeds:
            sampled = engine.call_symbol("matchedNeighborCups", cups, seed)
            assert sampled == expected(cups, seed)[0]
            engine.call_symbol("generateRosterNeighbor", roster, opponent, NPC, seed, 0, 0)
            assert (engine.get(opponent+8), engine.get(opponent+12)) == (0, sampled)
            assert engine.call_symbol("validEncounter", opponent, NPC, 0, 0, 0) == 1
        assert engine.field(2840) == cups

    # An ordinary import still uses the match window. A directory special
    # keeps its stored cups and uses the separate appearance roll.
    seed = next(i for i in range(1, 25000) if seed_roll(i ^ 0x703af8d1) < 75)
    name = list(map(ord, "P2 fixture"))
    candidate = [8123, 800, 1, *name, *([0]*(40-len(name))), 0, 2, 0, 0, 1]
    source = engine.alloc(4 * (1 + 224))
    for marker, allow, kind in ((0, 1, 0), (0x10000 | 76, 0, 0), (0x10000 | 76, 1, 8)):
        candidate[43] = marker
        words = [1, *candidate, *([0]*(224-len(candidate)))]
        engine.u.mem_write(source, struct.pack(f"<{len(words)}I", *words))
        engine.run("offlinePresetCommand", 8, source, len(words))
        assert engine.u.reg_read(UC_ARM_REG_R0) == 2
        engine.call_symbol("generateRosterNeighbor", roster, opponent, NPC, seed, 0, allow)
        assert engine.get(opponent+8) == kind
        assert engine.get(opponent+12) == (800 if kind else expected(500, seed)[0])


def check(folder):
    sys.meta_path.insert(0, Definitions())
    import check_offline_pvp_arm as core
    import check_offline_pvp_v81_arm as garrison
    import check_offline_pvp_v60_arm as battle
    from check_offline_pvp_v93_focused import key

    core.OUT = folder
    manager = core.M
    class Engine(garrison.GarrisonEngine):
        def __init__(self):
            super().__init__()
            self.definitions = []
            self.definition_handle = 0
            self.missing_definition = None

        def hook(self, emu, address, size, data):
            off = address - core.BASE
            out = emu.reg_read(UC_ARM_REG_R0)
            if off == 0x440dc4:
                name = self.txt(self.get(emu.reg_read(UC_ARM_REG_R2)))
                self.definitions.append(name)
                self.definition_handle = out
                self.put(out, int(name != self.missing_definition))
            elif off == 0x1da034 and self.definition_handle and emu.reg_read(UC_ARM_REG_R1) == self.definition_handle:
                out = self.get(self.definition_handle)
            else:
                return super().hook(emu, address, size, data)
            emu.reg_write(UC_ARM_REG_R0, out)
            emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))

        def resolve_definition(self, name):
            self.definitions.clear()
            out, ref = self.alloc(8), self.alloc(4)
            self.string(ref, name)
            self.stub(0x225a54, out, manager, ref)
            self.definition_handle = 0
            return tuple(self.definitions)

        def state(self):
            return core.BASE + self.exports["_ZL14economyRuntime"] + 16

        def field(self, offset):
            return self.get(self.state() + offset)

        def set_field(self, offset, value):
            self.put(self.state() + offset, value)

        def advance_without_raids(self, seconds):
            self.advance(seconds)
            # Isolate storage and collection from the separate daily raid clock.
            self.set_field(796, self.now)
            for index in range(15):
                if self.owned() & (1 << index):
                    offset = 800 + 4 * index if index < 2 else 3200 + 16 * (index - 2)
                    self.set_field(offset, self.now)

        def call_symbol(self, name, *args):
            callers = [address for symbol, address in self.exports.items() if name in symbol]
            assert len(callers) == 1, callers
            self.run(callers[0], *args)
            return self.u.reg_read(UC_ARM_REG_R0)

        def balance(self):
            return self.get(manager + 4)

        def medals(self):
            return self.get(manager + 8)

        def base_stats(self):
            return tuple(self.get(manager + offset) for offset in (0x144, 0x13c, 0x14c, 0x148))

    def make_engine(level, coins=1000, *, medals=200, cups=0, shops=False, source=None):
        engine = Engine()
        if source is not None:
            engine.copy_state(source)
            engine.now = source.now
            engine.enter()
            return engine
        engine.enter()
        for offset, value in ((12, coins), (16, level), (180, medals), (184, level), (2840, cups)):
            engine.set_field(offset, value)
        if shops:
            engine.set_field(460, 7)
            if "offlineBusinessUsesOwnName" in engine.exports:
                engine.set_field(2936, 0x0f)  # Both legacy lots plus Coffee and Hot Dog in zone 2.
        engine.run("_ZL11saveEconomyjR7Economy", engine.state())
        assert engine.u.reg_read(UC_ARM_REG_R0) == 1 and engine.files[key(engine)]
        engine.run("_ZL12applyEconomyjPh", manager)
        return engine

    check_progression(make_engine)
    check_battles(make_engine, battle, manager)
    check_shop_storage(make_engine, garrison.claim, manager)
    check_shop_formations(make_engine, battle, garrison.claim, manager)
    check_matching(make_engine)
    print("P2 ARM passed: bases 1/10/19, training, upgrades, storage, 0-3 stars and retreat, "
          "shop formations and saved moves, matching at 499/500/501 and high cups, special import.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    check(parser.parse_args().folder)
