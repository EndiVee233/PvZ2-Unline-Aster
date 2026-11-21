"""Build the PvP feedback candidate for ARM32 and the ARM64 guest bridge."""
from pathlib import Path
from zipfile import ZipFile
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess

from build_aster_arm64_game import ROOT, copy_compressed_entry, retarget_arm64_guest_loads
from build_aster_save_path_fix import manifest_version
from rebuild_bootstrap_dex import rebuild_bootstrap


DYNAMIC = 'assets/reconstruction/dynamic-original-speed.rsb.smf'
PLAN = 'assets/reconstruction/aster-dynamic-rgba.plan'
CATALOGUE = 'assets/pvp-presets/catalogue.json'
A188_DYNAMIC_SHA256 = '4e570ad7e843f7a7c0caa08c9c2eccd45303cdcc2a4f1e034dcb4ccb5ae36805'
JAVA_PREFIX = Path('com/popcap/pvz2cthd')
FILE_PREFIXES = ('GithubPresetCatalog', 'PvpLevelStorage')
JAVA_FILES = ('PvpPresetDocument', 'PvpLevelStorage', 'PresetEditor', 'GithubPresetCatalog',
              'PvpMusic', 'GateUnlockAudio', 'SpeedFeedback', 'ReleaseUpdater')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def catalogue_dex(original, sdk, output):
    output.mkdir(exist_ok=True)
    source = ROOT / 'src/bootstrap-extra' / JAVA_PREFIX
    android = sdk / 'platforms/android-34/android.jar'
    classes, dex = output / 'classes', output / 'compiled'
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    jar = output / 'compiled.jar'
    subprocess.run(['javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8',
                    '-classpath', android, '-d', classes,
                    *(source / (name + '.java') for name in JAVA_FILES)], check=True)
    with ZipFile(jar, 'w') as archive:
        for item in classes.rglob('*.class'):
            archive.write(item, item.relative_to(classes).as_posix())
    subprocess.run(['java', '-Xmx384m', '-cp', sdk / 'build-tools/34.0.0/lib/d8.jar',
                    'com.android.tools.r8.D8', '--min-api', '24', '--lib', android,
                    '--output', dex, jar], check=True)
    apktool = ROOT.parent / 'tools/apktool.jar'
    subprocess.run(['javac', '-cp', apktool, '-d', output, ROOT / 'scripts/RepairDex.java'], check=True)
    repair = ['java', '-Xmx384m', '-cp', str(apktool) + os.pathsep + str(output), 'RepairDex']
    original_path = output / 'original.dex'
    original_path.write_bytes(original)
    old_tree, new_tree = output / 'old-smali', output / 'new-smali'
    subprocess.run([*repair, 'decode', original_path, old_tree], check=True)
    subprocess.run([*repair, 'decode', dex / 'classes.dex', new_tree], check=True)
    for prefix in FILE_PREFIXES:
        original_types = list((old_tree / JAVA_PREFIX).glob(prefix + '*.smali'))
        replacement_types = list((new_tree / JAVA_PREFIX).glob(prefix + '*.smali'))
        if not original_types or not replacement_types:
            raise ValueError(f'Missing DEX types for {prefix}')
        for item in original_types:
            item.unlink()
        for item in replacement_types:
            (old_tree / JAVA_PREFIX / item.name).write_bytes(item.read_bytes())
    rebuilt = output / 'classes10.dex'
    subprocess.run([*repair, 'encode', old_tree, rebuilt], check=True)
    return rebuilt.read_bytes()


def bootstrap_dex(original, prior, dynamic, output):
    before, after = sha(prior), sha(dynamic)
    marker = '.method private static isSupportedResourcePredecessor(Ljava/lang/String;)Z\n    .registers 2'
    extra = ''.join(f'''
    const-string v0, "{digest}"
    invoke-virtual {{v0, p0}}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :feedback_old_dynamic_{index}
    const/4 v0, 0x1
    return v0
    :feedback_old_dynamic_{index}'''
                    for index, digest in enumerate((before, A188_DYNAMIC_SHA256)))
    replacements = {
        before: after,
        marker: marker + extra,
        '.offline-pvp-balance-A186-' + before[:12]: '.offline-pvp-review-' + after[:12],
    }
    if len(prior) != len(dynamic):
        replacements[hex(len(prior))] = hex(len(dynamic))
    return rebuild_bootstrap(original, output, replacements, ROOT.parent / 'tools/apktool.jar')


def arm64_bootstrap_dex(original, output):
    output.mkdir(parents=True, exist_ok=True)
    apktool = ROOT.parent / 'tools/apktool.jar'
    subprocess.run(['javac', '-cp', apktool, '-d', output, ROOT / 'scripts/RepairDex.java'], check=True)
    repair = ['java', '-Xmx384m', '-cp', str(apktool) + os.pathsep + str(output), 'RepairDex']
    input_dex = output / 'original.dex'
    input_dex.write_bytes(original)
    tree = output / 'smali'
    subprocess.run([*repair, 'decode', input_dex, tree], check=True)
    warmup = tree / JAVA_PREFIX / 'AsterNativeWarmup$1.smali'
    smali = warmup.read_text(encoding='utf8')
    if 'Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V' not in smali:
        raise ValueError('Bootstrap native preload is missing')
    updated = retarget_arm64_guest_loads(smali)
    if updated == smali:
        return original
    warmup.write_text(updated, encoding='utf8')
    target = output / 'classes8.dex'
    subprocess.run([*repair, 'encode', tree, target], check=True)
    return target.read_bytes()


def build_one(apk, common, native, sdk, output, signing, input_digests, version):
    from prepare_aster_pvp_feedback import ENGINE
    with ZipFile(apk) as source:
        arm64 = 'assets/guest_libs/libSrc_a32.so' in source.namelist()
        architecture = 'ARM64' if arm64 else 'ARM32'
        engine = 'assets/guest_libs/libSrc_a32.so' if arm64 else 'lib/armeabi/libSrc.so'
        assert sha(source.read(engine)) == ENGINE
        for member, digest in input_digests.items():
            assert sha(source.read(member)) == digest, member
        manifest = source.read('AndroidManifest.xml')
        old, intermediate = (label.encode('utf-16le') for label in
                             ('1.7.5-Unline-Aster-A187', '1.7.5-Unline-Aster-v187'))
        assert manifest.count(old) == 1
        manifest = manifest_version(manifest.replace(old, intermediate), version, 187).replace(
            f'1.7.5-Unline-Aster-v{version}'.encode('utf-16le'),
            f'1.7.5-Unline-Aster-A{version}'.encode('utf-16le'))
        replacements = {**common, engine: native, 'AndroidManifest.xml': manifest}
        if arm64:
            replacements['classes8.dex'] = arm64_bootstrap_dex(
                replacements['classes8.dex'], output / 'arm64-loader')
    final = output / f'PvZ2-Unline-Aster-A{version}-{architecture}.apk'
    pack_apk(apk, replacements, sdk, final, signing)
    with final.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    info = {'version': f'A{version}', 'architecture': architecture, 'version_code': 1000 + version,
            'apk_sha256': digest, 'engine_sha256': sha(native), 'runtime_accepted': False}
    (output / f'A{version}-{architecture}-build.json').write_text(json.dumps(info, indent=2) + '\n')
    print(final, digest, flush=True)


def pack_apk(apk, replacements, sdk, final, signing, *, extra_entries=None, excluded=()):
    unsigned = final.with_suffix('.unsigned.apk')
    aligned = final.with_suffix('.aligned.apk')
    assert apk.resolve() not in (unsigned.resolve(), aligned.resolve(), final.resolve())
    extra_entries = extra_entries or {}
    excluded = set(excluded)
    with ZipFile(apk) as source:
        assert not extra_entries.keys() & (set(source.namelist()) | replacements.keys())
        assert excluded <= set(source.namelist()) and not excluded & replacements.keys()
        with ZipFile(unsigned, 'w') as target:
            for item in source.infolist():
                if item.filename in excluded:
                    continue
                if re.fullmatch(r'META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))', item.filename, re.I):
                    continue
                if item.filename in replacements:
                    replacement = replacements[item.filename]
                    if isinstance(replacement, Path):
                        with replacement.open("rb") as src, target.open(item, "w") as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                    else:
                        target.writestr(item, replacement)
                else:
                    copy_compressed_entry(source, item, target)
            for name, data in extra_entries.items():
                target.writestr(name, data)
    tools = sdk / 'build-tools/34.0.0'
    signer = ['java', '-jar', tools / 'lib/apksigner.jar']
    key = json.loads(signing.read_text(encoding='utf8'))
    subprocess.run([tools / 'zipalign.exe', '-p', '-f', '4', unsigned, aligned], check=True)
    unsigned.unlink()
    subprocess.run([*signer, 'sign', '--ks', key['keystore'], '--ks-key-alias', key['alias'],
                    '--ks-pass', 'env:ASTER_SIGN_PASS', '--key-pass', 'env:ASTER_SIGN_PASS',
                    '--out', final, aligned], env=dict(os.environ, ASTER_SIGN_PASS=key['password']), check=True)
    subprocess.run([*signer, 'verify', final], check=True)
    subprocess.run([tools / 'zipalign.exe', '-c', '4', final], check=True)
    with ZipFile(apk) as source, ZipFile(final) as target:
        assert not excluded.intersection(target.namelist())
        for item in source.infolist():
            if item.filename not in replacements and item.filename not in excluded and not item.filename.startswith('META-INF/'):
                assert item.CRC == target.getinfo(item.filename).CRC, item.filename
        for name, data in (replacements | extra_entries).items():
            if isinstance(data, Path):
                with data.open("rb") as src, target.open(name) as dst:
                    assert hashlib.file_digest(src, "sha256").digest() == hashlib.file_digest(dst, "sha256").digest(), name
            else:
                assert target.read(name) == data, name
    aligned.unlink()


def build(arm32, arm64, sdk, baseline, output, signing, version):
    from build_aster_rgba_background_pilot import create_plan
    from prepare_aster_pvp_feedback import prepare
    patched = output / 'patched'
    _, prior = prepare(arm32, sdk, baseline, patched)
    native = (patched / 'libSrc.so').read_bytes()
    dynamic = (patched / 'dynamic.rsb.smf').read_bytes()
    with ZipFile(arm32) as source:
        bootstrap = source.read('classes8.dex')
        catalogue = source.read('classes10.dex')
    plan = create_plan(dynamic, patched)
    assert plan[:4] == b'ABG1' and plan[12:44] == bytes.fromhex(sha(dynamic))
    common = {DYNAMIC: dynamic, PLAN: plan, CATALOGUE: (patched / 'catalogue.json').read_bytes(),
              'classes8.dex': bootstrap_dex(bootstrap, prior, dynamic, patched / 'bootstrap')}
    for architecture, apk in (('ARM32', arm32), ('ARM64', arm64)):
        with ZipFile(apk) as source:
            catalogue = source.read('classes10.dex')
        common['classes10.dex'] = catalogue_dex(catalogue, sdk, patched / f'java-{architecture}')
        build_one(apk, common, native, sdk, output, signing,
                  {DYNAMIC: sha(prior), 'classes8.dex': sha(bootstrap), 'classes10.dex': sha(catalogue)},
                  version)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('arm32', 'arm64', 'sdk', 'baseline', 'output', 'signing'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--version', type=int, default=190)
    build(**vars(parser.parse_args()))
