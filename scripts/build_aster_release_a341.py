"""Package the A341 WSA build with the full resources and ARM64 launcher."""

import argparse
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

from build_aster_arm64_game import ROOT, retarget_arm64_guest_loads
from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, rebuild_dynamic_bootstrap
from build_aster_no_lucky_treasure import launch_art_update
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS, entries
from build_aster_save_path_fix import manifest_version
from build_aster_zomboss_art import PATCH_ASSET, insert_update


GUEST_DEX = ("classes6.dex", "classes7.dex")
SHARED = (MANIFEST, ASSET, PLAN, "classes8.dex")
EXTRA = (
    "classes9.dex",
    "assets/reconstruction/aster-lucky-art-uiactive.patch",
    "assets/reconstruction/aster-lucky-art-uicommon.patch",
    PATCH_ASSET,
)


def retarget_guest_dex(dexes, output):
    output.mkdir(exist_ok=True)
    apktool = ROOT.parent / "tools/apktool.jar"
    subprocess.run(["javac", "-cp", apktool, "-d", output, ROOT / "scripts/RepairDex.java"], check=True)
    repair = ["java", "-Xmx256m", "-cp", str(apktool) + os.pathsep + str(output), "RepairDex"]
    rebuilt = {}
    for name, data in dexes.items():
        original = output / name
        tree = output / original.stem
        original.write_bytes(data)
        subprocess.run([*repair, "decode", original, tree], check=True)
        changed = []
        for path in tree.rglob("*.smali"):
            original_code = path.read_text(encoding="utf8")
            code = retarget_arm64_guest_loads(original_code)
            if code != original_code:
                path.write_text(code, encoding="utf8")
                changed.append(path.stem)
        expected = {"PresetEditor"} if name == "classes6.dex" else {"AsterRgbaPilot"}
        if set(changed) != expected:
            raise ValueError(f"Unexpected native library loads in {name}: {changed}")
        target = output / ("guest-" + name)
        subprocess.run([*repair, "encode", tree, target], check=True)
        rebuilt[name] = target.read_bytes()
    return rebuilt


def build(test, base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    arm32 = base / "PvZ2-Unline-Aster-A325-ARM32.apk"
    arm64 = base / "PvZ2-Unline-Aster-A325-ARM64.apk"
    with ZipFile(test) as tested, ZipFile(arm32) as full32, ZipFile(arm64) as full64:
        candidate, stock32, stock64 = map(entries, (tested, full32, full64))
        changed = {name for name in candidate.keys() & stock32.keys() if candidate[name] != stock32[name]}
        if (stock32.keys() - candidate.keys() != RESOURCE_PARTS
                or candidate.keys() - stock32.keys() != set(EXTRA)
                or changed != {*SHARED, *GUEST_DEX, BOOTSTRAP, ENGINE}):
            raise ValueError("Unexpected A341 runtime changes relative to A325")
        if (any(stock32[name] != stock64[name] for name in RESOURCE_PARTS | set(SHARED))
                or full32.read(ENGINE) != full64.read(ARM64_ENGINE)):
            raise ValueError("A325 ARM32 and ARM64 resource or guest engine mismatch")

        shared = {name: tested.read(name) for name in SHARED}
        if any(manifest_version(full.read(MANIFEST), 341, 325, prefix="A") != shared[MANIFEST]
               for full in (full32, full64)):
            raise ValueError("Release manifest differs from the WSA test manifest")
        engine = tested.read(ENGINE)
        extras = {name: tested.read(name) for name in EXTRA}
        dex32 = {name: tested.read(name) for name in GUEST_DEX}
        dex64 = retarget_guest_dex(dex32, output / "java-ARM64")
        dex32[BOOTSTRAP] = tested.read(BOOTSTRAP)
        dex64[BOOTSTRAP] = rebuild_dynamic_bootstrap(
            full64.read(BOOTSTRAP), output / "bootstrap-ARM64", full64.read(ASSET), shared[ASSET],
            transform=lambda smali: insert_update(launch_art_update(smali)))

    for abi, source, guest, dex in (
            ("ARM32", arm32, ENGINE, dex32), ("ARM64", arm64, ARM64_ENGINE, dex64)):
        final = output / f"PvZ2-Unline-Aster-A341-{abi}.apk"
        pack_apk(source, {**shared, **dex, guest: engine}, sdk, final, signing, extra_entries=extras)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("test", "base", "output", "sdk", "signing"):
        parser.add_argument("--" + option, type=Path, required=True)
    build(**vars(parser.parse_args()))
