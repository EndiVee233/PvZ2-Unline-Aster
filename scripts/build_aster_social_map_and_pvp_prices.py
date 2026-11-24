"""Build A344 with the effective map catalogue and compact PvP gem quotes."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from shutil import copyfile
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile

from build_aster_adventure_records import payload
from build_aster_friend_roster import installed_entries
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS
from build_aster_save_path_fix import manifest_version
from prepare_aster_adventure_levels import make_catalog
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


A343_ENGINE = "45604b5f463c40da4e87ab1dd784a7d23f814eea959885f72e1d27cb9064ec37"
CATALOG = "assets/adventure/levels.json"


def patch_guest(engine, ndk, output, prior):
    if sha256(engine).hexdigest() != A343_ENGINE:
        raise ValueError("Expected the A343 shared guest")

    elf = ELFFile(BytesIO(engine))
    loads = [(i, segment) for i, segment in enumerate(elf.iter_segments()) if segment["p_type"] == "PT_LOAD"]
    (_, writable), (tail_index, tail) = loads[-2:]
    if (writable["p_flags"] != 6 or tail["p_flags"] != 5
            or tail["p_memsz"] != tail["p_filesz"]
            or tail["p_offset"] + tail["p_filesz"] != len(engine)):
        raise ValueError("Unexpected A343 engine load segments")

    with prior.open("rb") as handle:
        runtime = ELFFile(handle).get_section_by_name(".runtime")
        state, size = runtime["sh_addr"], runtime["sh_size"]
    if not writable["p_vaddr"] <= state <= state + size <= writable["p_vaddr"] + writable["p_memsz"]:
        raise ValueError("Unexpected adventure state range")

    padding = -len(engine) % 16
    address = tail["p_vaddr"] + tail["p_filesz"] + padding
    code, new_size, entries = payload(ndk, output, address, state, False, True, True)
    if new_size != size:
        raise ValueError("Adventure state size changed")

    patched = bytearray(engine)
    for name, old, offset in installed_entries(engine, elf, prior):
        patched[offset:offset + 4] = branch(old, entries[name])

    def replace(site, before, after):
        offset = file_offset(elf, site)
        if len(before) != len(after) or engine[offset:offset + len(before)] != before:
            raise ValueError(f"Unexpected PvP quote bytes at {site:#x}")
        patched[offset:offset + len(before)] = after

    # Keep A313's existing queue state, callbacks and minute-based prices.
    # Training and facilities copy four UTF-32 suffix characters into a
    # temporary label. Terminate it immediately after the two currency glyphs.
    for site in (0x1ACBDD0, 0x1ACE128):
        replace(site, struct.pack("<4I", 0x94BB, 0x77F3, 0x7ACB, 0x5373),
                struct.pack("<4I", 0x94BB, 0x77F3, 0, 0))
    # Evolution and research share one formatter. Copy two suffix glyphs
    # into its zero-initialized buffer, then initialize the string object's
    # address as the stock path does before constructing the shorter label.
    replace(0x1AD0F18, bytes.fromhex("140075e3"), bytes.fromhex("080075e3"))
    replace(0x1AD0F20, bytes.fromhex("0c308ae0"), bytes.fromhex("4c504be2"))
    replace(0x1AD0F24, bytes.fromhex("042042e2"), branch(0x1AD0F24, 0x1AD0F98))

    patched.extend(bytes(padding) + code)
    segment_size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + tail_index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, segment_size, segment_size)
    return bytes(patched)


def build(base, prior, output, ndk, sdk, signing, installed_resources=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in ("adventure_packet_anchors.inc", "adventure_user_plants.inc"):
        copyfile(prior.parent / name, output.parent / name)
    catalog = make_catalog(base, output.parent)
    with ZipFile(base) as apk:
        old = json.loads(apk.read(CATALOG))
        new = json.loads(catalog)
        if any(new.get(alias) != info for alias, info in old.items()):
            raise ValueError("Existing level identifiers, star tiers or formation flags changed")
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_guest(apk.read(engine), ndk, output.parent, prior),
            CATALOG: catalog,
            MANIFEST: manifest_version(apk.read(MANIFEST), 344, 343, prefix="A"),
        }
    pack_apk(base, updates, sdk, output, signing,
             excluded=RESOURCE_PARTS if installed_resources else ())
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "prior", "output", "ndk", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--installed-resources", action="store_true")
    build(**vars(parser.parse_args()))
