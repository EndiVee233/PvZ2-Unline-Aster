"""Build the ARM32 friend roster, lending cards and map captions over A315."""
import argparse
from io import BytesIO
from pathlib import Path
from shutil import copyfile
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_adventure_records import patch_friend_entry, payload, social_dex
from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, create_plan, rebuild_dynamic_bootstrap
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_adventure_levels import write_packet_anchors, write_user_plants
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


ENGINE = "lib/armeabi/libSrc.so"
PAGE = 4096
SIGN_SPRITE_DRAW = 0xA1D304


def aligned(value):
    return (value + PAGE - 1) & -PAGE


def installed_entries(engine, source, prior, *, names=None):
    with prior.open("rb") as stream:
        guest = ELFFile(stream)
        code = guest.get_section_by_name(".payload")
        body = code.data()
        for symbol in guest.get_section_by_name(".symtab").iter_symbols():
            name = symbol.name
            if (symbol["st_info"]["type"] != "STT_FUNC" or symbol["st_info"]["bind"] != "STB_GLOBAL"
                    or not name.startswith("aster") or names is not None and name not in names):
                continue
            at = symbol["st_value"]
            expected = body[at - code["sh_addr"]:at - code["sh_addr"] + 4]
            offset = file_offset(source, at)
            if len(expected) != 4 or engine[offset:offset + 4] != expected:
                raise ValueError(f"Expected installed adventure entry {name} at {at:#x}")
            yield name, at, offset


def patch_guest(engine, ndk, output, old_social, star_overlay):
    source = ELFFile(BytesIO(engine))
    state_index, state = list((index, segment) for index, segment in enumerate(source.iter_segments())
                              if segment["p_type"] == "PT_LOAD")[-1]
    state_address = aligned(state["p_vaddr"] + state["p_memsz"])
    code_address = state_address + 0x20000
    code, state_size, entries = payload(ndk, output, code_address, state_address, False, True, True)
    if state_address + state_size > code_address:
        raise ValueError("Adventure state exceeded its reserved range")

    patched = bytearray(engine)
    for prior, names in ((old_social, None), (star_overlay, {"asterAdventureNextStar"})):
        for name, address, offset in installed_entries(engine, source, prior, names=names):
            patched[offset:offset + 4] = branch(address, entries[name])

    # Replace only the sign-in background draw. The original widget still
    # owns its pressed state, hit testing, and the reward notification badge.
    code.extend(bytes(-len(code) % 4))
    stub = code_address + len(code)
    original = file_offset(source, SIGN_SPRITE_DRAW)
    if engine[original:original + 4] != branch(SIGN_SPRITE_DRAW, 0x11694C8, link=True):
        raise ValueError("Unexpected sign-in background draw call")
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code.extend(assembler.asm(f"""
        mov r2,r1
        mov r1,r0
        ldrb r3,[r5,#0xec]
        adr r0,basepoint
        ldr ip,[r0]
        sub r0,r0,ip
        b #{entries["asterSignMapDraw"]}
        basepoint: .word {stub + 28}
    """, stub)[0])
    patched[original:original + 4] = branch(SIGN_SPRITE_DRAW, stub, link=True)

    # Houdini expects the program table to stay beside the ELF header.
    # The extra header occupies the unused interpreter name and the start of
    # .dynsym. Move that whole symbol table without changing its indices.
    stride = source["e_phentsize"]
    header_count = source["e_phnum"] + 1
    table_start = source["e_phoff"]
    new_header = table_start + source["e_phnum"] * stride
    interp = source.get_section_by_name(".interp")
    dynsym = source.get_section_by_name(".dynsym")
    if (stride != 32 or new_header != interp["sh_offset"] or
            any(segment["p_type"] == "PT_INTERP" for segment in source.iter_segments())):
        raise ValueError("Unexpected guest program header format")
    code_file = aligned(len(engine))
    symbol_start = (len(code) + 15) & -16
    code += bytes(symbol_start - len(code)) + dynsym.data()
    if struct.unpack_from("<I", patched, table_start)[0] != 6:
        raise ValueError("Expected the ARM guest's PT_PHDR first")
    struct.pack_into("<II", patched, table_start + 16, header_count * stride, header_count * stride)
    struct.pack_into("<I", patched, table_start + state_index * stride + 20,
                     state_address + state_size - state["p_vaddr"])
    struct.pack_into("<8I", patched, new_header, 1, code_file, code_address, code_address,
                     len(code), len(code), 5, PAGE)
    struct.pack_into("<H", patched, 44, header_count)
    dynamic = source.get_section_by_name(".dynamic")
    tag = next(index for index, item in enumerate(dynamic.iter_tags()) if item.entry.d_tag == "DT_SYMTAB")
    struct.pack_into("<I", patched, dynamic["sh_offset"] + tag * 8 + 4, code_address + symbol_start)
    section = source["e_shoff"] + source.get_section_index(".dynsym") * source["e_shentsize"]
    struct.pack_into("<II", patched, section + 12, code_address + symbol_start, code_file + symbol_start)
    patched += bytes(code_file - len(patched)) + code
    result = ELFFile(BytesIO(patched))
    assert file_offset(result, entries["asterAdventureSocialFrame"]) >= code_file
    return bytes(patched)


def build(base, stock, old_social, star_overlay, sdk, ndk, output, signing):
    output.mkdir(parents=True, exist_ok=True)
    write_packet_anchors(stock, output)
    write_user_plants(base, output)
    copyfile(old_social.with_name("adventure_levels.inc"), output / "adventure_levels.inc")
    with ZipFile(base) as archive:
        manifest = manifest_version(archive.read("AndroidManifest.xml"), 318, 315, prefix="A")
        engine = patch_guest(archive.read(ENGINE), ndk, output, old_social, star_overlay)
        original = archive.read(ASSET)
        dynamic = patch_friend_entry(original)
        bootstrap = rebuild_dynamic_bootstrap(archive.read(BOOTSTRAP), output / "bootstrap", original, dynamic)
        dex, = (name for name in archive.namelist() if name.startswith("classes") and name.endswith(".dex")
                and b"Lcom/popcap/pvz2cthd/AdventureFriendFiles;" in archive.read(name))
    (output / "libSrc.so").write_bytes(engine)
    plan = create_plan(dynamic, output, rgba_atlases=1)
    companion = social_dex(output / "social-dex", sdk)
    target = output / "PvZ2-Unline-Aster-A318-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest, ASSET: dynamic,
                    BOOTSTRAP: bootstrap, PLAN: plan, dex: companion}, sdk, target, signing,
             excluded=("assets/adventure/friends.json",))
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "stock", "old-social", "star-overlay", "sdk", "ndk", "output", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
