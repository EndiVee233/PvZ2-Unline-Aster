"""Build Aster's PvP updates on the accepted A305 ARM32 guest."""
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
from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, create_plan, rebuild_dynamic_bootstrap
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_feedback import ROOT, compile_payload, file_offset
from prepare_aster_shop_terrain import prepare_shop_terrain
from prepare_profile_memory import branch


A305 = "989dce8f9b66ef280c799e6de26375ce6ae26411e8178aa116bea2de3b8872df"
STATIC_PVP_ENTRIES = {"_ZL13projectGardenjPh", "_ZL21projectBusinessOwnersjPh", "_ZL21projectBusinessStocksjPh"}


def symbols(elf):
    return {s.name: s for s in elf.get_section_by_name(".symtab").iter_symbols() if s.name}


def patch_native(native, sdk, headers, prior, p0, output):
    if sha256(native).hexdigest() != A305:
        raise ValueError("Expected the signed A305 ARM32 guest")
    elf = ELFFile(BytesIO(native))
    loads = [(i, s) for i, s in enumerate(elf.iter_segments()) if s["p_type"] == "PT_LOAD"]
    (rx_index, rx), (rw_index, rw) = loads[-2:]
    if (rx["p_flags"], rw["p_flags"]) != (5, 6):
        raise ValueError("Unexpected guest segment flags")
    start = (rx["p_vaddr"] + rx["p_filesz"] + 15) & ~15
    alignment = rw["p_align"]
    runtime_address = (rw["p_vaddr"] + rw["p_memsz"] + alignment - 1) & -alignment
    patched_elf = compile_payload(sdk, ROOT / "src", headers, output, start, runtime_address,
                                  archived=False, extra_flags=("-DPVP_DISTRICT_SHOPS",))
    guest = ELFFile(BytesIO(patched_elf.read_bytes()))
    before = ELFFile(BytesIO(prior.read_bytes()))
    p0_elf = ELFFile(BytesIO(p0.read_bytes()))
    previous, p0_entries, current = map(symbols, (before, p0_elf, guest))
    runtime = guest.get_section_by_name(".runtime").data()

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

    # All previously installed entries must share the expanded wallet/runtime.
    # Older aliases that do not touch state can keep their original code.
    for entries in (previous, p0_entries):
        for name, entry in entries.items():
            info = entry["st_info"]
            exported = (info["type"] == "STT_FUNC" and info["bind"] == "STB_GLOBAL"
                        and not name.startswith("__aeabi_"))
            if name in STATIC_PVP_ENTRIES or exported and name in current:
                redirect(entry["st_value"], address(name))

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
    # The stock low-stock label normally replaces the record name with
    # “您的资产”. Retain the original blue label and chest behavior.
    redirect(0x10134d4, stub(f"""
        push {{r0-r4,lr}}
        mov r1,r10
        {base}
        bl #{address('offlineBusinessUsesOwnName')}
        cmp r0,#0
        pop {{r0-r4,lr}}
        bne #0x1011b10
        ldr r1,original
        b #0x10134d8
        original: .word {struct.unpack_from("<I", native, 0x1013730)[0]}
    """, base=True), 0xe59f1254)

    old_rw = rw["p_offset"]
    new_end = rx["p_offset"] + start - rx["p_vaddr"] + len(payload)
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
    runtime_offset = old_rw + growth + runtime_address - rw["p_vaddr"]
    if runtime_offset < len(result):
        raise ValueError("Expanded PvP runtime would overwrite guest metadata")
    result.extend(bytes(runtime_offset - len(result)))
    result.extend(runtime)
    length = len(result) - old_rw - growth
    struct.pack_into("<II", result, ph + rw_index * size + 16, length, length)
    sh = elf["e_shoff"] + (growth if elf["e_shoff"] >= old_rw else 0)
    struct.pack_into("<I", result, 32, sh)
    for idx, section in enumerate(elf.iter_sections()):
        if section["sh_offset"] >= old_rw:
            struct.pack_into("<I", result, sh + idx * elf["e_shentsize"] + 16,
                             section["sh_offset"] + growth)
    return result


def build(base, sdk, headers, prior, p0, output, signing, version):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_native(apk.read(ENGINE), sdk, headers, prior, p0, output)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), version, 305, prefix="A")
        original = apk.read(ASSET)
        shop_terrain = prepare_shop_terrain(original)
        bootstrap = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / "bootstrap", original, shop_terrain)
    plan = create_plan(shop_terrain, output, rgba_atlases=1)
    (output / "dynamic.rsb.smf").write_bytes(shop_terrain)
    (output / "libSrc.so").write_bytes(engine)
    (output / "generated").mkdir(exist_ok=True)
    copyfile(headers / "exchange-presets.json", output / "generated/exchange-presets.json")
    if signing:
        final = output / f"PvZ2-Unline-Aster-A{version}-ARM32-WSA-existing-data.apk"
        pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest, ASSET: shop_terrain,
                        BOOTSTRAP: bootstrap, PLAN: plan}, sdk, final, signing)
        print(final)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "sdk", "headers", "prior", "p0", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--signing", type=Path)
    parser.add_argument("--version", type=int, default=310)
    build(**vars(parser.parse_args()))
