"""Build A307 with P1 PvP changes on the accepted A305 ARM32 guest."""
import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from shutil import copyfile
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM

from build_aster_pickup_access import ENGINE
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_feedback import NEW_STATE, ROOT, compile_payload, file_offset
from prepare_profile_memory import branch


A305 = "989dce8f9b66ef280c799e6de26375ce6ae26411e8178aa116bea2de3b8872df"
PVP_NAMES = (
    "offlineGarden", "offlineMapArmyPrepare", "offlineDaveNarrativeAck", "offlineDaveLabel", "offlineAttack", "offlineInfo",
    "offlineBattleResult", "offlineBusinessAction", "offlineBusinessChest", "offlineScoutRewards",
    "offlineAttackPreviewFormat", "offlineAttackPreviewCost", "offlineHistoryLookup",
    "_ZL21projectBusinessOwnersjPh", "_ZL21projectBusinessStocksjPh",
)


def symbols(elf):
    return {s.name: s for s in elf.get_section_by_name(".symtab").iter_symbols() if s.name}


def runtime_layout(elf, entries):
    section = elf.get_section_by_name(".runtime")
    start = section["sh_addr"]
    return {name: (s["st_value"], s["st_size"]) for name, s in entries.items()
            if s["st_info"]["type"] == "STT_OBJECT" and start <= s["st_value"] < start + section["sh_size"]}


def patch_native(native, sdk, headers, prior, p0, output):
    if sha256(native).hexdigest() != A305:
        raise ValueError("Expected the signed A305 ARM32 guest")
    elf = ELFFile(BytesIO(native))
    loads = [(i, s) for i, s in enumerate(elf.iter_segments()) if s["p_type"] == "PT_LOAD"]
    (rx_index, rx), (rw_index, rw) = loads[-2:]
    if (rx["p_flags"], rw["p_flags"]) != (5, 6):
        raise ValueError("Unexpected guest segment flags")
    start = (rx["p_vaddr"] + rx["p_filesz"] + 15) & ~15
    patched_elf = compile_payload(sdk, ROOT / "src", headers, output, start, NEW_STATE, archived=False)
    guest = ELFFile(BytesIO(patched_elf.read_bytes()))
    before = ELFFile(BytesIO(prior.read_bytes()))
    p0_elf = ELFFile(BytesIO(p0.read_bytes()))
    previous, p0_entries, current = map(symbols, (before, p0_elf, guest))
    # Verify the installed A194 runtime. A303 appended a map projection,
    # whose entry is redirected below as well.
    if runtime_layout(before, previous) != runtime_layout(guest, current):
        raise ValueError("P1 must preserve the installed PvP runtime layout")
    runtime = guest.get_section_by_name(".runtime").data()
    runtime_offset = file_offset(elf, NEW_STATE, len(runtime))
    if native[runtime_offset:runtime_offset + len(runtime)] != runtime:
        raise ValueError("P1 must preserve the installed PvP runtime initial values")

    body = guest.get_section_by_name(".payload")
    payload = bytearray(bytes(body["sh_addr"] - start) + body.data())
    asm = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    replacements = {}

    def address(name):
        return current[name]["st_value"]

    def redirect(site, target, expected=None):
        offset = file_offset(elf, site)
        if expected is not None and native[offset:offset + 4] != struct.pack("<I", expected):
            raise ValueError(f"Unexpected A305 instruction at {site:#x}")
        replacements[offset] = branch(site, target)

    for name in PVP_NAMES:
        if name not in previous:
            raise ValueError(f"Missing installed PvP entry {name}")
        for entries in (previous, p0_entries):
            if name in entries:
                redirect(entries[name]["st_value"], address(name))
    garden = "_ZL13projectGardenjPh"
    redirect(p0_entries[garden]["st_value"], address(garden))

    def stub(source, *, base=False):
        payload.extend(bytes(-len(payload) % 4))
        origin = start + len(payload)
        if base:
            source += "\nanchor: .word 0"
        encoded = bytearray(asm.asm(source, origin)[0])
        if base:
            struct.pack_into("<I", encoded, len(encoded) - 4, origin + len(encoded) - 4)
        payload.extend(encoded)
        return origin

    base = "adr r0,anchor\nldr ip,[r0]\nsub r0,r0,ip"
    redirect(0x100cf10, stub(f"""
        push {{r0-r4,lr}}
        mov r1,r4
        {base}
        bl #{address('offlineDaveRemaining')}
        cmp r0,#0
        strge r0,[sp]
        pop {{r0-r4,lr}}
        bge #0x100cf20
        ldr r4,[r4,#0x28]
        b #0x100cf14
    """, base=True), 0xe5944028)
    redirect(0x107b664, stub(f"""
        ldr r7,[r3,#0x7c]
        push {{r0-r4,lr}}
        mov r1,r7
        {base}
        bl #{address('offlineLabEntryTime')}
        mov r7,r0
        pop {{r0-r4,lr}}
        b #0x107b668
    """, base=True), 0xe593707c)
    lab_draw = stub("push {r4-r10,fp,lr}\nb #0x1072aa4")
    redirect(0x1072aa0, stub(f"""
        push {{r4,lr}}
        mov r2,r1
        mov r1,r0
        movw r3,#{lab_draw & 65535}
        movt r3,#{lab_draw >> 16}
        {base}
        bl #{address('offlineLabCardDraw')}
        pop {{r4,pc}}
    """, base=True), 0xe92d4ff0)

    old_rw = rw["p_offset"]
    new_end = rx["p_offset"] + start - rx["p_vaddr"] + len(payload)
    alignment = rw["p_align"]
    growth = (max(0, new_end - old_rw) + alignment - 1) & -alignment
    if start + len(payload) >= rw["p_vaddr"] or any(native[rx["p_offset"] + rx["p_filesz"]:old_rw]):
        raise ValueError("PvP payload exceeds the A305 code range")
    result = bytearray(native[:old_rw] + bytes(growth) + native[old_rw:])
    result[new_end - len(payload):new_end] = payload
    for offset, data in replacements.items():
        result[offset:offset + 4] = data
    ph, size = elf["e_phoff"], elf["e_phentsize"]
    length = new_end - rx["p_offset"]
    struct.pack_into("<II", result, ph + rx_index * size + 16, length, length)
    struct.pack_into("<I", result, ph + rw_index * size + 4, old_rw + growth)
    sh = elf["e_shoff"] + (growth if elf["e_shoff"] >= old_rw else 0)
    struct.pack_into("<I", result, 32, sh)
    for idx, section in enumerate(elf.iter_sections()):
        if section["sh_offset"] >= old_rw:
            struct.pack_into("<I", result, sh + idx * elf["e_shentsize"] + 16,
                             section["sh_offset"] + growth)
    return result


def build(base, sdk, headers, prior, p0, output, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_native(apk.read(ENGINE), sdk, headers, prior, p0, output)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 307, 305, prefix="A")
    (output / "libSrc.so").write_bytes(engine)
    (output / "generated").mkdir(exist_ok=True)
    copyfile(headers / "exchange-presets.json", output / "generated/exchange-presets.json")
    if signing:
        final = output / "PvZ2-Unline-Aster-A307-ARM32-WSA-existing-data.apk"
        pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, final, signing)
        print(final)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "sdk", "headers", "prior", "p0", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--signing", type=Path)
    build(**vars(parser.parse_args()))
