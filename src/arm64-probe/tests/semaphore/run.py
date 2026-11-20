"""Compile the production semaphore thunks twice and run them against the same Bionic API."""
import argparse
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent

def between(source, start, after):
    return source[source.index(start):source.index(after, source.index(start))]

def test(mode, source_file, compiler, adb, serial):
    source = source_file.read_text(encoding='utf-8')
    registry = between(source, 'struct Semaphore {', 'struct Once {')
    registry += '\nstd::mutex g_sync_mutex;\n'
    registry += next(line + '\n' for line in source.splitlines() if line.endswith(' g_semaphores;'))
    registry += between(source, 'std::shared_ptr<Semaphore> GetSemaphore(', 'int WaitCondition(')
    thunks = between(source, '    RegisterThunk("sem_init"', '    RegisterThunk("malloc"')
    with TemporaryDirectory(dir=HERE) as tmp:
        build = Path(tmp)
        (build/'registry.inc').write_text(registry)
        (build/'thunks.inc').write_text(thunks)
        binary = build/'semaphore-test'
        subprocess.run([str(compiler), '-std=c++20', '-O1', '-static-libstdc++',
                        '-I', str(build), str(HERE/'test.cpp'), '-o', str(binary)], check=True)
        remote = '/data/local/tmp/aster-a197-' + build.name
        device = [str(adb), '-s', serial]
        subprocess.run([*device, 'push', str(binary), remote], check=True, capture_output=True)
        try:
            subprocess.run([*device, 'shell', 'chmod', '700', remote], check=True)
            subprocess.run([*device, 'shell', remote, mode], check=True, timeout=15)
        finally:
            subprocess.run([*device, 'shell', 'rm', '-f', remote], check=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('fixed', type=Path)
    parser.add_argument('compiler', type=Path)
    parser.add_argument('adb', type=Path)
    parser.add_argument('serial')
    args = parser.parse_args()
    for mode, source in [('baseline', args.baseline), ('fixed', args.fixed)]:
        test(mode, source, args.compiler, args.adb, args.serial)
