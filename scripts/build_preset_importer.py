"""Compile the profile migration DEX, optionally including its test entry point."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def build(out, test=False, sdk=None):
    sdk = sdk or os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        raise ValueError("Pass --sdk or set ANDROID_HOME to your Android SDK")
    sdk = Path(sdk)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    platform = sdk / "platforms/android-34/android.jar"
    compiler = sdk / "build-tools/34.0.0/lib/d8.jar"
    sources = [ROOT / "src/bootstrap-extra/com/popcap/pvz2cthd/PresetProfileImporter.java"]
    if test:
        sources.append(ROOT / "src/bootstrap-extra-test/com/popcap/pvz2cthd/PresetImporterTest.java")
    with TemporaryDirectory(dir=out) as temporary:
        workspace = Path(temporary)
        classes = workspace / "classes"
        dex = workspace / "dex"
        classes.mkdir()
        dex.mkdir()
        subprocess.run(["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8",
                        "-Xlint:-options", "-bootclasspath", str(platform), "-d", str(classes),
                        *sources], check=True)
        archive = workspace / "classes.jar"
        with ZipFile(archive, "w") as jar:
            for entry in sorted(classes.rglob("*.class")):
                jar.write(entry, entry.relative_to(classes).as_posix())
        subprocess.run(["java", "-Xmx256m", "-cp", str(compiler), "com.android.tools.r8.D8",
                        "--min-api", "21", "--lib", str(platform), "--output", str(dex),
                        str(archive)], check=True)
        raw = (dex / "classes.dex").read_bytes()
    (out / "dex").mkdir(exist_ok=True)
    (out / "dex/classes.dex").write_bytes(raw)
    report = {"sha256": hashlib.sha256(raw).hexdigest(),
              "sources": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources}, "synthetic_test_only": test}
    (out / "build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    return raw


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=ROOT / "work/preset-v86")
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    build(args.output, args.test, args.sdk)
