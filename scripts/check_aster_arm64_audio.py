"""Measure first-frame, PCM and AudioFlinger progress on a backed-up A196 test instance."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

PACKAGE = 'com.pvz2unline.aster'
START = PACKAGE + '/com.popcap.pvz2cthd.BootActivity'


def audio_track(report, pid):
    # MuMu Android 12 "Tracks" rows include track ID, active, client PID,
    # requested sample rate, and a hex server frame counter.
    pattern = (r'^\s*(\d+)\s+yes\s+' + re.escape(pid)
               + r'\s+\d+\s+\d+\s+[A-Z]\s+\S+\s+\S+\s+\S+\s+(\d+)'
                 r'\s+.*?\s([0-9a-fA-F]{8})\s+\d+\s+\d+\s+[A-Za-z]\s+(\d+)\s+')
    match = re.search(pattern, report, re.MULTILINE)
    if match:
        guest_time = float(report.splitlines()[0].split()[0])
        return dict(track=int(match[1]), rate=int(match[2]), frames=int(match[3], 16),
                    underruns=int(match[4]), device_uptime=guest_time)


def check(adb, serial, count, output):
    def android(*args):
        return subprocess.run([adb, '-s', serial, *args], encoding='utf8', errors='replace',
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=True, timeout=45).stdout

    def sample_track(pid):
        return audio_track(android('shell', 'cat /proc/uptime && dumpsys media.audio_flinger'), pid)

    meta = android('shell', 'dumpsys', 'package', PACKAGE)
    if 'primaryCpuAbi=arm64-v8a' not in meta or 'versionName=1.7.5-Unline-Aster-A196' not in meta:
        raise ValueError('Expected the A196 ARM64 test package')
    if android('shell', 'getprop', 'ro.build.version.sdk').strip() != '32':
        raise ValueError('This AudioFlinger report parser expects the tested API 32 image')
    samples = []
    for n in range(count):
        android('shell', 'am', 'force-stop', PACKAGE)
        android('shell', 'am', 'start', '-n', START)
        deadline = time.monotonic() + 135
        first_frame = False
        pcm = False
        pid = None
        first = None
        while time.monotonic() < deadline:
            current = android('shell', 'pidof ' + PACKAGE + ' || true').strip()
            if current and current.isdigit():
                if pid and current != pid:
                    raise RuntimeError('Game process restarted during audio check')
                pid = current
                log = android('logcat', '-d', '--pid=' + pid, '-s', 'AsterArm64:I', 'AsterAudio:I')
                first_frame |= 'First real game frame returned' in log
                pcm |= 'First non-silent PCM buffer accepted' in log
                if first_frame and pcm:
                    first = sample_track(pid)
                    if first:
                        break
            time.sleep(1)
        time.sleep(4)
        second = sample_track(pid) if pid else None
        delta = ((second['frames'] - first['frames']) % (1 << 32)
                 if first and second and first['track'] == second['track'] else 0)
        # The host can deschedule the Python sampler for longer than the requested
        # sleep. Compare against the guest clock at each actual observation.
        seconds = second['device_uptime'] - first['device_uptime'] if first and second else 0
        expected = seconds * first['rate'] if first else 0
        ok = bool(first_frame and pcm and first and second and first['rate'] == second['rate']
                  and seconds > 0 and .6 * expected < delta < 1.4 * expected
                  and second['underruns'] == 0)
        samples.append(dict(start=n + 1, pid=pid, real_frame=first_frame, non_silent_pcm=pcm,
                            first=first, second=second, advanced_frames=delta, passed=ok))
        output.write_text(json.dumps(samples, indent=2), encoding='utf8')
        print(json.dumps(samples[-1]), flush=True)
        if not ok:
            raise RuntimeError('Audio check failed; see the saved per-process evidence')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('adb')
    parser.add_argument('serial')
    parser.add_argument('output', type=Path)
    parser.add_argument('--count', type=int, default=3)
    args = parser.parse_args()
    if args.count < 1:
        parser.error('count must be positive')
    check(args.adb, args.serial, args.count, args.output)
