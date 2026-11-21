"""Build A201 with a smooth width-aware normal view on the A199 guest engine."""
import argparse
import hashlib
from io import BytesIO
import os
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from prepare_aster_pvp_runtime import file_offset
from prepare_profile_memory import branch

ROOT = Path(__file__).resolve().parents[1]
ENGINE = "1443c8421ab9c8b795fb513e16019613af270a6b1aca176d3e8e4a3d8d2d6f74"
ORIGINAL = {
    0x1a2d01c: bytes.fromhex("f04f2de91cb08de2"),
    0x1a2d590: bytes.fromhex("000052e3"),
    0x1a383bc: bytes.fromhex("48c005e323c040e3"),
}


def patch(engine, ndk, output):
    if hashlib.sha256(engine).hexdigest() != ENGINE:
        raise ValueError("Expected the shared A199 engine")
    elf = ELFFile(BytesIO(engine))
    for address, expected in ORIGINAL.items():
        offset = file_offset(elf, address, len(expected))
        if engine[offset:offset + len(expected)] != expected:
            raise ValueError(f"Incorrect camera instruction at {address:#x}")
    (index, rx), (state_index, rw) = [(i, p) for i, p in enumerate(elf.iter_segments()) if p["p_type"] == "PT_LOAD"][-2:]
    if (rx["p_flags"], rw["p_flags"]) != (5, 6) or rx["p_filesz"] != rx["p_memsz"]:
        raise ValueError("Unexpected A199 injected segments")
    used = (rx["p_filesz"] + 15) & ~15
    start = rx["p_vaddr"] + used
    state_start = (rw["p_vaddr"] + rw["p_memsz"] + 15) & ~15
    output.mkdir(parents=True, exist_ok=True)
    tools = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    obj, linked, script = [output / ("viewport-" + name) for name in ("fit.o", "fit.elf", "fit.ld")]
    flags = ["--target=armv7a-linux-androideabi24", "-marm", "-mfpu=vfpv3-d16", "-mfloat-abi=softfp",
             "-Os", "-fPIC", "-ffreestanding", "-fno-builtin", "-fno-exceptions", "-fno-rtti",
             "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables"]
    subprocess.run([tools / "clang++.exe", *flags, "-c", ROOT / "src/view-angle/viewport_fit.cpp",
                    "-o", obj], check=True)
    with obj.open("rb") as stream:
        if any(rel["r_info_type"] == 2 for sec in ELFFile(stream).iter_sections()
               if sec["sh_type"] == "SHT_REL" and ".exidx" not in sec.name for rel in sec.iter_relocations()):
            raise ValueError("Viewport helper uses an absolute relocation")
    script.write_text(
        f"SECTIONS {{ . = {start}; .payload : {{ *(.text*) *(.rodata*) }} "
        f". = {state_start}; .viewstate (NOLOAD) : {{ *(.bss*) }} "
        "/DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) } }",
        encoding="ascii")
    subprocess.run([tools / "ld.lld.exe", "-T", script, "--no-undefined", "--entry=asterViewportDraw",
                    obj, "-o", linked], check=True)
    with linked.open("rb") as stream:
        payload_elf = ELFFile(stream)
        section = payload_elf.get_section_by_name(".payload")
        state = payload_elf.get_section_by_name(".viewstate")
        code = section.data()
        if (section["sh_addr"] != start or state["sh_addr"] != state_start or state["sh_type"] != "SHT_NOBITS"
                or any(s["sh_size"] and s["sh_flags"] & 2 and s.name not in (".payload", ".viewstate")
                       for s in payload_elf.iter_sections())):
            raise ValueError("Unexpected viewport helper sections")
        state_end = state_start + state["sh_size"]
        symbols = {s.name: s["st_value"] for s in payload_elf.get_section_by_name(".symtab").iter_symbols()
                   if s.name.startswith("asterViewport")}
    adapter = start + len(code)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    # Camera's tail calls DrawBoard(board, graphics), after applying its pan
    # and clip. Keep that work and insert our matrix there instead.
    code += bytes(assembler.asm(f"""
        mov r2, r1
        mov r1, r0
        adr r0, anchor
        ldr ip, [r0]
        sub r0, r0, ip
        b #{symbols["asterViewportDraw"]}
        anchor: .word {adapter + 24}
    """, adapter)[0])
    start_at = rx["p_offset"] + used
    end_at = start_at + len(code)
    if end_at > rw["p_offset"] or any(engine[start_at:end_at]):
        raise ValueError("Viewport helper needs more than the A199 RX padding")
    result = bytearray(engine)
    result[start_at:end_at] = code
    entry = 0x1a2d01c
    # The previous wrapper received (base, board, graphics). The native
    # camera entry expects only (board, graphics) and reconstructs base.
    sites = {
        entry: bytes(assembler.asm("mov r0, r1; mov r1, r2", entry)[0]) + branch(entry + 8, 0x1a2b1c4, False),
        0x1a2d590: branch(0x1a2d590, symbols["asterViewportPoint"], False),
        0x1a383bc: bytes(assembler.asm(f"movw ip, #{adapter & 65535}; movt ip, #{adapter >> 16}", 0x1a383bc)[0]),
    }
    for address, new in sites.items():
        offset = file_offset(elf, address, len(new))
        result[offset:offset + len(new)] = new
    segment = elf["e_phoff"] + index * elf["e_phentsize"] + 16
    struct.pack_into("<II", result, segment, used + len(code), used + len(code))
    # Only extend the zero-filled part of the final writable segment.
    state_segment = elf["e_phoff"] + state_index * elf["e_phentsize"] + 20
    struct.pack_into("<I", result, state_segment, state_end - rw["p_vaddr"])
    return bytes(result), symbols


def build(args):
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(args.jdk / "bin") + os.pathsep + os.environ["PATH"]
    with ZipFile(args.base / "PvZ2-Unline-Aster-A199-ARM32.apk") as z:
        updated, _ = patch(z.read("lib/armeabi/libSrc.so"), args.ndk, args.output / "native")
    (args.output / "native/libSrc.so").write_bytes(updated)
    for abi, member in (("ARM32", "lib/armeabi/libSrc.so"), ("ARM64", "assets/guest_libs/libSrc_a32.so")):
        apk = args.base / f"PvZ2-Unline-Aster-A199-{abi}.apk"
        with ZipFile(apk) as z:
            if hashlib.sha256(z.read(member)).hexdigest() != ENGINE:
                raise ValueError("ARM32 and ARM64 must start with the same engine")
            manifest = manifest_version(z.read("AndroidManifest.xml"), 201, 199, prefix="A")
        target = args.output / f"PvZ2-Unline-Aster-A201-{abi}.apk"
        pack_apk(apk, {member: updated, "AndroidManifest.xml": manifest}, args.sdk, target, args.signing)
        print(target, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("base", "output", "sdk", "ndk", "jdk", "signing"):
        parser.add_argument("--" + arg, type=Path, required=True)
    build(parser.parse_args())
