"""Run native message styles and effect dispatcher inside the actual view scope.

Font/paragraph rendering and the graphics backend are boundary fixtures. Native
message placement, style branches, effect flags and transform wrappers execute
from the patched engine. --old demonstrates A183's inherited world transform.
"""
from pathlib import Path
import argparse,json,struct
from unicorn.arm_const import *
from keystone import Ks,KS_ARCH_ARM,KS_MODE_ARM
from check_aster_view_matrix import World,signed
from check_aster_view_angle import BASE,MEM,STOP,bits

NORMAL=struct.pack('<3I',0x31564155,1,0xfffffffe)
IDENTITY=(1.,0.,0.,0.,1.,0.,0.,0.,1.)

class ScreenText(World):
    def __init__(self,folder,normal,width,scale):
        super().__init__(folder,NORMAL if normal else None)
        self.message=MEM+0x16000;self.paragraph=MEM+0x17000
        self.owner=MEM+0x18000;self.effect=MEM+0x18100
        self.stack=[];self.states=[];self.texts=[];self.effects=[];self.bands=[]
        self.placed=None;self.scaled=None;self.depths=[];self.after=[];self.ui_mode=False
        self.put(self.app+0x524,width);self.put(self.app+0x78,width)
        self.put(self.app+0x7c,round(600*scale))
        for o in (0x690,0x698):self.put(self.app+o,bits(scale))
        # Native renderer has two LawnApp GOT aliases and three clock slots.
        for literal,pc in ((0x46e354,0x46d8bc),(0x46e358,0x46d8dc)):
            slot=(self.get(BASE+literal)+BASE+pc)&0xffffffff
            self.put(self.get(slot),self.app)
        clock=MEM+0x19000;self.put(clock+0x24,bits(100))
        for literal,pc in ((0x46e35c,0x46da34),(0x46e36c,0x46dc98),(0x46e364,0x46dc04)):
            self.put((self.get(BASE+literal)+BASE+pc)&0xffffffff,clock)
        self.put(self.message+0x204,bits(105));self.put(self.message+0x208,bits(5))
        self.put(self.message+0x410,self.paragraph)
        self.put(self.paragraph,self.paragraph+0x100)
        self.put(self.paragraph+0x174,STOP+0x900)
        self.put(self.owner+0x28,self.effect);self.put(self.effect,self.effect+0x100)
        self.put(self.effect+0x150,STOP+0x904)
        self.u.mem_write(self.effect+0x68,b'\1')
        for o,v in ((0x6c,10),(0x70,20),(0x74,30),(0x78,40)):self.put(self.effect+o,v)
        source=f'''push {{r4,lr}}
ldr r0,message
ldr r1,graphics
ldr ip,messageDraw
blx ip
ldr r0,owner
ldr r1,graphics
ldr ip,effectDraw
blx ip
ldr ip,after
blx ip
pop {{r4,pc}}
message: .word {self.message}
graphics: .word {self.graphics}
messageDraw: .word {BASE+0x46e384}
owner: .word {self.owner}
effectDraw: .word {BASE+0x599044}
after: .word {STOP+0x908}'''
        self.u.mem_write(STOP+0xa00,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(source,STOP+0xa00)[0]))
        if 'asterViewScreenDraw' in self.symbols:
            data=MEM+0x1a000;node=MEM+0x1a100
            self.put(data+4,node);self.put(data+8,BASE)
            self.put(node,node+0x40);self.put(node+0x40,STOP+0x914)
            source=f'''push {{r4,lr}}
ldr r0,data
ldr r1,graphics
ldr ip,callback
blx ip
ldr ip,after
blx ip
pop {{r4,pc}}
data: .word {data}
graphics: .word {self.graphics}
callback: .word {BASE+self.symbols['asterViewUiEntry']}
after: .word {STOP+0x908}'''
            self.u.mem_write(STOP+0xc00,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(source,STOP+0xc00)[0]))

    def hook(self,u,address,size,unused):
        off=address-BASE
        r=[u.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if address==BASE+0x235048:
            self.world.append(self.matrix);u.reg_write(UC_ARM_REG_PC,STOP+(0xc00 if self.ui_mode else 0xa00));return
        if address==STOP+0x914:
            assert self.matrix is None
            u.reg_write(UC_ARM_REG_PC,STOP+0xa00);return
        if address==STOP+0x304:
            assert r[0]==self.backend and r[2] in (0,1)
            value=struct.unpack('<9f',u.mem_read(r[1],36))
            self.stack.append(self.matrix);self.matrix=value
            self.sequence.append(('push',r[2]));self.ret();return
        if address==STOP+0x308:
            assert r[0]==self.backend and self.stack
            self.matrix=self.stack.pop();self.sequence.append('pop');self.ret();return
        if off==0x46d77c:self.ret(MEM+0x19500);return # Font resource getter
        if off==0x13af490:self.ret(bits(40));return # font height
        if off in (0x112f794,0x112f7b0):
            alpha=self.get(u.reg_read(UC_ARM_REG_SP)) if off==0x112f7b0 else 255
            u.mem_write(r[0],struct.pack('<4I',*r[1:],alpha));self.ret(r[0]);return
        if off==0x13aa300:
            assert r[0]==self.paragraph
            self.placed=(signed(r[1]),signed(r[2]));self.ret();return
        if off==0x13aa3c4:
            self.scaled=tuple(struct.unpack('<f',struct.pack('<I',v))[0] for v in r[1:3]);self.ret();return
        if off==0x116d800:
            self.states.append(bytes(u.mem_read(r[0],0x74)));self.ret();return
        if off==0x116d764:
            u.mem_write(r[0],self.states.pop());self.ret();return
        if off in (0x1166c30,0x116b1e8):self.ret();return # color/clip backend
        if off==0x1167128:
            self.bands.append((self.matrix,struct.unpack('<4i',u.mem_read(r[1],16))));self.ret();return
        if address==STOP+0x900:
            assert r[:2]==[self.paragraph,self.graphics]
            assert self.get(self.graphics+8)==self.get(self.graphics+12)==0
            self.texts.append((self.matrix,self.placed,self.scaled));self.ret();return
        if address==STOP+0x904:
            assert r[:2]==[self.effect,self.graphics]
            self.effects.append(self.matrix);self.depths.append(len(self.stack));self.ret();return
        if address==STOP+0x908:
            self.after.append(self.matrix);self.ret();return
        return super().hook(u,address,size,unused)

    def draw(self,style,flags=0):
        self.put(self.message+0x20c,style);self.put(self.effect+0x10,flags)
        self.texts=[];self.effects=[];self.bands=[];self.depths=[];self.after=[]
        self.placed=self.scaled=None;self.sequence=[]
        graphics=bytes(self.u.mem_read(self.graphics,0xc0))
        self.run('asterViewDraw',self.board,self.graphics)
        assert self.matrix is None and not self.stack and not self.states
        assert graphics==bytes(self.u.mem_read(self.graphics,0xc0))

def check(folder,old=False):
    cases=0;styles=[]
    for width,scale in ((1420,1.58),(710,.79),(2112,2.56)):
        high=ScreenText(folder,False,width,scale);normal=ScreenText(folder,True,width,scale)
        for style in range(1,28):
            high.draw(style);normal.draw(style)
            assert len(high.texts)==len(normal.texts)==1,(style,normal.texts)
            hm,hp,hs=high.texts[0];nm,np,ns=normal.texts[0]
            assert hm is None and hp==np and hs==ns
            assert (nm is not None) if old else nm is None
            assert normal.after==[normal.world[-1]] and high.after==[None]
            assert normal.effects==[normal.world[-1]] and high.effects==[None]
            assert [v for _,v in normal.bands]==[v for _,v in high.bands]
            assert all((m is not None) if old else m is None for m,_ in normal.bands)
            # Native text bounds are symmetric about the physical screen center.
            # The old extra matrix changes that center to 40% of viewport width.
            center=width*.5 if nm is None else nm[0]*(width*.5)+nm[2]
            assert abs(center-width*(.4 if old else .5))<.001
            cases+=7
            if width==1420:styles.append(dict(style=style,position=np,scale=ns,banner=bool(normal.bands)))
        for flags in (0,0x80):
            for p in (high,normal):
                p.draw(16,flags)
                expected=IDENTITY if flags else p.world[-1]
                assert p.effects==[expected]
                assert p.depths==[(2 if old and p is normal else 1) if flags else (1 if p is normal else 0)]
                assert p.after==[p.world[-1]]
                cases+=3
        # Calls outside the world draw scope must retain native placement.
        for p in (high,normal):
            p.texts=[];p.sequence=[]
            p.run(0x46e384,p.message,p.graphics,native=True)
            assert len(p.texts)==1 and p.texts[0][0] is None and not p.sequence
            cases+=1
        # Native expiry/style guards remain authoritative and balance state.
        for style,duration in ((0,5),(16,0)):
            normal.put(normal.message+0x208,bits(duration));normal.draw(style)
            assert not normal.texts and normal.after==[normal.world[-1]];cases+=1
        normal.put(normal.message+0x208,bits(5))
        if not old:
            # Already inside a UI delegate: neither nested message nor screen
            # effect may pop the lawn a second time or restore it too early.
            normal.ui_mode=True
            for flags in (0,0x80):
                normal.draw(22,flags)
                assert normal.texts[0][0] is None
                assert normal.effects==[IDENTITY if flags else None]
                assert normal.after==[None,normal.world[-1]]
                assert normal.depths==[1 if flags else 0]
                cases+=4
    report=dict(native_cases_passed=cases,old_bug_demonstrated=old,styles=styles,runtime_accepted=False)
    (folder/'screen-text-checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='styles'}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--old',action='store_true')
    check(**vars(p.parse_args()))
