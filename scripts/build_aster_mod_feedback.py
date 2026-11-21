"""Build the shared Aster local-resource, plant upgrade and PvP audio update."""
import argparse
from copy import copy
import os
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile

from build_aster_arm64_game import retarget_arm64_guest_loads
from build_aster_hud_pickup import (
    BASELINE, PREFIX, REFERENCE, ROOT, Bundle, ResourceZip, copy_compressed_entry,
    group_index, manifest_group, relocate_prefetch, split_archive,
)
from build_aster_pvp_feedback import catalogue_dex, pack_apk
from build_aster_rgba_background_pilot import compile_pilot_dex
from build_aster_save_path_fix import manifest_version


FRAMEWORK = 'Lcom/popcap/SexyAppFramework/AndroidGameApp;'
ACTIVITY = 'Lcom/popcap/SexyAppFramework/SexyAppFrameworkActivity;'
LOCAL = 'Lcom/popcap/pvz2cthd/AsterLocalFiles;'
UPGRADE = 'UI_LevelUp_1536'
UIACTIVE = 'uiactive.rsb.smf'


def unpack_dex(original, output):
    output.mkdir(exist_ok=True)
    apktool = ROOT.parent / 'tools/apktool.jar'
    subprocess.run(['javac', '-cp', apktool, '-d', output, ROOT / 'scripts/RepairDex.java'], check=True)
    repair = ['java', '-Xmx384m', '-cp', str(apktool) + os.pathsep + str(output), 'RepairDex']
    path, tree, result = output / 'original.dex', output / 'smali', output / 'classes.dex'
    path.write_bytes(original)
    subprocess.run([*repair, 'decode', path, tree], check=True)
    return repair, tree, result


def framework_dex(original, output):
    repair, tree, result = unpack_dex(original, output)
    game = tree / 'com/popcap/SexyAppFramework/AndroidGameApp.smali'
    smali = game.read_text(encoding='utf8')
    activity = f'    iget-object v0, p0, {FRAMEWORK}->mActivity:{ACTIVITY}'
    for name, signature, old_registers, new_registers, body in (
        ('Info', '(Ljava/lang/String;[J)Ljava/lang/String;', 6, 6, f"""
    invoke-static {{v0, p1, p2}}, {LOCAL}->assetInfo(Landroid/content/Context;Ljava/lang/String;[J)Ljava/lang/String;
    move-result-object v0
    if-eqz v0, :aster_bundled_asset
    return-object v0
"""),
        ('Size', '(Ljava/lang/String;)J', 4, 6, f"""
    invoke-static {{v0, p1}}, {LOCAL}->assetSize(Landroid/content/Context;Ljava/lang/String;)J
    move-result-wide v0
    const-wide/16 v2, -0x1
    cmp-long v2, v0, v2
    if-ltz v2, :aster_bundled_asset
    return-wide v0
"""),
    ):
        declaration = f'.method private Resources_GetAssetFile{name}{signature}\n    .registers '
        anchor = declaration + str(old_registers) + '\n'
        assert smali.count(anchor) == 1, name
        smali = smali.replace(anchor, declaration + str(new_registers) + '\n\n' +
                              activity + '\n' + body + '    :aster_bundled_asset\n')
    game.write_text(smali, encoding='utf8')
    subprocess.run([*repair, 'encode', tree, result], check=True)
    return result.read_bytes()


def arm64_pilot(original, output):
    repair, tree, result = unpack_dex(original, output)
    pilot = tree / 'com/popcap/pvz2cthd/AsterRgbaPilot.smali'
    smali = pilot.read_text(encoding='utf8')
    patched = retarget_arm64_guest_loads(smali)
    assert patched != smali
    pilot.write_text(patched, encoding='utf8')
    subprocess.run([*repair, 'encode', tree, result], check=True)
    return result.read_bytes()


def upgrade_atlas(base, donor):
    index = group_index(base, UPGRADE)
    donor_index = group_index(donor, UPGRADE)
    manifest_index, path, manifest = base.manifest()
    assets = manifest_group(manifest, UPGRADE)
    references = {item['id']: item for item in manifest_group(donor.manifest()[2], UPGRADE)}
    assert references.keys() == {item['id'] for item in assets}
    assert {name for name, _ in base.files(index)} == {name for name, _ in donor.files(donor_index)}
    count, first = struct.unpack_from('<II', base.infos[index], 196)
    donor_count, donor_first = struct.unpack_from('<II', donor.infos[donor_index], 196)
    assert count == donor_count
    assert base.h['ptxInfo_EachLength'] == donor.h['ptxInfo_EachLength']
    for position, original in enumerate(assets):
        reference = references[original['id']]
        assert reference['type'] == original['type']
        assets[position] = {**reference, 'slot': original['slot']}
    base.textures[first:first + count] = donor.textures[donor_first:donor_first + count]
    base.payloads[index] = donor.payloads[donor_index]
    base.sync_info(index)
    base.replace_manifest(manifest_index, path, manifest)
    return manifest


def rebuild_resources(source, reference, output, baseline, shim):
    archive_path = output / 'resources.zip'
    with ResourceZip(source) as stream, ZipFile(stream) as original, ZipFile(reference) as donor, \
            ZipFile(archive_path, 'w', allowZip64=False) as target:
        for entry in original.infolist():
            if entry.filename != PREFIX + UIACTIVE:
                copy_compressed_entry(original, entry, target)
                continue
            previous = Bundle(original.read(entry))
            base = Bundle(previous.data)
            manifest = upgrade_atlas(base, Bundle(donor.read(REFERENCE + UIACTIVE)))
            result = base.build()
            readback = Bundle(result)
            assert readback.manifest()[2] == manifest
            assert readback.payloads == base.payloads
            old = UIACTIVE.encode('ascii') + struct.pack('>I', entry.file_size)
            assert baseline.count(old) == 1 and len(result) != entry.file_size
            baseline = baseline.replace(old, UIACTIVE.encode('ascii') + struct.pack('>I', len(result)))
            shim, prefetches = relocate_prefetch(shim, previous, readback)
            target.writestr(copy(entry), result)
            print(f'{UIACTIVE}: {entry.file_size} -> {len(result)}, {prefetches} relocated cache rows',
                  flush=True)
    return split_archive(archive_path, output), baseline, shim


def build(args):
    args.output.mkdir(parents=True, exist_ok=True)
    sources = {abi: args.base / f'PvZ2-Unline-Aster-A243-{abi}.apk' for abi in ('ARM32', 'ARM64')}
    shims = {'ARM32': 'lib/armeabi/libRestart.so', 'ARM64': 'assets/guest_libs/libRestart_a32.so'}
    with ZipFile(sources['ARM32']) as arm32, ZipFile(sources['ARM64']) as arm64:
        baseline = arm32.read(BASELINE)
        shim = arm32.read(shims['ARM32'])
        assert shim == arm64.read(shims['ARM64'])
        assert baseline == arm64.read(BASELINE)
        for member in (f'assets/pvz2data.zip.00{i}' for i in (1, 2, 3)):
            assert arm32.getinfo(member).CRC == arm64.getinfo(member).CRC, member
    pilot = args.output / 'pilot'
    pilot.mkdir(exist_ok=True)
    local = compile_pilot_dex(pilot, args.sdk)
    parts, baseline, shim = rebuild_resources(sources['ARM32'], args.reference, args.output, baseline, shim)
    for abi, source in sources.items():
        with ZipFile(source) as apk:
            manifest = manifest_version(apk.read('AndroidManifest.xml'), 244, 243, prefix='A')
            framework = framework_dex(apk.read('classes.dex'), args.output / f'framework-{abi}')
            music = catalogue_dex(apk.read('classes6.dex'), args.sdk, args.output / f'music-{abi}',
                                  prefixes=('PvpMusic',))
        pilot_dex = local if abi == 'ARM32' else arm64_pilot(local, args.output / 'pilot-ARM64')
        final = args.output / f'PvZ2-Unline-Aster-A244-{abi}.apk'
        pack_apk(source, {**parts, BASELINE: baseline, shims[abi]: shim, 'AndroidManifest.xml': manifest,
                          'classes.dex': framework, 'classes6.dex': music, 'classes7.dex': pilot_dex},
                 args.sdk, final, args.signing)
        print(final, flush=True)
    for part in parts.values():
        part.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for parameter in ('base', 'reference', 'output', 'sdk', 'signing'):
        parser.add_argument('--' + parameter, type=Path, required=True)
    build(parser.parse_args())
