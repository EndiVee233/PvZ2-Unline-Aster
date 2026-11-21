"""A186 skill properties, fixed neighbor fee and three-star 300-coin loot."""
from pathlib import Path
from io import BytesIO,StringIO
from zipfile import ZipFile
import argparse,copy,hashlib,json,struct,sys,zlib
from keystone import Ks,KS_ARCH_ARM,KS_MODE_ARM
from elftools.elf.elffile import ELFFile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'tools/pyvz2/OBBEdit/libraries'))
from prepare_offline_economy import Bundle,u32,trie_write,cipher,RTONDecoder,JSONDecoder
from prepare_aster_pvp_runtime import file_offset
from rebuild_bootstrap_dex import rebuild_bootstrap
from build_aster_rgba_background_pilot import create_plan

CHANGES={
 'ZombiePVPSkillAid':{'AddHitpoints':([600,800,1000,1200],[1200,1600,2000,2400])},
 'ZombiePVPSkillInvisible':{'SkillTime':([5,6,7,8],[10,12,14,16])},
 'ZombiePVPSkillRage':{'SpeedScale':([2,2.4,2.8,3.2],[3,3.6,4.2,4.8])},
 'ZombiePVPSkillZombieFood':{'InitEnergyCost':(60,40)},
}

def patch_resource(original):
    bundle=Bundle(original);records=[];original_docs={}
    for i in range(len(bundle.groups)):
        files=list(bundle.files(i));block=bundle.payloads[i];off=u32(block,24)
        section=block[off:off+u32(block,28)]
        if u32(block,16)&2:section=zlib.decompress(section)
        for idx,(name,info) in enumerate(files):
            if not name.endswith('\\PROPERTYSHEETS.RTON'):continue
            raw=section[info[1]:info[1]+info[2]];encrypted=raw[:2]==b'\x10\0'
            if encrypted:raw=cipher.decrypt(raw[2:])
            f=BytesIO(raw[4:]);f.name=name;doc=json.loads(RTONDecoder(repairFiles=False).parse_root_object(f));before=copy.deepcopy(doc)
            for obj in doc['objects']:
                for alias in obj.get('aliases',[]):
                    if alias not in CHANGES:continue
                    for key,(old,new) in CHANGES[alias].items():
                        assert obj['objdata'][key]==old,(alias,key,obj['objdata'][key])
                        obj['objdata'][key]=new;records.append(dict(alias=alias,field=key,before=old,after=new))
            assert len(records)==4
            encoded=JSONDecoder().encode_root_object(StringIO(json.dumps(doc,ensure_ascii=False)))
            f=BytesIO(encoded[4:]);f.name=name;assert json.loads(RTONDecoder(repairFiles=False).parse_root_object(f))==doc
            replacement=b'\x10\0'+cipher.encrypt(encoded) if encrypted else encoded
            files[idx]=(name,(0,len(section),len(replacement)));section+=replacement;section+=bytes((-len(section))%4096)
            head=bytearray(block[:off]);table=trie_write(files,1);to=u32(head,0x4c);assert to+len(table)<=off
            head[to:to+len(table)]=table;struct.pack_into('<I',head,0x48,len(table));struct.pack_into('<I',head,16,u32(head,16)&~2)
            struct.pack_into('<II',head,28,len(section),len(section));struct.pack_into('<I',head,40,len(head)+len(section))
            bundle.payloads[i]=head+section+block[u32(block,40):u32(block,40)+u32(block,44)];bundle.sync_info(i)
            original_docs[name]=(before,doc)
    assert len(records)==4 and len(original_docs)==1
    result=bundle.build();verify=Bundle(result);prior=Bundle(original)
    for i in range(len(bundle.groups)):
        assert verify.payloads[i]==bundle.payloads[i]
        sections=[]
        for b in (prior,verify):
            block=b.payloads[i];section=block[u32(block,24):u32(block,24)+u32(block,28)]
            if u32(block,16)&2:section=zlib.decompress(section)
            sections.append((section,dict(b.files(i))))
        for name,_ in prior.files(i):
            if name.endswith('\\PROPERTYSHEETS.RTON'):continue
            # Compare every original resource's unpacked bytes, not only the
            # group list; modified RSG padding/offsets are allowed to change.
            def content(entry):
                section,index=entry;info=index[name];return section[info[1]:info[1]+info[2]]
            assert content(sections[0])==content(sections[1]),name
    return result,records,original_docs

def patch_native(original):
    assert hashlib.sha256(original).hexdigest()=='6fbd67f51a53ade43ba14d050ce2761ac01cbeb7ba74e2356a821275eeaa089b'
    elf=ELFFile(BytesIO(original));result=bytearray(original);ks=Ks(KS_ARCH_ARM,KS_MODE_ARM);records=[]
    changes=[
      (0x1a111cc,'movhs r6,#20','movhs r6,#10','preview_fee'),
      (0x1a112ac,'mov r6,#100','mov r6,#10','preview_fee'),
      (0x1a112b4,'movwlo r6,#50','movwlo r6,#10','preview_fee'),
      (0x1a18380,'movhs sl,#20','movhs sl,#10','actual_fee'),
      (0x1a1838c,'mov sl,#100','mov sl,#10','actual_fee'),
      (0x1a18394,'movwlo sl,#50','movwlo sl,#10','actual_fee'),
      (0x1a1ff54,'mov r1,#100','mov r1,#300','settlement_loot'),
      (0x1a1db8c,'mov r0,#100','mov r0,#300','neighbor_loot_display'),
    ]
    for site,old,new,role in changes:
        at=file_offset(elf,site);expected=bytes(ks.asm(old,site)[0]);replacement=bytes(ks.asm(new,site)[0])
        assert original[at:at+4]==expected,(hex(site),original[at:at+4].hex(),expected.hex())
        assert len(replacement)==4;result[at:at+4]=replacement
        records.append(dict(site=site,before=expected.hex(),after=replacement.hex(),role=role))
    return bytes(result),records

def prepare(apk,output):
    output.mkdir(parents=True,exist_ok=True)
    with ZipFile(apk) as z:
        old=z.read('assets/reconstruction/dynamic-original-speed.rsb.smf');new,records,docs=patch_resource(old)
        native,patches=patch_native(z.read('lib/armeabi/libSrc.so'));bootstrap=z.read('classes8.dex')
    oldsha=hashlib.sha256(old).hexdigest();newsha=hashlib.sha256(new).hexdigest()
    marker='.method private static isSupportedResourcePredecessor(Ljava/lang/String;)Z\n    .registers 2'
    extra=f'''\n    const-string v0, "{oldsha}"
    invoke-virtual {{v0, p0}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :a186_older_resources
    const/4 v0, 0x1
    return v0
    :a186_older_resources'''
    old_marker='.offline-tutorial-v167-'+oldsha[:12]
    new_marker='.offline-pvp-balance-A186-'+newsha[:12]
    bootstrap=rebuild_bootstrap(bootstrap,output/'bootstrap',{oldsha:newsha,marker:marker+extra,old_marker:new_marker,hex(len(old)):hex(len(new))},ROOT.parent/'tools/apktool.jar')
    (output/'dynamic-balance.rsb.smf').write_bytes(new);(output/'libSrc-balance.so').write_bytes(native);(output/'classes8.dex').write_bytes(bootstrap)
    # Existing installations may already use a verified RGBA generation and
    # skip BootActivity's overlay. A new plan source hash invalidates the old
    # proof, restores this new source atomically and stages its RGBA successor.
    plan=create_plan(new,output);(output/'aster-dynamic-rgba.plan').write_bytes(plan)
    assert plan[:4]==b'ABG1' and plan[12:44]==bytes.fromhex(newsha)
    report=dict(version='A186',skill_changes=records,native_patches=patches,source_native_sha256='6fbd67f51a53ade43ba14d050ce2761ac01cbeb7ba74e2356a821275eeaa089b',native_sha256=hashlib.sha256(native).hexdigest(),source_resource_sha256=oldsha,resource_sha256=newsha,resource_size=len(new),bootstrap_sha256=hashlib.sha256(bootstrap).hexdigest(),rgba_plan_sha256=hashlib.sha256(plan).hexdigest(),old_rgba_generation_invalidated=True,all_other_resources_unchanged=True,runtime_accepted=False)
    (output/'balance-patch.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path);p.add_argument('output',type=Path);prepare(**vars(p.parse_args()))
