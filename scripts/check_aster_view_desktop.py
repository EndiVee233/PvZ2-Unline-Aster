"""Exercise keyboard selection followed by the real native phase-5 hover bridge."""
from pathlib import Path
import argparse,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from check_aster_view_matrix import World,IrisInverse,BASE,MEM,STOP,f32

class Desktop(World):
    def __init__(self,folder,normal,belt):
        record=struct.pack('<3I',0x31564155,int(normal),(~int(normal))&0xffffffff)
        super().__init__(folder,record)
        self.belt=belt;self.driver=MEM+0x16000;self.app_table=MEM+0x16100
        self.object_table=MEM+0x16300;self.bank=MEM+0x16500;self.children=MEM+0x16700
        self.cards=[MEM+0x17000+i*0x180 for i in range(8)]
        self.widgets={'UISeedBank':self.bank,'UIShovel':MEM+0x16800,'UIPlantfood':MEM+0x16a00,'UIChangeSpeedButton':MEM+0x16c00,'UIPauseButton':MEM+0x16e00}
        self.centers={p:(120,200+i*110) for i,p in enumerate(self.cards)}
        self.centers.update({p:(1500+i*90,1400) for i,p in enumerate(list(self.widgets.values())[1:])})
        self.clicks=[];self.selected=None;self.blocked=False;self.disabled=False;self.finished=False
        self.viewport=MEM+0x19200;self.put(self.app+0x2c0,self.viewport)
        for offset,value in ((0xb8,2112),(0xbc,1536),(0xc8,2112),(0xcc,1536)):
            self.put(self.viewport+offset,value)
        self.put(self.driver+0x44,self.app);self.put(self.app,self.app_table)
        for offset,fn in ((0x12c,STOP+0x900),(0x1c8,STOP+0x904),(0x1cc,STOP+0x908)):
            self.put(self.app_table+offset,fn)
        for p in [self.bank,*self.cards,*list(self.widgets.values())[1:]]:
            self.put(p,self.object_table)
        self.put(self.object_table+0x10,STOP+0x90c)
        self.put(self.bank+0x48,self.children);self.put(self.bank+0x4c,self.children+64)
        self.u.mem_write(self.bank+0x11d,b'\x08')
        for i,p in enumerate(self.cards):
            self.put(self.children+i*8,p);self.put(self.children+i*8+4,1)
            self.put(p+0x10c,2 if belt else 0)
        self.put(self.board+0xc0,5);self.put(self.board+0x93c,0)
        self.put(self.board+0x94c,0)
        self.put(self.cursor,BASE+0x179b940)
    def cstring(self,p):
        s=bytearray()
        while self.u.mem_read(p,1)!=b'\0':s.extend(self.u.mem_read(p,1));p+=1
        return s.decode()
    def hook(self,u,address,size,unused):
        r=[u.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        off=address-BASE
        if off==0x14ed0e0:self.put(r[0],r[1]);self.ret();return
        if off==0x14ebf58:self.ret();return
        if off==0x97714c:self.ret(self.widgets.get(self.cstring(self.get(r[0])),0));return
        if off==0x976720:self.ret(int(bool(r[0]) and not self.disabled));return
        if off==0x976478:
            x,y=self.centers[r[1]];self.put(r[0],x);self.put(r[0]+4,y);self.ret();return
        if off==0x9775d4:
            self.ret(next((p for p,xy in self.centers.items() if xy==tuple(r[:2])),0));return
        if off in (0x8ac6f4,0x29a23c,0x11d74b4):self.ret(BASE+off);return
        if off==0x20bb34:self.ret(self.bank if self.belt else 0);return
        if off==0x1da034:self.ret(self.get(r[1]));return
        if off==0x1d9bb4:self.put(r[0],r[2]);self.put(r[0]+4,r[3]);self.ret();return
        if address==STOP+0x900:self.ret(int(self.blocked));return
        if address==STOP+0x90c:
            self.ret(int((r[0]==self.bank and self.belt and r[1]==BASE+0x29a23c) or (r[0] in self.cards and r[1]==BASE+0x8ac6f4)));return
        if address in (STOP+0x904,STOP+0x908):
            x,y=struct.unpack('<2i',u.mem_read(r[1]+8,8))
            p=next((p for p,xy in self.centers.items() if xy==(x,y)),None)
            assert p is not None
            self.clicks.append((p,0 if address==STOP+0x904 else 3))
            if address==STOP+0x908:
                self.selected=p;self.put(self.board+0x94c,self.cursor)
                if p in self.cards:self.put(self.cursor+0x28,p);self.put(self.cursor+0x2c,1)
            self.ret();return
        if off==0x132b688:
            self.finished=True;u.emu_stop();return
        return super().hook(u,address,size,unused)
    def key(self,key,x=800,y=900):
        self.u.mem_write(self.packet,struct.pack('<11i',1,0,key,0,x,y,1,0,0,0,6))
        # desktopInput takes four args; unlike view helpers its base is explicit.
        self.run('desktopInput',BASE,self.driver,self.packet,6,native=True)
    def hover(self,x,y):
        self.set_touch(x,y,5);self.finished=False
        for r in range(UC_ARM_REG_R0,UC_ARM_REG_R12+1):self.u.reg_write(r,0)
        for r,v in ((UC_ARM_REG_R3,5),(UC_ARM_REG_R4,self.packet),(UC_ARM_REG_R5,self.driver),(UC_ARM_REG_SP,0x4080000),(UC_ARM_REG_LR,STOP)):
            self.u.reg_write(r,v)
        self.u.emu_start(BASE+0x132b660,STOP,count=200000)
        assert self.finished

def check(folder,iris):
    cases=0;oracle=IrisInverse(iris);scale=f32(2.56)
    for normal in (False,True):
        for belt in (False,True):
            p=Desktop(folder,normal,belt)
            def expected(x,y):
                local=(x-80,y-80)
                return oracle.point(*local,2112,scale) if normal else local
            for i,key in enumerate((8,9,10,11,45,51,33,46)):
                p.clicks=[];p.key(key)
                assert p.selected==p.cards[i] and p.clicks==[(p.cards[i],0),(p.cards[i],3)]
                assert p.cursor_inputs[-1]==expected(800,900);cases+=1
                # No button is held. Execute the existing Java/native phase-5
                # branch, including its direct cursor setter after the command.
                for x,y in ((900,1000),(1200,750)):
                    p.hover(x,y);assert p.cursor_inputs[-1]==expected(x,y)
                    assert p.selected==p.cards[i] and len(p.clicks)==2;cases+=1
            p.key(9);p.key(52);assert p.selected==p.cards[2];cases+=1
            p.key(54);assert p.selected==p.cards[1];cases+=1
            for key,name in ((32,'UIShovel'),(34,'UIPlantfood')):
                p.key(key);assert p.selected==p.widgets[name];cases+=1
                p.hover(1000,1200);assert p.cursor_inputs[-1]==expected(1000,1200);cases+=1
            # Inverse is shared with actual mouse touch dispatch: clicks and
            # preview must refer to the same lawn location exactly once.
            p.set_touch(920,840,0);p.run('asterViewTouch',p.board,MEM+0x10000,p.packet)
            assert p.cursor_inputs[-1]==(oracle.point(920,840,2112,scale) if normal else (920,840));cases+=1
            # Execute the actual driver conversion with a resized client area
            # and a physical pixel origin, before Board and view conversion.
            for offset,value in ((0xc0,7),(0xc4,11),(0xc8,1056),(0xcc,768)):
                p.put(p.viewport+offset,value)
            p.key(8,500,400);assert p.cursor_inputs[-1]==expected(986,778);cases+=1
            p.hover(600,500);assert p.cursor_inputs[-1]==expected(1186,978);cases+=1
            before=len(p.cursor_inputs);p.u.mem_write(p.cursor+0x1d,b'\x01');p.hover(1000,1200)
            assert len(p.cursor_inputs)==before;p.u.mem_write(p.cursor+0x1d,b'\0');cases+=1
            p.put(p.board+0x94c,0);p.hover(1000,1200);assert len(p.cursor_inputs)==before;cases+=1
            p.blocked=True;p.clicks=[];p.key(8);assert p.clicks==[];p.blocked=False;cases+=1
            p.disabled=True;p.key(8);assert p.clicks==[];p.disabled=False;cases+=1
            p.u.mem_write(p.board+0x8d5,b'\x01');p.key(8);assert p.clicks==[];cases+=1
    report=dict(arm_cases_passed=cases,normal_and_high=True,ordinary_and_conveyor_banks=True,native_phase5_bridge_executed=True,native_window_coordinate_conversion_executed=True,held_mouse_button=False,keyboard_ui_routing_and_preview=True,shovel_and_plantfood_preview=True,runtime_accepted=False)
    (folder/'view-desktop-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('folder',type=Path);a.add_argument('iris',type=Path);v=a.parse_args();check(v.folder,v.iris)
