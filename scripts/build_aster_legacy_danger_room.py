"""Enable the original Egypt Danger Room map node on the shared A203 engine."""
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
ENGINE = "05c7f06941d35eb929e328dd39a727934c20a38a333f5ed431ed2e9a96827470"
STATUS_CALL = 0x9eade0
EGYPT_EXCLUSIONS = ((0x7471d0, 0x7471f0), (0x747548, 0x747568))


def patch(engine, ndk, output):
    if hashlib.sha256(engine).hexdigest() != ENGINE:
        raise ValueError("Expected the shared A203 guest engine")
    elf = ELFFile(BytesIO(engine))
    loads = [(index, item) for index, item in enumerate(elf.iter_segments()) if item["p_type"] == "PT_LOAD"]
    (index, rx), (_, rw) = loads[-2:]
    if rx["p_flags"] != 5 or rw["p_flags"] != 6 or rx["p_filesz"] != rx["p_memsz"]:
        raise ValueError("Unexpected native payload segments")
    used = (rx["p_filesz"] + 15) & ~15
    start = rx["p_vaddr"] + used
    output.mkdir(parents=True, exist_ok=True)
    tool = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    obj = output / "unlock.o"
    linker = output / "unlock.ld"
    linked = output / "unlock.elf"
    flags = ["--target=armv7a-linux-androideabi24", "-marm", "-Os", "-fPIC", "-ffreestanding",
             "-fno-builtin", "-fno-exceptions", "-fno-rtti", "-fno-stack-protector",
             "-fno-unwind-tables", "-fno-asynchronous-unwind-tables"]
    subprocess.run([tool / "clang++.exe", *flags, "-c", ROOT / "src/legacy-danger-room/unlock.cpp",
                    "-o", obj], check=True)
    linker.write_text(f"SECTIONS {{ . = {start}; .payload : {{ *(.text*) *(.rodata*) }} "
                      "/DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) } }\n",
                      encoding="ascii")
    subprocess.run([tool / "ld.lld.exe", "-T", linker, "--no-undefined",
                    "--entry=asterLegacyDangerRoomProgress", obj, "-o", linked], check=True)
    with linked.open("rb") as stream:
        payload = ELFFile(stream)
        section = payload.get_section_by_name(".payload")
        if section["sh_addr"] != start or any(
                s["sh_size"] and s["sh_flags"] & 2 and s.name != ".payload" for s in payload.iter_sections()):
            raise ValueError("Unexpected unlock payload sections")
        code = section.data()
        helper, = payload.get_section_by_name(".symtab").get_symbol_by_name("asterLegacyDangerRoomProgress")
        target = helper["st_value"]
    code += b"\0" * (-len(code) % 4)
    hook = start + len(code)
    assembler = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    code += bytes(assembler.asm(f"""
        mov r3, r4
        mov r2, r1
        mov r1, r0
        adr r0, anchor
        ldr ip, [r0]
        sub r0, r0, ip
        b #{target}
        anchor: .word {hook + 28}
    """, hook)[0])
    physical = rx["p_offset"] + used
    end = physical + len(code)
    if end > rw["p_offset"] or any(engine[physical:end]):
        raise ValueError("Unlock helper needs more room in the executable segment")
    patched = bytearray(engine)
    patched[physical:end] = code

    def replace(address, before, after):
        offset = file_offset(elf, address, len(before))
        if patched[offset:offset + len(before)] != before:
            raise ValueError(f"Unexpected engine instruction at {address:#x}")
        patched[offset:offset + len(before)] = after

    replace(STATUS_CALL, branch(STATUS_CALL, 0x708104, True), branch(STATUS_CALL, hook, True))
    for address, destination in EGYPT_EXCLUSIONS:
        # Ignore only the Egypt name comparison. Pirate and Cowboy keep the old guards.
        jump = branch(address, destination, False)
        conditional = jump[:3] + b"\x1a"
        replace(address, conditional, jump)
    header = elf["e_phoff"] + index * elf["e_phentsize"] + 16
    struct.pack_into("<II", patched, header, used + len(code), used + len(code))
    return bytes(patched)


def build(base, output, sdk, ndk, jdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(jdk / "bin") + os.pathsep + os.environ["PATH"]
    original = None
    for abi, member in (("ARM32", "lib/armeabi/libSrc.so"),
                        ("ARM64", "assets/guest_libs/libSrc_a32.so")):
        source = base / f"PvZ2-Unline-Aster-A203-{abi}.apk"
        with ZipFile(source) as apk:
            engine = apk.read(member)
            manifest = manifest_version(apk.read("AndroidManifest.xml"), 204, 203, prefix="A")
        if original is None:
            original = engine
            updated = patch(engine, ndk, output / "native")
            (output / "native/libSrc.so").write_bytes(updated)
        elif engine != original:
            raise ValueError("ARM64 guest engine differs from ARM32")
        final = output / f"PvZ2-Unline-Aster-A204-{abi}.apk"
        pack_apk(source, {member: updated, "AndroidManifest.xml": manifest}, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "output", "sdk", "ndk", "jdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
