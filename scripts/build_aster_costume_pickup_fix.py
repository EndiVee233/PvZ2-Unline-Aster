"""Handle collectible drops on preview boards that have no coin HUD."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A351_ENGINE = "b0538408b51c73b059aa731ae7d0fa2beadefe6e228f0c0524c28a746a27734a"
COIN_BANK_LOOKUP = 0x97714C
COIN_BANK_USES = (0x22D130, 0x22D1EC)
PICKUP_WITHOUT_HUD = 0x22D09C


def patch_guest(engine):
    if sha256(engine).hexdigest() != A351_ENGINE:
        raise ValueError("Expected the A351 shared guest")
    elf = ELFFile(BytesIO(engine))
    index, tail = [(i, segment) for i, segment in enumerate(elf.iter_segments())
                   if segment["p_type"] == "PT_LOAD"][-1]
    if (tail["p_flags"] != 5 or tail["p_memsz"] != tail["p_filesz"]
            or tail["p_offset"] + tail["p_filesz"] != len(engine)):
        raise ValueError("Unexpected A351 engine code segment")

    patched = bytearray(engine)
    padding = -len(engine) % 4
    patched.extend(bytes(padding))
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    for site in COIN_BANK_USES:
        offset = file_offset(elf, site - 4, 8)
        load_vtable = bytes(assembler.asm("ldr r3,[r0]", site)[0])
        if engine[offset:offset + 8] != branch(site - 4, COIN_BANK_LOOKUP, True) + load_vtable:
            raise ValueError(f"Unexpected coin-bank lookup at {site:#x}")
        stub = tail["p_vaddr"] + len(patched) - tail["p_offset"]
        # Use the native no-HUD pickup animation and string cleanup.
        # The normal branch continues to update the bank and credit the coin.
        code = bytes(assembler.asm(f"""
            cmp r0,#0
            beq #{PICKUP_WITHOUT_HUD}
            ldr r3,[r0]
            b #{site + 4}
        """, stub)[0])
        patched[offset + 4:offset + 8] = branch(site, stub)
        patched.extend(code)

    size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, size, size)
    return bytes(patched)


def build(base, output, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_guest(apk.read(engine)),
            MANIFEST: manifest_version(apk.read(MANIFEST), 352, 351, prefix="A"),
        }
    pack_apk(base, updates, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
