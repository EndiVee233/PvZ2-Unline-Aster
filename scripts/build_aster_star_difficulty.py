"""Integrate social adventure difficulty and multi-star challenges over A332."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks

from build_aster_adventure_records import STAR_RIBBON_ART, payload, social_dex, star_ribbon_instructions
from build_aster_friend_roster import installed_entries
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_adventure_levels import make_catalog, write_packet_anchors, write_user_plants
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch


ENGINE = "lib/armeabi/libSrc.so"
BASE_ENGINE = "316fd4423ac9083612d8c5bcb4f8b204c24cea4136c2f8e92469488a66b82193"


def patch_guest(engine, ndk, output, prior):
    if sha256(engine).hexdigest() != BASE_ENGINE:
        raise ValueError("Expected the A332 ARM32 guest engine")
    elf = ELFFile(BytesIO(engine))
    loads = [(index, segment) for index, segment in enumerate(elf.iter_segments())
             if segment["p_type"] == "PT_LOAD"]
    index, tail = loads[-1]
    state_index, state = loads[-2]
    if (tail["p_flags"] != 5 or tail["p_offset"] + tail["p_filesz"] != len(engine)
            or state["p_flags"] != 6):
        raise ValueError("Unexpected adventure load segments")
    with prior.open("rb") as file:
        state_address = ELFFile(file).get_section_by_name(".runtime")["sh_addr"]
    offset = (len(engine) + 15) & ~15
    address = tail["p_vaddr"] + offset - tail["p_offset"]
    code, state_size, entries = payload(ndk, output, address, state_address, False, True, True)
    if state_address < state["p_vaddr"] or state_address + state_size > tail["p_vaddr"]:
        raise ValueError("New adventure state does not fit in the existing writable segment")

    patched = bytearray(engine)
    for name, old, file in installed_entries(engine, elf, prior):
        patched[file:file + 4] = branch(old, entries[name])

    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def hook(site, stock, instructions, link=False):
        while len(code) % 4:
            code.append(0)
        target = address + len(code)
        stub = bytearray(assembler.asm(instructions + "\nanchor: .word 0", target)[0])
        struct.pack_into("<I", stub, len(stub) - 4, target + len(stub) - 4)
        file = file_offset(elf, site)
        if patched[file:file + 4] != stock:
            raise ValueError(f"Unexpected original instruction at {site:#x}")
        patched[file:file + 4] = branch(site, target, link)
        code.extend(stub)

    def helper(name, args):
        return f"{args}\nadr r0,anchor\nldr ip,[r0]\nsub r0,r0,ip\nbl #{entries[name]}"

    hook(STAR_RIBBON_ART, branch(STAR_RIBBON_ART, 0x1A965BC),
         star_ribbon_instructions(helper("asterAdventureOtherStarArt", "mov r1,r6")))

    hook(0x902280, struct.pack("<I", 0xE1550006), f"""
        push {{r0-r3,ip,lr}}
        {helper("asterAdventureLoadMultiStar", "mov r2,r0\nmov r1,r7")}
        cmp r0,#0
        pop {{r0-r3,ip,lr}}
        bne #0x902340
        cmp r5,r6
        b #0x902284
    """)

    # Keep ordinary failure advice, but a failed condition within a multi-star
    # run only disqualifies the stars that depend on it.
    hook(0x1FC6C0, struct.pack("<I", 0xE92D4870), f"""
        push {{r0-r3,ip,lr}}
        {helper("asterAdventureMultiStarFailure", "mov r2,r1\nmov r1,r0")}
        cmp r0,#0
        pop {{r0-r3,ip,lr}}
        bxne lr
        .word 0xe92d4870
        b #0x1fc6c4
    """)

    hook(0x903634, branch(0x903634, 0x902EA8, True), f"""
        mov r1,r0
        adr r0,anchor
        ldr ip,[r0]
        sub r0,r0,ip
        b #{entries["asterAdventureAwardMultiStar"]}
    """, link=True)

    hook(0x7B20D4, struct.pack("<I", 0xE59307F0), f"""
        push {{r0-r3,r12,lr}}
        {helper("asterAdventureMultiStarDescription", "mov r1,r3\nmov r2,r12")}
        cmp r0,#0
        strge r0,[sp]
        pop {{r0-r3,r12,lr}}
        bge #0x7b20e4
        ldr r0,[r3,#0x7f0]
        b #0x7b20d8
    """)

    hook(0x7B2238, struct.pack("<I", 0xE24BD020), f"""
        {helper("asterAdventureMergeMultiStarGoals", "mov r1,r7")}
        sub sp,r11,#32
        b #0x7b223c
    """)

    hook(0x7E5530, struct.pack("<I", 0xE3A01F91), f"""
        push {{r0-r3,ip,lr}}
        {helper("asterAdventureMultiStarTitle", "mov r1,r5")}
        pop {{r0-r3,ip,lr}}
        mov r1,#580
        b #0x7e5534
    """)

    # The original card centers short lists closer to the title. Lower the
    # combined five- and six-line lists into the body of the card.
    hook(0x8054E4, branch(0x8054E4, 0x15DEC20, True), f"""
        push {{r3,lr}}
        {helper("asterAdventureGoalListY", "mov r2,r0\nmov r1,r4")}
        pop {{r3,lr}}
        b #0x15dec20
    """, link=True)

    # The shorter pause card needs tighter spacing when all six goals fit
    # on one line each. Keep the font and the native vertical centering.
    hook(0x49E664, struct.pack("<I", 0xE2822001), """
        push {r3,ip}
        ldm r5,{r3,ip}
        sub r3,ip,r3
        cmp r3,#24
        add r2,r2,#1
        subhs r2,r2,r2,lsr #3
        subhs r2,r2,r2,lsr #5
        pop {r3,ip}
        b #0x49e668
    """)

    # Bind the collectable's standalone-image node at the stock star spawn.
    hook(0x998EC0, branch(0x998EC0, 0x21F2EC, True), f"""
        mov r2,r1
        mov r1,r0
        adr r0,anchor
        ldr ip,[r0]
        sub r0,r0,ip
        b #{entries["asterAdventureSpawnStarReward"]}
    """, link=True)

    # The fixed-image renderer holds its sprite's image reference at sb.
    hook(0x2FE020, branch(0x2FE020, 0x116A498, True), f"""
        sub r3,sb,#0x80
        push {{r3,lr}}
        {helper("asterAdventureDrawStarReward", "mov r3,r2\nmov r2,r1\nmov r1,r0")}
        pop {{r3,pc}}
    """, link=True)

    patched.extend(bytes(offset - len(patched)))
    patched.extend(code)
    table, stride = elf["e_phoff"], elf["e_phentsize"]
    length = len(patched) - tail["p_offset"]
    struct.pack_into("<II", patched, table + index * stride + 16, length, length)
    used_state = state_address + state_size - state["p_vaddr"]
    struct.pack_into("<I", patched, table + state_index * stride + 20, max(used_state, state["p_memsz"]))
    return bytes(patched)


def build(base, stock, prior, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    make_catalog(stock, output)
    write_packet_anchors(stock, output)
    write_user_plants(base, output)
    with ZipFile(base) as apk:
        patched = patch_guest(apk.read(ENGINE), ndk, output, prior)
        manifest = manifest_version(apk.read("AndroidManifest.xml"), 333, 332, prefix="A")
    result = output / "PvZ2-Unline-Aster-A333-ARM32-WSA-existing-data.apk"
    dex = social_dex(output / "social-dex", sdk)
    pack_apk(base, {ENGINE: patched, "classes8.dex": dex, "AndroidManifest.xml": manifest},
             sdk, result, signing)
    print(result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for argument in ("base", "stock", "prior", "output", "sdk", "ndk", "signing"):
        cli.add_argument("--" + argument, type=Path, required=True)
    build(**vars(cli.parse_args()))
