"""Keep the original Egyptian surface and guard the optional front-lawn draw."""
import argparse
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


ENGINE = "b06de0e39571bc93e12e8d124aa24b10d0db9d42979d9fc83afde220fea0d599"
DRAW_SITE = 0x8f6d80
DRAW_IMAGE = 0x11694c8
APP_SLOT = 0x1821674
EGYPT_LEVEL = "egypt_dangerroom"


def patch(engine):
    if sha256(engine).hexdigest() != ENGINE:
        raise ValueError("Expected the A205 guest engine")
    elf = ELFFile(BytesIO(engine))
    loads = [(index, item) for index, item in enumerate(elf.iter_segments()) if item["p_type"] == "PT_LOAD"]
    (index, rx), (_, rw) = loads[-2:]
    if rx["p_flags"] != 5 or rw["p_flags"] != 6 or rx["p_filesz"] != rx["p_memsz"]:
        raise ValueError("Unexpected guest payload segments")
    used = (rx["p_filesz"] + 15) & ~15
    start = rx["p_vaddr"] + used
    # This call site is specific to IMAGE_BACKGROUNDS_FRONTLAWN_ROW_05.
    # A cached image from an earlier board can still exist, so check the level too.
    code = f"""
        cmp r1, #0
        bxeq lr
        push {{r0-r4,lr}}
        adr r4, app_slot_offset
        ldr ip, [r4]
        ldr ip, [r4, ip]
        cmp ip, #0
        beq draw
        ldr ip, [ip]
        cmp ip, #0
        beq draw
        ldr ip, [ip, #0x6bc]
        cmp ip, #0
        beq draw
        ldr r0, [ip, #0xc4]
        cmp r0, #0
        beq draw
        adr r2, egypt_level
    compare_name:
        ldrb r3, [r0], #1
        ldrb r4, [r2], #1
        cmp r3, r4
        bne draw
        cmp r3, #0
        bne compare_name
        pop {{r0-r4,pc}}
    draw:
        pop {{r0-r4,lr}}
        b #{DRAW_IMAGE}
    app_slot_offset:
        .word 0
    egypt_level:
        .asciz "{EGYPT_LEVEL}"
    """
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    payload = bytearray(assembler.asm(code, start)[0])
    anchor = len(payload) - len(EGYPT_LEVEL) - 5
    struct.pack_into("<i", payload, anchor, APP_SLOT - start - anchor)
    physical = rx["p_offset"] + used
    end = physical + len(payload)
    site = file_offset(elf, DRAW_SITE, 4)
    if engine[site:site + 4] != branch(DRAW_SITE, DRAW_IMAGE, True):
        raise ValueError("Expected the original optional image draw")
    if end > rw["p_offset"] or any(engine[physical:end]):
        raise ValueError("Insufficient free executable space in the guest")
    updated = bytearray(engine)
    updated[site:site + 4] = branch(DRAW_SITE, start, True)
    updated[physical:end] = payload
    header = elf["e_phoff"] + index * elf["e_phentsize"] + 16
    struct.pack_into("<II", updated, header, used + len(payload), used + len(payload))
    return bytes(updated)


def build(base, output, sdk, jdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(jdk / "bin") + os.pathsep + os.environ["PATH"]
    reference = None
    for abi, member in (("ARM32", "lib/armeabi/libSrc.so"), ("ARM64", "assets/guest_libs/libSrc_a32.so")):
        source = base / f"PvZ2-Unline-Aster-A205-{abi}.apk"
        with ZipFile(source) as apk:
            engine = apk.read(member)
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 206, 205, prefix="A")
        if reference is None:
            reference = engine
            updated = patch(engine)
        elif engine != reference:
            raise ValueError("ARM64 guest engine differs from ARM32")
        final = output / f"PvZ2-Unline-Aster-A206-{abi}.apk"
        pack_apk(source, {member: updated, "AndroidManifest.xml": manifest}, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "jdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
