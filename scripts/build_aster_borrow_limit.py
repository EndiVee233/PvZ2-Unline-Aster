"""Build A339 with a daily use limit for each friend's individual borrowed plant."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from shutil import copyfile
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_adventure_records import payload
from build_aster_friend_roster import installed_entries
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_star_difficulty import ENGINE
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A338_ENGINE = "e9125c68fb7d567f17628bc82e1830ee21dab6553d897abc36a2c3453913f91b"
HEADERS = ("adventure_levels.inc", "adventure_packet_anchors.inc", "adventure_user_plants.inc")
PLACEMENT_EVENT = 0x4E7528
PLACEMENT_FAILURE = 0x4E7300


def patch_guest(engine, ndk, output, prior):
    if sha256(engine).hexdigest() != A338_ENGINE:
        raise ValueError("Expected the A338 ARM32 guest engine")

    elf = ELFFile(BytesIO(engine))
    loads = [(i, part) for i, part in enumerate(elf.iter_segments()) if part["p_type"] == "PT_LOAD"]
    (_, state), (index, tail) = loads[-2:]
    if (tail["p_flags"] != 5 or tail["p_offset"] + tail["p_filesz"] != len(engine)
            or tail["p_filesz"] != tail["p_memsz"] or state["p_flags"] != 6):
        raise ValueError("Unexpected adventure load segments in A338")

    with prior.open("rb") as handle:
        old_runtime = ELFFile(handle).get_section_by_name(".runtime")
        state_address, state_size = old_runtime["sh_addr"], old_runtime["sh_size"]
    if not (state["p_vaddr"] <= state_address
            and state_address + state_size <= state["p_vaddr"] + state["p_memsz"]):
        raise ValueError("Unexpected A335 adventure state range")

    offset = (len(engine) + 15) & ~15
    address = tail["p_vaddr"] + offset - tail["p_offset"]
    code, new_state_size, entries = payload(ndk, output, address, state_address, False, True, True)
    if new_state_size != state_size:
        raise ValueError("Adventure runtime must fit the existing allocation beside the audio state")

    patched = bytearray(engine)
    for name, old, file in installed_entries(engine, elf, prior):
        patched[file:file + 4] = branch(old, entries[name])

    # A rejected loan has no Plant object for the stock listener dispatch.
    # Route the explicit rejection to the cursor's normal failed-placement exit.
    event = file_offset(elf, PLACEMENT_EVENT)
    if struct.unpack_from("<I", engine, event)[0] != 0xE1A05000:
        raise ValueError("Unexpected cursor event prologue")
    code.extend(bytes(-len(code) % 4))
    stub = address + len(code)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code.extend(bytes(assembler.asm(f"""
        cmn r0,#1
        moveq r0,#0
        mov r5,r0
        beq #{PLACEMENT_FAILURE}
        b #{PLACEMENT_EVENT + 4}
    """, stub)[0]))
    patched[event:event + 4] = branch(PLACEMENT_EVENT, stub)

    patched.extend(bytes(offset - len(patched)))
    patched.extend(code)
    segment_size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, segment_size, segment_size)
    return bytes(patched)


def build(base, prior, output, ndk, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    for name in HEADERS:
        copyfile(prior.parent / name, output / name)
    with ZipFile(base) as apk:
        engine = patch_guest(apk.read(ENGINE), ndk, output, prior)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 339, 338, prefix="A")
    result = output / "PvZ2-Unline-Aster-A339-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "prior", "output", "ndk", "sdk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
