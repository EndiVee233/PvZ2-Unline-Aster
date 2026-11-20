"""Compile A195's PvP backend and place it in the matching A187 engine."""
from io import BytesIO
from pathlib import Path
import hashlib
import re
import struct
import subprocess

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from prepare_aster_pvp_runtime import file_offset


ROOT = Path(__file__).resolve().parents[1]
ENGINE = "78e8dbf5bab6d3ddd2afa9f1367773fb1b51ad3fec913b5f79b910614cf878ff"
BASELINE_CODE = 0x1a04410
NEW_CODE = 0x1a38000
NEW_STATE = 0x1b03000
BASELINE_FIXES = {
    0x1a0512c: 0xea00ad4f, 0x1a051d0: 0xeb00ac18, 0x1a05294: 0xea00ad4d,
    0x1a052bc: 0xea00ad45, 0x1a05474: 0xea00ad2b, 0x1a054c0: 0xea00ad1a,
    0x1a05650: 0xea00acb9, 0x1a05734: 0xea00ac91,
    0x1a111cc: 0x23a0600a, 0x1a112ac: 0xe3a0600a, 0x1a112b4: 0x3300600a,
    0x1a18380: 0x23a0a00a, 0x1a1838c: 0xe3a0a00a, 0x1a18394: 0x3300a00a,
    0x1a1db8c: 0xe3a00f4b, 0x1a1ff54: 0xe3a01f4b,
}


def compile_payload(sdk, source, headers, output, address, runtime, *, archived):
    output.mkdir(parents=True, exist_ok=True)
    compiler = sdk / 'ndk/27.0.12077973/toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    flags = re.findall(r"-D[A-Z_]+", (ROOT / 'scripts/build_pvp_v39.py').read_text(encoding='utf8')
                       .split("compiler=", 1)[1].split("subprocess.run([compiler,*flags,", 1)[0])
    flags = [flag for flag in dict.fromkeys(flags) if 'TEST' not in flag]
    common = [compiler, '--target=armv7a-linux-androideabi21', '-marm', '-Os', '-fPIC',
              '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fno-exceptions',
              '-fno-rtti', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
              '-I' + str(headers), *flags]
    inputs = ['offline-pvp/offline.cpp']
    if archived:
        inputs += ['profile-memory/selection.cpp', 'desktop-input/shortcuts.cpp',
                   'resource-index/retained_lookup.cpp']
    objects = []
    for name in inputs:
        obj = output / (Path(name).stem + '.o')
        extras = ['-DDESKTOP_PVP_SEEDS', '-DDESKTOP_EXTENDED_INPUT', '-DDESKTOP_ENDLESS_INPUT']
        subprocess.run([*common, *(extras if name.startswith('desktop-input/') else []),
                        '-c', source / name, '-o', obj], check=True)
        obj_elf = ELFFile(BytesIO(obj.read_bytes()))
        for section in obj_elf.iter_sections():
            if section['sh_type'] == 'SHT_REL' and 'exidx' not in section.name:
                if any(rel['r_info_type'] == 2 for rel in section.iter_relocations()):
                    raise ValueError(f'Absolute ARM relocation in {obj.name}')
        objects.append(obj)
    linker = output / 'flat.ld'
    linker.write_text(
        f'ENTRY(offlineGarden)\nSECTIONS {{ . = {address}; .payload : {{ *(.text.entry) *(.text*) *(.rodata*) }}'
        f' . = {runtime}; .runtime : {{ *(.data*) *(.bss*) *(COMMON) *(.got*) }}'
        ' /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) } }\n'
    )
    target = output / 'offline.elf'
    subprocess.run([*common, '-nostdlib', '-static', '-Wl,--no-undefined',
                    '-Wl,-T,' + str(linker), *objects, '-o', target], check=True)
    return target


def branch(at, to):
    offset = to - at - 8
    assert not offset % 4 and -0x2000000 <= offset < 0x2000000
    return struct.pack('<I', 0xea000000 | (offset // 4 & 0xffffff))


def function_symbols(elf):
    return {symbol.name: symbol['st_value'] for symbol in elf.get_section_by_name('.symtab').iter_symbols()
            if symbol['st_info']['type'] == 'STT_FUNC' and symbol['st_info']['bind'] == 'STB_GLOBAL'}


def patch_engine(engine, old, new):
    assert hashlib.sha256(engine).hexdigest() == ENGINE
    base = ELFFile(BytesIO(engine))
    legacy = ELFFile(BytesIO(old.read_bytes()))
    payload = legacy.get_section_by_name('.payload')
    start, size = payload['sh_addr'], payload['sh_size']
    assert start == BASELINE_CODE
    original = payload.data()
    offset = file_offset(base, start, size)
    verified = bytearray(original)
    for site, word in BASELINE_FIXES.items():
        struct.pack_into('<I', verified, site - start, word)
    assert engine[offset:offset + size] == verified, 'A187 baseline payload differs from archived source'
    rx_index, rx = next((i, s) for i, s in enumerate(base.iter_segments()) if s['p_vaddr'] == 0x1a00000)
    rw_index, rw = next((i, s) for i, s in enumerate(base.iter_segments()) if s['p_vaddr'] == 0x1b00000)

    installed = bytearray(engine[:rw['p_offset']])
    prior_state = engine[rw['p_offset']:]
    assert len(prior_state) == rw['p_filesz'] == rw['p_memsz']
    compiled = ELFFile(BytesIO(new.read_bytes()))
    relocated = compiled.get_section_by_name('.payload')
    state = compiled.get_section_by_name('.runtime')
    assert relocated['sh_addr'] == NEW_CODE and state['sh_addr'] == NEW_STATE
    new_entry = function_symbols(compiled)
    old_offline = ELFFile(BytesIO(old.with_name('offline.o').read_bytes()))
    old_entry = function_symbols(legacy)
    kept = set(BASELINE_FIXES).intersection(old_entry.values())
    moved = {}
    for name in function_symbols(old_offline):
        if name == 'offlineNeighborRoll' or name.startswith('__aeabi_'):
            continue
        location = old_entry[name]
        if location in kept:
            continue
        if name not in new_entry:
            raise ValueError(f'Missing replacement entry for {name}')
        at = file_offset(base, location)
        installed[at:at + 4] = branch(location, new_entry[name])
        moved[name] = new_entry[name]

    native_hooks = [
        (0x7aaa70, 0xea4a0168, f'''
            push {{r0-r4, lr}}
            adr r0, here
            ldr r3, here
            sub r0, r0, r3
            bl #{new_entry['offlinePvpProfileSelected']}
            pop {{r0-r4, lr}}
            b #0x1a2b018
            here: .word 0
        '''),
        # Predicate already hit the stock chest rectangle and carries its 64-byte record.
        (0x101a034, 0xe59f44f8, f'''
            push {{r0-r4, lr}}
            mov r1, r6
            mov r2, r7
            adr r0, here
            ldr r3, here
            sub r0, r0, r3
            bl #{new_entry['offlineBusinessChest']}
            cmp r0, #0
            pop {{r0-r4, lr}}
            bne #0x10197b8
            ldr r4, old_literal
            b #0x101a038
            here: .word 0
            old_literal: .word {struct.unpack_from('<I', engine, 0x101a534)[0]}
        '''),
        # The common paged layout has already placed every visible card.
        (0x102dafc, 0xe24bd020, f'''
            push {{r0-r4, lr}}
            mov r1, r6
            adr r0, here
            ldr r3, here
            sub r0, r0, r3
            bl #{new_entry['offlineCenterPvpPlantBank']}
            pop {{r0-r4, lr}}
            sub sp, fp, #0x20
            b #0x102db00
            here: .word 0
        '''),
        # After the native scout widget has initialized its localized labels.
        (0x109a1a8, 0xe59070a8, f'''
            push {{r0-r4, lr}}
            mov r2, r0
            mov r1, r4
            adr r0, here
            ldr r3, here
            sub r0, r0, r3
            bl #{new_entry['offlineScoutRewards']}
            cmp r0, #0
            pop {{r0-r4, lr}}
            bne #0x109a1c0
            ldr r7, [r0, #0xa8]
            b #0x109a1ac
            here: .word 0
        '''),
        # Select the native trophy image before measuring and drawing it.
        (0x109b0d0, 0xe2899068, '''
            add r9, r9, #104
            ldrb ip, [r5, #0xef]
            cmp ip, #1
            bne #0x109b0d4
            adr ip, here
            ldr r9, here
            sub ip, ip, r9
            ldr r9, trophy
            add r9, r9, ip
            b #0x109b0d4
            trophy: .word 0x18a5448
            here: .word 0
        '''),
        # Tutorial's forced card selection bypasses the regular card gate.
        (0x10a647c, 0xe1c424d0, f'''
            push {{r0-r4, lr}}
            bl #0x11d74b4
            mov r1, r5
            bl #0x1da034
            mov r1, r0
            adr r0, here
            ldr r3, here
            sub r0, r0, r3
            bl #{new_entry['offlineTutorialSkillAllowed']}
            cmp r0, #0
            pop {{r0-r4, lr}}
            beq #0x10a6444
            ldrd r2, r3, [r4, #64]
            b #0x10a6480
            here: .word 0
        '''),
        # Recheck at release before either native placement path can run.
        (0x4e5e3c, 0xe5953000, f'''
            push {{r0-r4, lr}}
            mov r1, r5
            adr r0, here
            ldr r3, here
            sub r0, r0, r3
            bl #{new_entry['offlineTutorialSkillAllowed']}
            cmp r0, #0
            pop {{r0-r4, lr}}
            beq #0x4e5d78
            ldr r3, [r5]
            b #0x4e5e40
            here: .word 0
        '''),
    ]
    for site, expected, source_register in ((0x11fbf10, 0xebfcc653, 'r7'),
                                            (0x1326230, 0xebf81d8b, 'r5')):
        native_hooks.append((site, expected, f'''
            push {{r0-r4, lr}}
            mov r3, r2
            mov r2, r1
            mov r1, r0
            adr r0, here
            ldr ip, here
            sub r0, r0, ip
            bl #{new_entry['offlineAdoptLargeFile']}
            cmp r0, #0
            pop {{r0-r4, lr}}
            movne {source_register}, #0
            bne #{site+4}
            bl #0x112d864
            b #{site+4}
            here: .word 0
        '''))
    new_file = rx['p_offset'] + NEW_CODE - rx['p_vaddr']
    installed.extend(bytes(new_file - len(installed)))
    installed.extend(relocated.data())
    while len(installed) % 4:
        installed.append(0)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    for site, expected, assembly in native_hooks:
        assert struct.unpack_from('<I', engine, site)[0] == expected, hex(site)
        target = rx['p_vaddr'] + len(installed) - rx['p_offset']
        if 'here: .word 0' in assembly:
            probe = assembler.asm(assembly, target)[0]
            trailing_words = 2 if site == 0x101a034 else 1
            literal = target + len(probe) - 4*trailing_words
            assembly = assembly.replace('here: .word 0', f'here: .word {literal}')
        installed.extend(bytes(assembler.asm(assembly, target)[0]))
        installed[site:site + 4] = branch(site, target)

    used = len(installed) - rx['p_offset']
    installed.extend(bytes((-len(installed)) % 4096))
    state_offset = len(installed)
    installed.extend(prior_state)
    installed.extend(bytes(NEW_STATE - rw['p_vaddr'] - len(prior_state)))
    installed.extend(state.data())
    rw_size = len(installed) - state_offset
    ph = base.header.e_phoff
    struct.pack_into('<II', installed, ph + rx_index * 32 + 16, used, used)
    struct.pack_into('<I', installed, ph + rw_index * 32 + 4, state_offset)
    struct.pack_into('<II', installed, ph + rw_index * 32 + 16, rw_size, rw_size)
    # MuMu Android 12's ARM32 translator rejects a PT_LOAD ending exactly at
    # EOF. Keep a padding byte outside the mapping (including p_memsz).
    installed.append(0)
    check = ELFFile(BytesIO(installed))
    assert all(s['p_offset'] + s['p_filesz'] < len(installed)
               for s in check.iter_segments() if s['p_type'] == 'PT_LOAD')
    assert installed[file_offset(check, NEW_CODE, len(relocated.data())):][:len(relocated.data())] == relocated.data()
    assert installed[file_offset(check, NEW_STATE, len(state.data())):][:len(state.data())] == state.data()
    return bytes(installed), moved
