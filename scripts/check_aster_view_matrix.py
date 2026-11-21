"""Compare with Iris's inverse zoom and exercise native world/UI matrix ABI."""
from pathlib import Path
import argparse,json,math,os,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from keystone import Ks,KS_ARCH_ARM,KS_MODE_ARM
from check_aster_view_angle import Probe,BASE,MEM,STOP,bits
from native_emulation_support import machine

def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
def signed(v):return v-0x100000000 if v&0x80000000 else v

class World(Probe):
    def __init__(self,folder,record=None,fail=None):
        super().__init__(folder,record,fail)
        self.matrix=None;self.sequence=[];self.world=[];self.touches=[];self.cursor_inputs=[]
        self.cursor=MEM+0x11000;self.packet=MEM+0x12000;self.point=MEM+0x12100
        self.device=MEM+0x13000;self.backend=MEM+0x13100;self.table=MEM+0x13200
        self.put(self.app+0x6bc,self.board);self.put(self.board+0x94c,self.cursor)
        self.put(self.get(BASE+0x18216bc),self.app) # cursor's native LawnApp singleton GOT
        self.put(self.app+0x524,2112)
        for offset in (0x690,0x698):self.put(self.app+offset,bits(2.56))
        for offset in (0x2c,0x30):self.put(self.board+offset,80)
        self.put(self.board+0x34,3395);self.put(self.board+0x994,-557)
        for offset in (8,12):self.put(self.graphics+offset,bits(80))
        for offset in (0x10,0x14):self.put(self.graphics+offset,bits(1))
        self.put(self.graphics+0x74,self.device);self.put(self.device+4,self.backend);self.put(self.backend,self.table)
        for slot,address in ((0x18,STOP+0x300),(0xb0,STOP+0x304),(0xb4,STOP+0x308)):self.put(self.table+slot,address)
        source=f'''push {{r4,lr}}
add r1,r1,#8
ldr r0,cursor
ldr ip,setter
blx ip
mov r0,#1
pop {{r4,pc}}
cursor: .word {self.cursor}
setter: .word {BASE+0x1efccc}'''
        self.u.mem_write(STOP+0x400,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(source,STOP+0x400)[0]))
    def ret(self,result=0):
        self.u.reg_write(UC_ARM_REG_R0,result&0xffffffff)
        self.u.reg_write(UC_ARM_REG_PC,self.u.reg_read(UC_ARM_REG_LR))
    def hook(self,u,address,size,unused):
        off=address-BASE
        r=[u.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if address==STOP+0x300:
            assert r[:2]==[self.backend,self.device+8];self.ret();return
        if off==0x147adc:self.ret();return
        if address==STOP+0x304:
            assert r[0]==self.backend and r[2]==1 and self.matrix is None
            self.matrix=struct.unpack('<9f',u.mem_read(r[1],36));self.sequence.append('push');self.ret();return
        if address==STOP+0x308:
            assert r[0]==self.backend and self.matrix is not None
            self.sequence.append('pop');self.matrix=None;self.ret();return
        if off==self.report['old_hooks'][str(0x23aa00)]:return # execute actual camera clamp
        if off==0x235048:
            assert r[:2]==[self.board,self.graphics]
            self.sequence.append('world');self.world.append(self.matrix);self.ret();return
        if off==0x3476ac:
            self.touches.append(tuple(struct.unpack('<11i',u.mem_read(r[1],44))))
            u.reg_write(UC_ARM_REG_PC,STOP+0x400);return
        if off==0x1efcd0:
            self.cursor_inputs.append(struct.unpack('<2i',u.mem_read(r[1],8)))
            return # execute original cursor scale conversion, including its saved prologue
        return super().hook(u,address,size,unused)
    def set_point(self,x,y):self.u.mem_write(self.point,struct.pack('<2i',x,y))
    def point_value(self):return struct.unpack('<2i',self.u.mem_read(self.point,8))
    def set_touch(self,x,y,phase):self.u.mem_write(self.packet,struct.pack('<11i',1,0,x,y,x,y,1,0,0,0,phase))

class IrisInverse:
    def __init__(self,path):
        os.environ['PVZ2_NATIVE_ORIGINAL']=str(path);self.u,_=machine()
        self.u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);self.u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.u.hook_add(UC_HOOK_CODE,self.hook)
    def hook(self,u,a,size,_):
        if a==STOP:u.emu_stop()
        elif a==BASE+0xe8700:
            value=struct.unpack('<f',struct.pack('<I',u.reg_read(UC_ARM_REG_R0)))[0]
            u.reg_write(UC_ARM_REG_R0,bits(math.floor(value)));u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
    def point(self,x,y,width,scale,bx=80,by=80):
        board=MEM+0x5000;point=MEM+0x12100
        for o,v in ((0x28,bx),(0x2c,by),(0x678,bits(1.2)),(0x67c,bits(width)),(0x680,bits(f32(by+f32(540*scale))))):self.u.mem_write(board+o,struct.pack('<I',v&0xffffffff))
        self.u.mem_write(point,struct.pack('<2i',x,y))
        for r,v in ((UC_ARM_REG_R0,board),(UC_ARM_REG_R1,point),(UC_ARM_REG_SP,0x4080000),(UC_ARM_REG_LR,STOP)):self.u.reg_write(r,v)
        self.u.emu_start(BASE+0x1841fc,STOP,count=2000)
        assert self.u.reg_read(UC_ARM_REG_PC)==STOP
        return struct.unpack('<2i',self.u.mem_read(point,8))

class UiWorld(World):
    def __init__(self,folder,record):
        super().__init__(folder,record)
        self.records=MEM+0x14000;self.count=MEM+0x15000;self.moved=MEM+0x15100
        self.nodes=[MEM+0x15200,MEM+0x15300];self.ui_draws=[];self.tagged=None
        self.graphics_states=[]
        self.originals=[]
        for i,(kind,node) in enumerate(((0,0),(12,MEM+0x15400),(12,self.nodes[0]),(12,self.nodes[1]))):
            row=[kind,100-i,0x22,0x33,0x44,0x55,0x66,0,node]
            data=struct.pack('<9I',*row);self.originals.append(data)
            self.u.mem_write(self.records+36*i,data)
        for i,node in enumerate(self.nodes):
            self.put(node,node+0x40);self.put(node+0x40,STOP+0x610+i*4)
        self.put(self.count,2)
        collector=next(h['target'] for h in self.report['hooks'] if h['site']==0x235194)
        source=f'''push {{r4-r8,lr}}
ldr r0,records
ldr r1,count
ldr ip,collector
blx ip
ldr ip,validate
blx ip
ldr r0,records
add r1,r0,#144
ldr r2,compare
ldr ip,sort
blx ip
ldr ip,sorted
blx ip
ldr r4,moved
ldr r1,graphics
ldr r0,[r4]
cmp r0,#15
addeq r0,r4,#8
ldreq ip,[r4,#28]
ldrne r0,[r4,#32]
ldrne ip,[r0]
ldrne ip,[ip]
blx ip
ldr ip,finish
blx ip
pop {{r4-r8,pc}}
records: .word {self.records}
count: .word {self.count}
collector: .word {BASE+collector}
validate: .word {STOP+0x600}
moved: .word {self.moved}
graphics: .word {self.graphics}
finish: .word {STOP+0x604}'''
        source+=f'''
compare: .word {STOP+0x800}
sort: .word {BASE+0x22ea34}
sorted: .word {STOP+0x608}'''
        self.u.mem_write(STOP+0x500,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(source,STOP+0x500)[0]))
        compare='ldr r0,[r0,#4]\nldr r1,[r1,#4]\ncmp r0,r1\nmovlt r0,#1\nmovge r0,#0\nbx lr'
        self.u.mem_write(STOP+0x800,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(compare,STOP+0x800)[0]))
        nested=f'''push {{r4,lr}}
ldr r0,data
ldr r1,graphics
ldr ip,callback
blx ip
pop {{r4,pc}}
data: .word {self.records+2*36+8}
graphics: .word {self.graphics}
callback: .word {BASE+self.symbols['asterViewUiEntry']}'''
        self.u.mem_write(STOP+0x700,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(nested,STOP+0x700)[0]))
    def hook(self,u,address,size,unused):
        r0=u.reg_read(UC_ARM_REG_R0);r1=u.reg_read(UC_ARM_REG_R1)
        if address==BASE+0x235048:
            self.world.append(self.matrix);self.sequence.append('world')
            u.reg_write(UC_ARM_REG_PC,STOP+0x500);return
        if address==BASE+0x9779a0:
            assert (r0,r1)==(self.records,self.count)
            self.put(self.count,4);self.ret();return
        if address==BASE+0x116d800:
            assert r0==self.graphics
            self.graphics_states.append(bytes(u.mem_read(r0,0x74)));self.ret();return
        if address==BASE+0x116d764:
            assert r0==self.graphics and self.graphics_states
            u.mem_write(r0,self.graphics_states.pop());self.ret();return
        if address==STOP+0x600:
            assert bytes(u.mem_read(self.records,72))==b''.join(self.originals[:2])
            self.tagged=self.get(self.records+72)==15
            for i in (2,3):
                row=self.records+i*36
                assert self.get(row+4)==100-i and self.get(row+32)==self.nodes[i-2]
                if self.tagged:
                    assert self.get(row+8)==0x22 # native delegate vptr is not payload
                    assert self.get(row+12)==self.nodes[i-2] and self.get(row+16)==BASE
                    assert self.get(row+28)==BASE+self.symbols['asterViewUiEntry']
                else:assert bytes(u.mem_read(row,36))==self.originals[i]
            self.ret();return
        if address==STOP+0x608:
            assert [self.get(self.records+i*36+4) for i in range(4)]==[97,98,99,100]
            # The real C++ sort skips record word 2 (the embedded object's
            # vptr). A memcpy-only sort model missed A175's erased payload.
            assert self.get(self.records+32)==self.nodes[1]
            u.mem_write(self.moved,bytes(u.mem_read(self.records,36)))
            nested_data=self.records+36+8
            assert self.get(nested_data+4)==self.nodes[0] if self.tagged else True
            # Nested callback uses node 1 after its native sort move.
            nested=f'''push {{r4,lr}}
ldr r0,data
ldr r1,graphics
ldr ip,callback
blx ip
pop {{r4,pc}}
data: .word {nested_data}
graphics: .word {self.graphics}
callback: .word {BASE+self.symbols['asterViewUiEntry']}'''
            u.mem_write(STOP+0x700,bytes(Ks(KS_ARCH_ARM,KS_MODE_ARM).asm(nested,STOP+0x700)[0]))
            self.ret();return
        if address in (STOP+0x610,STOP+0x614):
            assert r0 in self.nodes and r1==self.graphics and self.matrix is None
            self.ui_draws.append(r0)
            if self.tagged:self.put(self.graphics+8,bits(999))
            if address==STOP+0x614 and self.tagged:u.reg_write(UC_ARM_REG_PC,STOP+0x700)
            else:self.ret()
            return
        if address==STOP+0x604:
            assert self.matrix==self.world[-1]
            assert not self.graphics_states and self.floating(self.graphics+8)==80
            self.sequence.append('world-resumed');self.ret();return
        return super().hook(u,address,size,unused)

def check(folder,iris):
    cases=0
    p=World(folder);p.run('asterViewSettingsReady',p.ui);assert p.rows==[(1005,'视角',None)];cases+=1
    p.open();assert p.rows_now()==[(1041,'高',1),(1042,'正常',0)];cases+=1
    p.run('asterViewDraw',p.board,p.graphics)
    assert p.sequence==['world'] and p.world==[None];cases+=1
    p.run('asterViewClick',p.ui,1042);record=p.record
    p=World(folder,record);p.open();assert p.rows_now()[1][2]==1;cases+=1
    app=bytes(p.u.mem_read(p.app,0x800));board=bytes(p.u.mem_read(p.board,0xa00));graphics=bytes(p.u.mem_read(p.graphics,0xc0))
    p.run('asterViewDraw',p.board,p.graphics)
    assert p.sequence==['push','world','pop'] and p.matrix is None;cases+=1
    matrix=p.world[-1]
    assert abs(matrix[0]-1.2)<1e-6 and matrix[0]==matrix[4] and matrix[8]==1
    assert matrix[1]==matrix[3]==matrix[6]==matrix[7]==0;cases+=1
    assert app==bytes(p.u.mem_read(p.app,0x800)) and board==bytes(p.u.mem_read(p.board,0xa00)) and graphics==bytes(p.u.mem_read(p.graphics,0xc0));cases+=1
    for _ in range(5):p.run('asterViewDraw',p.board,p.graphics);assert p.world[-1]==matrix and p.matrix is None;cases+=1
    oracle=IrisInverse(iris);scale=f32(2.56)
    # Actual native Iris inverse, including negative/fractional anchors and
    # the rounding at every cell. This catches a misaligned visual-only zoom.
    for width,bx,by in ((2112,80,80),(2730,-200,60),(1800,40,-100)):
        p.put(p.app+0x524,width);p.put(p.board+0x2c,bx);p.put(p.board+0x30,by)
        for x,y in [(-111,-117),(0,0),(25,63),(10000,10000)]+[(int((200+c*64+32)*scale),int((160+r*76+38)*scale)) for r in range(5) for c in range(9)]:
            p.set_point(x,y);p.run('asterViewPoint',p.board,p.point)
            expected=oracle.point(x,y,width,scale,bx,by)
            assert p.point_value()==expected,(x,y,p.point_value(),expected);cases+=1
    p.put(p.app+0x524,2112);p.put(p.board+0x2c,80);p.put(p.board+0x30,80)
    for phase in (0,1,3,4):
        x,y=700,800;expected=oracle.point(x,y,2112,scale)
        p.set_touch(x,y,phase);before=bytes(p.u.mem_read(p.packet,44))
        assert p.run('asterViewTouch',p.board,MEM+0x10000,p.packet)==1
        assert p.touches[-1][2:4]==expected and p.cursor_inputs[-1]==expected
        assert bytes(p.u.mem_read(p.packet,44))==before;cases+=1
    # The direct desktop cursor setter must invert once outside the dispatcher.
    p.set_point(700,800);p.run('asterViewDesktopCursor',p.board,p.cursor,p.point)
    assert p.cursor_inputs[-1]==oracle.point(700,800,2112,scale) and p.point_value()==(700,800);cases+=1
    # Execute the installed ARM stubs with each real caller's register/stack
    # convention, including the moved-touch tail's already-saved frame.
    for site in (0x22a344,0x221858,0x1fbf74):
        stub=next(h['target'] for h in p.report['hooks'] if h['site']==site)
        p.set_touch(700,800,1);state={'configured':False}
        def configure(u,a,size,_):
            if a!=BASE+stub or state['configured']:return
            state['configured']=True
            if site==0x1fbf74:
                u.reg_write(UC_ARM_REG_R4,p.board);u.reg_write(UC_ARM_REG_R5,p.packet)
                u.mem_write(u.reg_read(UC_ARM_REG_SP),struct.pack('<4I',0x44,0x55,0x66,STOP))
            else:
                u.reg_write(UC_ARM_REG_R4,0x44);u.reg_write(UC_ARM_REG_R5,p.board)
        handle=p.u.hook_add(UC_HOOK_CODE,configure)
        try:assert p.run(stub,MEM+0x10000,p.packet,native=True)==1
        finally:p.u.hook_del(handle)
        assert state['configured'] and p.cursor_inputs[-1]==oracle.point(700,800,2112,scale)
        assert p.u.reg_read(UC_ARM_REG_R4)==0x44;cases+=1
    # Resource and HUD scales remain the original values after all operations.
    assert p.floating(p.app+0x690)==scale and p.floating(p.app+0x698)==scale;cases+=1
    for bad in (b'',b'bad',struct.pack('<3I',0,1,0xfffffffe),record+b'x'):
        q=World(folder,bad);q.open();assert q.rows_now()[0][2]==1;cases+=1
    for fail in ('open','write','fsync','close','rename'):
        q=World(folder,None,fail);q.open();q.run('asterViewClick',q.ui,1042);assert q.rows_now()[0][2]==1 and q.record is None;cases+=1
    p.run('asterViewClick',p.ui,1041);p.sequence=[];p.run('asterViewDraw',p.board,p.graphics);assert p.sequence==['world'];cases+=1
    for selection in (0,1):
        ui=UiWorld(folder,struct.pack('<3I',0x31564155,selection,(~selection)&0xffffffff))
        ui.run('asterViewDraw',ui.board,ui.graphics)
        assert ui.tagged==bool(selection) and ui.matrix is None;cases+=1
        assert ui.ui_draws==([ui.nodes[1],ui.nodes[0]] if selection else [ui.nodes[1]]);cases+=1
        assert ui.sequence==(['push','world','pop','push','world-resumed','pop'] if selection else ['world','world-resumed']);cases+=1
    # Execute the native insertion, quicksort and heap fallback paths. The
    # object's vptr belongs to its storage slot; only payload words travel.
    for count,entry,depth in ((4,0x22ea34,None),(32,0x234d44,10),(32,0x234d44,0)):
        q=UiWorld(folder,record);base=q.records
        keys=[((i*13)%count) for i in range(count)]
        originals={}
        for i,key in enumerate(keys):
            row=[15,key,0x1000+i,0x9000+key,BASE,key+10,key+20,BASE+q.symbols['asterViewUiEntry'],0xa000+key]
            q.u.mem_write(base+36*i,struct.pack('<9I',*row));originals[key]=row
        args=(base,base+count*36,STOP+0x800) if depth is None else (base,base+count*36,depth,STOP+0x800)
        q.run(entry,*args,native=True)
        # Introsort deliberately leaves small partitions for the caller's
        # final insertion pass (the native world renderer does this too).
        if depth is not None:q.run(0x22ea34,base,base+count*36,STOP+0x800,native=True)
        for i in range(count):
            actual=list(struct.unpack('<9I',q.u.mem_read(base+36*i,36)))
            expected=originals[i].copy();expected[2]=0x1000+i
            assert actual==expected,(entry,depth,i,actual,expected)
        cases+=1
    for button,expected in ((1001,1001),(1004,1004),(1005,9)):
        q=World(folder);q.run(0x8e8884,q.ui,button,native=True)
        assert q.calls[-1]==('fallback',q.report['old_hooks'][str(0x8e8884)],q.ui,expected);cases+=1
    report=dict(arm_cases_passed=cases,iris_native_inverse_compared=True,native_render_device_push_pop_executed=True,ui_collector_scope_sort_copy_nested_checked=True,native_record_insertion_quick_heap_sort_executed=True,application_and_board_geometry_unchanged=True,runtime_accepted=False)
    (folder/'view-matrix-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return cases

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('folder',type=Path);a.add_argument('iris',type=Path);v=a.parse_args();check(v.folder,v.iris)
