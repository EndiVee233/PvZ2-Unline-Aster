"""Build the PvP review fixes on the published A190 APKs."""
import json
from pathlib import Path
from shutil import copytree
from zipfile import ZipFile
from io import BytesIO

from build_aster_pvp_feedback import manifest_version, pack_apk, sha
from prepare_aster_pvp_feedback import ROOT, NEW_CODE, NEW_STATE, compile_payload, patch_engine
from build_preset_importer import build as build_importer
from prepare_offline_economy import cipher, RTONDecoder

VERSION = 195


def profile_template(apk, generated):
    with ZipFile(apk) as archive:
        encrypted = archive.read('assets/pvz2tool/saves/save_1/pp.dat')
    assert sha(encrypted) == 'ee08d895f7fb56670f8cb834896e6c90d8f67ab37a28f7404dd35425ae73b0c6'
    raw = cipher.decrypt(encrypted[2:]).rstrip(b'\x00')
    assert raw[:4] == b'RTON' and raw.endswith(b'DONE')
    stream = BytesIO(raw[4:])
    stream.name = 'public-all-one'
    player, = json.loads(RTONDecoder(repairFiles=False).parse_root_object(stream))['objects']
    data = player['objdata']
    assert player['objclass'] == 'PlayerInfo' and data['i'] == 1722523140
    assert len(set(data['p'])) == 109 and {v['icpi'] for v in data['psla'] if v['icl'] == 1} == set(data['p'])
    lines = [','.join(str(n) for n in raw[i:i+32])+',' for i in range(0,len(raw),32)]
    (generated / 'all_one_template.h').write_text(
        'alignas(4) static constexpr unsigned char allOneRton[]={\n'+'\n'.join(lines)+'\n};\n')


def build():
    sdk = Path('Y:/Android/Sdk')
    feedback = ROOT / 'work/feedback'
    baseline = feedback / 'A190/patched'
    output = feedback / f'A{VERSION}'
    patched = output / 'patched'
    patched.mkdir(parents=True, exist_ok=True)
    generated = patched / 'generated'
    copytree(baseline / 'generated', generated, dirs_exist_ok=True)
    profile_template(feedback / 'A190/PvZ2-Unline-Aster-A190-ARM32.apk', generated)
    migration = build_importer(output / 'profile-migration')
    compiled = compile_payload(sdk, ROOT / 'src', generated, patched / 'new',
                               NEW_CODE, NEW_STATE, archived=False)
    with ZipFile(ROOT / 'work/balance/A187/PvZ2-Unline-Aster-A187-ARM32.apk') as source:
        native, moved = patch_engine(source.read('lib/armeabi/libSrc.so'),
                                     baseline / 'baseline/offline.elf', compiled)
    (patched / 'libSrc.so').write_bytes(native)
    (patched / 'offline.elf').write_bytes(compiled.read_bytes())
    (patched / 'catalogue.json').write_bytes((baseline / 'catalogue.json').read_bytes())
    (patched / 'engine.json').write_text(json.dumps({'entry_points': moved}, indent=2) + '\n')

    signing = ROOT.parent / 'APK签名数据/aster/signing-private.json'
    targets = (
        ('ARM32', feedback / 'A190', 'lib/armeabi/libSrc.so'),
        ('ARM64', feedback / 'A190/arm64-startup-fix/heap-fix', 'assets/guest_libs/libSrc_a32.so'),
    )
    for architecture, directory, engine in targets:
        apk = directory / f'PvZ2-Unline-Aster-A190-{architecture}.apk'
        with ZipFile(apk) as source:
            assert sha(source.read(engine)) == 'ec31ac99ed7e33e722b49b0aff43ec0943bd8c9fb4f8e58904eecd7cc87acb05'
            if architecture == 'ARM64':
                assert source.read('lib/arm64-v8a/libSrc.so') == (directory / 'libSrc.so').read_bytes()
            manifest = source.read('AndroidManifest.xml')
            assert sha(source.read('classes9.dex')).startswith('0b316b9a9b00')
        old, legacy, next_legacy, new = (f'1.7.5-Unline-Aster-{suffix}'.encode('utf-16le')
                                         for suffix in ('A190', 'v190', f'v{VERSION}', f'A{VERSION}'))
        manifest = manifest_version(manifest.replace(old, legacy), VERSION, 190).replace(next_legacy, new)
        final = output / f'PvZ2-Unline-Aster-A{VERSION}-{architecture}.apk'
        pack_apk(apk, {engine: native, 'AndroidManifest.xml': manifest, 'classes9.dex': migration},
                 sdk, final, signing)
        print(final, flush=True)


if __name__ == '__main__':
    build()
