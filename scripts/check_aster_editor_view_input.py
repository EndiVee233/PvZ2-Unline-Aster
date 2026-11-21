"""Check editor cell selection and cursor-constructor touch/stack forwarding."""
import argparse,json,struct
from pathlib import Path
from unicorn.arm_const import *
from check_aster_view_matrix import World,BASE,MEM,STOP,f32

class Editor(World):
 def __init__(self,folder,normal,geometry):
  super().__init__(folder,struct.pack('<3I',0x31564155,int(normal),(~int(normal))&0xffffffff))
  self.normal=normal;self.width,self.bx,self.by,self.scale=geometry;self.scale=f32(self.scale)
  for o,v in ((0x524,self.width),):self.put(self.app+o,v)
  self.put(self.board+0x2c,self.bx);self.put(self.board+0x30,self.by)
  for o in (0x690,0x698):self.put(self.app+o,struct.unpack('<I',struct.pack('<f',self.scale))[0])
  self.out=MEM+0x17000;self.weak=MEM+0x17100;self.rect=MEM+0x17200;self.plant=MEM+0x17300
  self.finish=None;self.constructed=[]
 def hook(self,u,a,s,d):
  off=a-BASE
  if off==0x10ab71c:
   r=[u.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
   assert r[0]==self.cursor and r[2:]==[self.weak,self.rect]
   assert struct.unpack('<2I',u.mem_read(u.reg_read(UC_ARM_REG_SP),8))==(0,self.plant)
   self.constructed.append(struct.unpack('<11i',u.mem_read(r[1],44)));self.ret(self.cursor);return
  if self.finish is not None and off==self.finish:u.reg_write(UC_ARM_REG_PC,STOP);u.emu_stop();return
  return super().hook(u,a,s,d)
 def point_for_row(self,row):
  x,y=488*self.scale,(160+(row+0.5)*76)*self.scale
  if self.normal:x=1.2*x+0.2*self.bx-0.2*self.width;y=1.2*y-0.2*540*self.scale
  return round(x),round(y)
 def cell(self,row):
  self.set_point(*self.point_for_row(row));before=bytes(self.u.mem_read(self.point,8));self.finish=0x22a3d0
  self.run(0x22a3cc,self.out,self.board,self.point,native=True);self.finish=None
  assert bytes(self.u.mem_read(self.point,8))==before
  assert struct.unpack('<2i',self.u.mem_read(self.out,8))==(4,row)
 def constructor(self,row):
  x,y=self.point_for_row(row);self.set_touch(x,y,0)
  if row%2:self.put(self.packet+16,-1);self.put(self.packet+20,-1)
  original=bytes(self.u.mem_read(self.packet,44));wanted=list(struct.unpack('<11i',original))
  self.set_point(x,y);self.run('asterViewPoint',self.board,self.point);wanted[2:4]=self.point_value()
  if wanted[4:6]!=[-1,-1]:
   self.set_point(*wanted[4:6]);self.run('asterViewPoint',self.board,self.point);wanted[4:6]=self.point_value()
  regs=(UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8)
  values=(self.cursor,self.packet,self.weak,self.rect,self.packet,self.board,0x666,0x777,0x888)
  for r,v in zip(regs,values):self.u.reg_write(r,v)
  self.put(0x4080000,0);self.put(0x4080004,self.plant)
  self.u.reg_write(UC_ARM_REG_SP,0x4080000);self.u.reg_write(UC_ARM_REG_LR,STOP);self.finish=0x22a48c
  self.u.emu_start(BASE+0x22a488,STOP,count=200000);self.finish=None
  assert self.u.reg_read(UC_ARM_REG_PC)==STOP and self.u.reg_read(UC_ARM_REG_SP)==0x4080000
  assert self.u.reg_read(UC_ARM_REG_R0)==self.cursor
  assert [self.u.reg_read(r) for r in regs[4:]]==list(values[4:])
  assert self.constructed[-1]==tuple(wanted)
  assert bytes(self.u.mem_read(self.packet,44))==original

def check(folder):
 cases=0
 for normal in (False,True):
  for geometry in ((2112,80,80,2.56),(2730,-200,60,3.2),(1800,40,-100,2.0)):
   p=Editor(folder,normal,geometry)
   for row in range(5):p.cell(row);p.constructor(row);cases+=2
 report=dict(native_cases_passed=cases,native_cell_conversion_executed=True,cursor_constructor_boundary_stubbed=True,constructor_touch_stack_and_callee_registers_preserved=True,original_input_unmodified=True,runtime_accepted=False)
 (folder/'editor-view-input-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);check(p.parse_args().folder)
