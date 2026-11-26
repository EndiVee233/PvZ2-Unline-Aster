"""Package Qin Chapter One from A461 without the four-rank test encounter."""

import argparse
from pathlib import Path
import shutil
from zipfile import ZipFile

from build_aster_qin_almanac import register_zombie_card_types
from build_aster_qin_zoybean import (
    ASSET, BASELINE, BOOTSTRAP, ENGINE, LEVEL_MODULES, MANIFEST, PLAN, SHEET_PACKAGE,
    TEST_LEVEL, TYPE_PACKAGE, Bundle, build_guest, create_plan, level_document, manifest_version,
    pack_apk, prepare_bank, prepare_moton_bank, rebuild_dynamic_bootstrap, replace_rton, resource, unwrap,
)
from build_aster_qin_zoybean_showcase import TARGET
from build_aster_release_a325 import ARM64_ENGINE, RESOURCE_PARTS, entries


SHIM = "lib/armeabi/libRestart.so"
ARM64_SHIM = "assets/guest_libs/libRestart_a32.so"
SHARED = {MANIFEST, ASSET, PLAN, BASELINE, *RESOURCE_PARTS}


def release_engine(args, work):
    moton = prepare_moton_bank(args.moton_bank.read_bytes())
    with ZipFile(args.donor) as donor:
        bundle = Bundle(unwrap(donor.read("assets/dynamic.rsb.smf")))
        rows = level_document(resource(bundle, LEVEL_MODULES), LEVEL_MODULES)["objects"]
        modules = {alias: row["objdata"] for row in rows for alias in row.get("aliases", ())}
        layouts = tuple(modules[name]["Roads"] for name in ("TunnelDefendDefaultX", "TunnelDefendDefault1"))
        del bundle
        audio = Bundle(unwrap(donor.read("assets/plant2.rsb.smf")))
        zoybean = prepare_bank(resource(audio, r"PLANT2_SOUNDBANKS\PLANT_ZOYBEAN.BNK"), moton)
    with ZipFile(args.upstream) as upstream:
        return register_zombie_card_types(build_guest(
            upstream.read(ENGINE), args.ndk, work, layouts, args.qin_bank.read_bytes(),
            moton, args.tea_bank.read_bytes(), zoybean,
        ))


def remove_showcase_type(document):
    rows = document["objects"]
    target, = (row for row in rows if TARGET in row.get("aliases", ()))
    rows.remove(target)


def arm32(args, output):
    work = output.parent
    work.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.sample) as sample:
        example = level_document(resource(Bundle(sample.read(ASSET)), TEST_LEVEL), TEST_LEVEL)
    with ZipFile(args.accepted) as accepted:
        old = accepted.read(ASSET)
        bundle = Bundle(old)

        def restore_example(document):
            document.clear()
            document.update(example)

        replace_rton(bundle, TEST_LEVEL, restore_example, allow_growth=True)
        for package in (TYPE_PACKAGE, SHEET_PACKAGE):
            replace_rton(bundle, package, remove_showcase_type, allow_growth=True)
        dynamic = bundle.build()
        assert level_document(resource(Bundle(dynamic), TEST_LEVEL), TEST_LEVEL) == example
        plan = create_plan(dynamic, work, rgba_atlases=len(bundle.textures) - 2)
        bootstrap = rebuild_dynamic_bootstrap(accepted.read(BOOTSTRAP), work / "bootstrap-ARM32", old, dynamic)
        manifest = manifest_version(accepted.read(MANIFEST), 462, 461, prefix="A")
    del bundle, old
    engine = release_engine(args, work)
    assert b"AsterZoybeanTest" not in engine
    pack_apk(args.accepted, {MANIFEST: manifest, ASSET: dynamic, PLAN: plan, BOOTSTRAP: bootstrap, ENGINE: engine},
             args.sdk, output, args.signing)


def arm64(args, released32, output):
    work = output.parent
    with ZipFile(args.baseline32) as stock32, ZipFile(args.baseline64) as stock64, ZipFile(released32) as release:
        prior32, prior64, candidate = map(entries, (stock32, stock64, release))
        assert candidate.keys() == prior32.keys()
        assert {name for name in candidate if candidate[name] != prior32[name]} == SHARED | {BOOTSTRAP, ENGINE, SHIM}
        assert all(prior32[name] == prior64[name] for name in SHARED)
        assert stock32.read(ENGINE) == stock64.read(ARM64_ENGINE)
        assert stock32.read(SHIM) == stock64.read(ARM64_SHIM)

        updates = {name: release.read(name) for name in SHARED - RESOURCE_PARTS}
        assert manifest_version(stock64.read(MANIFEST), 462, 355, prefix="A") == updates[MANIFEST]
        updates[BOOTSTRAP] = rebuild_dynamic_bootstrap(
            stock64.read(BOOTSTRAP), work / "bootstrap-ARM64", stock64.read(ASSET), updates[ASSET],
        )
        updates[ARM64_ENGINE] = release.read(ENGINE)
        updates[ARM64_SHIM] = release.read(SHIM)
        parts = work / "shared-resources"
        parts.mkdir(exist_ok=True)
        for name in sorted(RESOURCE_PARTS):
            path = parts / Path(name).name
            with release.open(name) as src, path.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            updates[name] = path
    pack_apk(args.baseline64, updates, args.sdk, output, args.signing)
    with ZipFile(output) as result:
        shipped = entries(result)
        assert all(shipped[name] == candidate[name] for name in SHARED)
        assert shipped[ARM64_ENGINE] == candidate[ENGINE] and shipped[ARM64_SHIM] == candidate[SHIM]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    for name in ("sdk", "signing", "output-dir"):
        common.add_argument("--" + name, type=Path, required=True)
    commands = parser.add_subparsers(dest="abi", required=True)
    build32 = commands.add_parser("ARM32", parents=[common])
    for name in ("accepted", "sample", "donor", "upstream", "qin-bank", "moton-bank", "tea-bank", "ndk"):
        build32.add_argument("--" + name, type=Path, required=True)
    build64 = commands.add_parser("ARM64", parents=[common])
    for name in ("baseline32", "baseline64"):
        build64.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    out32 = args.output_dir / "PvZ2-Unline-Aster-A462-ARM32.apk"
    output = args.output_dir / f"PvZ2-Unline-Aster-A462-{args.abi}.apk"
    if args.abi == "ARM32":
        arm32(args, output)
    else:
        arm64(args, out32, output)
    print(output, flush=True)
