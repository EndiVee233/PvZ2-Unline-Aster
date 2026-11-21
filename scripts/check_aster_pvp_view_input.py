"""Exercise PVP zombie cursor -> native event bus -> native row conversion.

This isolates input/action coordinates, without resource layout or a real
window. Passing it does not establish that the reported device fault is fixed.
"""
import argparse,json,struct
from pathlib import Path
from keystone import Ks,KS_ARCH_ARM,KS_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_IP,UC_ARM_REG_PC,UC_ARM_REG_SP,UC_ARM_REG_LR
from check_aster_view_matrix import World,BASE,MEM,STOP,f32

class Pvp(World):
 def __init__(self,folder,normal,geometry):
  super().__init__(folder,struct.pack('<3I',0x31564155,int(normal),(~int(normal))&0xffffffff))
  self.u.mem_map(MEM+0x20000,0x10000)
  self.normal=normal;self.width,self.bx,self.by,self.scale=geometry;self.scale=f32(self.scale)
  self.put(self.app+0x524,self.width);self.put(self.board+0x2c,self.bx);self.put(self.board+0x30,self.by)
  for off in (0x690,0x698):self.put(self.app+off,struct.unpack('<I',struct.pack('<f',self.scale))[0])
  self.tablep=MEM+0x15000;self.packetobj=MEM+0x16000;self.pvpmodule=MEM+0x17000;self.dispatcher=MEM+0x18000;self.entry=MEM+0x18100
  self.bus=MEM+0x20000;self.node=MEM+0x20100;self.delegate=MEM+0x20200;self.sink=[];self.logs=0
  self.enabled=True;self.paused=False;self.event_points=[]
  self.u.mem_write(self.tablep,bytes(self.u.mem_read(BASE+0x180e928,0x50)));self.put(self.cursor,self.tablep)
  for off,v in ((0xc,0),(0x10,0),(0x14,1),(0x18,1)):self.put(self.cursor+off,v)
  self.put(self.pvpmodule+0x28,self.packetobj);self.put(self.packetobj,self.tablep+0x100);self.put(self.tablep+0x100+0xcc,STOP+0xc00)
  self.put(self.board+0xb4,9);self.put(self.board+0xc0,5)
  level=MEM+0x20300;self.u.mem_write(level,b'arena_test\0');self.put(self.board+0xc4,level)
  self.put(self.get(BASE+0x1821678),self.bus)
  self.put(self.bus+0xc,self.node);self.put(self.node+0x10,BASE+0x1f9020);self.put(self.node+0x14,self.delegate);self.put(self.node+0x18,self.delegate+24)
  self.put(self.delegate+12,self.pvpmodule);self.put(self.delegate+20,STOP+0xd00)
  self.put(self.dispatcher,self.entry);self.put(self.dispatcher+4,self.entry+0x48);self.put(self.entry+12,self.cursor);self.put(self.entry+20,STOP+0xe00)
  self.put(self.board+0x93c,self.dispatcher);self.ui_consumes=False
  for pos,fn in ((STOP+0xd00,0x109133c),(STOP+0xe00,0x1ef560)):
   asm=f'push {{r4,lr}}\nldr r0,[r0,#12]\nldr ip,target\nblx ip\npop {{r4,pc}}\ntarget: .word {BASE+fn}'
   self.u.mem_write(pos,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(asm,pos)[0]))
 def hook(self,u,a,s,d):
  off=a-BASE;r=[u.reg_read(v) for v in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
  if off==0x3476ac:return
  if off==0x975c28:self.ret();return # widget focus side effects, not world input
  if off==0x9776d4:self.ret(int(self.ui_consumes));return
  if off==0xf26fc8:self.ret(BASE+off);return
  if off==0x11d74b4:self.ret(self.bus);return
  if off==0x1da034:self.ret(self.get(r[1]));return
  if off==0x204a24:self.ret(int(self.paused));return
  if off in (0x108c3d4,0x33f688,0x216600,0x43af38):self.ret();return
  if a==STOP+0xc00:self.ret(int(self.enabled));return
  if a==STOP+0xc04:self.event_points.append((r[1],r[2]));self.ret();return
  if off==0x108c2b4:self.sink.append(struct.unpack('<2i',u.mem_read(r[2],8)));self.ret();return
  if off==0x1d9bb4:self.put(r[0],r[2]);self.put(r[0]+4,r[3]);self.ret();return
  if off==0x8aa930:self.put(r[0],self.get(r[1]));self.put(r[0]+4,1);self.ret();return
  if off==0x1efd38:self.ret();return # full lifecycle has a separate native check
  if off==0x147adc:self.logs+=1;self.ret();return
  return super().hook(u,a,s,d)
 def click_row(self,row,phase=3):
  self.put(self.cursor+0x24,0);self.put(self.cursor+0x1c,0);self.sink=[]
  # Forward the same native world matrix to generate an ideal UI point.
  # Real resource rendering and physical-window conversion are not modeled.
  x,y=840*self.scale,(160+(row+0.5)*76)*self.scale
  if self.normal:
   x=1.2*x+0.2*self.bx-0.2*self.width
   y=1.2*y-0.2*540*self.scale
  self.set_touch(round(x),round(y),0)
  before=bytes(self.u.mem_read(self.packet,44));self.run('asterViewTouch',self.board,self.dispatcher,self.packet)
  assert bytes(self.u.mem_read(self.packet,44))==before
  self.put(self.packet+40,phase);self.run('asterViewTouch',self.board,self.dispatcher,self.packet)
  return self.sink
 def fallback(self,row,fraction=0.5):
  self.put(self.dispatcher+4,self.entry);self.sink=[]
  x,y=840*self.scale,(160+(row+fraction)*76)*self.scale
  if self.normal:
   x=1.2*x+0.2*self.bx-0.2*self.width;y=1.2*y-0.2*540*self.scale
  return self.fallback_point(round(x),round(y))
 def fallback_point(self,x,y):
  self.put(self.dispatcher+4,self.entry);self.sink=[]
  self.set_touch(x,y,3);before=bytes(self.u.mem_read(self.packet,44))
  self.run(0x2217dc,self.board,self.packet,native=True)
  assert bytes(self.u.mem_read(self.packet,44))==before
  return self.sink

class Query(World):
 def __init__(self,folder,site):
  super().__init__(folder)
  self.site=site;self.logs=0;self.queries=0;self.out=MEM+0x17000;self.target_point=MEM+0x17200
  level=MEM+0x17300;self.u.mem_write(level,b'arena_test\0');self.put(self.board+0xc4,level)
  self.put(self.out,MEM+0x17100);self.put(self.out+4,MEM+0x17108)
  self.u.mem_write(self.target_point,struct.pack('<2f',838.5,350.25))
  record=next(r for r in self.report['hooks'] if r['site']==site)
  word=int.from_bytes(bytes.fromhex(record['before']),'little');d=word&0xffffff;d=d-0x1000000 if d&0x800000 else d
  self.original=site+8+4*d
 def hook(self,u,a,s,d):
  off=a-BASE
  if off==self.original:
   regs=[u.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
   assert regs==[self.out,2,self.target_point,0x42000000]
   self.queries+=1
   for r,v in ((UC_ARM_REG_R0,101),(UC_ARM_REG_R1,102),(UC_ARM_REG_R2,103),(UC_ARM_REG_R3,104),(UC_ARM_REG_IP,105)):u.reg_write(r,v)
   u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR));return
  if off==0x147adc:self.logs+=1;self.ret();return
  if off==self.site+4:
   self.returned=[u.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_IP)]
   assert u.reg_read(UC_ARM_REG_SP)==0x4080000
   u.reg_write(UC_ARM_REG_PC,STOP);u.emu_stop();return
  return super().hook(u,a,s,d)

def check(folder,expect_old=False):
 cases=0;logs=0
 for normal in (False,True):
  for geometry in ((2112,80,80,2.56),(2730,-200,60,3.2),(1800,40,-100,2.0)):
   p=Pvp(folder,normal,geometry)
   for row in range(5):
    assert p.click_row(row)==[(9,row)];cases+=1
    assert not p.click_row(row,phase=4);cases+=1
   p.enabled=False;assert not p.click_row(2);cases+=1
   p.enabled=True;p.paused=True;assert not p.click_row(2);cases+=1
   logs+=p.logs
   p=Pvp(folder,normal,geometry)
   if expect_old:
    assert p.fallback(2,fraction=0.25)==[(9,1 if normal else 2)];cases+=1
   else:
    for row in range(5):
     for fraction in (0.25,0.5,0.75):assert p.fallback(row,fraction)==[(9,row)];cases+=1
    p.ui_consumes=True;assert not p.fallback(2);cases+=1
    p.ui_consumes=False;p.enabled=False;assert not p.fallback(2);cases+=1
    p.enabled=True;p.paused=True;assert not p.fallback(2);cases+=1
 p=Pvp(folder,True,(2114,-80,0,2.56))
 assert p.fallback_point(1565,770)==[(9,1 if expect_old else 2)];cases+=1
 if not expect_old:
  # A stale Board release must not invert using a newly active Board.
  p=Pvp(folder,True,(2114,-80,0,2.56));other=MEM+0x21000
  p.put(p.app+0x6bc,other);p.put(other+0x938,MEM+0x22000)
  p.put(p.delegate+20,STOP+0xc04);p.fallback_point(1565,770)
  assert p.event_points==[(1565,770)];cases+=1
 for site in (0x10067f0,0x1007924,0x105a220):
  p=Query(folder,site);p.run(site,p.out,2,p.target_point,0x42000000,native=True)
  assert p.queries==1 and p.logs==1 and p.returned==[101,102,103,104,105];cases+=1
 report=dict(native_cases_passed=cases,native_board_dispatcher=True,native_cursor_input_and_release=True,native_zombie_action_event_bus_and_module=True,native_board_release_fallback_executed=True,native_cell_conversion=True,query_diagnostic_register_and_stack_preservation=True,diagnostic_log_calls=logs,real_window_or_resource_layout=False,previous_fallback_row_failure_expected=expect_old,recorded_device_point_tested=True,runtime_accepted=False)
 (folder/('pvp-view-input-negative-checks.json' if expect_old else 'pvp-view-input-checks.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--expect-old',action='store_true');a=p.parse_args();check(a.folder,a.expect_old)
