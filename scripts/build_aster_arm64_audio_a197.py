"""Package the tutorial fixes for ARM32 or replace the ARM64 audio host."""
import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from aster_release_apk import manifest_version, pack_apk

HOST = 'lib/arm64-v8a/libSrc.so'
A196_HOST_HASH = 'b19649f8d0eb1f4d32e0db092fdc12121f47943d5d7fa8f0a97620be85dab253'
A197_HOST_HASH = 'b64a72b11ed81c552929b648e90b990ee1c7b4e434d08fd69c2dc59b1d162f06'
ENGINE_HASH = '1443c8421ab9c8b795fb513e16019613af270a6b1aca176d3e8e4a3d8d2d6f74'


def build(base, host, output, sdk, signing, arm32=False, from_release=False):
    if arm32 == bool(host):
        raise ValueError('ARM64 requires a host library; omit it for --arm32')
    engine = 'lib/armeabi/libSrc.so' if arm32 else 'assets/guest_libs/libSrc_a32.so'
    with ZipFile(base) as source:
        if (sha256(source.read(engine)).hexdigest() != ENGINE_HASH or
                any(f'assets/pvz2data.zip.{part:03d}' not in source.namelist() for part in (1, 2, 3))):
            raise ValueError('Expected the complete Aster tutorial-fixed base APK')
        manifest = source.read('AndroidManifest.xml')
        if from_release:
            # Check both the release version name and code, keeping the original manifest.
            manifest_version(manifest, 198, 197, prefix='A')
            changes = {}
        else:
            changes = {'AndroidManifest.xml': manifest_version(manifest, 197, 196, prefix='A')}
        if host:
            expected = A197_HOST_HASH if from_release else A196_HOST_HASH
            if sha256(source.read(HOST)).hexdigest() != expected:
                raise ValueError('Unknown ARM64 host in base APK')
            native = host.read_bytes()
            if (native[:6] != b'\x7fELF\x02\x01' or native[18:20] != b'\xb7\x00'
                    or sha256(native).hexdigest() == A196_HOST_HASH
                    or any(tag in native for tag in (b'AsterSem\0', b'AsterAudioIO\0'))):
                raise ValueError('Expected a rebuilt AArch64 game host without test instrumentation')
            changes[HOST] = native
    output.parent.mkdir(parents=True, exist_ok=True)
    pack_apk(base, changes, sdk, output, signing)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm32', action='store_true', help='package ARM32 without an ARM64 host')
    parser.add_argument('--from-release', action='store_true', help='use the public A197 APK as the base')
    parser.add_argument('base', type=Path)
    parser.add_argument('host', type=Path, nargs='?')
    for name in ('output', 'sdk', 'signing'):
        parser.add_argument(name, type=Path)
    build(**vars(parser.parse_args()))
