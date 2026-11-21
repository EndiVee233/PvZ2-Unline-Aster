"""Run native Board scope rectangles through A187's actual wrapper chain."""
from pathlib import Path
import argparse,json,math,struct
from unicorn.arm_const import *
from check_aster_skill_board import Skills
from check_aster_view_angle import BASE,MEM,bits

class Scope(Skills):
 def __init__(self,folder,normal):
  super().__init__(folder,normal);self.rectangles=[];self.widths=[];self.states=[]
  slot=(self.get(BASE+0x2072ac)+BASE+0x2070d8)&0xffffffff
  self.put(self.get(slot),self.app)
 def hook(self,u,a,s,d):
  off=a-BASE;r=[u.reg_read(v) for v in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
  if off==0x207088:
   self.widths.append(self.get(u.reg_read(UC_ARM_REG_SP)))
   assert r[:2]==[self.board,self.graphics]
   return # execute native square placement/geometry
  if off==0x116d800:self.states.append(bytes(u.mem_read(r[0],0x74)));self.ret();return
  if off==0x116d764:u.mem_write(r[0],self.states.pop());self.ret();return
  if off==0x14780c or self.imports.get(a)=='floor':
   value=struct.unpack('<d',struct.pack('<2I',*r[:2]))[0]
   low,high=struct.unpack('<2I',struct.pack('<d',float(math.floor(value))))
   u.reg_write(UC_ARM_REG_R1,high);self.ret(low);return
  if off==0x112f7b0:
   u.mem_write(r[0],struct.pack('<4I',*r[1:],self.get(u.reg_read(UC_ARM_REG_SP))));self.ret(r[0]);return
  if off==0x1166c30:self.ret();return
  if off==0x1167128:
   self.rectangles.append(tuple(struct.unpack('<4i',u.mem_read(r[1],16))));self.ret();return
  return super().hook(u,a,s,d)

def check(folder):
 cases=0
 for normal in (False,True):
  p=Scope(folder,normal)
  for scale in (1.,2.56,3.2):
   p.put(p.app+0x690,bits(scale))
   for cost in (25,20,30,40):
    p.put(p.props+0x160,cost)
    for grade in range(1,5):
     p.put(BASE+0x1b00000,grade);p.put(BASE+0x1b00004,grade)
     p.put(0x4080000,2);p.put(0x4080000+4,p.props)
     graphics=bytes(p.u.mem_read(p.graphics,0x74));p.rectangles=[];p.widths=[]
     p.run(0x1a05650,p.board,p.graphics,4)
     assert p.widths==[3] and len(p.rectangles)==1,(normal,scale,cost,grade,p.widths,p.rectangles)
     x,y,w,h=p.rectangles[0]
     assert abs(w-3*64*scale)<2 and abs(h-3*76*scale)<2,(scale,p.rectangles)
     assert abs(x-(200+3*64)*scale)<2 and abs(y-(160+76)*scale)<2,(scale,p.rectangles)
     assert graphics==bytes(p.u.mem_read(p.graphics,0x74)) and not p.states;cases+=1
  # The rectangle wrapper no longer stretches a square into a level-dependent
  # rectangle; execute the installed legacy entry redirect itself.
  rect=MEM+0x17500;data=struct.pack('<4i',100,200,192,228);p.u.mem_write(rect,data)
  p.rectangles=[];p.run(0x1a05734,p.graphics,rect)
  assert p.rectangles==[(100,200,192,228)] and bytes(p.u.mem_read(rect,16))==data;cases+=1
 report=dict(native_scope_cases_passed=cases,all_four_skills_all_grades_fixed_3x3=True,actual_native_square_geometry_executed=True,legacy_wrapper_chain_and_graphics_state_checked=True,rectangle_not_stretched=True,runtime_accepted=False)
 (folder/'fixed-scope-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);check(p.parse_args().folder)
