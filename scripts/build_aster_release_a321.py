"""Add the complete A305 resource volumes to the tested A321 build."""
import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, rebuild_dynamic_bootstrap
from build_aster_pickup_access import ENGINE
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a305 import ARM64_ENGINE, MANIFEST, RESOURCE_PARTS, entries
from build_aster_save_path_fix import manifest_version


BUILT_IN_FRIENDS = "assets/adventure/friends.json"
SHARED = (MANIFEST, ASSET, PLAN, "classes8.dex")


def build(test, base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    arm32 = base / "PvZ2-Unline-Aster-A305-ARM32.apk"
    arm64 = base / "PvZ2-Unline-Aster-A305-ARM64.apk"
    with ZipFile(test) as accepted, ZipFile(arm32) as full32, ZipFile(arm64) as full64:
        tested, stock32, stock64 = map(entries, (accepted, full32, full64))
        excluded = {BUILT_IN_FRIENDS}
        replacements = {*SHARED, BOOTSTRAP, ENGINE}
        if (stock32.keys() - tested.keys() != RESOURCE_PARTS | excluded
                or tested.keys() - stock32.keys()
                or {name for name in tested if tested[name] != stock32[name]} != replacements):
            raise ValueError("Unexpected differences between A321 test and A305 ARM32 full APKs")
        if (any(stock32[name] != stock64[name] for name in RESOURCE_PARTS | set(SHARED))
                or full32.read(ENGINE) != full64.read(ARM64_ENGINE)
                or BUILT_IN_FRIENDS not in stock64):
            raise ValueError("A305 ARM32 and ARM64 shared bases differ")

        shared = {name: accepted.read(name) for name in SHARED}
        if any(manifest_version(full.read(MANIFEST), 321, 305, prefix="A") != shared[MANIFEST]
               for full in (full32, full64)):
            raise ValueError("Release manifest differs from the tested A321 manifest")
        engine = accepted.read(ENGINE)
        bootstrap32 = accepted.read(BOOTSTRAP)
        bootstrap64 = rebuild_dynamic_bootstrap(full64.read(BOOTSTRAP), output / "bootstrap-ARM64",
                                                 full64.read(ASSET), shared[ASSET])

    for abi, source, guest, bootstrap in (
            ("ARM32", arm32, ENGINE, bootstrap32), ("ARM64", arm64, ARM64_ENGINE, bootstrap64)):
        final = output / f"PvZ2-Unline-Aster-A321-{abi}.apk"
        pack_apk(source, {**shared, BOOTSTRAP: bootstrap, guest: engine}, sdk, final, signing,
                 excluded=excluded)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("test", "base", "output", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
