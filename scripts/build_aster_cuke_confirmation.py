"""Port the CN 4.2.8 Tactical Cucumber confirmation to the A327 guest."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_adventure_records import FLAGS, ROOT
from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, create_plan, rebuild_dynamic_bootstrap
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_cn_user_art import Bundle, append_cn_user_credit, crop_sprites, unwrap
from prepare_aster_social_art import edit_social_atlas
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


ENGINE = "lib/armeabi/libSrc.so"
A327_ENGINE = "ddee5bec31d7c3274ae1b03ec14a01b87c8af1d8ba9f01dfac49dac18b35fec8"


def patch_guest(engine, ndk, output):
    if sha256(engine).hexdigest() != A327_ENGINE:
        raise ValueError("Expected the A327 guest engine")
    elf = ELFFile(BytesIO(engine))
    state, code = (elf.get_segment(index) for index in (7, 8))
    if (state["p_flags"] != 6 or code["p_flags"] != 5 or code["p_memsz"] != code["p_filesz"]
            or code["p_offset"] + code["p_filesz"] != len(engine)):
        raise ValueError("Unexpected A327 load segments")
    state_at = (state["p_vaddr"] + state["p_memsz"] + 15) & -16
    code_at = (code["p_vaddr"] + code["p_memsz"] + 15) & -16
    linker = output / "cuke.ld"
    linked = output / "cuke.elf"
    linker.write_text(f"""ENTRY(asterCukeTouch)
SECTIONS {{
    . = {state_at}; .runtime (NOLOAD) : {{ *(.bss*) *(COMMON) }}
    . = {code_at}; .payload : {{ *(.text*) *(.rodata*) }}
    .initialized : {{ *(.data*) *(.got*) }}
    /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.note*) *(.comment*) }}
}}
ASSERT(SIZEOF(.initialized) == 0, "Confirmation state must be zero-initialized")
""", encoding="ascii")
    clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe"
    subprocess.run([clang, *FLAGS, "-nostdlib", "-static", "-Wl,--no-undefined", "-Wl,-T," + str(linker),
                    ROOT / "src/tactical-cuke/confirmation.cpp", "-o", linked], check=True)
    with linked.open("rb") as stream:
        helper = ELFFile(stream)
        body = bytearray(helper.get_section_by_name(".payload").data())
        state_end = state_at + helper.get_section_by_name(".runtime")["sh_size"]
        symbols = {s.name: s["st_value"] for s in helper.get_section_by_name(".symtab").iter_symbols()
                   if s.name.startswith("asterCuke")}
    if state_end > code["p_vaddr"]:
        raise ValueError("Confirmation state overlaps the executable load")

    patched = bytearray(engine)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    base_arg = "adr r0, anchor\nldr ip,[r0]\nsub r0,r0,ip"

    def wrap(site, expected, source, link=False):
        pos = file_offset(elf, site)
        if patched[pos:pos + 4] != expected:
            raise ValueError(f"Unexpected Tactical Cucumber instruction at {site:#x}")
        body.extend(bytes(-len(body) % 4))
        address = code_at + len(body)
        stub = bytearray(assembler.asm(source + "\nanchor: .word 0", address)[0])
        struct.pack_into("<I", stub, len(stub) - 4, address + len(stub) - 4)
        body.extend(stub)
        patched[pos:pos + 4] = branch(site, address, link)

    wrap(0x7891AC, branch(0x7891AC, 0x224508, True), f"""
        mov r2,r1
        mov r1,r0
        ldr r3,[fp,#-0x5c]
        {base_arg}
        b #{symbols['asterCukeOffer']}
    """, True)
    # The price bubble extends beyond the stock widget. Handle Board touches before
    # the normal widget hit test and before the high/normal camera transformations.
    for site, prologue in ((0x22A2C8, 0xE92D4FF0), (0x1FBF08, 0xE92D4830), (0x2217DC, 0xE92D4BF0)):
        wrap(site, struct.pack("<I", prologue), f"""
            push {{r0-r4,lr}}
            mov r2,r1
            mov r1,r0
            {base_arg}
            bl #{symbols['asterCukeTouch']}
            cmp r0,#0
            pop {{r0-r4,lr}}
            movne r0,#1
            bxne lr
            .word {prologue:#x}
            b #{site + 4:#x}
        """)
    wrap(0x78A784, branch(0x78A784, 0x797918, True), f"""
        mov r2,r1
        mov r1,r0
        {base_arg}
        b #{symbols['asterCukeDraw']}
    """, True)
    wrap(0x788AEC, struct.pack("<I", 0xE92D4818), f"""
        push {{r0-r4,lr}}
        mov r1,r0
        {base_arg}
        bl #{symbols['asterCukeDismiss']}
        pop {{r0-r4,lr}}
        .word 0xe92d4818
        b #0x788af0
    """)

    patched += bytes(code_at - code["p_vaddr"] - code["p_filesz"]) + body
    size = len(patched) - code["p_offset"]
    phdr, stride = elf["e_phoff"], elf["e_phentsize"]
    struct.pack_into("<I", patched, phdr + 7 * stride + 20, state_end - state["p_vaddr"])
    struct.pack_into("<II", patched, phdr + 8 * stride + 16, size, size)
    (output / "cuke-hooks.json").write_text(json.dumps(symbols, indent=2) + "\n", encoding="ascii")
    return bytes(patched)


def port_art(dynamic, donor):
    with ZipFile(donor) as apk:
        reference = Bundle(unwrap(apk.read("assets/uicommon.rsb.smf")))
    group, = (item for item in reference.manifest()[2]["groups"] if item["id"] == "UI_AlwaysLoaded_1200")
    art = dict(crop_sprites(reference, group, {
        "CUKE_BUY_CONFIRMATION": "IMAGE_UI_HUD_INGAME_CUKE_BUY_CONFIRMATION",
    }))
    if art["CUKE_BUY_CONFIRMATION"].size != (196, 228):
        raise ValueError("Expected the CN 4.2.8 price bubble")
    revised = Bundle(edit_social_atlas(dynamic, art))
    append_cn_user_credit(revised, "战术黄瓜确认气泡素材提取自")
    return revised.build()


def build(base, donor, output, ndk, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(base) as apk:
        engine = patch_guest(apk.read(ENGINE), ndk, output)
        dynamic = apk.read(ASSET)
        updated = port_art(dynamic, donor)
        plan = create_plan(updated, output, rgba_atlases=1)
        bootstrap = rebuild_dynamic_bootstrap(apk.read(BOOTSTRAP), output / "bootstrap", dynamic, updated)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 328, 327, prefix="A")
    result = output / "PvZ2-Unline-Aster-A328-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, ASSET: updated, PLAN: plan, BOOTSTRAP: bootstrap,
                    "AndroidManifest.xml": manifest}, sdk, result, signing)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "donor", "output", "ndk", "sdk", "signing"):
        parser.add_argument("--" + name, required=True, type=Path)
    build(**vars(parser.parse_args()))
