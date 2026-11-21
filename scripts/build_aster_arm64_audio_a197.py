"""Package the corrected ARM64 host with the A196 game and resources."""
import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version

HOST = 'lib/arm64-v8a/libSrc.so'
A196_HOST_HASH = 'b19649f8d0eb1f4d32e0db092fdc12121f47943d5d7fa8f0a97620be85dab253'
A196_ENGINE_HASH = '1443c8421ab9c8b795fb513e16019613af270a6b1aca176d3e8e4a3d8d2d6f74'


def build(base, host, output, sdk, signing):
    with ZipFile(base) as source:
        if (sha256(source.read(HOST)).hexdigest() != A196_HOST_HASH
                or sha256(source.read('assets/guest_libs/libSrc_a32.so')).hexdigest() != A196_ENGINE_HASH
                or any(f'assets/pvz2data.zip.{part:03d}' not in source.namelist() for part in (1, 2, 3))):
            raise ValueError('Expected the complete A196 ARM64 base APK')
        manifest = manifest_version(source.read('AndroidManifest.xml'), 197, 196, prefix='A')
    native = host.read_bytes()
    if (native[:6] != b'\x7fELF\x02\x01' or native[18:20] != b'\xb7\x00'
            or sha256(native).hexdigest() == A196_HOST_HASH
            or any(tag in native for tag in (b'AsterSem\0', b'AsterAudioIO\0'))):
        raise ValueError('Expected the rebuilt AArch64 game host without test instrumentation')
    output.parent.mkdir(parents=True, exist_ok=True)
    pack_apk(base, {HOST: native, 'AndroidManifest.xml': manifest}, sdk, output, signing)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'host', 'output', 'sdk', 'signing'):
        parser.add_argument(name, type=Path)
    build(**vars(parser.parse_args()))
