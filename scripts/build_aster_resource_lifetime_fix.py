"""Keep resource groups alive until their queued reads have completed."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


ENGINE_SHA = "402ec0705606c9dac9e52c77363aa325e442158bea41444f27a86d2db40ae5a1"
FINALIZE_GROUP = 0x11CB754
NEXT_GROUP = 0x11CB81C


def retain_group_for_reads(engine):
    if sha256(engine).hexdigest() != ENGINE_SHA:
        raise ValueError("Expected the shared A341 engine")
    elf = ELFFile(BytesIO(engine))
    index, segment = [(i, s) for i, s in enumerate(elf.iter_segments())
                      if s["p_type"] == "PT_LOAD"][-1]
    if (segment["p_flags"] != 5 or segment["p_filesz"] != segment["p_memsz"]
            or segment["p_offset"] + segment["p_filesz"] != len(engine)):
        raise ValueError("Unexpected engine patch segment")
    offset = file_offset(elf, FINALIZE_GROUP)
    if engine[offset:offset + 4] != bytes.fromhex("1420d4e5"):
        raise ValueError("Unexpected resource finalization instruction")

    padding = -len(engine) % 16
    address = segment["p_vaddr"] + segment["p_filesz"] + padding
    # The scheduler holds the lock for the manager (r7) and is about to finalize
    # the group (r4). The pending and in-flight request vectors are at +0x14 and
    # +0x20, respectively. A request's group pointer is at +0x08.
    # GoldCan_1536 can be marked ready with GPU reads still outstanding. Keep
    # the group linked so those callbacks run before the allocator reuses it.
    payload = bytes(Ks(KS_ARCH_ARM, KS_MODE_ARM).asm(f"""
        push {{r0-r3, ip, lr}}
        add r2, r7, #0x14
        ldmia r2, {{r0, r1}}
        bl scan
        beq wait
        add r2, r7, #0x20
        ldmia r2, {{r0, r1}}
        bl scan
        beq wait
        pop {{r0-r3, ip, lr}}
        ldrb r2, [r4, #0x14]
        b #{FINALIZE_GROUP + 4}
    wait:
        pop {{r0-r3, ip, lr}}
        b #{NEXT_GROUP}
    scan:
        cmp r0, r1
        bhs exhausted
        ldr r3, [r0], #4
        ldr r3, [r3, #8]
        cmp r3, r4
        bne scan
        bx lr
    exhausted:
        mov r3, #1
        cmp r3, #0
        bx lr
    """, address)[0])
    result = bytearray(engine)
    result.extend(bytes(padding) + payload)
    result[offset:offset + 4] = branch(FINALIZE_GROUP, address)
    length = len(result) - segment["p_offset"]
    struct.pack_into("<II", result, elf["e_phoff"] + index * elf["e_phentsize"] + 16,
                     length, length)
    return bytes(result)


def build(base, output, sdk, signing, installed_resources=False):
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: retain_group_for_reads(apk.read(engine)),
            MANIFEST: manifest_version(apk.read(MANIFEST), 342, 341, prefix="A"),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    pack_apk(base, updates, sdk, output, signing,
             excluded=RESOURCE_PARTS if installed_resources else ())
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--installed-resources", action="store_true")
    build(**vars(parser.parse_args()))
