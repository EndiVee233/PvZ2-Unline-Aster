"""Queue a private battle command for the Aster WSA test build."""

import argparse
import os
import subprocess


COMMANDS = {"clear": "C", "sweep": "R", "stop": "S"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args()
    adb = os.environ.get("PVZ2_ADB", "Y:/Android/Sdk/platform-tools/adb.exe")
    command = COMMANDS[args.command]
    script = ("tmp=$(mktemp cache/aster-battle-tools.XXXXXX) || exit 1\n"
              f'printf %s {command} >"$tmp" && mv -f "$tmp" cache/aster-battle-tools.cmd\n')
    subprocess.run([adb, "shell", "run-as com.pvz2unline.aster sh"],
                   input=script.encode("ascii"), check=True)
    print("Command queued for the running battle-tools build.")


if __name__ == "__main__":
    main()
