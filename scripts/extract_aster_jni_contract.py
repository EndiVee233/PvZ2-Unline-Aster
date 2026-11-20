"""Generate the native host's JNI declarations from an Aster release APK."""
import argparse
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from build_aster_arm64_game import contract_source


def extract(apk, apktool, output):
    declarations = {}
    # classes3 through classes7 carry compressed resource payloads.
    executable_dex = ('classes.dex', 'classes2.dex', 'classes8.dex', 'classes9.dex',
                      'classes10.dex', 'classes11.dex')
    with TemporaryDirectory() as directory, ZipFile(apk) as archive:
        temp = Path(directory)
        repair = Path(__file__).with_name('RepairDex.java')
        subprocess.run(['javac', '-cp', apktool, '-d', temp, repair], check=True)
        classpath = os.pathsep.join((str(apktool.resolve()), str(temp)))
        for name in executable_dex:
            if name not in archive.namelist():
                continue
            dex = temp / name
            dex.write_bytes(archive.read(name))
            smali = dex.with_suffix('')
            subprocess.run(['java', '-Xmx512m', '-cp', classpath, 'RepairDex', 'decode',
                            dex, smali], check=True)
            for file in (smali / 'com/popcap').rglob('*.smali'):
                source = file.read_text(encoding='utf8')
                owner = re.search(r'^\.class (?:.* )?L([^;]+);$', source, re.M)
                if not owner:
                    raise ValueError(f'Invalid class declaration in {file.name}')
                methods = []
                for line in re.findall(r'^\.method .+$', source, re.M):
                    if ' native ' in line:
                        method, signature = line.rsplit(' ', 1)[-1].split('(', 1)
                        methods.append((method, '(' + signature, ' static ' in line))
                if methods:
                    if owner[1] in declarations:
                        raise ValueError(f'Duplicate class: {owner[1]}')
                    declarations[owner[1]] = methods
    main = 'com/popcap/SexyAppFramework/AndroidGameApp'
    if len(declarations.get(main, [])) < 10:
        raise ValueError('Missing Aster game native declarations')
    owners = sorted(declarations.items(), key=lambda item: (item[0] != main, item[0]))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'aster_jni_contract.inc').write_text(contract_source(owners), encoding='utf8')
    print(f'{len(owners)} classes, {sum(len(methods) for _, methods in owners)} native methods')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('apk', 'apktool', 'output'):
        parser.add_argument(name, type=Path)
    extract(**vars(parser.parse_args()))
