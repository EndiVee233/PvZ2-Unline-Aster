"""Version and sign incremental Aster APKs with the caller's own key."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from build_aster_arm64_game import copy_compressed_entry
from build_aster_save_path_fix import manifest_version as _legacy_manifest_version


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest_version(data, build_number=164, old_build=163, prefix='v'):
    if prefix == 'v':
        return _legacy_manifest_version(data, build_number, old_build)

    def label(letter, number):
        return f'1.7.5-Unline-Aster-{letter}{number}'.encode('utf-16le')

    if len(prefix) != 1 or data.count(label(prefix, old_build)) != 1:
        raise ValueError(f'Expected {prefix}{old_build} manifest')
    legacy = data.replace(label(prefix, old_build), label('v', old_build))
    updated = _legacy_manifest_version(legacy, build_number, old_build)
    return updated.replace(label('v', build_number), label(prefix, build_number))


def pack_apk(apk, replacements, sdk, output, signing):
    if apk.resolve() == output.resolve():
        raise ValueError('Choose an output separate from the base APK')
    tools = sdk / 'build-tools/34.0.0'
    align = tools / ('zipalign.exe' if os.name == 'nt' else 'zipalign')
    signer = ['java', '-jar', tools / 'lib/apksigner.jar']
    key = json.loads(signing.read_text(encoding='utf8'))
    signature = re.compile(r'META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))', re.I)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as directory, ZipFile(apk) as source:
        temp = Path(directory)
        unsigned, aligned, signed = (temp / f'{name}.apk' for name in ('unsigned', 'aligned', 'signed'))
        missing = replacements.keys() - set(source.namelist())
        if missing:
            raise ValueError(f'Missing original APK entries: {sorted(missing)}')
        with ZipFile(unsigned, 'w') as target:
            for item in source.infolist():
                if signature.fullmatch(item.filename):
                    continue
                if item.filename in replacements:
                    target.writestr(item, replacements[item.filename])
                else:
                    copy_compressed_entry(source, item, target)
        subprocess.run([align, '-p', '-f', '4', unsigned, aligned], check=True)
        unsigned.unlink()
        subprocess.run([*signer, 'sign', '--ks', key['keystore'], '--ks-key-alias', key['alias'],
                        '--ks-pass', 'env:ASTER_SIGN_PASS', '--key-pass', 'env:ASTER_SIGN_PASS',
                        '--out', signed, aligned], env=dict(os.environ, ASTER_SIGN_PASS=key['password']),
                       check=True)
        subprocess.run([*signer, 'verify', signed], check=True)
        subprocess.run([align, '-c', '4', signed], check=True)
        with ZipFile(signed) as result:
            for item in source.infolist():
                if item.filename not in replacements and not signature.fullmatch(item.filename):
                    if item.CRC != result.getinfo(item.filename).CRC:
                        raise ValueError(f'Unexpected change in {item.filename}')
            for name, data in replacements.items():
                if result.read(name) != data:
                    raise ValueError(f'Replacement verification failed for {name}')
        signed.replace(output)
