"""Exercise difficulty gates and independent multi-star results in the ARM32 guest."""

import argparse
import math
from pathlib import Path
import struct
from zipfile import ZipFile

from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R9, UC_ARM_REG_SP

from check_aster_adventure_records import (
    ARGS, BASE, BOARD, DATA, DIALOG, GRAPHICS, PROFILE, PROPERTIES, SCENE, SocialGame,
)
from build_aster_star_difficulty import ENGINE


DIFFICULTY_FILE = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-difficulty.bin"
MODULE, MANAGER, GOALS, CONDITIONS = [DATA + x for x in (0x10100, 0x10200, 0x10300, 0x10400)]
CONDITION_VTABLE = DATA + 0x10800
SATISFIED = 0x10020
REWARD, SPRITE, IMAGE, MATRIX = [DATA + x for x in (0x11000, 0x11200, 0x11400, 0x11600)]
NATIVE_TRANSFORM = (1.5, -0.25, 480.0, 0.25, 1.5, 270.0, 0.0, 0.0, 1.0)


class ChallengeGame(SocialGame):
    def __init__(self, output, engine, difficulty=None, social=True):
        super().__init__(output, social_enabled=social, engine=engine)
        self.arm.mem_map(DATA + 0x10000, 0x10000)
        self.goals = []
        self.failures = set()
        self.awards = []
        self.reward_layers = []
        if difficulty is not None:
            self.files[DIFFICULTY_FILE] = struct.pack("<III", 0x31444953, difficulty, difficulty ^ 0xffffffff)
        self.put(CONDITION_VTABLE + 0x5c, BASE + SATISFIED)
        for i, goal in enumerate(((1, 4), (2, 4), (3, 4))):
            rows = self.get(PROPERTIES + 0x1c)[0]
            start = GOALS + 16 * i
            self.put(rows + 12 * i, start, start + 16, start + 16)
            self.put(start, goal[0], 10, goal[1], 10)

    def native(self, arm, address, size, context):
        offset = address - BASE
        a, b, c, d = (arm.reg_read(reg) for reg in ARGS)
        result = 0
        if offset == 0x43a0e0:
            assert a == MODULE
            result = MANAGER
        elif offset == 0x43be34:
            assert a == MANAGER
            goal, serial = self.get(b, 2)
            assert serial == 10 and goal not in self.goals
            self.goals.append(goal)
            result = CONDITIONS + goal * 0x40
            self.put(result, CONDITION_VTABLE)
        elif offset == SATISFIED:
            goal = (a - CONDITIONS) // 0x40
            assert goal in self.goals
            result = goal not in self.failures
        elif offset == 0x7482e4:
            assert a == PROFILE and d == 1
            assert not self.earned & (1 << c)
            self.awards.append(c + 1)
            self.earned |= 1 << c
        elif offset == 0x21f2ec:
            assert a == BOARD
            self.put(REWARD + 0x80, 12, 34)
            result = REWARD
        elif offset == 0x116a498:
            assert (a, b, d) == (GRAPHICS, IMAGE, 0)
            assert self.get(arm.reg_read(UC_ARM_REG_SP))[0] == 0
            self.reward_layers.append(struct.unpack("<9f", self.arm.mem_read(c, 36)))
        else:
            return super().native(arm, address, size, context)
        arm.reg_write(UC_ARM_REG_R0, result)
        arm.reg_write(UC_ARM_REG_PC, arm.reg_read(UC_ARM_REG_LR))

    def select(self, *tiers):
        assert self.choose() is not None
        self.update_menu()
        for tier in tiers:
            self.click(16 + tier)
        self.click(2)
        assert self.launched.pop()[2] == "egypt1"
        assert self.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        self.put(SCENE + 0x984, 6)
        return self.get(BOARD + 0x7f0)[0] + 1


    def draw_reward(self, expected):
        assert self.execute(0x998ec0, BOARD, 0, return_from_call=True) == REWARD
        self.put(IMAGE + 0x28, 96, 93)
        self.arm.mem_write(MATRIX, struct.pack("<9f", *NATIVE_TRANSFORM))
        self.arm.reg_write(UC_ARM_REG_R9, SPRITE + 0x80)
        self.put(SPRITE + 8, 12, 99)
        self.execute(0x2fe020, GRAPHICS, IMAGE, MATRIX, 0, return_from_call=True)
        assert self.reward_layers == [NATIVE_TRANSFORM]
        self.reward_layers.clear()
        self.put(SPRITE + 8, 12, 34)
        self.execute(0x2fe020, GRAPHICS, IMAGE, MATRIX, 0, return_from_call=True)
        assert len(self.reward_layers) == expected
        if expected == 1:
            assert self.reward_layers == [NATIVE_TRANSFORM]
            return
        assert len(set(self.reward_layers)) == expected
        for drawn in self.reward_layers:
            assert drawn[0] < NATIVE_TRANSFORM[0]
            assert math.isclose(drawn[0], drawn[4])
            assert math.isclose(drawn[1], -drawn[3])


def check(output, engine):
    for difficulty in (None, 1, 2):
        locked = ChallengeGame(output, engine, difficulty)
        locked.trophy_progress[1, "egypt11"] = 2
        assert locked.choose() is None and locked.launched.pop()[2] == "egypt1"
        assert locked.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
        assert locked.get(BOARD + 0x7f0)[0] == 0xffffffff

    disabled = ChallengeGame(output, engine, 0, social=False)
    assert disabled.choose() is None and disabled.launched.pop()[2] == "egypt1"
    assert not disabled.execute("asterAdventureSelectChallenge", BASE, BOARD, PROPERTIES)
    assert disabled.execute("asterSocialSettingsClick", BASE, DIALOG, 1064) == 1

    settings = ChallengeGame(output, engine)
    settings.put(DATA + 4, 0)
    assert settings.execute("asterSocialSettingsClick", BASE, DIALOG, 1064) == 2
    assert settings.execute("asterSocialSettingsClick", BASE, DIALOG, 1065) == 1
    assert settings.files[DIFFICULTY_FILE] == struct.pack("<III", 0x31444953, 0, 0xffffffff)

    conflict = ChallengeGame(output, engine, 0)
    assert conflict.choose(b"lostcity24") is not None
    conflict.update_menu()
    conflict.click(17)
    conflict.click(18)
    assert 2 not in conflict.menu_buttons
    conflict.click(18)
    assert 2 in conflict.menu_buttons

    hard = ChallengeGame(output, engine, 2)
    assert hard.select(1, 3) == 3
    assert not hard.execute("asterAdventureLoadMultiStar", BASE, MODULE, PROPERTIES)

    for difficulty, missed, existing, awards in (
        (0, 0, 0, (1, 3)), (1, 0, 0, (1, 3)),
        (0, 1, 0, (3,)), (1, 3, 0, (1,)), (0, 4, 0, ()), (1, 0, 1, (3,)),
    ):
        game = ChallengeGame(output, engine, difficulty)
        if difficulty == 0:
            game.trophy_progress[1, "egypt11"] = 1
        game.earned = existing
        if existing:
            game.start(8, stars=1)
            game.tick(8.125)
            game.finish()
            assert game.best(stars=1)[4] == 125
        assert game.select(1, 3) == 3
        assert game.execute("asterAdventureLoadMultiStar", BASE, MODULE, PROPERTIES)
        assert game.goals == [1, 4, 3]
        assert game.execute("asterAdventureMultiStarDescription", BASE, BOARD, 0) == 1
        assert game.execute("asterAdventureMultiStarDescription", BASE, BOARD, 1) == 0
        assert game.execute("asterAdventureMultiStarDescription", BASE, BOARD, 2) == 1
        game.start(10, stars=3)
        game.tick(10.25)
        if missed == 1:
            game.execute(0x1fc6c0, BOARD, CONDITIONS + missed * 0x40)
            assert not game.arm.mem_read(BOARD + 0x7fe, 1)[0]
        elif missed:
            game.failures.add(missed)
        game.finish()
        game.execute(0x903634, MODULE, return_from_call=True)
        game.execute(0x903634, MODULE, return_from_call=True)
        assert tuple(game.awards) == awards
        game.draw_reward(max(1, len(awards)))
        assert not game.best(stars=2)
        paths = {tier: [v for p,v in game.files.items() if p.endswith(f"-1-{tier}.run")]
                 for tier in (1, 3)}
        if not missed:
            one, = paths[1]
            three, = paths[3]
            assert one[16:-4] == three[16:-4]
        elif missed == 4:
            assert not paths[1] and not paths[3]
        else:
            assert not paths[missed] and len(paths[4-missed]) == 1
        assert game.get(MODULE + 0x19)[0] & 0xffffff == (1 if not awards else 0x010101)
    triple = ChallengeGame(output, engine, 0)
    assert triple.select(1, 2, 3) == 3
    assert triple.execute("asterAdventureLoadMultiStar", BASE, MODULE, PROPERTIES)
    assert triple.goals == [1, 4, 2, 3]
    triple.start(10, stars=3)
    triple.tick(10.25)
    triple.finish()
    triple.execute(0x903634, MODULE, return_from_call=True, instruction_limit=350_000)
    assert triple.awards == [1, 2, 3]
    triple.draw_reward(3)
    triple.put(SPRITE + 0xb0, GOALS, GOALS + 6 * 4)
    assert triple.execute("asterAdventureGoalListY", BASE, SPRITE, 200) == 218
    triple.put(SPRITE + 0xb4, GOALS + 4 * 4)
    assert triple.execute("asterAdventureGoalListY", BASE, SPRITE, 200) == 200
    assert triple.best(stars=1)[4:] == triple.best(stars=2)[4:] == triple.best(stars=3)[4:]

    print("Difficulty and multi-star ARM checks passed (unlock, opt-out, shared rule, partial win, record parity, replay, reward-art layering).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("output", type=Path, help="Directory containing the linked adventure payload")
    args = parser.parse_args()
    engine = args.output / "tested-engine.so"
    with ZipFile(args.apk) as apk:
        engine.write_bytes(apk.read(ENGINE))
    check(args.output, engine)
