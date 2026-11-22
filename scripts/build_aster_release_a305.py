"""Package the accepted A305 ARM32 build and its shared guest for release."""
import argparse
from pathlib import Path
import re
from zipfile import ZipFile

from build_aster_adventure_records import hook_save_restore, hook_social_frame
from build_aster_hud_pickup import ASSET, BOOTSTRAP, PLAN, rebuild_dynamic_bootstrap
from build_aster_pickup_access import ENGINE, patch_native
from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version


ARM64_ENGINE = "assets/guest_libs/libSrc_a32.so"
MANIFEST = "AndroidManifest.xml"
RESOURCE_PARTS = {f"assets/pvz2data.zip.{index:03d}" for index in range(1, 4)}
SOCIAL_DATA = ("assets/adventure/friends.json", "assets/adventure/levels.json", "classes8.dex")
COMMON = (ASSET, PLAN)


def entries(apk):
    return {i.filename: (i.CRC, i.file_size) for i in apk.infolist()
            if not re.fullmatch(r"META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))", i.filename, re.I)}


def build(test, seed, base, output, sdk, ndk, signing):
    output.mkdir(parents=True, exist_ok=True)
    arm32 = base / "PvZ2-Unline-Aster-A250-ARM32.apk"
    arm64 = base / "PvZ2-Unline-Aster-A250-ARM64.apk"
    with ZipFile(test) as accepted, ZipFile(seed) as a303, ZipFile(arm32) as full32, ZipFile(arm64) as full64:
        engine = accepted.read(ENGINE)
        if engine != patch_native(a303.read(ENGINE), ndk, output):
            raise ValueError("The installed A305 engine differs from the release source")
        test_entries, prior_entries, arm64_entries = map(entries, (accepted, full32, full64))
        changed = {ENGINE, MANIFEST, "classes.dex", BOOTSTRAP, *COMMON}
        if (prior_entries.keys() - test_entries.keys() != RESOURCE_PARTS
                or test_entries.keys() - prior_entries.keys() != set(SOCIAL_DATA)
                or {name for name in test_entries.keys() & prior_entries.keys()
                    if test_entries[name] != prior_entries[name]} != changed):
            raise ValueError("Unexpected difference between the runtime APK and complete resource base")
        if any(prior_entries[name] != arm64_entries[name] for name in RESOURCE_PARTS | set(COMMON)):
            raise ValueError("ARM32 and ARM64 resource bases differ")

        manifest = accepted.read(MANIFEST)
        if any(manifest_version(full.read(MANIFEST), 305, 250, prefix="A") != manifest
               for full in (full32, full64)):
            raise ValueError("Release manifest differs from the tested manifest")

        shared = {name: accepted.read(name) for name in (*COMMON, MANIFEST)}
        extra = {name: accepted.read(name) for name in SOCIAL_DATA}
        current32 = {name: accepted.read(name) for name in ("classes.dex", BOOTSTRAP)}
        current64 = {
            "classes.dex": hook_social_frame(full64.read("classes.dex"), output / "renderer-ARM64"),
            BOOTSTRAP: rebuild_dynamic_bootstrap(full64.read(BOOTSTRAP), output / "bootstrap-ARM64",
                                                 full64.read(ASSET), shared[ASSET], transform=hook_save_restore),
        }

    for abi, source, guest, executable in (
            ("ARM32", arm32, ENGINE, current32), ("ARM64", arm64, ARM64_ENGINE, current64)):
        final = output / f"PvZ2-Unline-Aster-A305-{abi}.apk"
        pack_apk(source, {**shared, **executable, guest: engine}, sdk, final, signing,
                 extra_entries=extra)
        print(final, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("test", "seed", "base", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(**vars(parser.parse_args()))
