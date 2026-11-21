"""Exercise A186's real fee branches, reward journal guard and skill readers."""
from pathlib import Path
from io import BytesIO
import argparse,copy,json,os,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from native_emulation_support import machine
from prepare_aster_pvp_balance import Bundle,u32,cipher,RTONDecoder,CHANGES

BASE=0x10000;MEM=0x6000000;STOP=0x5000100
def bits(v):return struct.unpack('<I',struct.pack('<f',v))[0]

def properties(raw):
    import zlib
    b=Bundle(raw)
    for i in range(len(b.groups)):
        for name,info in b.files(i):
            if not name.endswith('\\PROPERTYSHEETS.RTON'):continue
            block=b.payloads[i];data=block[u32(block,24):u32(block,24)+u32(block,28)]
            if u32(block,16)&2:data=zlib.decompress(data)
            raw=data[info[1]:info[1]+info[2]]
            if raw[:2]==b'\x10\0':raw=cipher.decrypt(raw[2:])
            f=BytesIO(raw[4:]);f.name=name;return json.loads(RTONDecoder(repairFiles=False).parse_root_object(f))
    raise ValueError('Properties missing')

class Engine:
    def __init__(self,path):
        os.environ['PVZ2_NATIVE_ORIGINAL']=str(path);self.u,_=machine();self.end=set()
        self.u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);self.u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.u.hook_add(UC_HOOK_CODE,self.hook)
        self.profile=MEM+0x10000;self.state=MEM+0x11000;self.info=MEM+0x12000
        self.props=MEM+0x13000;self.vector=MEM+0x14000;self.condition=MEM+0x15000;self.entity=MEM+0x16000
    def put(self,p,v):self.u.mem_write(p,struct.pack('<I',v&0xffffffff))
    def get(self,p):return struct.unpack('<I',self.u.mem_read(p,4))[0]
    def f(self,p):return struct.unpack('<f',self.u.mem_read(p,4))[0]
    def hook(self,u,a,size,_):
        if a==STOP or a-BASE in self.end:u.emu_stop()
        elif a==BASE+0x1df738:
            u.reg_write(UC_ARM_REG_R0,self.profile);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
    def run(self,entry,registers,end=()):
        self.end=set(end)
        self.u.reg_write(UC_ARM_REG_SP,0x4080000);self.u.reg_write(UC_ARM_REG_FP,0x4070000);self.u.reg_write(UC_ARM_REG_LR,STOP)
        for r,v in registers.items():self.u.reg_write(r,v)
        self.u.emu_start(BASE+entry,STOP,count=50000)
        pc=self.u.reg_read(UC_ARM_REG_PC)
        assert pc==STOP or pc-BASE in self.end,hex(pc)
        return self.u.reg_read(UC_ARM_REG_R0)
    def global_slot(self,literal,pc):return (BASE+pc+self.get(BASE+literal))&0xffffffff
    def setup_reward(self,coins,owner=7,serial=9,npc=0x70000001):
        self.u.mem_write(self.state,bytes(0x100));self.put(self.profile+0x74,7)
        for literal,pc,value in ((0x1a1ffa8,0x1a1ff18,owner),(0x1a1ffac,0x1a1ff30,serial),(0x1a1ffb0,0x1a1ff50,npc)):
            self.put(self.global_slot(literal,pc),value)
        for o,v in ((0xc,coins),(0xe0,9),(0xe8,0x70000001),(0xec,2),(0xf0,10)):self.put(self.state+o,v)
    def reward(self,stars):return self.run(0x1a1fedc,{UC_ARM_REG_R0:BASE,UC_ARM_REG_R1:self.state,UC_ARM_REG_R2:stars})

def check(folder,source):
    from zipfile import ZipFile
    with ZipFile(source) as z:before=properties(z.read('assets/reconstruction/dynamic-original-speed.rsb.smf'))
    after=properties((folder/'dynamic-balance.rsb.smf').read_bytes());expected=copy.deepcopy(before)
    for obj in expected['objects']:
        for alias in obj.get('aliases',[]):
            for field,(old,new) in CHANGES.get(alias,{}).items():
                assert obj['objdata'][field]==old;obj['objdata'][field]=new
    assert expected==after
    props={a:o['objdata'] for o in after['objects'] for a in o.get('aliases',[])}
    p=Engine(folder/'libSrc-balance.so');cases=1
    # Execute both native count-dependent price branches, including old late
    # tiers and unsigned extremes; retain all surrounding UI/journal code.
    for count in list(range(101))+[1000,0x7fffffff,0xffffffff]:
        p.run(0x1a111c8,{UC_ARM_REG_R1:count,UC_ARM_REG_R6:10},(0x1a111d8,))
        assert p.u.reg_read(UC_ARM_REG_R6)==10;cases+=1
        p.run(0x1a18378,{UC_ARM_REG_R0:count},(0x1a183c4,))
        assert p.u.reg_read(UC_ARM_REG_R10)==10;cases+=1
    for stars in range(4):
        for coins in (0,100,10000,1999999950,1999999999,2000000000):
            p.setup_reward(coins);assert p.reward(stars)==1
            assert p.get(p.state+0xc)==min(2000000000,coins+100*stars)
            assert p.get(p.state+0xe4)==9 and all(p.get(p.state+o)==0 for o in (0xe0,0xe8,0xec,0xf0))
            prior=bytes(p.u.mem_read(p.state,0x100));assert p.reward(stars)==0 and prior==bytes(p.u.mem_read(p.state,0x100));cases+=2
    for stars,owner,serial,npc in ((4,7,9,0x70000001),(3,8,9,0x70000001),(3,7,0,0x70000001),(3,7,8,0x70000001),(3,7,9,0x70000002)):
        p.setup_reward(100,owner,serial,npc);prior=bytes(p.u.mem_read(p.state,0x100))
        assert p.reward(stars)==0 and prior==bytes(p.u.mem_read(p.state,0x100));cases+=1
    p.put(p.entity+8,123)
    p.run(0x1a1db8c,{UC_ARM_REG_R6:p.entity},(0x1a1db98,))
    assert p.get(0x4080000+0x20)==300;cases+=1
    # The real grade/bounds/float conversion portions after type/weak lookup.
    # Metadata fixtures supply exactly the values decoded from the new RTON.
    for grade in range(0,6):
        p.put(p.info+4,grade);p.put(p.props+0x19c,p.vector);p.put(p.props+0x1a0,p.vector+16)
        for i,v in enumerate(props['ZombiePVPSkillAid']['AddHitpoints']):p.put(p.vector+4*i,bits(v))
        p.run(0x10018fc,{UC_ARM_REG_R0:p.info,UC_ARM_REG_R5:p.props},(0x1001928,))
        actual=p.u.reg_read(UC_ARM_REG_R5);expected=props['ZombiePVPSkillAid']['AddHitpoints'][grade-1] if 1<=grade<=4 else 0
        assert actual==bits(expected),(grade,actual,expected);cases+=1
        p.put(p.entity+0x38,grade);p.put(p.props+0x198,p.vector);p.put(p.props+0x19c,p.vector+16)
        for i,v in enumerate(props['ZombiePVPSkillInvisible']['SkillTime']):p.put(p.vector+4*i,bits(v))
        actual=p.run(0x100568c,{UC_ARM_REG_R4:p.props,UC_ARM_REG_R6:p.entity},(0x10056b0,0x10056bc))
        expected=props['ZombiePVPSkillInvisible']['SkillTime'][grade-1] if 1<=grade<=4 else 0
        assert actual==bits(expected);cases+=1
        p.put(p.props+0x19c,p.vector);p.put(p.props+0x1a0,p.vector+16);p.put(p.props+0x1a8,bits(2))
        p.put(p.condition+0x54,bits(1));p.put(p.condition+0x58,bits(1))
        p.put(0x4070000-0x44,p.info);p.put(0x4070000-0x40,p.condition)
        for i,v in enumerate(props['ZombiePVPSkillRage']['SpeedScale']):p.put(p.vector+4*i,bits(v))
        p.run(0xb0e448,{UC_ARM_REG_R5:p.props},(0xb0e484,))
        expected=props['ZombiePVPSkillRage']['SpeedScale'][grade-1] if 1<=grade<=4 else 1
        assert abs(p.f(p.condition+0x54)-expected)<1e-6 and p.f(p.condition+0x58)==2;cases+=1
        # Execute the real condition-50 aggregation too: the native common
        # timing multiplier changes, while the extra walk-only modifier and
        # damage multiplier retain their own original semantics.
        p.put(p.condition+8,0);p.put(p.condition+12,1<<(50-32))
        p.run(0xb0fc80,{UC_ARM_REG_R0:p.condition},(0xb0fd5c,))
        assert abs(p.f(p.condition+0x1c)-expected)<1e-6
        assert p.f(p.condition+0x20)==1 and p.f(p.condition+0x28)==2;cases+=1
    assert props['ZombiePVPSkillZombieFood']['InitEnergyCost']==40
    assert props['ZombiePVPSkillZombieFood']['ReduceCost']==[0,.15,.28,.4];cases+=1
    report=dict(native_and_resource_cases_passed=cases,fixed_fee_branches_executed=True,native_reward_journal_owner_clamp_and_duplicate_checks=True,native_neighbor_loot_record_checked=True,real_native_grade_reader_and_rage_cache_blocks=True,native_rage_condition_timing_aggregation_executed=True,skill_resource_diff_exactly_four_fields=True,full_skill_application_and_animation_tested=False,runtime_accepted=False)
    (folder/'balance-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('source',type=Path);check(**vars(p.parse_args()))
