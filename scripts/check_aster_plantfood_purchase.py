"""Run native plant-food +/offer geometry and capture/release state machine."""
from pathlib import Path
import argparse,json,struct
from keystone import Ks,KS_ARCH_ARM,KS_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_R0
from check_aster_view_matrix import World,BASE,MEM,STOP

class Purchase(World):
    def __init__(self,folder,normal,capacity=3):
        super().__init__(folder,struct.pack('<3I',0x31564155,int(normal),(~int(normal))&0xffffffff))
        self.widget=MEM+0x16000;self.out=MEM+0x16300;self.dispatcher=MEM+0x18000;self.entry=MEM+0x18100
        self.capacity=capacity;self.confirmations=0;self.enabled=True
        for off,v in ((0x28,530),(0x2c,1400),(0x30,180),(0x34,160),(0x54,4)):
            self.put(self.widget+off,v)
        self.u.mem_write(self.widget+0xf9,b'\x01')
        self.put(self.board+0x94c,0)
        self.put(self.dispatcher,self.entry);self.put(self.dispatcher+4,self.entry+0x48)
        self.put(self.entry+12,self.widget);self.put(self.entry+0x14,STOP+0xe00)
        code=f'''push {{r4,lr}}
ldr r0,[r0,#12]
ldr ip,callback
blx ip
pop {{r4,pc}}
callback: .word {BASE+0x4f2530}'''
        self.u.mem_write(STOP+0xe00,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(code,STOP+0xe00)[0]))
        # Resource sizes are fixture data. Both native draw/hit rectangle
        # getters consume these same image dimensions and application scale.
        base=(self.get(BASE+0x4f1c14)+BASE)&0xffffffff
        refs=[(base+a)&0xffffffff for a in (0x4f1b24,0x4f1b3c,0x4f1b54,0x4f1b6c,0x4f1b84)]
        buy=(self.get(BASE+0x4f1c1c)+BASE+0x4f1c18)&0xffffffff
        offer=(self.get(BASE+0x4f1cc0)+BASE+0x4f1cd8)&0xffffffff
        self.images={}
        for i,(ref,w,h) in enumerate([(r,w,160) for r,w in zip(refs,(144,144,80,80,80))]+[(buy,100,100),(offer,160,200)]):
            p=MEM+0x1b000+i*0x100;self.put(p+0x28,w);self.put(p+0x2c,h);self.images[ref]=p
        audio=(self.get(BASE+0x4f2808)+BASE+0x4f2764)&0xffffffff
        self.put(audio,MEM+0x1a000)
    def hook(self,u,address,size,unused):
        off=address-BASE;r0=u.reg_read(UC_ARM_REG_R0)
        if off==0x3476ac:return # actual sort/capture/phase propagation
        if off in (0x9762c4,0x1ecd30,0x21df78):self.ret();return
        if off==0x976720:self.ret(int(self.enabled));return
        if off==0x402110:self.ret(self.capacity);return
        if off==0x1ddff0:
            assert r0 in self.images,('unknown native image reference',hex(r0),[hex(k) for k in self.images])
            self.ret(self.images[r0]);return
        if off==0x4f229c:self.confirmations+=1;self.ret();return # purchasing side effects are out of scope
        return super().hook(u,address,size,unused)
    def rectangle(self,offer=False):
        self.run(0x4f1c20 if offer else 0x4f1ad0,self.out,self.widget,native=True)
        return struct.unpack('<4i',self.u.mem_read(self.out,16))
    def center(self,offer=False):
        x,y,w,h=self.rectangle(offer);return x+w//2,y+h//2
    def event(self,point,phase,direct=False):
        self.set_touch(point[0]-80,point[1]-80,phase)
        before=bytes(self.u.mem_read(self.packet,44))
        result=self.run(0x4f2530,self.widget,self.packet,native=True) if direct else self.run('asterViewTouch',self.board,self.dispatcher,self.packet)
        assert bytes(self.u.mem_read(self.packet,44))==before
        return result
    def click(self,point,direct=False):return self.event(point,0,direct),self.event(point,3,direct)
    def shown(self):return self.u.mem_read(self.widget+0x105,1)[0]

def check(folder,expect_old=False):
    cases=0;examples=[]
    for normal in (False,True):
        p=Purchase(folder,normal)
        leaf=(620,1480);plus=p.center()
        p.click(leaf)
        assert bool(p.shown())==bool(expect_old and normal),('leaf unexpectedly opens purchase',normal,p.shown())
        examples.append(dict(normal=normal,leaf=leaf,plus=plus,leaf_opens_offer=bool(p.shown())))
        cases+=1
        p=Purchase(folder,normal);p.click(p.center())
        assert bool(p.shown())==(not (expect_old and normal)),('plus did not open purchase',normal,p.shown())
        cases+=1
        if expect_old and normal:continue
        p.click(p.center(offer=True));assert p.confirmations==1 and not p.shown();cases+=1
        # Raw UI callers outside the Board scope must not be transformed,
        # even following a completed scoped callback in normal view.
        p.click(p.center(),direct=True);assert p.shown();cases+=1
        for condition in ('disabled','locked','full','not-interactive'):
            q=Purchase(folder,normal)
            if condition=='disabled':q.enabled=False
            if condition=='locked':q.u.mem_write(q.widget+0xf9,b'\0')
            if condition=='full':q.put(q.widget+0xf4,q.capacity)
            if condition=='not-interactive':q.put(q.widget+0x54,0)
            q.click(q.center());assert not q.shown() and q.get(q.widget+0x108)==0;cases+=1
        q=Purchase(folder,normal);q.event(q.center(),0);q.event(q.center(),4)
        assert not q.shown() and q.get(q.widget+0x108)==0;cases+=1
        for capacity in (2,4,5):
            q=Purchase(folder,normal,capacity);q.click(q.center());assert q.shown();cases+=1
    report=dict(native_cases_passed=cases,expect_previous_failure=expect_old,native_purchase_handler_and_rectangles_executed=True,actual_board_dispatcher_executed=True,native_image_dimension_getters_executed=True,examples=examples,runtime_accepted=False)
    (folder/('plantfood-purchase-negative-checks.json' if expect_old else 'plantfood-purchase-checks.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('folder',type=Path);a.add_argument('--expect-old',action='store_true');v=a.parse_args();check(v.folder,v.expect_old)
