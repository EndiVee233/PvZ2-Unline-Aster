"""Run the changed PvP paths of the installed engine against synthetic saves."""
import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import struct
import sys

from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
    UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_PC,
    UC_ARM_REG_LR, UC_ARM_REG_FP,
)
from check_offline_pvp_v76_focused import Definitions


def seed_roll(value):
    value ^= value >> 16
    value = value * 0x7feb352d & 0xffffffff
    value ^= value >> 15
    value = value * 0x846ca68b & 0xffffffff
    value ^= value >> 16
    return (value or 1) % 10000


def seal(data, checksum_offset):
    checksum = 2166136261
    for index, value in enumerate(data):
        if not checksum_offset <= index < checksum_offset + 4:
            checksum = ((checksum ^ value) * 16777619) & 0xffffffff
    struct.pack_into('<I', data, checksum_offset, checksum)


def check(folder):
    sys.argv = [sys.argv[0], str(folder)]
    sys.meta_path.insert(0, Definitions())
    core = importlib.import_module('check_offline_pvp_arm')
    core.OUT = folder
    parent = importlib.import_module('check_offline_pvp_v81_arm')
    evolution_engine = importlib.import_module('check_offline_pvp_v63_arm').EvolutionEngine
    session = importlib.import_module('check_offline_pvp_v48_arm').SessionEngine
    BASE, M, END, PROFILE, GM, PM = core.BASE, core.M, core.END, core.PROFILE, core.GM, core.PM

    class Feedback(parent.GarrisonEngine):
        def __init__(self):
            super().__init__()
            self.now = int(datetime(2026, 11, 18, 12, tzinfo=timezone.utc).timestamp())
            self.history_ids = []
            self.chest_route = None
            self.buffer_copy = None

        def hook(self, em, addr, size, data):
            if addr - BASE in (0x101a034, 0x11fbf10, 0x1326230) or BASE+0x15de9dc <= addr <= BASE+0x15dea08:
                return
            if addr - BASE in (0x11fbf14, 0x1326234):
                em.reg_write(UC_ARM_REG_PC, END)
                return
            if addr == BASE + 0x112d864:
                self.buffer_copy = tuple(em.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
                em.reg_write(UC_ARM_REG_PC, em.reg_read(UC_ARM_REG_LR))
                return
            if addr == BASE + 0x105b774:
                vector = em.reg_read(UC_ARM_REG_R1)
                self.history_ids = [(self.get(p), self.get(p + 4))
                                    for p in range(self.get(vector), self.get(vector + 4), 8)]
            elif addr in (BASE + 0x10197b8, BASE + 0x101a038):
                self.chest_route = addr - BASE
            elif addr in (END+0x300, END+0x310, END+0x330):
                return session.hook(self, em, addr, size, data)
            elif addr in (BASE + 0x1019668,):
                pass
            else:
                return super().hook(em, addr, size, data)
            em.reg_write(UC_ARM_REG_PC, em.reg_read(UC_ARM_REG_LR) & ~1)

        def address(self, fragment):
            return next(value for key, value in self.exports.items() if fragment in key)

        def wallet(self):
            return BASE + self.address('economyRuntime') + 16

        def stored_wallet(self):
            return next(v for k, v in self.files.items() if k.endswith('.eco'))

        def chest(self, record):
            self.u.reg_write(UC_ARM_REG_R6, M + 0x18000)
            self.u.reg_write(UC_ARM_REG_R7, record)
            self.run(0x101a034)
            return self.chest_route

    e = Feedback()
    e.enter()
    e.run('offlineGarden')
    e.put(e.wallet() + 12, 100000)
    e.put(e.wallet() + 460, 7)  # Fixture owns access to the two merchant plots.
    e.run('offlineProgressionInit')
    e.run('offlineGarden')
    e.upgrade(1)
    evolution = e.evo_ui()
    evolution_engine.click(e, evolution)
    research = e.research_ui(0)
    e.click_research(research)
    deadlines = [e.get(e.wallet() + o) for o in (200, 300, 328)]
    assert all(deadline > e.now for deadline in deadlines), deadlines
    assert [e.get(e.wallet() + o) for o in (196, 296, 324)] == [1, 1, 1]
    assert e.get(M + 0x6c) == 1
    restarted = Feedback()
    restarted.copy_state(e)
    restarted.now = e.now
    restarted.enter()
    assert [restarted.get(restarted.wallet() + o) for o in (200, 300, 328)] == deadlines
    restarted.evo_ui()
    restarted.research_ui(0)
    restarted.advance(max(deadlines) - restarted.now + 1)
    restarted.enter()
    assert restarted.level(1) == restarted.grade() == restarted.research_grade() == 2
    assert [restarted.get(restarted.wallet() + o) for o in (196, 296, 324)] == [0, 0, 0]

    for _ in range(3):
        e.train()
    e.advance(91)
    e.run('offlineTrainingTick', e.get(M + 0x20))
    parent.claim(e, 0)
    parent.claim(e, 1)
    e.advance(180)
    e.enter()
    e.run('offlineGarden')
    shop_a, shop_b = e.shops()
    wallet = (e.get(M+4), e.get(M+8))
    assert (e.get(shop_a+32), e.get(shop_a+24)) == (2, 1), (
        e.owned(), e.get(shop_a+8), e.get(shop_a+32), e.get(shop_a+24),
        struct.unpack_from('<10I', e.stored_wallet(), 416))
    e.failwrite = True
    assert e.chest(shop_a) == 0x10197b8
    assert (e.get(M+4), e.get(M+8)) == wallet
    e.failwrite = False
    assert e.chest(shop_a) == 0x10197b8
    assert (e.get(M+4), e.get(M+8)) == (wallet[0]+2, wallet[1]+1)
    assert (e.get(shop_a+32), e.get(shop_a+24)) == (0, 0)
    assert (e.get(shop_b+32), e.get(shop_b+24)) == (2, 1)
    saved = bytes(e.stored_wallet())
    assert e.chest(shop_a) == 0x10197b8 and bytes(e.stored_wallet()) == saved
    assert e.chest(e.alloc(64)) == 0x101a038

    # Give the battle a freshly generated ordinary street and a separate army.
    battle = importlib.import_module('check_offline_pvp_v60_arm')
    e = Feedback()
    e.enter()
    e.run('offlineGarden')
    for _ in range(3):
        e.train()
    e.advance(91)
    e.run('offlineTrainingTick', e.get(M+0x20))
    targets = [p for p in e.residents() if e.get(p) != 0x70000007]
    assert targets, (e.messages, e.notices, tuple(e.files))
    target = targets[0]
    opponent = e.get(target)
    e.selected(target)
    e.stub(0x1042fe8, M, 0, 1, 0)
    battle.board(e)
    e.run(0x1030a50, M+0x14300, e.held())
    e.deaths(0)
    review_fixes = 'offlineScoutRewards' in e.exports
    stars = 1 if review_fixes else 3
    battle.result(e, stars, opponent)
    e.run('offlineHistoryLoad', e.alloc(0x100))
    serial, namespace = e.history_ids[0]
    e.stub(0x103bdb0, 0, 0, serial, namespace)
    brief = e.u.reg_read(UC_ARM_REG_R0)
    assert [e.get(brief+o) for o in (0xac, 0xb0, 0xb4)] == [2*stars-1, 0, 100*stars]
    row = e.alloc(0xd8)
    e.put(row+0xa8, serial)
    e.put(row+0xac, namespace)
    e.run('offlineHistoryRowReady', row)
    columns = [e.get(row+o) for o in (0xc8, 0xcc, 0xd0)]
    assert columns == ([100, 1, 0] if review_fixes else [0, 5, 300])
    if review_fixes:
        assert columns == [e.get(M+o) for o in (0xc4, 0xcc, 0xc8)]

    root = Path(__file__).resolve().parents[1]
    presets = sorted((root/'pvp-presets/special-enemies').glob('*.json'))
    catalogue = json.loads((folder/'catalogue.json').read_text(encoding='utf8'))
    plant_ids = {entry['name']: entry['id'] for entry in catalogue if entry['allowed']}
    assert len(presets) == 7
    words = [len(presets)]
    for seed, path in enumerate(presets, 1):
        doc = json.loads(path.read_text(encoding='utf8'))
        name = [ord(ch) for ch in doc['名字']]
        plants = doc['阵容']
        marker = 0x10000 | (0x20000 if path.name.startswith('fbi.') else 0)
        fixture = [seed, doc['奖杯'], len(plants), *name, *([0]*(40-len(name))), marker | 76]
        for plant in plants:
            fixture.extend([plant_ids[plant['type']], plant['row'], plant['column'], plant['level']])
        words.extend(fixture + [0]*(224-len(fixture)))
    data = e.alloc(len(words)*4)
    e.u.mem_write(data, struct.pack(f'<{len(words)}I', *words))
    e.run('offlinePresetCommand', 8, data, len(words))
    assert e.u.reg_read(UC_ARM_REG_R0) == 8
    roster, encounter = e.alloc(24+900*17), e.alloc(900)
    generator = e.address('generateRosterNeighbor')
    hits = [seed for seed in range(1, 25000) if seed_roll(seed ^ 0x703af8d1) < 75]
    boundary = next(seed for seed in range(1, 100000) if seed_roll(seed ^ 0x703af8d1) == 75)
    for seed in hits[:50]:
        e.run(generator, roster, encounter, 0x70000002, seed, 0, 1)
        assert e.get(encounter+8) in (1, 8)
    for seed, enabled in [(boundary, 1), (hits[0], 0)]:
        e.run(generator, roster, encounter, 0x70000002, seed, 0, enabled)
        assert e.get(encounter+8) == 0
        for index in range(e.get(encounter+16)):
            assert e.get(encounter+20+index*16) not in (26, 41, 58, 90, 93)

    legacy_key = next(key for key in e.files if key.endswith('.neighbors'))
    legacy = bytearray(e.files[legacy_key])
    slot = next(index for index in range(24, len(legacy), 900)
                if struct.unpack_from('<I', legacy, index + 4)[0])
    struct.pack_into('<III', legacy, slot + 8, 1, 999, 45)
    tier = next(plant['maxLevel'] for plant in catalogue if plant['id'] == 34)
    for index in range(45):
        struct.pack_into('<4I', legacy, slot + 20 + 16*index, 34, tier, index//9, index%9)
    legacy[slot + 740:slot + 900] = bytes(160)
    seal(legacy, 20)
    migration = Feedback()
    migration.copy_state(e)
    migration.files[legacy_key] = legacy
    migration.enter()
    migration.run('offlineGarden')
    assert struct.unpack_from('<I', migration.files[legacy_key], slot + 8)[0] == 0

    own_board = bytearray(24 + 128*12 + 128*144)
    struct.pack_into('<5I', own_board, 0, 0x4f505650, 1, 42, 3, 3)
    struct.pack_into('<9I', own_board, 24, 58, 1, 1, 2, 2, 2, 93, 3, 3)
    info = 24 + 128*12
    struct.pack_into('<2I', own_board, info, 58, 1)
    struct.pack_into('<2I', own_board, info + 144, 2, 1)
    struct.pack_into('<2I', own_board, info + 288, 93, 1)
    seal(own_board, 20)
    own_path = legacy_key.removesuffix('.neighbors') + '.def'
    migration.files[own_path] = own_board
    output = migration.alloc(len(own_board))
    migration.run(migration.address('readStore'), BASE, output)
    assert migration.u.reg_read(UC_ARM_REG_R0) == 1
    assert [migration.get(output+o) for o in (12, 16, 24, info)] == [1, 1, 2, 2]
    assert struct.unpack_from('<I', migration.files[own_path], 12)[0] == 3

    profiles = Feedback()
    profiles.enter()
    first = profiles.wallet()
    profiles.put(first+216, 2)
    profiles.put(first+308, 3)
    profiles.put(first+312, 4)
    profiles.put(first+248, 3)
    profiles.run(profiles.address('saveEconomy'), BASE, first)
    profiles.run(profiles.address('applyEconomy'), BASE, M)
    assert [profiles.get(M+0x15c), profiles.research_grade(), profiles.research_grade(1),
            profiles.grade()] == [2, 3, 4, 3]
    profiles.put(PM+0x74, 43)
    profiles.put(PROFILE+0x75c, 2)
    profiles.run('offlinePvpProfileSelected')
    assert [profiles.get(M+0x15c), profiles.research_grade(), profiles.research_grade(1),
            profiles.grade()] == [0, 1, 1, 1]
    row = profiles.alloc(64)
    profiles.put(row, 0x70000007)
    profiles.put(row+0x24, 4)
    profiles.put(row+0x2c, 2)
    profiles.run('offlineDaveLabel', row)
    assert [profiles.get(row+0x2c), profiles.get(row+0x30)] == [0, 6]
    profiles.enter()
    profiles.put(PROFILE+0x75c, 9)
    profiles.enter()
    assert [profiles.get(first+o) for o in (216, 248, 308, 312, 316, 320)] == [0, 1, 1, 1, 1, 1]
    profiles.put(PM+0x74, 42)
    profiles.run('offlinePvpProfileSelected')
    profiles.enter()
    assert [profiles.get(M+0x15c), profiles.research_grade(), profiles.research_grade(1),
            profiles.grade()] == [2, 3, 4, 3]

    profiles.put(GM+0x984, 6)
    application = profiles.get(profiles.get(BASE+0x1821674))
    board = profiles.alloc(0xa00)
    profiles.put(application+0x6bc, board)
    profiles.u.mem_write(application+0x88, struct.pack('<d', 1.0))
    for level, track in (('arena_plant_tutorial', 2), ('arena_battle_attack_tutorial', 2),
                         ('arena_plant_test', 2), ('arena_battle_test', 2), ('egypt1', 0)):
        profiles.string(board+0xc4, level)
        profiles.run('offlinePvpMusicSample')
        assert profiles.u.reg_read(UC_ARM_REG_R0) & 3 == track
    profiles.put(application+0x6bc, 0)
    profiles.put(GM+0xa24, 6)
    profiles.string(GM+0xa40, 'arena_plant_tutorial')
    profiles.run('offlinePvpMusicSample')
    assert profiles.u.reg_read(UC_ARM_REG_R0) & 3 == 2
    music_cases = 6
    if any('allOneRton' in name for name in profiles.exports):
        lobby = profiles.alloc(0x110)
        for scene in (25, 28, 29):
            profiles.put(GM+0x984, scene)
            profiles.put(BASE+0x1833c14, 0)
            profiles.run('offlinePvpMusicSample')
            assert profiles.u.reg_read(UC_ARM_REG_R0) & 3 == 1
            profiles.put(BASE+0x1833c14, lobby)
            music_cases += 1
            for handle in (0xe0, 0xe4, 0xf0, 0xf4):
                profiles.put(lobby+handle, 123)
                for completed, expected in ((0, 0), (1, 1)):
                    profiles.u.mem_write(lobby+0xf9, bytes([completed]))
                    profiles.run('offlinePvpMusicSample')
                    assert profiles.u.reg_read(UC_ARM_REG_R0) & 3 == expected
                    music_cases += 1
                profiles.put(lobby+handle, 0)
            profiles.u.mem_write(lobby+0xf9, bytes([0]))
            profiles.run('offlinePvpMusicSample')
            assert profiles.u.reg_read(UC_ARM_REG_R0) & 3 == 1
            music_cases += 1

    for site, reg in ((0x11fbf10, UC_ARM_REG_R7), (0x1326230, UC_ARM_REG_R5)):
        for large in (False, True):
            raw, buffer = profiles.alloc(64), profiles.alloc(32)
            size = 32*1024*1024 if large else 64
            profiles.buffer_copy = None
            profiles.u.reg_write(reg, raw)
            profiles.run(site, buffer, raw, size)
            if large:
                assert profiles.buffer_copy is None and profiles.u.reg_read(reg) == 0
                assert [profiles.get(buffer+o) for o in (4, 8, 12, 16, 24)] == [
                    raw, raw+size, raw+size, size*8, size*8]
            else:
                assert profiles.buffer_copy == (buffer, raw, size) and profiles.u.reg_read(reg) == raw

    layout_cases = check_plant_bank(core)
    report = {'parallel_queues_restarted_completed': 3, 'native_chest_cases': 4,
              'history_stars': stars, 'history_columns': columns, 'directory_presets_loaded': len(presets),
              'directory_native_roll_cases': 52, 'legacy_special_slot_migrated': True,
              'legacy_home_preserved_after_filter': True, 'profile_swap_projection': True,
              'pvp_music_cases': music_cases, 'large_file_reader_cases': 4,
              'plant_bank_layout_cases': layout_cases, 'gameplay_acceptance': False}
    if review_fixes:
        report.update(check_review_ui(Feedback, core))
    (folder/'feedback-checks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


def check_review_ui(parent, core):
    base, m, end = core.BASE, core.M, core.END

    class ReviewUI(parent):
        def hook(self, em, addr, size, data):
            off = addr-base
            if off in self.stops:
                self.route = off
                em.reg_write(UC_ARM_REG_PC, end)
                return
            if 0x109a1a8 <= off <= 0x109a1b4 or off in (0x109b0d0, 0x10a647c, 0x4e5e3c, 0x10189d4):
                return
            if off == 0x10290ac:
                result = self.bank_type
            elif off == 0x43af38 and em.reg_read(UC_ARM_REG_R1) == self.bank_type:
                assert em.reg_read(UC_ARM_REG_R0) == self.modules
                result = self.bank
            elif off == 0x11d74b4:
                result = m
            elif off == 0x1da034 and self.bank and em.reg_read(UC_ARM_REG_R1) == self.bank+0x58:
                result = self.get(self.bank+0x58)
            elif off == 0x1da034 and em.reg_read(UC_ARM_REG_R1) == self.selection_handle:
                result = self.get(self.selection_handle)
            elif off == 0x14e9b0c:
                target, source = (em.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1))
                self.put(target, self.get(source))
                result = target
            else:
                return super().hook(em, addr, size, data)
            em.reg_write(UC_ARM_REG_R0, result)
            em.reg_write(UC_ARM_REG_PC, em.reg_read(UC_ARM_REG_LR))

        def section(self, start, stops, registers=(), args=()):
            self.stops = stops
            self.route = None
            for reg, value in registers:
                self.u.reg_write(reg, value)
            self.run(start, *args)
            assert self.route in stops, (hex(start), self.route)
            self.stops = ()
            return self.route

    e = ReviewUI()
    e.stops = ()
    e.bank = 0
    e.selection_handle = 0
    e.bank_type = e.alloc(0x80)
    e.enter()
    e.run('offlineGarden')
    records = e.residents()
    dave = next(p for p in records if e.get(p) == 0x70000007)
    neighbor = next(p for p in records if p != dave)
    six_rounds = any('daveTargetForCycle' in name for name in e.exports)
    assert e.native_panel(neighbor)[6] == 10
    if six_rounds:
        assert e.native_panel(dave)[6] == 30
    # The same field flows through the native red-button formatter as its amount.
    panel = e.alloc(0x150)
    e.put(panel+0xac, e.get(neighbor+28))
    e.put(panel+0xa8, e.get(neighbor+32))
    e.u.reg_write(UC_ARM_REG_R10, panel)
    e.run(0x10190f4)
    e.section(0x10189d4, (0x10189d8,), ((UC_ARM_REG_R10, panel),))
    assert e.u.reg_read(UC_ARM_REG_R2) == 10

    def scout_widget(target, mode, expected):
        e.put(base+e.address('arenaNpc'), target)
        e.put(base+e.address('arenaUser'), e.get(core.PM+0x74))
        e.put(base+e.address('requestedArenaView'), 1)
        e.put(m+0xa8, mode)
        e.put(m+0x100, 1)
        widget = e.alloc(0x140)
        e.string(widget+0x110, '可获得的奖励', wide=True)
        e.u.mem_write(widget+0xef, b'\xff')
        route = e.section(0x109a1a8, (0x109a1c0, 0x109a210), ((UC_ARM_REG_R4, widget),), (m,))
        actual = [e.get(widget+o) for o in (0x118, 0xf0, 0xfc)]
        expected_route = 0x109a1c0 if expected[0] == 1 else 0x109a210
        assert actual == expected and route == expected_route, (actual, expected, hex(route))
        e.section(0x109b0d0, (0x109b0d4,), ((UC_ARM_REG_R5, widget),
                                            (UC_ARM_REG_R9, base+0x18a67e0)))
        icon = 0x18a5448 if target == e.get(neighbor) else 0x18a6848
        assert e.u.reg_read(UC_ARM_REG_R9) == base+icon
        label = e.get(widget+0x110)
        actual_title = bytes(e.u.mem_read(label, e.get(label-12)*4)).decode('utf-32-le')
        expected_title = '3星可获得奖励' if six_rounds and target == e.get(neighbor) else '可获得的奖励'
        assert actual_title == expected_title

    scout_widget(e.get(neighbor), 2, [1, 5, 300])
    for round_index, medals in enumerate((250, 300, 350, 400, 450, 500)):
        e.put(base+e.address('arenaDaveRound'), round_index)
        scout_widget(e.get(dave), 1, [1, medals, 0])
    scout_widget(0x71000001, 2, [2, 0, 0])

    app, board = e.alloc(0x700), e.alloc(0x940)
    e.modules, e.bank, energy, card = (e.alloc(n) for n in (32, 0x60, 0x140, 0x160))
    e.put(base+0x1821674, m+0x3200)
    e.put(m+0x3200, app)
    e.put(app+0x6bc, board)
    e.put(board+0x938, e.modules)
    e.put(e.bank+0x58, energy)
    e.selection_handle = e.alloc(8)
    e.put(e.selection_handle, card)
    e.put(card, e.alloc(0x100))
    e.string(board+0xc4, 'arena_battle_attack_tutorial')
    cases = 0
    for cost in (40, 25, 20, 30, 300):
        e.put(card+0x154, cost)
        for balance in (0, cost-1, cost, cost+1):
            e.put(energy+0xf0, balance)
            selection = e.section(0x10a647c, (0x10a6444, 0x10a6480),
                                  ((UC_ARM_REG_R4, e.bank), (UC_ARM_REG_R5, e.selection_handle)), (1,))
            release = e.section(0x4e5e3c, (0x4e5d78, 0x4e5e40), ((UC_ARM_REG_R5, card),))
            allowed = balance >= cost
            assert selection == (0x10a6480 if allowed else 0x10a6444)
            assert release == (0x4e5e40 if allowed else 0x4e5d78)
            assert e.get(energy+0xf0) == balance
            cases += 1
    e.put(e.bank+0x58, 0)
    assert e.section(0x4e5e3c, (0x4e5d78, 0x4e5e40), ((UC_ARM_REG_R5, card),)) == 0x4e5d78
    e.string(board+0xc4, 'arena_battle_test')
    assert e.section(0x4e5e3c, (0x4e5d78, 0x4e5e40), ((UC_ARM_REG_R5, card),)) == 0x4e5e40
    return {'native_red_button_cost': 10, 'scout_native_widget_cases': 8,
            'tutorial_selection_and_release_cases': cases+2}


def check_plant_bank(core):
    base, end = core.BASE, core.END

    class Bank(core.Engine):
        def __init__(self):
            super().__init__()
            self.app, self.board = self.alloc(0x800), self.alloc(0xa00)
            self.module, self.bank, self.modules = self.alloc(0x80), self.alloc(0x180), self.alloc(24)
            self.packets = [self.alloc(0x120) for _ in range(14)]
            holder = self.alloc(4)
            self.put(base+0x1821674, holder)
            self.put(holder, self.app)
            self.put(self.app+0x6bc, self.board)
            self.put(self.board+0x938, self.modules)
            self.put(self.module+0x48, self.bank)
            self.put(self.bank+0x14c, 6)
            self.moves = []
            self.parent_x = 26

        def setup(self, count, page, width, stride, level='arena_plant_test'):
            self.string(self.board+0xc4, level)
            self.put(self.app+0x524, width)
            self.u.mem_write(self.bank+0x11d, bytes([count]))
            self.put(self.bank+0x148, page)
            self.put(self.bank+0x28, 150)
            self.u.mem_write(self.bank+0x5c, struct.pack('<ff', 150.0, 590.0))
            for slot, card in enumerate(self.packets):
                self.put(card+0x28, (slot % 6)*stride)
                self.put(card+0x30, stride)
            self.put(self.bank+0x150, -48)
            self.put(self.bank+0x158, 40)
            self.put(self.bank+0x15c, 30)
            self.put(self.bank+0x160, 6*stride+8)
            self.put(self.bank+0x168, 40)
            self.put(self.bank+0x16c, 30)
            self.moves.clear()

        def hook(self, em, addr, size, data):
            off = addr-base
            r0, r1, r2 = (em.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            result = 0
            if off in (0x102dafc,) or 0x102e260 <= off <= 0x102e34c:
                return
            if off == 0x102db00:
                em.reg_write(UC_ARM_REG_PC, end)
                return
            if off == 0x97636c:
                assert r1 == self.bank
                self.put(r0, self.parent_x+self.get(self.bank+0x28))
                self.put(r0+4, 590)
            elif off == 0x9766cc:
                assert r0 == self.bank
                position, y = struct.unpack('<ff', struct.pack('<II', r1, r2))
                self.moves.append((position, y))
                self.put(self.bank+0x5c, r1)
                self.put(self.bank+0x28, int(position))
            elif off == 0x895f0c:
                assert r1 == self.bank
                self.put(r0, self.packets[r2])
            elif off == 0x11d74b4:
                result = core.M
            elif off == 0x1da034:
                result = self.get(r1)
            elif off == 0x1d9bb4:
                pass
            elif off == 0x10290ac:
                result = core.M+0x88
            elif off == 0x43af38:
                assert r0 == self.modules and r1 == core.M+0x88
                result = self.module
            elif off == 0x15ddedc:
                result = r0//r1
            else:
                return super().hook(em, addr, size, data)
            em.reg_write(UC_ARM_REG_R0, result)
            em.reg_write(UC_ARM_REG_PC, em.reg_read(UC_ARM_REG_LR))

        def layout(self):
            self.u.reg_write(UC_ARM_REG_R6, self.bank)
            self.u.reg_write(UC_ARM_REG_FP, core.END+0x1f0020)
            self.run(0x102dafc)

    bank = Bank()
    cases = [
        (6, 0, 1424, 132, 'arena_plant_test'),
        (14, 1, 2572, 234, 'arena_plant_test'),
        (14, 2, 2572, 234, 'arena_plant_test'),
        (1, 0, 800, 80, 'arena_plant_tutorial'),
    ]
    for count, page, width, stride, level in cases:
        bank.setup(count, page, width, stride, level)
        bank.layout()
        x = bank.parent_x + bank.get(bank.bank+0x28)
        span = min(6, count-page*6)*stride
        assert x == (width-span)//2
        assert bank.moves == [(x-bank.parent_x, 590.0)]
        bank.layout()
        assert len(bank.moves) == 1
        # Execute the stock paging hit test with the bank's new widget bounds.
        bank.run(0x102e260, bank.bank, x-40, 598)
        assert bank.u.reg_read(UC_ARM_REG_R0) == (1 if page else 0)
        bank.run(0x102e260, bank.bank, x+6*stride+12, 598)
        assert bank.u.reg_read(UC_ARM_REG_R0) == (2 if count > (page+1)*6 else 0)
    for count, page, level in [(0, 0, 'arena_plant_test'), (2, 99, 'arena_plant_test'),
                               (6, 0, 'arena_battle_test'), (6, 0, 'egypt1')]:
        bank.setup(count, page, 1424, 132, level)
        bank.layout()
        assert not bank.moves
    return 2*len(cases)+4


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    check(parser.parse_args().folder)
