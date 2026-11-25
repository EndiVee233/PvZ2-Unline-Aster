"""Build A355 with wrapping challenge indicators below the right-side HUD."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from shutil import copyfile
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_adventure_records import payload
from build_aster_borrow_limit import HEADERS
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A354_ENGINE = "81744752e5faf4dd8110f5f627ad145561e2677be34322921d7b6bca0f3dad24"
LAYOUT_CALL = 0x205FF4
STOCK_LAYOUT = 0x2057C0


def patch_guest(engine, ndk, output, prior):
    if sha256(engine).hexdigest() != A354_ENGINE:
        raise ValueError("Expected the A354 shared guest")
    elf = ELFFile(BytesIO(engine))
    index, tail = [(i, segment) for i, segment in enumerate(elf.iter_segments())
                   if segment["p_type"] == "PT_LOAD"][-1]
    if (tail["p_flags"] != 5 or tail["p_filesz"] != tail["p_memsz"]
            or tail["p_offset"] + tail["p_filesz"] != len(engine)):
        raise ValueError("Unexpected A354 executable segment")
    with prior.open("rb") as handle:
        runtime = ELFFile(handle).get_section_by_name(".runtime")
        state, expected_size = runtime["sh_addr"], runtime["sh_size"]

    padding = -len(engine) % 16
    address = tail["p_vaddr"] + tail["p_filesz"] + padding
    code, size, entries = payload(ndk, output, address, state, False, True, True)
    if size != expected_size:
        raise ValueError("Adventure runtime size changed")
    code.extend(bytes(-len(code) % 4))
    stub = address + len(code)
    layout = entries["asterAdventureLayoutChallengeHud"]
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code.extend(bytes(assembler.asm(f"""
        push {{r0,lr}}
        adr r0,anchor
        ldr ip,[r0]
        sub r0,r0,ip
        bl #{layout}
        cmp r0,#0
        pop {{r0,lr}}
        bxne lr
        b #{STOCK_LAYOUT}
        anchor: .word 0
    """, stub)[0]))
    struct.pack_into("<I", code, len(code) - 4, address + len(code) - 4)

    offset = file_offset(elf, LAYOUT_CALL, 4)
    if engine[offset:offset + 4] != branch(LAYOUT_CALL, STOCK_LAYOUT, link=True):
        raise ValueError("Unexpected call to the challenge layout")
    patched = bytearray(engine + bytes(padding)) + code
    patched[offset:offset + 4] = branch(LAYOUT_CALL, stub, link=True)
    segment_size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, segment_size, segment_size)
    return bytes(patched)


def build(base, prior, output, ndk, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in HEADERS:
        copyfile(prior.parent / name, output.parent / name)
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_guest(apk.read(engine), ndk, output.parent, prior),
            MANIFEST: manifest_version(apk.read(MANIFEST), 355, 354, prefix="A"),
        }
    pack_apk(base, updates, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "prior", "output", "ndk", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
