"""Build A345 with the native plant preview for a picked-up loan."""

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
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS
from build_aster_save_path_fix import manifest_version
from prepare_profile_memory import branch


A344_ENGINE = "cdf51e5964ebd89a37daa785c6bd339f4eb77268fdabaf320d0f945bfd5b4637"


def patch_guest(engine, ndk, output, prior):
    if sha256(engine).hexdigest() != A344_ENGINE:
        raise ValueError("Expected the A344 shared guest")
    return replace_adventure_payload(engine, ndk, output, prior)


def replace_adventure_payload(engine, ndk, output, prior, *, names=None):
    elf = ELFFile(BytesIO(engine))
    loads = [(i, segment) for i, segment in enumerate(elf.iter_segments()) if segment["p_type"] == "PT_LOAD"]
    (_, writable), (tail_index, tail) = loads[-2:]
    if (writable["p_flags"] != 6 or tail["p_flags"] != 5
            or tail["p_memsz"] != tail["p_filesz"]
            or tail["p_offset"] + tail["p_filesz"] != len(engine)):
        raise ValueError("Unexpected adventure engine load segments")

    with prior.open("rb") as handle:
        prior_elf = ELFFile(handle)
        runtime = prior_elf.get_section_by_name(".runtime")
        state, size = runtime["sh_addr"], runtime["sh_size"]
        runtime_index = prior_elf.get_section_index(".runtime")
        state_symbols = {symbol.name: symbol["st_value"]
                         for symbol in prior_elf.get_section_by_name(".symtab").iter_symbols()
                         if symbol.name and symbol["st_shndx"] == runtime_index}
    if not writable["p_vaddr"] <= state <= state + size <= writable["p_vaddr"] + writable["p_memsz"]:
        raise ValueError("Unexpected adventure state range")

    padding = -len(engine) % 16
    address = tail["p_vaddr"] + tail["p_filesz"] + padding
    code, new_size, entries = payload(ndk, output, address, state, False, True, True)
    if new_size != size:
        raise ValueError("Adventure state size changed")
    if names is not None and any(entries.get(name) != value for name, value in state_symbols.items()):
        raise ValueError("Adventure state layout changed while replacing selected entry points")

    patched = bytearray(engine)
    hooks = list(installed_entries(engine, elf, prior, names=names))
    if names is not None and {name for name, _, _ in hooks} != names:
        raise ValueError("Missing installed adventure entry points")
    for name, old, offset in hooks:
        patched[offset:offset + 4] = branch(old, entries[name])

    patched.extend(bytes(padding) + code)
    segment_size = len(patched) - tail["p_offset"]
    header = elf["e_phoff"] + tail_index * elf["e_phentsize"]
    struct.pack_into("<II", patched, header + 16, segment_size, segment_size)
    return bytes(patched)


def build(base, prior, output, ndk, sdk, signing, installed_resources=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in HEADERS:
        copyfile(prior.parent / name, output.parent / name)
    with ZipFile(base) as apk:
        engine = ARM64_ENGINE if ARM64_ENGINE in apk.namelist() else ENGINE
        updates = {
            engine: patch_guest(apk.read(engine), ndk, output.parent, prior),
            MANIFEST: manifest_version(apk.read(MANIFEST), 345, 344, prefix="A"),
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
