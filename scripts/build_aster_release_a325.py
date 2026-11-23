"""Package the tested A325 build with A321's complete resources and launchers."""
import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_hud_pickup import ASSET, BOOTSTRAP, rebuild_dynamic_bootstrap
from build_aster_pvp_feedback import pack_apk
from build_aster_release_a321 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS, SHARED, entries
from build_aster_save_path_fix import manifest_version


def build(test, base, output, sdk, signing):
    output.mkdir(parents=True, exist_ok=True)
    arm32 = base / "PvZ2-Unline-Aster-A321-ARM32.apk"
    arm64 = base / "PvZ2-Unline-Aster-A321-ARM64.apk"
    with ZipFile(test) as accepted, ZipFile(arm32) as full32, ZipFile(arm64) as full64:
        tested, stock32, stock64 = map(entries, (accepted, full32, full64))
        if (stock32.keys() - tested.keys() != RESOURCE_PARTS or tested.keys() - stock32.keys()
                or {name for name in tested if tested[name] != stock32[name]} != {*SHARED, BOOTSTRAP, ENGINE}):
            raise ValueError("Unexpected differences between tested A325 and A321 ARM32")
        if (any(stock32[name] != stock64[name] for name in RESOURCE_PARTS | set(SHARED))
                or full32.read(ENGINE) != full64.read(ARM64_ENGINE)):
            raise ValueError("A321 ARM32 and ARM64 shared bases differ")

        shared = {name: accepted.read(name) for name in SHARED}
        if any(manifest_version(full.read(MANIFEST), 325, 321, prefix="A") != shared[MANIFEST]
               for full in (full32, full64)):
            raise ValueError("Release manifest differs from the tested A325 manifest")
        engine = accepted.read(ENGINE)
        bootstrap32 = accepted.read(BOOTSTRAP)
        bootstrap64 = rebuild_dynamic_bootstrap(full64.read(BOOTSTRAP), output / "bootstrap-ARM64",
                                                 full64.read(ASSET), shared[ASSET])

    for abi, source, guest, bootstrap in (
            ("ARM32", arm32, ENGINE, bootstrap32), ("ARM64", arm64, ARM64_ENGINE, bootstrap64)):
        final = output / f"PvZ2-Unline-Aster-A325-{abi}.apk"
        pack_apk(source, {**shared, BOOTSTRAP: bootstrap, guest: engine}, sdk, final, signing)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("test", "base", "output", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
