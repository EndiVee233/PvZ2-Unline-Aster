"""Run the packaged viewport, intro and PvP input in ARM emulation."""
import argparse
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from unicorn.arm_const import UC_ARM_REG_R1

from check_aster_view_angle import MEM, bits
from check_aster_view_matrix import World, signed
from check_aster_pvp_view_input import Pvp

NORMAL = struct.pack("<3I", 0x31564155, 1, 0xfffffffe)
HIGH = struct.pack("<3I", 0x31564155, 0, 0xffffffff)
OUT = MEM + 0x12120


class TimedWorld(World):
    now_ms = 0

    def hook(self, engine, address, size, context):
        if self.imports.get(address) == "clock_gettime":
            stamp = engine.reg_read(UC_ARM_REG_R1)
            self.put(stamp, self.now_ms // 1000)
            self.put(stamp + 4, self.now_ms % 1000 * 1_000_000)
            self.ret()
            return
        super().hook(engine, address, size, context)


def draw(probe, width, scale, origin, phase=5):
    probe.put(probe.app + 0x524, width)
    probe.put(probe.app + 0x690, bits(scale))
    probe.put(probe.board + 0xc0, phase)
    probe.put(probe.board + 0x2c, origin)
    probe.put(probe.graphics + 8, bits(origin))
    probe.run("asterViewDraw", probe.board, probe.graphics)
    return probe.world[-1]


def screen(probe, matrix, x, y, scale, local=False):
    origin_x, origin_y = [signed(probe.get(probe.board + at)) for at in (0x2c, 0x30)]
    x = (x * scale + origin_x) * matrix[0] + matrix[2]
    y = (y * scale + origin_y) * matrix[4] + matrix[5]
    return (round(x - origin_x), round(y - origin_y)) if local else (x, y)


def check(folder):
    cases = 0
    normal = World(folder, NORMAL)
    for width, scale, origin in ((2338, 2.56, -156), (2114, 2.56, -80),
                                 (1680, 2.56, -400), (2730, 2.56, 40), (2338, 2.56, -156)):
        matrix = draw(normal, width, scale, origin)
        assert 0 < matrix[0] <= 1.200001 and matrix[0] == matrix[4]
        assert screen(normal, matrix, 200, 0, scale)[0] >= min(112 * scale, width / 4) - .01
        assert screen(normal, matrix, 776, 0, scale)[0] <= width - 12 * scale + .01
        assert normal.sequence[-3:] == ["push", "world", "pop"]
        for column, row in ((0, 0), (4, 2), (8, 4)):
            x, y = screen(normal, matrix, 200 + (column + .5) * 64, 160 + (row + .5) * 76, scale, True)
            normal.set_point(x, y)
            normal.run("asterViewGridPoint", OUT, normal.board, normal.point)
            assert (normal.get(OUT), normal.get(OUT+4)) == (column, row)
            cases += 1
    # A normal-level intro keeps the existing camera pan and zoom.
    matrix = draw(normal, 2338, 2.56, -156, phase=2)
    assert abs(matrix[0] - 1.2) < 1e-5 and abs(matrix[2] + .2 * 2338) < .001
    assert draw(World(folder, HIGH), 2338, 2.56, -156) is None
    cases += 2
    transition = TimedWorld(folder, NORMAL)
    width, scale = 2338, 2.56
    preview = draw(transition, width, scale, -156, phase=3)
    previous = screen(transition, preview, 200, 160, scale)
    transition.now_ms = 1450
    for elapsed in (0, 110, 275, 440, 550):
        transition.now_ms = 1450 + elapsed
        # The native camera can update its position on the handoff frame.
        step = draw(transition, width, scale, -80)
        left = screen(transition, step, 200, 160, scale)
        if elapsed == 0:
            assert all(abs(a - b) < .001 for a, b in zip(left, previous))
        else:
            assert left[0] > previous[0]
        previous = left
        x, y = screen(transition, step, 232, 198, scale, True)
        transition.set_point(x, y)
        transition.run("asterViewGridPoint", OUT, transition.board, transition.point)
        assert (transition.get(OUT), transition.get(OUT + 4)) == (0, 0)
        cases += 1
    assert all(abs(a - b) < .001 for a, b in zip(step, draw(World(folder, NORMAL), width, scale, -80)))
    cases += 1
    for width, scale, origin in ((2338, 2.56, -156), (2114, 2.56, -80), (1680, 2.56, -400)):
        arena = Pvp(folder, True, (width, origin, 0, scale))
        matrix = draw(arena, width, scale, origin, phase=3)
        assert screen(arena, matrix, 112, 0, scale)[0] >= 0  # includes flags left of the lawn
        assert screen(arena, matrix, 904, 0, scale)[0] <= width - 12 * scale + .01
        # Test the release path used when the selected zombie card stays active.
        arena.put(arena.board + 0xc0, 5)
        for row in range(5):
            x, y = screen(arena, matrix, 840, 160 + (row + .5) * 76, scale, True)
            assert arena.fallback_point(x, y) == [(9, row)]
            cases += 1
    print(f"{cases} viewport, board and PvP input checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("old_layout", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(dir=args.input.parent) as temp:
        folder = Path(temp)
        (folder / "view-angle-patch.json").write_text(json.dumps(json.loads(args.old_layout.read_text())))
        if args.input.suffix == ".apk":
            with ZipFile(args.input) as apk:
                engine = apk.read("lib/armeabi/libSrc.so")
        else:
            engine = args.input.read_bytes()
        (folder / "libSrc-view-angle.so").write_bytes(engine)
        check(folder)
