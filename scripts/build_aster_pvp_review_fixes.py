"""Rebuild the A195 PvP guest and migration DEX, optionally packaging both A190 APKs.

The historical symbol-bearing A187 guest build and A190's generated resource
headers are separate inputs. They are not in the release source repository.
"""
import argparse
import hashlib
from pathlib import Path
from shutil import copyfile
from zipfile import ZipFile

from py3rijndael import RijndaelCbc, ZeroPadding

from build_preset_importer import build as build_importer
from prepare_aster_pvp_feedback import NEW_CODE, NEW_STATE, ROOT, compile_payload, patch_engine

GUEST_A190 = "ec31ac99ed7e33e722b49b0aff43ec0943bd8c9fb4f8e58904eecd7cc87acb05"
TEMPLATE_A190 = "ee08d895f7fb56670f8cb834896e6c90d8f67ab37a28f7404dd35425ae73b0c6"


def prepare_template(archive, folder):
    with ZipFile(archive) as apk:
        encrypted = apk.read("assets/pvz2tool/saves/save_1/pp.dat")
    if hashlib.sha256(encrypted).hexdigest() != TEMPLATE_A190:
        raise ValueError("Unexpected bundled A190 test profile")
    key = hashlib.md5(b"com_popcap_pvz2_magento_product_2013_05_05").hexdigest().encode()
    cipher = RijndaelCbc(key, key[4:28], ZeroPadding(24), block_size=24)
    raw = cipher.decrypt(encrypted[2:]).rstrip(b"\0")
    if not (raw.startswith(b"RTON") and raw.endswith(b"DONE")):
        raise ValueError("Invalid test profile template")
    lines = [",".join(map(str, raw[offset:offset + 32])) + "," for offset in range(0, len(raw), 32)]
    (folder / "all_one_template.h").write_text(
        "alignas(4) static constexpr unsigned char allOneRton[]={\n" + "\n".join(lines) + "\n};\n",
        encoding="ascii",
    )


def build(args):
    if bool(args.arm64) != bool(args.signing):
        raise ValueError("To package both APKs, provide both --arm64 and --signing")
    generated = args.output / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    names = ("dave_presets.h", "evolution_presets.h", "exchange_presets.h", "neighbor_catalog.h",
             "npc_presets.h", "preset_editor_catalog.h", "progression_presets.h", "research_presets.h",
             "training_presets.h")
    for name in names:
        copyfile(args.headers / name, generated / name)
    for name in ("evolution-presets.json", "research-presets.json", "exchange-presets.json"):
        copyfile(args.headers / name, generated / name)
    prepare_template(args.arm32, generated)
    with ZipFile(args.arm32) as source:
        (args.output / "catalogue.json").write_bytes(source.read("assets/pvp-presets/catalogue.json"))
    compiled = compile_payload(args.sdk, ROOT / "src", generated, args.output / "native",
                               NEW_CODE, NEW_STATE, archived=False)
    if args.a187_engine.suffix.lower() == ".apk":
        with ZipFile(args.a187_engine) as apk:
            previous = apk.read("lib/armeabi/libSrc.so")
    else:
        previous = args.a187_engine.read_bytes()
    native, _ = patch_engine(previous, args.baseline / "offline.elf", compiled)
    (args.output / "libSrc.so").write_bytes(native)
    copyfile(compiled, args.output / "offline.elf")
    migration = build_importer(args.output / "profile-migration", sdk=args.sdk)
    (args.output / "classes9.dex").write_bytes(migration)
    if args.signing:
        from aster_release_apk import manifest_version, pack_apk, sha
        for architecture, apk, guest in (("ARM32", args.arm32, "lib/armeabi/libSrc.so"),
                                        ("ARM64", args.arm64, "assets/guest_libs/libSrc_a32.so")):
            with ZipFile(apk) as source:
                if sha(source.read(guest)) != GUEST_A190:
                    raise ValueError(f"Unexpected {architecture} A190 guest")
                manifest = manifest_version(source.read("AndroidManifest.xml"), 195, 190, prefix="A")
            target = args.output / f"PvZ2-Unline-Aster-A195-{architecture}.apk"
            pack_apk(apk, {guest: native, "AndroidManifest.xml": manifest, "classes9.dex": migration},
                     args.sdk, target, args.signing)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm32", type=Path, required=True, help="published A190 ARM32 APK")
    parser.add_argument("--a187-engine", type=Path, required=True, help="A187 ARM32 APK or its lib/armeabi/libSrc.so")
    parser.add_argument("--baseline", type=Path, required=True, help="A187 symbol-bearing offline.elf and offline.o")
    parser.add_argument("--headers", type=Path, required=True, help="A190 generated PvP headers directory")
    parser.add_argument("--sdk", type=Path, required=True, help="Android SDK with NDK 27.0.12077973 and Build Tools 34.0.0")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arm64", type=Path, help="published A190 ARM64 APK")
    parser.add_argument("--signing", type=Path, help="local signing configuration for the two output APKs")
    build(parser.parse_args())
