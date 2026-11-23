"""Refresh the sign-in renderer in A325 and package an A326 ARM32 test build."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from elftools.elf.elffile import ELFFile

from build_aster_pvp_feedback import pack_apk
from build_aster_save_path_fix import manifest_version
from build_aster_sign_in_layout import A313_ENGINE, ENGINE
from prepare_aster_auto_pickup import patch_native
from prepare_aster_pvp_runtime import file_offset


A315_ENGINE = "a38e4669dc7cf5e8b555da310584d1639a1a6cf4178cfdd23aff51b0271143ca"
A325_ENGINE = "db35b598e51e1d92a725472476c74fd3180d62252fad1a6e6ac79904b170f170"
A313_SIGN_IN_HOOKS = {
    0xa1c920: 0x1ac5ecc, 0x418504: 0x1ac5ee4, 0xf655c8: 0x1ac5ef8, 0xf64c4c: 0x1ac5f0c,
    0xf68f38: 0x1ac5f20, 0xf64c64: 0x1ac5f34, 0xf629bc: 0x1ac5f50, 0xf68f58: 0x1ac5f78,
}


def refresh_renderer(engine, layout_base, installed, ndk, output):
    for version, data, digest in ((313, layout_base, A313_ENGINE), (315, installed, A315_ENGINE),
                                  (325, engine, A325_ENGINE)):
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"Expected A{version} ARM32 guest")

    refreshed = patch_native(layout_base, ndk, output, offline_sign_in=True, refresh_sign_in=True,
                             sign_in_hooks=A313_SIGN_IN_HOOKS, four_column_sign_in=True)
    baseline_elf, installed_elf, updated_elf, current_elf = (
        ELFFile(BytesIO(image)) for image in (layout_base, installed, refreshed, engine)
    )
    # A315 added the sign-in payload at the end of the original injected code.
    # Later builds retain that range and add their own patches elsewhere.
    code_index, state_index = 4, 7
    baseline_code = baseline_elf.get_segment(code_index)
    start = file_offset(current_elf, baseline_code["p_vaddr"] + baseline_code["p_filesz"])
    old_code, new_code, current_code = (elf.get_segment(code_index) for elf in
                                         (installed_elf, updated_elf, current_elf))
    old_end = old_code["p_offset"] + old_code["p_filesz"]
    new_end = new_code["p_offset"] + new_code["p_filesz"]
    if (old_code["p_offset"] != new_code["p_offset"] or old_code.header != current_code.header
            or not start < old_end <= new_end <= current_elf.get_segment(state_index)["p_offset"]
            or engine[start:old_end] != installed[start:old_end] or any(engine[old_end:new_end])):
        raise ValueError("A325 no longer has space for the refreshed sign-in payload")
    if installed_elf.get_segment(state_index).data() != updated_elf.get_segment(state_index).data():
        raise ValueError("Sign-in runtime data layout changed")

    result = bytearray(engine)
    result[start:new_end] = refreshed[start:new_end]
    report_path = output / "auto-pickup.json"
    report = json.loads(report_path.read_bytes())
    for site in map(int, report["hooks"]):
        old_offset = file_offset(installed_elf, site)
        new_offset = file_offset(updated_elf, site)
        current_offset = file_offset(current_elf, site)
        if engine[current_offset:current_offset + 4] != installed[old_offset:old_offset + 4]:
            raise ValueError(f"A325 sign-in hook changed at {site:#x}")
        result[current_offset:current_offset + 4] = refreshed[new_offset:new_offset + 4]
    header = current_elf["e_phoff"] + code_index * current_elf["e_phentsize"]
    struct.pack_into("<II", result, header + 16, new_code["p_filesz"], new_code["p_memsz"])
    report["sha256"] = sha256(result).hexdigest()
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="ascii")
    return bytes(result)


def build(base, layout_base, installed, output, sdk, ndk, signing):
    with ZipFile(layout_base) as previous, ZipFile(installed) as a315, ZipFile(base) as current:
        engine = refresh_renderer(current.read(ENGINE), previous.read(ENGINE), a315.read(ENGINE), ndk, output)
        manifest = manifest_version(current.read("AndroidManifest.xml"), 326, 325, prefix="A")
    apk = output / "PvZ2-Unline-Aster-A326-ARM32-WSA-existing-data.apk"
    pack_apk(base, {ENGINE: engine, "AndroidManifest.xml": manifest}, sdk, apk, signing)
    print(apk)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "layout-base", "installed", "output", "sdk", "ndk", "signing"):
        parser.add_argument("--" + name, required=True, type=Path)
    build(**vars(parser.parse_args()))
