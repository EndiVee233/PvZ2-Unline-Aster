"""Execute A173 native settings, persistence and view transforms in ARM emulation."""
from pathlib import Path
import argparse,json,os,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from native_emulation_support import machine

BASE=0x10000;MEM=0x6000000;STOP=0x5000100
def bits(f):return struct.unpack('<I',struct.pack('<f',f))[0]

class Probe:
    def __init__(self,folder,record=None,fail=None):
        os.environ['PVZ2_NATIVE_ORIGINAL']=str(folder/'libSrc-view-angle.so')
        self.u,self.imports=machine();self.report=json.loads((folder/'view-angle-patch.json').read_text())
        self.u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);self.u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.symbols=self.report['symbols'];self.record=record;self.fail=fail;self.temporary=b'';self.pos=0
        self.rows=[];self.calls=[];self.heap=MEM+0xc000
        self.app=MEM;self.ui=MEM+0x3000;self.board=MEM+0x5000;self.graphics=MEM+0x7000;self.description=MEM+0x9000
        self.put(BASE+0x1821674,MEM+0x2800);self.put(MEM+0x2800,self.app)
        self.put(self.ui+0xbc,MEM+0x3800);self.put(self.description,MEM+0x9800);self.put(MEM+0x9804,STOP+0x100)
        self.put(self.board+0x938,MEM+0xa000)
        for o in (0x690,0x698):self.put(self.app+o,bits(1.0))
        for o in (0x6a0,0x6a4):self.put(self.app+o,1536)
        self.u.hook_add(UC_HOOK_CODE,self.hook)
    def put(self,a,v):self.u.mem_write(a,struct.pack('<I',v&0xffffffff))
    def get(self,a):return struct.unpack('<I',self.u.mem_read(a,4))[0]
    def floating(self,a):return struct.unpack('<f',self.u.mem_read(a,4))[0]
    def text(self,p):
        result=[]
        while self.get(p):result.append(chr(self.get(p)));p+=4
        return ''.join(result)
    def hook(self,u,address,size,_):
        if address==STOP:u.emu_stop();return
        r=[u.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        name=self.imports.get(address);off=address-BASE;result=0
        if name=='open':
            if r[1]:self.temporary=b'';result=-1 if self.fail=='open' else 8
            else:self.pos=0;result=7 if self.record is not None else -1
        elif name=='read':
            data=self.record[self.pos:self.pos+r[2]];self.pos+=len(data)
            if data:u.mem_write(r[1],data)
            result=len(data)
        elif name=='write':
            self.temporary=bytes(u.mem_read(r[1],r[2]));result=4 if self.fail=='write' else r[2]
        elif name in ('fsync','close','rename'):
            result=-1 if self.fail==name else 0
            if name=='rename' and not result:self.record=self.temporary
        elif name in ('remove','unlink'):self.temporary=b''
        elif off==0x14eb450:
            text=r[1];n=0
            while self.get(text+4*n):n+=1
            self.heap+=16;p=self.heap;u.mem_write(p,bytes(u.mem_read(text,4*(n+1))));self.heap+=4*(n+1);self.put(r[0],p)
        elif off==0x14ea238:pass
        elif off==0x1dd8f0:result=MEM+0xb000
        elif off in (0x8e4898,0x8e4edc):
            checked=r[3] if off==0x8e4edc else None
            self.rows.append((r[1],self.text(self.get(r[2])),checked));result=MEM+0xb800
        elif off==0x8e5924:pass
        elif off==0x14e9b0c:self.calls.append(('title',self.text(self.get(r[1]))))
        elif off==0x8e7820:self.calls.append(('refresh',r[0]))
        elif address==STOP+0x100:self.calls.append(('destroy-description',))
        elif off in self.report['old_hooks'].values():self.calls.append(('fallback',off,r[0],r[1]))
        elif off in (0x204b04,0x426964,0x402464):
            self.calls.append(('resume',off));u.emu_stop();return
        elif off==0x204b00:self.calls.append(('bounds',r[0]))
        else:return
        u.reg_write(UC_ARM_REG_R0,result&0xffffffff);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
    def run(self,name,*args,native=False):
        for reg in range(UC_ARM_REG_R0,UC_ARM_REG_R12+1):self.u.reg_write(reg,0)
        self.u.reg_write(UC_ARM_REG_SP,0x4080000);self.u.reg_write(UC_ARM_REG_LR,STOP)
        values=args if native else (BASE,*args)
        for reg,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):self.u.reg_write(reg,v)
        entry=name if isinstance(name,int) else self.symbols[name]
        self.u.emu_start(BASE+entry,STOP,count=200000)
        assert self.u.reg_read(UC_ARM_REG_PC)==STOP or self.calls[-1][0]=='resume'
        return self.u.reg_read(UC_ARM_REG_R0)
    def open(self):assert self.run('asterViewClick',self.ui,1005)==2
    def rows_now(self):
        self.rows=[];assert self.run('asterViewRows',MEM+0x3800,self.description)==1;return self.rows

def check(folder):
    cases=0
    e=Probe(folder);e.run('asterViewSettingsReady',e.ui);assert e.rows==[(1005,'视角',None)];cases+=1
    e.open();assert e.run('asterViewTitle',MEM+0xa800)==1 and e.calls[-1]==('title','视角');cases+=1
    assert e.rows_now()==[(1041,'高',1),(1042,'正常',0)];cases+=1
    assert e.run('asterViewClick',e.ui,1042)==1;record=e.record
    assert struct.unpack('<3I',record)==(0x31564155,1,0xfffffffe);cases+=1
    assert e.rows_now()==[(1041,'高',0),(1042,'正常',1)];cases+=1
    e=Probe(folder,record);e.open();assert e.rows_now()[1][2]==1;cases+=1
    e.run('asterViewScale');assert abs(e.floating(e.app+0x690)-1.2)<1e-6
    assert e.get(e.app+0x6a0)==1843 and e.get(e.app+0x6a4)==1536 and e.floating(e.app+0x698)==1;cases+=1
    e.put(e.board+0x30,20);e.put(e.graphics+12,bits(20))
    e.run('asterViewPosition',e.board,e.graphics);assert e.get(e.board+0x30)==(-88&0xffffffff) and e.floating(e.graphics+12)==-88;cases+=1
    e.run('asterViewPosition',e.board,e.graphics);assert e.get(e.board+0x30)==(-88&0xffffffff) and e.floating(e.graphics+12)==-88;cases+=1
    # Resize resets the game scale; the next draw must restore world scale/bounds.
    e.put(e.app+0x690,bits(1));e.put(e.board+0x30,30)
    e.run('asterViewPosition',e.board,e.graphics);assert abs(e.floating(e.app+0x690)-1.2)<1e-6 and ('bounds',e.board) in e.calls;cases+=1
    # Native touch conversion is the inverse of the persisted scale/origin.
    for row in range(5):
        world=160+(row+0.5)*76
        screen=(-78)+world*e.floating(e.app+0x690)
        recovered=(screen-(-78))/e.floating(e.app+0x690)
        assert e.run(0x2410b8,int(recovered),native=True)==row;cases+=1
    e.run('asterViewClick',e.ui,1041);e.run('asterViewScale');e.run('asterViewPosition',e.board,0)
    assert e.floating(e.app+0x690)==1 and e.get(e.board+0x30)==30;cases+=1
    e.run('asterViewClick',e.ui,1);assert e.run('asterViewRows',MEM+0x3800,e.description)==0;cases+=1
    for bad in (b'',b'bad',struct.pack('<3I',0,1,0xfffffffe),struct.pack('<3I',0x31564155,2,0xfffffffd),record+b'x'):
        p=Probe(folder,bad);p.open();assert p.rows_now()[0][2]==1;cases+=1
    for fail in ('open','write','fsync','close','rename'):
        p=Probe(folder,None,fail);p.open();p.run('asterViewClick',p.ui,1042);assert p.rows_now()[0][2]==1 and p.record is None;cases+=1
    # Test the actual patched dispatcher preserves legacy entries and routes
    # the new row through the original submenu ID 9.
    for button,expected in ((1001,1001),(1004,1004),(1005,9)):
        p=Probe(folder);p.run(0x8e8884,p.ui,button,native=True)
        assert p.calls[-1]==('fallback',p.report['old_hooks'][str(0x8e8884)] if str(0x8e8884) in p.report['old_hooks'] else p.report['old_hooks'][0x8e8884],p.ui,expected);cases+=1
    report=dict(arm_cases_passed=cases,runtime_accepted=False)
    (folder/'view-angle-checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return cases

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);check(p.parse_args().folder)
