"""Run the embedded skill queries with native owners, vectors and cell math.

The entity registry is deliberately separate from Board. Weak-object lookup,
vector allocation and resource properties are fixture dependencies; actual
queries, native expired checks and native coordinate getters execute.
"""
import argparse,json,math,struct
from pathlib import Path
from unicorn.arm_const import *
from check_aster_view_matrix import World,BASE,MEM,STOP

class Skills(World):
 def __init__(self,folder,normal):
  super().__init__(folder,struct.pack('<3I',0x31564155,int(normal),(~int(normal))&0xffffffff))
  self.u.mem_map(MEM+0x20000,0x20000)
  self.registry=MEM+0x18000;self.objects=MEM+0x19000;self.out=MEM+0x28000;self.output=MEM+0x29000
  self.point=MEM+0x17100;self.props=MEM+0x2b000;self.seed=MEM+0x2b200;self.sub=MEM+0x2b400
  self.zone=MEM+0x2b500;self.weak_zone=MEM+0x2b600;self.owners=[];self.live=set();self.entities=[];self.finish=None
  address=(self.get(BASE+0x20ec8c)+BASE+0x20ec24)&0xffffffff;self.put(address,self.registry)
  for row in range(-1,6):
   for col in range(-1,12):
    z=MEM+0x20000+len(self.entities)*64;self.put(z+8,z);self.live.add(z)
    self.u.mem_write(z+16,struct.pack('<2f',232+64*col,198+76*row));self.entities.append((z,col,row))
  dead=MEM+0x24000;self.put(dead+8,dead);self.u.mem_write(dead+16,struct.pack('<2f',488,350));self.dead=dead
  for i,z in enumerate([z for z,_,_ in self.entities]+[dead,0]):self.put(self.objects+i*4,z)
  self.put(self.board+0x9ec,self.objects);self.put(self.board+0x9f0,self.objects+4*(len(self.entities)+2))
  self.put(self.cursor+0x30,self.seed);self.put(self.seed,self.props)
  self.put(self.weak_zone,self.zone);self.put(self.sub+0x14,self.weak_zone);self.put(self.sub+0x18,self.weak_zone+8)
  self.set_point(0,0);self.run('asterViewPoint',self.board,self.point) # load requested view
 def hook(self,u,a,s,d):
  off=a-BASE;r=[u.reg_read(v) for v in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
  if off==0x105a220 and self.finish==off+4:u.reg_write(UC_ARM_REG_R6,self.cursor)
  name=self.imports.get(a)
  if name=='floorf':
   value=struct.unpack('<f',struct.pack('<I',r[0]))[0];self.ret(struct.unpack('<I',struct.pack('<f',math.floor(value)))[0]);return
  if off==0x11d74b4:self.ret(self.registry);return
  if off==0x11d761c:u.mem_write(r[0],bytes(u.mem_read(r[2],8)));self.ret();return
  if off==0x11d7538:self.ret(self.registry);return
  if off==0x11d6620:self.ret(self.get(r[1]) if self.get(r[1]) in self.live else 0);return
  if off==0x1da034:self.ret(self.get(r[1]));return
  if off==0xb82850:self.put(r[0],self.props);self.put(r[0]+4,0);self.ret();return
  if off==0x1d9bb4:self.put(r[0],r[2]);self.put(r[0]+4,r[3]);self.ret();return
  if off==0x44a310:
   p=self.get(r[0]+4);assert p<self.output+4096;self.put(p,self.get(r[1]));self.put(r[0]+4,p+4);self.ret();return
  if off==0x20a1c0:self.owners.append(r[0]) # execute real Board+0x9ec getter
  if self.finish is not None and off==self.finish:u.reg_write(UC_ARM_REG_PC,STOP);u.emu_stop();return
  return super().hook(u,a,s,d)
 def query(self,site,col,row,cost=40):
  self.put(self.out,self.output);self.put(self.out+4,self.output);self.put(self.out+8,self.output+4096)
  self.u.mem_write(self.point,struct.pack('<2f',232+64*col,198+76*row));self.put(self.props+0x160,cost)
  self.finish=site+4;self.owners=[]
  # The original preview call site obtains its cursor from native r6.
  self.u.reg_write(UC_ARM_REG_R6,self.cursor)
  self.run(site,self.out,2,self.point,0x42800000,native=True);self.finish=None
  count=(self.get(self.out+4)-self.output)//4
  return set(struct.unpack('<'+'I'*count,self.u.mem_read(self.output,count*4))) if count else set()
 def expected(self,col,row,w,h):
  x,y=col-w//2,row-h//2
  return {z for z,c,r in self.entities if x<=(8 if 9<=c<=10 and x<=8<x+w else c)<x+w and y<=r<y+h}

def check(folder,expect_old=False,fixed_ranges=False):
 cases=0
 for normal in (False,True):
  p=Skills(folder,normal)
  # Execute the actual registry getter as well; repairing the query must not
  # change this singleton or its legitimate scene/entity callers.
  assert p.run(0x20ec10,native=True)==p.registry;cases+=1
  for site,cost,w,h in ((0x10067f0,40,3,3),(0x1007924,30,5,4),(0x105a220,40,3,3),(0x105a220,25,3,3),(0x105a220,20,3,3),(0x105a220,30,5,4)):
   if fixed_ranges:w=h=3
   for col,row in ((4,2),(0,0),(8,4),(8,2),(10,2)):
    got=p.query(site,col,row,cost)
    assert got==(set() if expect_old else p.expected(col,row,w,h)),(normal,hex(site),cost,col,row,len(got))
    assert p.owners==[p.registry if expect_old else p.board]
    assert p.dead not in got;cases+=1
  # These two grade-cache addresses were confirmed from actual embedded
  # helper reads. Change emulator memory only, never a player save.
  # Native zone correction is +24 in the entity, -24 in containment.
  p.u.mem_write(p.zone+16,struct.pack('<2f',232+64*8,198+76*2+24))
  for grade,w,h in ((1,3,3),(2,3,4),(3,4,4),(4,4,5)):
   if fixed_ranges:w=h=3
   for site,offset,cost,cache in ((0x1001a60,0x18,25,0x1b00000),(0x10060cc,0x14,20,0x1b00004)):
    p.put(BASE+cache,grade)
    for col,row in ((4,2),(8,2)):
     got=p.query(0x105a220,col,row,cost)
     assert got==(set() if expect_old else p.expected(col,row,w,h)),(grade,cost,col,row,len(got));cases+=1
    p.put(p.sub+offset,p.weak_zone);p.put(p.sub+offset+4,p.weak_zone+8)
    for z,col,row in p.entities:
     got=p.run(site,p.sub,z,native=True)
     assert bool(got)==(z in p.expected(8,2,w,h)),(hex(site),grade,col,row,got);cases+=1
    p.put(p.sub+offset+4,p.weak_zone);assert p.run(site,p.sub,p.entities[0][0],native=True)==0;cases+=1
  p.put(p.app+0x6bc,0);assert not p.query(0x10067f0,4,2);cases+=1
 report=dict(native_cases_passed=cases,previous_wrong_owner_expected=expect_old,fixed_3x3_all_grades=fixed_ranges,native_registry_getter_executed=True,native_board_list_getter_executed=True,native_expired_filter_and_cell_getters_executed=True,real_embedded_food_rage_and_four_preview_queries=True,native_aid_fog_zone_containment=True,aid_fog_grades_1_through_4=True,status_application_and_visual_effects_tested=False,runtime_accepted=False)
 (folder/('skill-board-negative-checks.json' if expect_old else 'skill-board-checks.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--expect-old',action='store_true');p.add_argument('--fixed-ranges',action='store_true');a=p.parse_args();check(a.folder,a.expect_old,a.fixed_ranges)
