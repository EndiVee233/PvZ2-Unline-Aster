"""A187: fixed 3x3 native queries, indicators and matching ground effects."""
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
import argparse,hashlib,json,struct,subprocess,sys
from elftools.elf.elffile import ELFFile
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'tools/pyvz2/OBBEdit/libraries'))
from prepare_offline_economy import Bundle,u32
from prepare_offline_pvp_skill_art import patch_pam
from rebuild_bootstrap_dex import rebuild_bootstrap

ENTRIES={0x1a0512c:'offlineFoodTargets',0x1a05294:'offlineRageTargets',
         0x1a052bc:'offlineAidContains',0x1a05474:'offlineFogContains',
         0x1a054c0:'offlineSkillCursorTargets',0x1a05650:'offlineSkillScope',
         0x1a05734:'offlineSkillScopeRect'}

def patch_native(native,ndk,output):
    assert hashlib.sha256(native).hexdigest()=='7fda65c0d7b114b15f01366da44e44fe52af01a82f699ff60a67818bc5522c71'
    elf=ELFFile(BytesIO(native));loads=[(i,s) for i,s in enumerate(elf.iter_segments()) if s['p_type']=='PT_LOAD']
    (ci,code),(ri,rw)=loads[-2:];assert code['p_flags']==5 and rw['p_flags']==6
    assert code['p_filesz']==code['p_memsz'] and rw['p_filesz']==rw['p_memsz']
    end=code['p_vaddr']+code['p_filesz'];start=(end+15)&~15
    compiler=ndk/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    obj=output/'fixed-ranges.o';linked=output/'fixed-ranges.elf';ld=output/'fixed-ranges.ld'
    flags=['--target=armv7a-linux-androideabi24','-marm','-march=armv7-a','-mfloat-abi=softfp','-mfpu=vfpv3-d16','-Os','-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-exceptions','-fno-rtti','-fno-unwind-tables','-fno-asynchronous-unwind-tables']
    subprocess.run([compiler,*flags,'-c',ROOT/'src/offline-pvp/fixed_skill_ranges.cpp','-o',obj],check=True)
    with obj.open('rb') as f:
        for sec in ELFFile(f).iter_sections():
            if sec['sh_type']=='SHT_REL' and 'exidx' not in sec.name:
                assert not any(r['r_info_type']==2 for r in sec.iter_relocations()),'Absolute relocation'
    ld.write_text(f'ENTRY(offlineFoodTargets)\nSECTIONS {{ . = {start}; .payload : {{ *(.text*) *(.rodata*) }} .state : {{ *(.data*) *(.bss*) *(COMMON) *(.got*) }} /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }} }}')
    subprocess.run([compiler,*flags,'-nostdlib','-static','-Wl,--no-undefined','-Wl,-T,'+str(ld),obj,'-o',linked],check=True)
    with linked.open('rb') as f:
        image=ELFFile(f);section=image.get_section_by_name('.payload');payload=section.data();state=image.get_section_by_name('.state')
        assert section['sh_addr']==start and (state is None or state['sh_size']==0),'Unexpected mutable state'
        symbols={s.name:s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols() if s.name in ENTRIES.values()}
    assert len(symbols)==7
    code_file_end=code['p_offset']+code['p_filesz'];assert not any(native[code_file_end:rw['p_offset']])
    result=bytearray(native[:code_file_end])+bytes(start-end)+payload
    rw_offset=(len(result)+4095)&~4095;result+=bytes(rw_offset-len(result));result+=native[rw['p_offset']:]
    ph=elf.header['e_phoff'];stride=elf.header['e_phentsize'];size=start+len(payload)-code['p_vaddr']
    struct.pack_into('<II',result,ph+ci*stride+16,size,size)
    struct.pack_into('<I',result,ph+ri*stride+4,rw_offset)
    changes=[]
    for address,name in ENTRIES.items():
        at=file_offset(elf,address);before=native[at:at+4];after=branch(address,symbols[name])
        result[at:at+4]=after;changes.append(dict(site=address,target=symbols[name],name=name,before=before.hex(),after=after.hex()))
    output_file=output/'libSrc-fixed-ranges.so';output_file.write_bytes(result)
    return bytes(result),dict(symbols=symbols,entry_hooks=changes,payload_address=start,payload_size=len(payload),rw_file_offset=rw_offset)

def patch_art(original):
    b=Bundle(original);changes=[]
    for i,g in enumerate(b.groups):
        if not g['ID'].startswith(('ZombiePVPSkillAidGroup_Common','ZombiePVPSkillRageGroup_Common')):continue
        block=b.payloads[i];assert u32(block,16)&2==0
        off=u32(block,24);section=bytearray(block[off:off+u32(block,28)])
        for name,info in b.files(i):
            phase=None
            # Undo v58's even-footprint half-cell shift as well as its scale.
            # An odd 3x3 footprint centers on the selected cell again.
            if '\\ZOMBIE\\' in name and name.endswith('\\ZOMBIE_PVPSKILL_AID.PAM'):phase=(3/4,3/4,173.5,177.5,50,50,'idle')
            if '\\ZOMBIE\\' in name and name.endswith('\\ZOMBIE_PVPSKILL_RAGE.PAM'):phase=(3/5,3/4,226.3,184.7,0,50,'idle')
            if not phase:continue
            raw=bytes(section[info[1]:info[1]+info[2]]);fixed,record=patch_pam(raw,False,phase)
            assert len(fixed)==len(raw) and record['ground_moves_rescaled']>0
            section[info[1]:info[1]+info[2]]=fixed
            changes.append(dict(name=name,phase=phase,sha256_before=hashlib.sha256(raw).hexdigest(),sha256_after=hashlib.sha256(fixed).hexdigest(),**record))
        b.payloads[i]=block[:off]+section+block[off+len(section):]
    assert len(changes)==2
    result=b.build();check=Bundle(result);prior=Bundle(original)
    assert len(result)==len(original)
    for i in range(len(b.groups)):
        assert check.payloads[i]==b.payloads[i]
        # PTX offsets and bytes, data indexes and all other animation files
        # remain byte-identical. Only the two idle phase move records change.
        old=prior.payloads[i];new=check.payloads[i];assert old[:u32(old,24)]==new[:u32(new,24)]
        assert old[u32(old,40):]==new[u32(new,40):]
        for name,info in prior.files(i):
            if name in {x['name'] for x in changes}:continue
            start=u32(old,24)+info[1];assert old[start:start+info[2]]==new[start:start+info[2]],name
    return result,changes

def prepare(apk,ndk,output):
    output.mkdir(parents=True,exist_ok=True)
    with ZipFile(apk) as z:
        native,nrecord=patch_native(z.read('lib/armeabi/libSrc.so'),ndk,output)
        old=z.read('assets/reconstruction/zombie2-pvp.rsb.smf');new,art=patch_art(old);bootstrap=z.read('classes8.dex')
    oldsha=hashlib.sha256(old).hexdigest();newsha=hashlib.sha256(new).hexdigest()
    marker='.method private static isPvpResourcePredecessor(Ljava/lang/String;)Z\n    .registers 2'
    extra=f'''\n    const-string v0, "{oldsha}"
    invoke-virtual {{v0, p0}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :a187_older_art
    const/4 v0, 0x1
    return v0
    :a187_older_art'''
    old_marker='.pvp-original-art-v103-'+oldsha[:12];new_marker='.pvp-fixed-ranges-A187-'+newsha[:12]
    bootstrap=rebuild_bootstrap(bootstrap,output/'bootstrap',{oldsha:newsha,marker:marker+extra,old_marker:new_marker},ROOT.parent/'tools/apktool.jar')
    (output/'zombie2-fixed-ranges.rsb.smf').write_bytes(new);(output/'classes8.dex').write_bytes(bootstrap)
    report=dict(version='A187',source_native_sha256='7fda65c0d7b114b15f01366da44e44fe52af01a82f699ff60a67818bc5522c71',native_sha256=hashlib.sha256(native).hexdigest(),source_art_sha256=oldsha,art_sha256=newsha,art_size=len(new),art_changes=art,bootstrap_sha256=hashlib.sha256(bootstrap).hexdigest(),all_grades_footprint=[3,3],**nrecord,runtime_accepted=False)
    (output/'fixed-ranges-patch.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('apk','ndk','output'):p.add_argument(name,type=Path)
    prepare(**vars(p.parse_args()))
