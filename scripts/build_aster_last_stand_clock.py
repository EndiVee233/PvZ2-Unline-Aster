"""Build A340 with adventure timing gated by the Last Stand battle phase."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from shutil import copyfile
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile

from build_aster_adventure_records import payload
from build_aster_borrow_limit import HEADERS
from build_aster_friend_roster import installed_entries
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_star_difficulty import ENGINE
from prepare_profile_memory import branch


A339_ENGINE = "65121af35633bf2becb36cc25c2b85ea4fe9beb02656bac2d868e7c1d3ca4154"


def patch_guest(engine, ndk, output, prior):
    if sha256(engine).hexdigest() != A339_ENGINE:
        raise ValueError("Expected the A339 ARM32 guest engine")

    elf = ELFFile(BytesIO(engine))
    loads = [(i, part) for i, part in enumerate(elf.iter_segments()) if part["p_type"] == "PT_LOAD"]
    (_, state), (index, tail) = loads[-2:]
    if (tail["p_flags"] != 5 or tail["p_offset"] + tail["p_filesz"] != len(engine)
            or tail["p_filesz"] != tail["p_memsz"] or state["p_flags"] != 6):
        raise ValueError("Unexpected adventure load segments in A339")

    with prior.open("rb") as handle:
        old_runtime = ELFFile(handle).get_section_by_name(".runtime")
        state_address, state_size = old_runtime["sh_addr"], old_runtime["sh_size"]
    if not (state["p_vaddr"] <= state_address
            and state_address + state_size <= state["p_vaddr"] + state["p_memsz"]):
        raise ValueError("Unexpected A339 adventure state range")

    offset = (len(engine) + 15) & ~15
    address = tail["p_vaddr"] + offset - tail["p_offset"]
    code, new_state_size, entries = payload(ndk, output, address, state_address, False, True, True)
    if new_state_size != state_size:
        raise ValueError("The adventure runtime must retain its existing allocation")

    patched = bytearray(engine)
    for name, old, file in installed_entries(engine, elf, prior):
        patched[file:file + 4] = branch(old, entries[name])

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
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 340, 339, prefix="A")
    result = output / "PvZ2-Unline-Aster-A340-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "prior", "output", "ndk", "sdk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
