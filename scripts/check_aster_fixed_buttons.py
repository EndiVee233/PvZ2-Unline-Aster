"""Execute fixed UI button native hit/capture handlers in Board's dispatcher."""
from pathlib import Path
import argparse,json,struct
from keystone import Ks,KS_ARCH_ARM,KS_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2
from check_aster_view_matrix import World,BASE,MEM,STOP,f32

BUTTONS=[('NextWaveButton',0x8f4870,0x17c1d20),('StartGameButton',0x926b94,0x17c3400),
 ('ArenaPVPStartButton',0x109c20c,0x180e4a0),('ArenaOccupyStartButton',0x109fe80,0x180e738),
 ('ArenaOccupyQuitButton',0x10a1208,0x180e830),('ArenaChangeSpeedButton',0x10a21ec,0x180e978),
 ('ArenaEndingButton',0x10a3474,0x180ea70)]

class Button(World):
    def __init__(self,folder,normal,definition=BUTTONS[0],geometry=(2112,80,80,2.56)):
        super().__init__(folder,struct.pack('<3I',0x31564155,int(normal),(~int(normal))&0xffffffff))
        self.name,self.callback,table=definition;self.width,self.bx,self.by,scale=geometry
        self.put(self.app+0x524,self.width);self.put(self.board+0x2c,self.bx);self.put(self.board+0x30,self.by)
        for off in (0x690,0x698):self.put(self.app+off,struct.unpack('<I',struct.pack('<f',f32(scale)))[0])
        self.widget=MEM+0x16000;self.widget_table=MEM+0x16800;self.sheet=MEM+0x17000
        self.out=MEM+0x17300;self.dispatcher=MEM+0x18000;self.entries=MEM+0x18100
        self.animation=MEM+0x1c500;self.capture=0xf4 if self.name=='ArenaChangeSpeedButton' else 0xf8
        self.enabled=True;self.messages=[];self.states=[];self.world_events=[];self.hit_points=[]
        self.u.mem_write(self.widget_table,bytes(self.u.mem_read(BASE+table,0xb0)))
        assert self.get(self.widget_table+0x40)==BASE+0x974f70
        assert self.get(self.widget_table+0x54)==BASE+0x97680c
        assert self.get(self.widget_table+0x5c)==BASE+0x9764c8
        self.put(self.widget_table+0x6c,STOP+0xd04);self.put(self.widget,self.widget_table)
        self.put(self.widget+0x20,self.sheet);self.put(self.widget+0x24,1)
        for off,value in ((0x28,self.width-200),(0x2c,240),(0x30,160),(0x34,140),(0x54,4)):
            self.put(self.widget+off,value)
        if self.capture!=0xf4:self.put(self.widget+0xf4,self.animation)
        self.put(self.dispatcher,self.entries);self.put(self.dispatcher+4,self.entries+0x90)
        self.put(self.entries+12,self.widget);self.put(self.entries+0x14,STOP+0xe00);self.put(self.entries+0x40,8)
        self.put(self.entries+0x48+0x14,STOP+0xd08);self.put(self.entries+0x48+0x40,1)
        code=f'''push {{r4,lr}}
ldr r0,[r0,#12]
ldr ip,callback
blx ip
pop {{r4,pc}}
callback: .word {BASE+self.callback}'''
        self.u.mem_write(STOP+0xe00,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(code,STOP+0xe00)[0]))
    def hook(self,u,address,size,unused):
        off=address-BASE;r0=u.reg_read(UC_ARM_REG_R0);r1=u.reg_read(UC_ARM_REG_R1)
        if off==0x3476ac:return
        if off==0x9762c4:self.ret();return # fixture layout is already resolved
        if off==0x976720:self.ret(int(self.enabled));return
        if off==0x11d74b4:self.ret(self.sheet);return
        if off==0x1da034:self.ret(self.get(r1));return
        if off==0x21df78:self.messages.append(r1);self.ret();return # notification sink
        if off==0x97680c:self.hit_points.append((r1,u.reg_read(UC_ARM_REG_R2)))
        if address==STOP+0xd04:self.states.append(r1);self.ret();return # visual state sink
        if address==STOP+0xd08:
            self.world_events.append(struct.unpack('<11i',u.mem_read(r1,44)));self.ret();return
        return super().hook(u,address,size,unused)
    def rectangle(self):
        self.run(0x9764c8,self.out,self.widget,native=True)
        return struct.unpack('<4i',self.u.mem_read(self.out,16))
    def center(self):
        x,y,w,h=self.rectangle();return x+w//2,y+h//2
    def reset(self):
        self.messages=[];self.states=[];self.world_events=[];self.hit_points=[]
        self.put(self.widget+self.capture,0);self.enabled=True;self.put(self.widget+0x54,4)
    def event(self,point,phase,tid=1,direct=False):
        self.set_touch(point[0]-self.bx,point[1]-self.by,phase);self.put(self.packet,tid)
        before=bytes(self.u.mem_read(self.packet,44))
        result=self.run(self.callback,self.widget,self.packet,native=True) if direct else self.run('asterViewTouch',self.board,self.dispatcher,self.packet)
        assert bytes(self.u.mem_read(self.packet,44))==before
        return result

def check(folder,expect_old=False):
    cases=0;examples=[]
    for normal in (False,True):
      for geometry in ((2112,80,80,2.56),(2730,-200,60,3.2),(1800,40,-100,2.0)):
        p=Button(folder,normal,geometry=geometry);center=p.center()
        p.event(center,0);p.event(center,3)
        expected=not (normal and expect_old)
        assert len(p.messages)==int(expected),(normal,geometry,p.rectangle(),center,p.hit_points,p.messages)
        assert p.get(p.widget+p.capture)==0
        examples.append(dict(normal=normal,geometry=geometry,next_wave_requests=len(p.messages)));cases+=1
        if not expected:continue
        assert p.states==[4,2]
        assert len(p.world_events)==1 and p.world_events[0][10]==4;cases+=1
        # UI restoration is local: subsequent world listeners keep the exact
        # inverse coordinates, including native consumed-release phase 4.
        p.set_point(center[0]-p.bx,center[1]-p.by);p.run('asterViewPoint',p.board,p.point)
        assert p.world_events[-1][2:4]==p.point_value();cases+=1
        outside=(center[0]-500,center[1]+500)
        p.reset();p.event(center,0);p.event(outside,1);p.event(outside,3)
        assert not p.messages and p.get(p.widget+p.capture)==0;cases+=1
        p.reset();p.event(center,0);p.event(center,4)
        assert not p.messages and p.get(p.widget+p.capture)==0;cases+=1
        p.reset();p.event(center,0);p.event(center,3,tid=2)
        assert not p.messages and p.get(p.widget+p.capture)==1
        p.event(center,4);assert p.get(p.widget+p.capture)==0;cases+=1
        for condition in ('disabled','not-interactive','disabled-on-release'):
            p.reset()
            if condition=='disabled-on-release':p.event(center,0);p.enabled=False
            else:
                if condition=='disabled':p.enabled=False
                else:p.put(p.widget+0x54,0)
                p.event(center,0)
            p.event(center,3)
            assert not p.messages and p.get(p.widget+p.capture)==0;cases+=1
        p.reset();p.event(center,0,direct=True);p.event(center,3,direct=True)
        assert len(p.messages)==1;cases+=1
    if not expect_old:
      # Audit companions: execute each confirmed fixed UI handler's actual
      # hit/capture/cancel path without starting or ending PVP gameplay.
      for definition in BUTTONS[1:]:
        for normal in (False,True):
            p=Button(folder,normal,definition);center=p.center()
            p.event(center,0);assert p.get(p.widget+p.capture)==1 and p.states==[4];cases+=1
            assert p.hit_points[-1]==center
            p.event(center,4);assert p.get(p.widget+p.capture)==0 and p.states==[4,2];cases+=1
            p.reset();p.event(center,2);assert p.hit_points[-1]==center and not p.messages;cases+=1
    report=dict(native_cases_passed=cases,expect_previous_failure=expect_old,native_button_hit_and_capture_and_release_executed=True,native_widget_hit_and_rectangle_executed=True,actual_board_dispatcher_executed=True,companion_ui_handlers_checked=[] if expect_old else [b[0] for b in BUTTONS[1:]],examples=examples,runtime_accepted=False)
    (folder/('fixed-buttons-negative-checks.json' if expect_old else 'fixed-buttons-checks.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('folder',type=Path);a.add_argument('--expect-old',action='store_true');v=a.parse_args();check(v.folder,v.expect_old)
