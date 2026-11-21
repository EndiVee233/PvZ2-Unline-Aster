"""Execute native cursor pickup predicates, release, keep and finish bodies."""
from pathlib import Path
import argparse,json,struct
from unicorn.arm_const import *
from check_aster_view_matrix import World,BASE,MEM,STOP,f32

class Pickup(World):
    def __init__(self,folder,normal,food=False,point=(50,240),geometry=(2112,80,80,2.56)):
        super().__init__(folder,struct.pack('<3I',0x31564155,int(normal),(~int(normal))&0xffffffff))
        self.food=food;self.actions=[];self.native_calls=[]
        self.setting_bounds=False;self.bounds_site=0x4e7f1c if food else 0x4e5900
        width,bx,by,scale=geometry;scale=f32(scale)
        self.put(self.app+0x524,width);self.put(self.board+0x2c,bx);self.put(self.board+0x30,by)
        for off in (0x690,0x698):self.put(self.app+off,struct.unpack('<I',struct.pack('<f',scale))[0])
        self.cursor_table=MEM+0x15000;self.bus=MEM+0x19000;self.bus_table=MEM+0x19100
        self.handlers=MEM+0x19200;self.module=MEM+0x19300;self.active=MEM+0x19500
        table=BASE+(0x179b990 if food else 0x179b940)
        self.u.mem_write(self.cursor_table,bytes(self.u.mem_read(table,0x48)))
        self.put(self.cursor,self.cursor_table);self.put(self.cursor_table+0xc,STOP+0xd04)
        self.u.mem_write(self.cursor+0x1c,bytes(4))
        self.put(self.bus,self.bus_table);self.put(self.bus_table+4,STOP+0xd00)
        # Original static event bus global, resolved through its real GOT slot.
        got=(self.get(BASE+0x1efe18)+BASE+0x1efd68)&0xffffffff
        self.put(self.get(got),self.bus)
        # Plant-food activation audio bus; audio output is outside this check.
        audio=(self.get(BASE+0x4e8bd4)+BASE+0x4e8b68)&0xffffffff
        self.put(audio,self.bus)
        # Execute the actual constructor call instruction to the native bounds
        # setter (or its installed hook), with its real r0/r1 ABI.
        rectangle=MEM+0x19800
        self.u.mem_write(rectangle,struct.pack('<4i',*[int(x*scale) for x in (20,200,60,80)]))
        self.setting_bounds=True;self.run(self.bounds_site,self.cursor,rectangle,native=True);self.setting_bounds=False
        self.set_point(int(point[0]*scale),int(point[1]*scale))
        if normal:self.run('asterViewPoint',self.board,self.point)
        self.event_point=self.point_value()
        self.run(0x1efccc,self.cursor,self.point,native=True)
        self.put(self.cursor+0x24,0x7ffffffe)
        self.put(self.board+0x94c,0)
        self.put(self.board+0x940,self.active);self.put(self.board+0x944,self.active+4);self.put(self.board+0x948,self.active+4)
        self.put(self.active,self.cursor)
    def hook(self,u,address,size,unused):
        off=address-BASE;r0=u.reg_read(UC_ARM_REG_R0);r1=u.reg_read(UC_ARM_REG_R1);r2=u.reg_read(UC_ARM_REG_R2)
        if self.setting_bounds and off==self.bounds_site+4:
            u.reg_write(UC_ARM_REG_PC,STOP);u.emu_stop();return
        if off==0x147adc:self.ret();return # bounded diagnostic logger
        if off==0xf26fc8:self.ret(BASE+off);return
        if off==0x43af38:self.ret(0);return # no optional level restriction module
        if off in (0x223db8,0x223ab0):self.ret(self.module);return
        if off in (0x11d74b4,0x7837a4):self.ret(self.bus);return
        if off==0x11d761c:u.mem_write(r0,bytes(u.mem_read(r2,8)));self.ret();return
        if off==0x1d9bb4:
            self.put(r0,r2);self.put(r0+4,u.reg_read(UC_ARM_REG_R3));self.ret();return
        if off in (0x33f688,0x344358,0x1ecd30):self.ret();return
        if off in (0x4e7720,0x4e865c):self.actions.append('attempt-use');self.ret();return
        if off in (0x1efe24,0x1efd38,0x224204):self.native_calls.append(off)
        if address==STOP+0xd00:self.ret(self.handlers);return
        if address==STOP+0xd04:self.actions.append('destroy');self.ret();return
        return super().hook(u,address,size,unused)
    def predicate(self):return self.run(self.get(self.cursor_table+0x24)-BASE,self.cursor,native=True)
    def release(self,phase=3):
        self.set_touch(*self.event_point,phase);self.put(self.packet,0x7ffffffe)
        return self.run(0x1ef560,self.cursor,self.packet,native=True)

def check(folder,expect_old=False):
    rows=[]
    for food in (False,True):
      for normal in (False,True):
       for geometry in ((2112,80,80,2.56),(2730,-200,60,3.2),(1800,40,-100,2.0)):
        for point,phase,inside in (((50,240),3,True),((400,400),3,False),((50,240),4,False)):
            p=Pickup(folder,normal,food,point,geometry)
            position=tuple(p.get(p.cursor+o) for o in (4,8));predicate=p.predicate()
            rectangle=tuple(p.get(p.cursor+o) for o in (0xc,0x10,0x14,0x18))
            before=bytes(p.u.mem_read(p.cursor+4,24));p.release(phase)
            kept=p.get(p.board+0x94c)==p.cursor and not p.u.mem_read(p.cursor+0x1d,1)[0]
            expected=inside and not (expect_old and normal)
            assert kept==expected,(food,normal,position,predicate,p.native_calls,p.actions)
            assert bytes(p.u.mem_read(p.cursor+4,24))==before
            assert (0x1efe24 in p.native_calls)==kept
            assert (0x1efd38 in p.native_calls)==(not kept)
            assert ('attempt-use' in p.actions)==(phase==3 and not kept)
            rows.append(dict(food=food,normal=normal,geometry=geometry,point=point,phase=phase,native_position=position,native_pickup_rectangle=rectangle,native_predicate=predicate,pending_after_native_release=kept,native_finish_called=0x1efd38 in p.native_calls,dragged_flag=p.u.mem_read(p.cursor+0x1f,1)[0]))
    report=dict(native_cursor_event_handler_executed=True,native_pickup_and_release_executed=True,native_keep_and_board_pending_executed=True,native_finish_executed=True,expect_previous_failure=expect_old,cases=rows,runtime_accepted=False)
    (folder/('pickup-negative-checks.json' if expect_old else 'pickup-checks.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(native_pickup_release_cases_passed=len(rows),previous_failure_expected=expect_old,native_keep_finish_and_board_pending_executed=True)))

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('folder',type=Path);a.add_argument('--expect-old',action='store_true');v=a.parse_args();check(v.folder,v.expect_old)
