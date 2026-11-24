"""Pair the accepted A350 ARM32 APK with the upgraded A341 ARM64 launcher."""

import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, rebuild_dynamic_bootstrap
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS, entries
from build_aster_save_path_fix import manifest_version
from build_aster_social_map_and_pvp_prices import CATALOG


def build(accepted, base, output, sdk, signing):
    output.parent.mkdir(parents=True, exist_ok=True)
    arm32 = base / "PvZ2-Unline-Aster-A341-ARM32.apk"
    arm64 = base / "PvZ2-Unline-Aster-A341-ARM64.apk"
    shared = {MANIFEST, ASSET, PLAN, CATALOG}
    with ZipFile(accepted) as candidate, ZipFile(arm32) as old32, ZipFile(arm64) as old64:
        current, prior32, prior64 = map(entries, (candidate, old32, old64))
        if current.keys() != prior32.keys() or {
            name for name in current if current[name] != prior32[name]
        } != shared | {ENGINE, BOOTSTRAP}:
            raise ValueError("Unexpected changes from the A341 release")
        if (any(prior32[name] != prior64[name] for name in RESOURCE_PARTS | shared)
                or old32.read(ENGINE) != old64.read(ARM64_ENGINE)):
            raise ValueError("The A341 release packages have different shared inputs")
        updates = {name: candidate.read(name) for name in shared}
        if manifest_version(old64.read(MANIFEST), 350, 341, prefix="A") != updates[MANIFEST]:
            raise ValueError("A350 ARM64 manifest differs from the accepted ARM32 manifest")
        updates[ARM64_ENGINE] = candidate.read(ENGINE)
        updates[BOOTSTRAP] = rebuild_dynamic_bootstrap(
            old64.read(BOOTSTRAP), output.parent / "bootstrap-ARM64", old64.read(ASSET), updates[ASSET]
        )
    pack_apk(arm64, updates, sdk, output, signing)
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("accepted", "base", "output", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
