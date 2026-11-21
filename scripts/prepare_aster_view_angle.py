"""Append the shared native view setting without rebuilding prior engine/JNI code."""
from io import BytesIO
from pathlib import Path
import argparse,hashlib,json,struct,subprocess
from elftools.elf.elffile import ELFFile
from keystone import Ks,KS_ARCH_ARM,KS_MODE_ARM
from prepare_profile_memory import branch
from prepare_aster_pvp_runtime import file_offset

ROOT=Path(__file__).resolve().parents[1]

def patch(native,ndk,output):
    output.mkdir(parents=True,exist_ok=True)
    elf=ELFFile(BytesIO(native))
    loads=[(i,s) for i,s in enumerate(elf.iter_segments()) if s['p_type']=='PT_LOAD']
    (ci,code),(ri,rw)=loads[-2:]
    if (code['p_flags'],rw['p_flags'])!=(5,6) or code['p_filesz']!=code['p_memsz'] or rw['p_filesz']!=rw['p_memsz']:
        raise ValueError('Unknown v172 payload segments')
    def word(va):return struct.unpack_from('<I',native,file_offset(elf,va))[0]
    def target(va,link):
        w=word(va)
        if w>>24!=(0xeb if link else 0xea):raise ValueError(f'Unexpected hook at {va:x}')
        d=w&0xffffff
        if d&0x800000:d-=0x1000000
        return va+8+4*d
    old={va:target(va,va!=0x8e8884) for va in (0x8e6114,0x8e8884,0x8e7868,0x8e7b34,0x23aa00)}
    # Require the exact preserved settings/camera hooks from this baseline.
    expected={0x8e6114:0x1a2b3e8,0x8e8884:0x1a2b47c,0x8e7868:0x1a2b574,0x8e7b34:0x1a2b598,0x23aa00:0x1a2b1c4}
    if old!=expected:raise ValueError('Engine is not the expected Aster v172 baseline')
    entry=(code['p_vaddr']+code['p_filesz']+15)&~15
    runtime=(rw['p_vaddr']+rw['p_memsz']+15)&~15
    tool=ndk/'toolchains/llvm/prebuilt/windows-x86_64/bin'
    obj=output/'view-angle.o';linked=output/'view-angle.elf'
    flags=['--target=armv7a-linux-androideabi24','-marm','-march=armv7-a','-mfloat-abi=softfp','-mfpu=vfpv3-d16','-Os','-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-exceptions','-fno-rtti','-fno-unwind-tables','-fno-asynchronous-unwind-tables']
    subprocess.run([tool/'clang++.exe',*flags,'-c',ROOT/'src/view-angle/view_angle.cpp','-o',obj],check=True)
    desktop=output/'desktop-view.o'
    subprocess.run([tool/'clang++.exe',*flags,'-DDESKTOP_PVP_SEEDS','-DDESKTOP_EXTENDED_INPUT','-DDESKTOP_ENDLESS_INPUT','-DDESKTOP_VIEW_ANGLE','-c',ROOT/'src/desktop-input/shortcuts.cpp','-o',desktop],check=True)
    for source in (obj,desktop):
        with source.open('rb') as f:
            for sec in ELFFile(f).iter_sections():
                if sec['sh_type']=='SHT_REL' and 'exidx' not in sec.name:
                    if any(r['r_info_type']==2 for r in sec.iter_relocations()):raise ValueError('Absolute ASLR relocation')
    ld=output/'view-angle.ld'
    ld.write_text(f'ENTRY(asterViewClick)\nSECTIONS {{ . = {entry}; .payload : {{ *(.text*) *(.rodata*) }} . = {runtime}; .runtime : {{ *(.data*) *(.bss*) *(COMMON) *(.got*) }} /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }} }}')
    subprocess.run([tool/'clang++.exe',*flags,'-nostdlib','-static','-no-pie','-Wl,--no-undefined','-Wl,-T,'+str(ld),obj,desktop,'-o',linked],check=True)
    with linked.open('rb') as f:
        helper=ELFFile(f);p=helper.get_section_by_name('.payload');state=helper.get_section_by_name('.runtime')
        symbols={s.name:s['st_value'] for s in helper.get_section_by_name('.symtab').iter_symbols()}
        start=entry;gap=p['sh_addr']-entry
        payload=bytearray(bytes(gap)+p.data());state_size=state['sh_size'];state_data=state.data() if state['sh_type']!='SHT_NOBITS' else bytes(state_size)
    assembler=Ks(KS_ARCH_ARM,KS_MODE_ARM)
    def baseasm():return 'adr r0,basepoint\nldr ip,[r0]\nsub r0,r0,ip\n'
    def stub(source):
        while len(payload)%4:payload.append(0)
        va=start+len(payload)
        b=bytearray(assembler.asm(source+'\nbasepoint: .word 0x11223344',va)[0])
        at=b.index(struct.pack('<I',0x11223344));struct.pack_into('<I',b,at,va+at)
        payload.extend(b);return va
    changes={};records=[]
    def hook(site,dest,link=False):
        changes[site]=branch(site,dest,link);records.append(dict(site=site,target=dest,before=native[file_offset(elf,site):file_offset(elf,site)+4].hex()))
    hook(0x8e6114,stub('push {r0-r4,lr}\nmov r1,r4\n'+baseasm()+f'bl #{symbols["asterViewSettingsReady"]}\npop {{r0-r4,lr}}\nb #{old[0x8e6114]}'),True)
    hook(0x8e8884,stub('push {r0-r4,lr}\nmov r2,r1\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewClick"]}\ncmp r0,#2\nmoveq r1,#9\nstreq r1,[sp,#4]\nbeq fallback\ncmp r0,#0\npop {{r0-r4,lr}}\nbne handled\nb #{old[0x8e8884]}\nfallback: pop {{r0-r4,lr}}\nb #{old[0x8e8884]}\nhandled: bx lr'))
    hook(0x8e7868,stub('push {r0-r4,lr}\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewTitle"]}\ncmp r0,#0\npop {{r0-r4,lr}}\nbne handled\nb #{old[0x8e7868]}\nhandled: bx lr'),True)
    hook(0x8e7b34,stub('push {r0-r4,lr}\nmov r2,r1\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewRows"]}\ncmp r0,#0\npop {{r0-r4,lr}}\nbeq #{old[0x8e7b34]}\nb #0x8e7be4'),True)
    # Apply one native RenderDevice matrix to the complete world. No scale
    # or layout hooks: the stock geometry and UI hit tests remain authoritative.
    hook(0x23aa00,stub('push {r4,lr}\nmov r2,r1\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewDraw"]}\npop {{r4,pc}}'),True)
    if target(0x235194,True)!=0x9779a0:raise ValueError('Unknown native UI collector')
    hook(0x235194,stub('push {r4,lr}\nmov r2,r1\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewCollectUi"]}\npop {{r4,pc}}'),True)
    # Board's NPC/message renderer draws screen-aligned banners, ready/set,
    # level titles and advice, then the caller resumes world cursor drawing.
    for site in (0x46d890,):
        if word(site)&0xffff0000!=0xe92d0000:raise ValueError('Unknown screen text prologue')
        original=stub(f'.word {word(site)}\nb #{site+4}')
        hook(site,stub('push {r4,lr}\nmov r2,r1\nmov r1,r0\n'+f'movw r3,#{original&65535}\nmovt r3,#{original>>16}\n'+baseasm()+f'bl #{symbols["asterViewScreenDraw"]}\npop {{r4,pc}}'))
    # Standalone effects explicitly mark screen coordinates with flag 0x80.
    # Keep their native identity push/pop. Do not apply the additional lawn
    # matrix to these effects; unflagged floating/damage text keeps its world
    # transform and uses a short assembly fast path with no helper call.
    site=0x599044
    if word(site)!=0xe52db004:raise ValueError('Unknown standalone draw prologue') # str fp,[sp,#-4]!
    original=stub(f'.word {word(site)}\nb #{site+4}')
    effect='ldr ip,[r0,#40]\ncmp ip,#0\nbeq world_effect\nldr ip,[ip,#16]\ntst ip,#128\nbeq world_effect\npush {r4,lr}\nmov r2,r1\nmov r1,r0\n'+f'movw r3,#{original&65535}\nmovt r3,#{original>>16}\n'+baseasm()+f'bl #{symbols["asterViewScreenDraw"]}\npop {{r4,pc}}\nworld_effect: .word {word(site)}\nb #{site+4}'
    hook(site,stub(effect))
    for site in (0x22a344,0x221858):
        if target(site,True)!=0x3476ac:raise ValueError('Unexpected world touch dispatcher')
        hook(site,stub('push {r4,lr}\nmov r3,r1\nmov r2,r0\nmov r1,r5\n'+baseasm()+f'bl #{symbols["asterViewTouch"]}\npop {{r4,pc}}'),True)
    if word(0x1fbf74)!=0xe594093c:raise ValueError('Unexpected moved-touch tail')
    hook(0x1fbf74,stub('push {r4,lr}\nmov r3,r5\nldr r2,[r4,#0x93c]\nmov r1,r4\n'+baseasm()+f'bl #{symbols["asterViewTouch"]}\npop {{r4,lr}}\nb #0x1fbf24'))
    # Board's unconsumed release publishes its own point after the dispatcher.
    # Restore only the register pair feeding that world event; keep the UI
    # touch packet and the previously dispatched cursor point untouched.
    if word(0x22186c)!=0xe5945008 or word(0x22187c)!=0xe594700c:raise ValueError('Unknown unconsumed release coordinates')
    hook(0x22186c,stub('push {r0-r4,lr}\nsub sp,sp,#8\nldr r3,[r4,#8]\nstr r3,[sp]\nldr r3,[r4,#12]\nstr r3,[sp,#4]\nmov r2,sp\nmov r1,r5\n'+baseasm()+f'bl #{symbols["asterViewPoint"]}\nldr r5,[sp]\nldr r7,[sp,#4]\nadd sp,sp,#8\npop {{r0-r4,lr}}\nb #0x221870'))
    # r5 was still this Board at 22186c. r7 already holds transformed Y;
    # the intervening original event-key loads do not use r7.
    changes[0x22187c]=struct.pack('<I',0xe1a00000)
    records.append(dict(site=0x22187c,before=struct.pack('<I',word(0x22187c)).hex(),instruction='nop; Y loaded by release point wrapper'))
    # The editor's unconsumed down path also bypasses the dispatcher. Both
    # selecting the plant cell and constructing its cursor need world points.
    if target(0x22a3cc,True)!=0x204930:raise ValueError('Unknown editor cell conversion')
    hook(0x22a3cc,stub('push {r4,lr}\nmov r3,r2\nmov r2,r1\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewGridPoint"]}\npop {{r4,pc}}'),True)
    if target(0x22a488,True)!=0x10ab71c:raise ValueError('Unknown editor cursor constructor')
    editor='push {r0-r8,lr}\nsub sp,sp,#56\nldr r4,[sp,#96]\nstr r4,[sp]\nldr r4,[sp,#100]\nstr r4,[sp,#4]\nadd r3,sp,#8\nmov r2,r1\nmov r1,r5\n'+baseasm()+f'bl #{symbols["asterViewCopyTouch"]}\nldr r0,[sp,#56]\nadd r1,sp,#8\nldr r2,[sp,#64]\nldr r3,[sp,#68]\nbl #0x10ab71c\nadd sp,sp,#72\npop {{r4-r8,pc}}'
    hook(0x22a488,stub(editor),True)
    # The preserved v172 skillQuery called the entity registry and treated it
    # as Board. Patch this one call, not the registry's legitimate callers.
    if [word(a) for a in (0x1a051c4,0x1a051c8,0x1a051cc,0x1a051d0)]!=[0xe30e0c10,0xe3400020,0xe08a0000,0xe12fff30]:raise ValueError('Unknown skillQuery registry call')
    hook(0x1a051d0,stub('push {r4,lr}\n'+baseasm()+f'bl #{symbols["asterViewSkillBoard"]}\npop {{r4,pc}}'),True)
    if word(0x1a010a4)>>24!=0xea:raise ValueError('Missing existing desktop entry redirect')
    hook(0x1a010a4,symbols['desktopInput'])
    # The native phase-5 bridge updates the pending cursor after desktopInput
    # returns. Transform that call too; a global setter hook would also affect
    # game-internal positions which already use world coordinates.
    if target(0x1a01c18,True)!=0x1efccc:raise ValueError('Unknown desktop hover cursor call')
    hook(0x1a01c18,stub('push {r4,lr}\nmov r3,r1\nmov r2,r0\nldr r1,[r5,#0x44]\nldr r1,[r1,#0x6bc]\n'+baseasm()+f'bl #{symbols["asterViewDesktopCursor"]}\npop {{r4,pc}}'),True)
    for site in (0x4e5900,0x4e7f1c):
        if target(site,True)!=0x1eff40:raise ValueError('Unknown UI cursor pickup bounds setter')
        hook(site,stub('push {r4,lr}\nmov r2,r1\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewPickupRect"]}\npop {{r4,pc}}'),True)
    if word(0x1efd38)!=0xe92d48f0:raise ValueError('Unknown native cursor finish prologue')
    hook(0x1efd38,stub('push {r0-r4,lr}\nmov r2,lr\nmov r1,r0\n'+baseasm()+f'bl #{symbols["asterViewTraceFinish"]}\npop {{r0-r4,lr}}\n.word 0xe92d48f0\nb #0x1efd3c'))
    if word(0x4f2530)&0xffff0000!=0xe92d0000:raise ValueError('Unknown plantfood purchase prologue')
    purchase=stub(f'.word {word(0x4f2530)}\nb #0x4f2534')
    hook(0x4f2530,stub('push {r4,lr}\nmov r2,r1\nmov r1,r0\n'+f'movw r3,#{purchase&65535}\nmovt r3,#{purchase>>16}\n'+baseasm()+f'bl #{symbols["asterViewPlantfoodPurchase"]}\npop {{r4,pc}}'))
    # Audited UIWidget constructors explicitly register these fixed-UI touch
    # handlers in Board's dispatcher (priority 8). Keep their native actions.
    fixed_buttons={0x8f4870:'NextWaveButton',0x926b94:'StartGameButton',
                   0x109c20c:'ArenaPVPStartButton',0x109fe80:'ArenaOccupyStartButton',
                   0x10a1208:'ArenaOccupyQuitButton',0x10a21ec:'ArenaChangeSpeedButton',
                   0x10a3474:'ArenaEndingButton'}
    for site,name in fixed_buttons.items():
        if word(site)&0xffff0000!=0xe92d0000:raise ValueError(f'Unknown {name} touch prologue')
        original=stub(f'.word {word(site)}\nb #{site+4}')
        hook(site,stub('push {r4,lr}\nmov r2,r1\nmov r1,r0\n'+f'movw r3,#{original&65535}\nmovt r3,#{original>>16}\n'+baseasm()+f'bl #{symbols["asterViewFixedButton"]}\npop {{r4,pc}}'))
    # Keep bounded PVP input/action traces for device regression acceptance.
    # Saved entry arguments and the original prologue are restored verbatim.
    for site in (0x1ef560,0x108c474,0x109133c,0x10a1afc,0x1030ae8):
        if word(site)&0xffff0000!=0xe92d0000:raise ValueError(f'Unknown PVP trace prologue {site:x}')
        hook(site,stub('push {r0-r4,lr}\nmov r2,sp\n'+f'movw r1,#{site&65535}\nmovt r1,#{site>>16}\n'+baseasm()+f'bl #{symbols["asterViewPvpTrace"]}\npop {{r0-r4,lr}}\n.word {word(site)}\nb #{site+4}'))
    for site in (0x10067f0,0x1007924,0x105a220):
        original=target(site,True)
        hook(site,stub('push {r0-r4,lr}\n'+f'bl #{original}\n'+'push {r0-r3,ip,lr}\nadd r2,sp,#24\n'+f'movw r1,#{site&65535}\nmovt r1,#{site>>16}\n'+baseasm()+f'bl #{symbols["asterViewPvpQueryTrace"]}\npop {{r0-r3,ip,lr}}\nldr r4,[sp,#16]\nldr lr,[sp,#20]\nadd sp,sp,#24\nbx lr'),True)
    # Move the last RW file extent forward if the appended RX payload needs
    # more than its original alignment padding. Virtual addresses stay fixed.
    payload_at=code['p_offset']+start-code['p_vaddr']
    payload_end=payload_at+len(payload)
    if start+len(payload)>=rw['p_vaddr']:raise ValueError('Code would overlap RW virtual extent')
    if any(native[code['p_offset']+code['p_filesz']:rw['p_offset']]):raise ValueError('Nonempty original RX alignment padding')
    new_rw=max(rw['p_offset'],(payload_end+4095)&~4095)
    shift=new_rw-rw['p_offset']
    result=bytearray(native[:rw['p_offset']]+bytes(shift)+native[rw['p_offset']:])
    result[payload_at:payload_end]=payload
    state_at=new_rw+runtime-rw['p_vaddr']
    old_end=new_rw+rw['p_filesz']
    addition=state_at+state_size-old_end
    result[old_end:old_end]=bytes(addition)
    result[state_at:state_at+state_size]=state_data
    for site,value in changes.items():
        at=file_offset(elf,site);result[at:at+4]=value
    ph=elf['e_phoff'];stride=elf['e_phentsize']
    struct.pack_into('<II',result,ph+ci*stride+16,start-code['p_vaddr']+len(payload),start-code['p_vaddr']+len(payload))
    struct.pack_into('<I',result,ph+ri*stride+4,new_rw)
    struct.pack_into('<II',result,ph+ri*stride+16,runtime-rw['p_vaddr']+state_size,runtime-rw['p_vaddr']+state_size)
    shoff=elf['e_shoff']
    new_shoff=shoff+(shift if shoff>=rw['p_offset'] else 0)+(addition if shoff>=rw['p_offset']+rw['p_filesz'] else 0)
    struct.pack_into('<I',result,32,new_shoff)
    for i,sec in enumerate(elf.iter_sections()):
        off=sec['sh_offset']
        delta=(shift if off>=rw['p_offset'] else 0)+(addition if off>=rw['p_offset']+rw['p_filesz'] else 0)
        if delta:struct.pack_into('<I',result,new_shoff+i*elf['e_shentsize']+16,off+delta)
    report=dict(source_sha256=hashlib.sha256(native).hexdigest(),sha256=hashlib.sha256(result).hexdigest(),symbols={n:v for n,v in symbols.items() if n.startswith('asterView') or n=='desktopInput'},hooks=records,payload_address=start,payload_size=len(payload),state_address=runtime,state_size=state_size,old_hooks=old,native_world_matrix=True,application_scale_unchanged=True,runtime_accepted=False)
    (output/'libSrc-view-angle.so').write_bytes(result)
    (output/'view-angle-patch.json').write_text(json.dumps(report,indent=2)+'\n')
    return bytes(result),report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('native','ndk','output'):p.add_argument(name,type=Path)
    a=p.parse_args();patch(a.native.read_bytes(),a.ndk,a.output)
