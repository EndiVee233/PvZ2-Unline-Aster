"""Fit the animated Evil Dave portrait to the PvP raid popup in A347."""

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


A346_ENGINE = "09319045dd6a21239f7a042143647fab517367825d666e93e93dc6b360ebcedd"
DAVE_TRANSFORM_CALL = 0x10193E8
SET_PAM_TRANSFORM = 0x773FBC


def patch_guest(engine):
    if sha256(engine).hexdigest() != A346_ENGINE:
        raise ValueError("Expected the A346 shared guest")
    elf = ELFFile(BytesIO(engine))
    index, tail = [(i, segment) for i, segment in enumerate(elf.iter_segments())
                   if segment["p_type"] == "PT_LOAD"][-1]
    if (tail["p_flags"] != 5 or tail["p_memsz"] != tail["p_filesz"]
            or tail["p_offset"] + tail["p_filesz"] != len(engine)):
        raise ValueError("Unexpected A346 engine code segment")

    patched = bytearray(engine)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def replace(address, before, after):
        offset = file_offset(elf, address, len(before))
        if len(before) != len(after) or engine[offset:offset + len(before)] != before:
            raise ValueError(f"Unexpected Evil Dave instructions at {address:#x}")
        patched[offset:offset + len(after)] = after

    # In UI layout units, center the PAM's gold ring horizontally over
    # the recess and keep its bottom edge above the reward heading.
    for address, before, after in (
        (0x1019388, "mov r1,#0x42000000; add r1,r1,#0x960000",
         "mov r1,#0x42000000; add r1,r1,#0x980000"),  # 75 -> 76
        (0x10193B4, "mov r1,#0xc1000000; add r1,r1,#0xa00000",
         "mov r1,#0xc1000000; add r1,r1,#0xc80000"),  # -20 -> -25
    ):
        replace(address, bytes(assembler.asm(before, address)[0]),
                bytes(assembler.asm(after, address)[0]))

    # The panel already uses the UI scale in r7 for translation. Apply it
    # uniformly to the two diagonal entries of this portrait's PAM matrix.
    padding = -len(engine) % 4
    stub = tail["p_vaddr"] + tail["p_filesz"] + padding
    code = bytes(assembler.asm(f"""
        str r7,[r1]
        str r7,[r1,#16]
        b #{SET_PAM_TRANSFORM}
    """, stub)[0])
    replace(DAVE_TRANSFORM_CALL, branch(DAVE_TRANSFORM_CALL, SET_PAM_TRANSFORM, True),
            branch(DAVE_TRANSFORM_CALL, stub, True))
    patched.extend(bytes(padding) + code)
    size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, size, size)
    return bytes(patched)


def build(base, output, sdk, signing, installed_resources=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_guest(apk.read(engine)),
            MANIFEST: manifest_version(apk.read(MANIFEST), 347, 346, prefix="A"),
        }
    pack_apk(base, updates, sdk, output, signing,
             excluded=RESOURCE_PARTS if installed_resources else ())
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--installed-resources", action="store_true")
    build(**vars(parser.parse_args()))
