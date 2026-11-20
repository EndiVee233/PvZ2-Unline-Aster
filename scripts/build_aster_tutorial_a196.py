"""Build signed A196 candidates from the original A195 packages."""
import argparse
from hashlib import sha256
from pathlib import Path
import struct
from zipfile import ZipFile

from aster_release_apk import manifest_version, pack_apk

ENGINE = '0b4db4f66e178cb878237d1aec0077a10e9bf210f3624a2c847523dde279338b'
HOST = '686540cfb1a6676668b184ed53ecbd2962297c6e1fc75fd46e677b3fb928b6d3'
# Terminal / informational reminders. Style 1 uses the same board banner as
# style 2, with the native five-second lifetime. Interactive prompts keep style 2.
REMINDERS = {
    0x963F04: 'Tutorial1 ADVICE_ZOMBIE_ONSLAUGHT',
    0x968330: 'Tutorial2 ADVICE_PLANT_SUNFLOWER4',
    0x96845C: 'Tutorial2 ADVICE_MORE_SUNFLOWERS',
    0x96C8B4: 'Tutorial3 ADVICE_DONE_DIGGING',
    0x96C9A0: 'Tutorial3 ADVICE_PLANT_SUNFLOWER4',
}


def patch_game(data):
    if sha256(data).hexdigest() != ENGINE:
        raise ValueError('Expected the shared A195 ARM32 engine')
    game = bytearray(data)

    def replace(address, old, new):
        if struct.unpack_from('<I', game, address)[0] != old:
            raise ValueError(f'Unexpected instruction at {address:#x}')
        struct.pack_into('<I', game, address, new)

    # The original skip-to-day-4 callback acquires an extra copy of the level
    # groups and sets a one-shot flag. The restored "play the tutorial" path
    # does no such acquire. Passing its old true flag into TutorialLevel4's
    # constructor made the module release the *live* board's references.
    replace(0x964BC4, 0xE3A01001, 0xE3A01000)
    for address in REMINDERS:
        replace(address, 0xE3A02002, 0xE3A02001)
    return bytes(game)


def manifest_a196(data):
    def label(version):
        return ('1.7.5-Unline-Aster-' + version).encode('utf-16le')

    if data.count(label('A195')) != 1:
        raise ValueError('Expected an A195 manifest')
    manifest = manifest_version(data.replace(label('A195'), label('v195')), 196, 195)
    return manifest.replace(label('v196'), label('A196'))


def build(base, output, sdk, signing, audio_host=None, architecture=None):
    output.mkdir(parents=True, exist_ok=True)
    architectures = (architecture,) if architecture else ('ARM64', 'ARM32')
    for arch in architectures:
        apk = base / f'PvZ2-Unline-Aster-A195-{arch}.apk'
        engine = 'assets/guest_libs/libSrc_a32.so' if arch == 'ARM64' else 'lib/armeabi/libSrc.so'
        with ZipFile(apk) as z:
            changes = {engine: patch_game(z.read(engine)),
                       'AndroidManifest.xml': manifest_a196(z.read('AndroidManifest.xml'))}
            if arch == 'ARM64':
                member = 'lib/arm64-v8a/libSrc.so'
                if sha256(z.read(member)).hexdigest() != HOST:
                    raise ValueError('Unexpected A195 audio host')
                if audio_host is None:
                    raise ValueError('Supply the rebuilt ARM64 OpenSL host for an ARM64 build')
                host = audio_host.read_bytes()
                if (len(host) < 20 or host[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', host, 18)[0] != 183
                        or b'First non-silent PCM buffer accepted' not in host):
                    raise ValueError('Expected the rebuilt Aster ARM64 OpenSL host')
                changes[member] = host
        target = output / f'PvZ2-Unline-Aster-A196-{arch}.apk'
        pack_apk(apk, changes, sdk, target, signing)
        print('Verified', target.name, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('base', 'output', 'sdk', 'signing'):
        p.add_argument(arg, type=Path)
    p.add_argument('audio_host', nargs='?', type=Path)
    p.add_argument('--architecture', choices=['ARM32', 'ARM64'])
    args = p.parse_args()
    build(**vars(args))
