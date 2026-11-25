"""Build the A355 ARM64 package from the tested ARM32 and both A350 releases."""

import argparse
from pathlib import Path
from zipfile import ZipFile

from build_aster_pvp_feedback import pack_apk
from build_aster_release_a325 import ARM64_ENGINE, ENGINE, MANIFEST, RESOURCE_PARTS, entries
from build_aster_save_path_fix import manifest_version


def build(accepted, base, output, sdk, signing):
    arm32 = base / "PvZ2-Unline-Aster-A350-ARM32.apk"
    arm64 = base / "PvZ2-Unline-Aster-A350-ARM64.apk"
    shared = {MANIFEST, "classes8.dex"}
    with ZipFile(accepted) as candidate, ZipFile(arm32) as old32, ZipFile(arm64) as old64:
        current, prior32, prior64 = map(entries, (candidate, old32, old64))
        if (current.keys() != prior32.keys()
                or {name for name in current if current[name] != prior32[name]} != shared | {ENGINE}):
            raise ValueError("Unexpected file changes relative to A350 ARM32")
        if (any(prior32[name] != prior64[name] for name in RESOURCE_PARTS | shared)
                or old32.read(ENGINE) != old64.read(ARM64_ENGINE)):
            raise ValueError("The A350 bases disagree on shared resources or engine")
        updates = {name: candidate.read(name) for name in shared}
        if manifest_version(old64.read(MANIFEST), 355, 350, prefix="A") != updates[MANIFEST]:
            raise ValueError("ARM64 manifest differs from the tested A355 manifest")
        updates[ARM64_ENGINE] = candidate.read(ENGINE)
    output.parent.mkdir(parents=True, exist_ok=True)
    pack_apk(arm64, updates, sdk, output, signing)
    with ZipFile(output) as result:
        if any(result.read(name) != data for name, data in updates.items()):
            raise ValueError("The release package differs from the tested shared files")
    print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("accepted", "base", "output", "sdk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))

