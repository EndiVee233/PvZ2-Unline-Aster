"""Run test-profile settings actions in ARM with synthetic player and filesystem boundaries."""
from pathlib import Path
import sys
import check_offline_pvp_arm as core
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_LR, UC_ARM_REG_SP, UC_ARM_REG_PC,
)


class Registry(core.Engine):
    def __init__(self):
        super().__init__()
        self.db, self.ui, self.type, self.vtable = [self.alloc(n) for n in (0x200, 0x180, 32, 32)]
        self.description = self.alloc(8)
        self.put(self.description, self.vtable)
        self.put(self.vtable+4, core.BASE+0x146008)
        self.put(self.vtable+0x14, core.BASE+0x146004)
        self.put(self.type+12, core.BASE+0x146000)
        self.put(core.PM+4, self.alloc(128))
        for got, func in ((0x1822ebc, 0x148448), (0x1822ec4, 0x148460), (0x1822bd4, 0x147b90)):
            self.put(core.BASE+got, core.BASE+func)
        self.files['/dev/urandom'] = bytes(range(1, 65))
        self.slots, self.rows, self.destroyed = [], [], []
        self.write_count = 0
        self.link()

    def link(self):
        end = self.db+0x30
        for left, right in zip([end, *self.slots], [*self.slots, end]):
            self.put(left, right)
        self.put(self.db+0x50, len(self.slots))

    def slot(self, player, uid):
        slot = self.alloc(32)
        self.put(slot+8, player)
        self.put(slot+0x10, 0x90000001)
        for i, word in enumerate(uid):
            self.put(slot+0x14+4*i, word)
        self.slots.append(slot)
        self.link()
        return slot

    def ordinary(self, number, name):
        player = self.alloc(0x900)
        self.put(player, self.vtable)
        self.put(player+0x1ec, number)
        self.string(player+0x58, name, wide=True)
        return self.slot(player, (1, 0, number))

    def wide(self, ptr):
        return bytes(self.u.mem_read(ptr, self.get(ptr-12)*4)).decode('utf-32-le')

    def hook(self, em, addr, size, data):
        off = addr-core.BASE
        x, y, z, w = [em.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
        result = 0
        if off == 0x20ec10:
            result = core.M
        elif off == 0x864900:
            assert y == 0x2d
            result = self.db
        elif off == 0x72c500:
            result = self.type
        elif off == 0x146000:
            result = self.alloc(0x900)
            self.put(result, self.vtable)
        elif off == 0x146004:
            assert x not in self.destroyed
            self.destroyed.append(x)
        elif off == 0x11f2c88:
            assert bytes(em.mem_read(y, 4)) == b'RTON' and bytes(em.mem_read(y+z-4, 4)) == b'DONE'
        elif off == 0x11dad94:
            assert x == self.db and self.get(z+4)-self.get(z) == 4 and self.get(y+8) == 1
            self.put(self.get(self.get(z))+0x1ec, 1722523140)
            result = 1
        elif off in (0x7aab68, 0x7aa7c8):
            assert y == core.PM
            for slot in self.slots:
                player = self.get(slot+8)
                hit = (self.get(player+0x1ec) == z if off == 0x7aab68 else
                       self.wide(self.get(player+0x58)) == self.wide(self.get(z)))
                if hit:
                    self.put(x, slot)
                    break
        elif 0x1d9bb4 <= off <= 0x1d9c6c:
            if off == 0x1d9bb4:
                assert (z, w) == (0, 0), f'invalid null handle r2={z:#x}, r3={w:#x}'
            return  # Execute the shipped ARM weak-handle setter itself.
        elif off in (0x14eae74, 0x14e9b0c):
            self.put(x, self.get(y))
            result = x
        elif off == 0x11dd120:
            sp = em.reg_read(UC_ARM_REG_SP)
            uid = self.get(sp+4)
            assert y == self.db and w == 0 and self.get(sp) == 1
            uid = tuple(self.get(uid+i) for i in (0, 4, 8))
            assert uid == (1, 193, 0x41535452)
            self.put(x, self.slot(z, uid))
        elif off == 0x11d62c8:
            result = self.get(y)
        elif 0x11d635c <= off <= 0x11d6390:
            return  # Run the stock ownership-mode setter.
        elif off == 0x11d6450:
            slot = self.get(y)
            self.slots.remove(slot)
            if not self.get(slot+0x10) & 0x20000000:
                self.destroyed.append(self.get(slot+8))
            self.link()
            # r3 is caller-saved. A193 passed its leftover high bit to the
            # stock setter after detaching a slot (WSA guest LR 0x1a47910).
            em.reg_write(UC_ARM_REG_R3, 0x80000001)
            result = 1
        elif off == 0x4a10a0:
            assert x == self.get(core.PM+4)+4
            self.write_count += 1
            result = not self.failwrite
        elif off == 0x7aaa74:
            self.put(core.PM+0x74, self.get(self.get(self.slots[0]+8)+0x1ec))
        elif off == 0x8e4edc:
            self.rows.append((y, self.wide(self.get(z)), w))
            result = self.alloc(4)
        elif off in (0x146008, 0x8e5924, 0x11ed448, 0x8e7820):
            pass
        else:
            return super().hook(em, addr, size, data)
        em.reg_write(UC_ARM_REG_R0, result)
        em.reg_write(UC_ARM_REG_PC, em.reg_read(UC_ARM_REG_LR))

    def click(self, action):
        self.run('offlinePresetSettingsClick', self.ui, action)

    def state(self, enabled, title='测试存档'):
        self.rows.clear()
        self.run('offlinePresetPageRows', self.ui, self.description)
        assert self.rows == [(1051, '开启', int(enabled)), (1052, '关闭', int(not enabled))], self.rows
        self.run('offlinePresetPageTitle', self.ui, 0)
        assert self.wide(self.get(self.ui+0xa0)) == title


def check(folder):
    core.OUT = folder
    # Start from a previously saved, renamed test user. This reproduces the
    # reported close action independently of the code that creates a slot.
    for selected in (42, 77):
        existing = Registry()
        regular = existing.ordinary(42, '全一 TEST')
        managed = existing.ordinary(77, '改过名的测试用户')
        for offset, value in ((0x18, 193), (0x1c, 0x41535452)):
            existing.put(managed+offset, value)
        existing.put(core.PM+0x74, selected)
        existing.click(1006)
        existing.state(True)
        existing.click(1052)
        existing.state(False)
        assert existing.slots == [regular] and existing.get(core.PM+0x74) == 42
    e = Registry()
    ordinary = e.ordinary(42, '全一 TEST')
    e.click(1006)
    e.state(False)
    e.failwrite = True
    e.click(1051)
    e.state(False, '存档保存失败，请重试')
    assert e.slots == [ordinary]
    e.failwrite = False
    e.click(1051)
    e.state(True)
    player = e.get(e.slots[-1]+8)
    assert e.wide(e.get(player+0x58)) == '全一 TEST 2'
    assert e.get(core.PM+0x74) == 42
    e.string(player+0x58, '已改名', wide=True)
    writes = e.write_count
    e.click(1051)
    assert e.write_count == writes
    e.state(True)
    e.put(core.PM+0x74, e.get(player+0x1ec))
    e.failwrite = True
    e.click(1052)
    e.state(True, '存档保存失败，请重试')
    assert e.get(e.slots[-1]+8) == player and player not in e.destroyed
    e.failwrite = False
    e.click(1052)
    e.state(False)
    assert e.slots == [ordinary] and player in e.destroyed and e.get(core.PM+0x74) == 42
    e.click(1051)
    e.click(1052)
    e.state(False)
    assert e.slots == [ordinary] and e.get(core.PM+0x74) == 42
    e.click(1051)
    e.slots.pop()  # The stock profile list deleted the managed slot.
    e.link()
    e.click(0)
    e.click(1006)
    e.state(False)
    for i in range(4):
        e.ordinary(50+i, str(i))
    full, writes = e.slots[:], e.write_count
    e.click(1051)
    e.state(False, '玩家槽位已满（最多5个）')
    e.click(1052)
    e.state(False)
    assert e.slots == full and e.write_count == writes
    only = Registry()
    only.click(1006)
    only.click(1051)
    only.put(core.PM+0x74, only.get(only.get(only.slots[0]+8)+0x1ec))
    only.click(1052)
    only.state(False)
    assert not only.slots and only.get(core.PM+0x74) == 0
    print('ARM settings: default off, namesake, rename, repeated enable, write rollback, '
          'active/inactive/last-player deletion, manual deletion, full and retry passed')


if __name__ == '__main__':
    check(Path(sys.argv[1]))
