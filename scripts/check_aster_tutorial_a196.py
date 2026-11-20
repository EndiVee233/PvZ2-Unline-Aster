"""Run the packaged tutorial handoff, banner timers and expiry checks on ARM.

The group acquisition/release and text-localization boundaries are observed
with fixtures. The decision to release, group names, style, deadline, game
clock comparisons and message clear instructions all run from the APK.
"""
import argparse
from collections import Counter
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from native_emulation_support import machine
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_FP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_SP,
)

BASE = 0x10000
APP, BOARD, MODULES = 0x6000000, 0x6002000, 0x6004000
TUTORIAL, CLOCK, MESSAGE = 0x6005000, 0x6006000, 0x6007000
STAGE, EMPTY_STRING = 0x6008000, 0x600900c
FRAME = 0x4070000
REMINDERS = (0x963F04, 0x968330, 0x96845C, 0x96C8B4, 0x96C9A0)
INTERACTIVE = (0x963B50, 0x963CF0, 0x963E3C, 0x9681D4, 0x96C79C, 0x96CB6C, 0x96CBE4)
GROUPS = Counter(('board modules', 'LevelCommon', 'LevelCommon2', 'LevelImage', 'AudioCommon', 'Keys'))


class TutorialProbe:
    def __init__(self, engine):
        os.environ['PVZ2_NATIVE_ORIGINAL'] = str(engine)
        self.u, _ = machine()
        self.acquires = Counter()
        self.releases = Counter()
        self.music_events = []
        self.u.hook_add(UC_HOOK_CODE, self.boundary)
        self.u.mem_write(APP + 0x6BC, struct.pack('<I', BOARD))
        self.u.mem_write(BOARD + 0x938, struct.pack('<I', MODULES))
        self.u.mem_write(BOARD + 0x800, struct.pack('<I', MESSAGE))
        self.app_slot = self.word(BASE + 0x1821674)
        self.u.mem_write(self.app_slot, struct.pack('<I', APP))
        self.u.mem_write(STAGE + 0x34, struct.pack('<I', EMPTY_STRING))
        # The timer constructor and update read the same native clock singleton.
        clock_slot = (BASE + 0x46D640 + 8 + self.word(BASE + 0x46D768)) & 0xffffffff
        self.u.mem_write(clock_slot, struct.pack('<I', CLOCK))

    def word(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def boundary(self, u, pc, size, context):
        offset = pc - BASE
        if offset == self.stop:
            u.emu_stop()
            return
        if offset == 0x2081DC:  # resolve the active board's stage
            assert u.reg_read(UC_ARM_REG_R0) == BOARD
            u.reg_write(UC_ARM_REG_R0, STAGE)
        elif offset == 0x8F7548:
            # Omit construction of Music_Type/LevelStarted switches. Resume at
            # the native choice between a level override and Play_Music_World.
            u.reg_write(UC_ARM_REG_PC, BASE + 0x8F75CC)
            return
        elif offset == 0x406C7C:
            assert u.reg_read(UC_ARM_REG_R0) == APP
            pointer = u.reg_read(UC_ARM_REG_R1)
            self.music_events.append(bytes(u.mem_read(pointer, 40)).split(b'\0')[0].decode('ascii'))
        elif offset == 0x14ED0E0:  # narrow string construction at the group API boundary
            u.mem_write(u.reg_read(UC_ARM_REG_R0), struct.pack('<I', u.reg_read(UC_ARM_REG_R1)))
        elif offset in (0x41C410, 0x41C74C):
            assert u.reg_read(UC_ARM_REG_R0) == APP
            pointer = self.word(u.reg_read(UC_ARM_REG_R1))
            name = bytes(u.mem_read(pointer, 32)).split(b'\0')[0].decode('ascii')
            (self.acquires if offset == 0x41C74C else self.releases)[name] += 1
        elif offset in (0x43B2D0, 0x43B40C):
            assert u.reg_read(UC_ARM_REG_R0) == MODULES
            (self.acquires if offset == 0x43B2D0 else self.releases)['board modules'] += 1
        elif offset not in (0x14EBF58, 0xD07BB4, 0x1479A4, 0x202D58):
            return
        u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))

    def run(self, start, stop, registers=()):
        self.stop = stop
        self.u.reg_write(UC_ARM_REG_FP, FRAME)
        self.u.reg_write(UC_ARM_REG_SP, FRAME - 0x100)
        self.u.reg_write(UC_ARM_REG_LR, BASE + stop)
        for register, value in registers:
            self.u.reg_write(register, value)
        self.u.emu_start(BASE + start, BASE + stop, count=4096)
        assert self.u.reg_read(UC_ARM_REG_PC) == BASE + stop, hex(start)

    def handoff(self, route, old):
        self.acquires.clear()
        self.releases.clear()
        flag = BASE + 0x184ADF8
        self.u.mem_write(flag, b'\0' if route == 'cold' else b'\x7f')
        if route == 'skip':
            self.run(0x964838, 0x96495C, ((UC_ARM_REG_R3, APP), (UC_ARM_REG_R7, self.app_slot),
                                         (UC_ARM_REG_R4, FRAME - 0x28)))
        elif route == 'continue':
            self.run(0x964BBC, 0x964BD0)
        expected = int(route == 'skip' or (route == 'continue' and old))
        assert self.u.mem_read(flag, 1)[0] == expected
        self.run(0x96ECDC, 0x96ECF8, ((UC_ARM_REG_R6, TUTORIAL),))
        assert self.u.mem_read(flag, 1)[0] == 0
        assert self.u.mem_read(TUTORIAL + 0x58, 1)[0] == expected
        self.run(0x9719E0, 0x971A04, ((UC_ARM_REG_R0, TUTORIAL),))
        assert self.acquires == (GROUPS if route == 'skip' else Counter())
        assert self.releases == (GROUPS if expected else Counter())
        self.u.mem_write(STAGE + 0x81, b'\x7f')
        self.run(0x96EA04, 0x5000000 - BASE, ((UC_ARM_REG_R0, TUTORIAL),))
        assert self.u.mem_read(STAGE + 0x81, 1)[0] == 1 - expected
        for start, end, stage_reg in ((0x8F7708, 0x5000000 - BASE, UC_ARM_REG_R0),
                                      (0x8F9A9C, 0x8F9AB4, UC_ARM_REG_R4)):
            self.music_events.clear()
            self.run(start, end, ((stage_reg, STAGE),))
            assert self.music_events == ([] if expected else ['Play_Music_World'])

    def hint(self, site, finite):
        self.u.mem_write(CLOCK + 0x24, struct.pack('<f', 100.0))
        self.run(site, 0x1E62FC, ((UC_ARM_REG_R0, TUTORIAL), (UC_ARM_REG_R1, FRAME - 0x30)))
        self.run(0x1E62FC, 0x46EA24)
        duration = struct.unpack('<f', self.u.mem_read(MESSAGE + 0x208, 4))[0]
        deadline = struct.unpack('<f', self.u.mem_read(MESSAGE + 0x204, 4))[0]
        style = 1 if finite else 2
        assert self.word(MESSAGE + 0x20C) == style
        assert (duration == 5 and deadline == 105) if finite else (duration > 1e30 and deadline > 1e30)
        for time, visible in ((104.99, True), (105.01, not finite)):
            self.u.mem_write(CLOCK + 0x24, struct.pack('<f', time))
            self.run(0x46D60C, 0x5000000 - BASE, ((UC_ARM_REG_R0, MESSAGE),))
            assert self.word(MESSAGE + 0x20C) == (style if visible else 0)


def check(folder, version):
    def engine(arch, name):
        with ZipFile(folder / f'PvZ2-Unline-Aster-A{version}-{arch}.apk') as archive:
            return archive.read(name)
    arm32 = engine('ARM32', 'lib/armeabi/libSrc.so')
    assert engine('ARM64', 'assets/guest_libs/libSrc_a32.so') == arm32
    with TemporaryDirectory(dir=folder) as temporary:
        path = Path(temporary) / 'libSrc.so'
        path.write_bytes(arm32)
        probe = TutorialProbe(path)
        for route in ('cold', 'continue', 'skip'):
            probe.handoff(route, version == 195)
        for site in REMINDERS + INTERACTIVE:
            probe.hint(site, version == 196 and site in REMINDERS)
    print(f'A{version}: both guest engines identical; 3 handoffs, 6 music dispatches/guards and 12 banner timers verified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('a195', type=Path)
    parser.add_argument('a196', type=Path)
    args = parser.parse_args()
    check(args.a195, 195)
    check(args.a196, 196)
