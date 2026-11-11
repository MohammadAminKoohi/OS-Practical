#!/usr/bin/env python3
"""Cumulative Langar HW3-HW8 public functional judge. Linux, Python stdlib only.
Build student code unprivileged, then run this judge with sudo in the lab Linux.
Exit: 0 all passed, 1 functional failures, 2 infrastructure/setup failure.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location('baseline', HERE / 'hw2.py')
baseline = importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
require = baseline.require
CASES = {n: [] for n in range(3, 9)}

def case(hw, name, points):
    def register(fn):
        CASES[hw].append((name, points, fn)); return fn
    return register

class Harness(baseline.Harness):
    def __init__(self, binary, directory, cc, hw):
        super().__init__(binary, directory, cc)
        self.hw = hw
        self.runtime = self.directory / 'runtime-probe'
        subprocess.run([*shlex.split(cc), '-static', '-D_GNU_SOURCE', '-std=c11',
                        '-Wall', '-Wextra', '-Werror', str(HERE / 'probe_runtime.c'),
                        '-o', str(self.runtime)], check=True, timeout=60)
        self.root = rootfs.create(self.directory / 'rootfs', self.runtime) if hw >= 6 else None
        self.state = self.directory / 'state'; self.state.mkdir(); os.chown(self.state, 65534, 65534)
        self.env = dict(os.environ, LANGAR_STATE_DIR=str(self.state))
        self.ns_pid = 2 if hw >= 8 else 1
    def fresh(self, name):
        path = Path(tempfile.mkdtemp(prefix=name+'-', dir=self.directory)); path.chmod(0o755); return path
    def call(self, opts=(), command=None, **kwargs):
        return self.run(['run', *map(str, opts), '--', *(command if command is not None else [str(self.runtime), 'identity'])],
                        env=self.env, **kwargs)
    def launch(self, opts=(), command=None):
        return self.start(['run', *map(str, opts), '--', *(command if command is not None else [str(self.runtime), 'hold'])], env=self.env)
    def rootcall(self, command, opts=(), **kwargs):
        return self.call(['--isolate','--rootfs',self.root,*opts], command, **kwargs)
    def newimage(self, **kwargs):
        base = self.fresh('oci'); return image(base / 'image', self.runtime, **kwargs)
    def imagecall(self, img, command=(), **kwargs):
        return self.call(['--isolate','--image',img], command=list(command), **kwargs)

def read_line(p):
    data = b''; deadline = time.monotonic()+5
    with selectors.DefaultSelector() as selector:
        selector.register(p.stdout, selectors.EVENT_READ)
        while b'\n' not in data:
            require(selector.select(max(0, deadline-time.monotonic())), 'readiness timed out')
            block = os.read(p.stdout.fileno(), 1)
            require(block, 'process exited before readiness'); data += block
            require(len(data) < 8192, 'unexpected readiness output')
    return data

def finish(p):
    baseline.stop_group(p)
    for stream in (p.stdin, p.stdout, p.stderr):
        stream.close()

def good(result, output=None, status=0):
    code, out, err, _ = result
    require(code == status and (output is None or out == output) and not err,
            f'expected status {status}, output {output!r}, stderr empty; got {code}, {out[:300]!r}, {err[:4000]!r}')
    return out

@case(3, 'hw2_regression', 20)
def regression(h):
    for _, _, fn in baseline.CASES:
        fn(h)

@case(3, 'pid_namespace', 20)
def pid_namespace(h):
    out = good(h.call(['--isolate']))
    pid, ppid, _ = out.decode().split()
    require(int(pid) == h.ns_pid and int(ppid) == (1 if h.hw >= 8 else 0), 'wrong namespace PID/parent topology')
    p = h.launch(['--isolate'])
    try:
        read_line(p); read_line(p)
        children = Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()
        require(len(children) == 1, 'launcher must have exactly one isolated child')
        require(os.readlink(f'/proc/{children[0]}/ns/pid') != p.namespaces['pid'], 'actual PID namespace unchanged')
        out, err = p.communicate(b'x', timeout=5)
        require(p.returncode == 0 and not out and not err, 'isolated wait failed')
    finally:
        finish(p)

@case(3, 'private_hostname', 15)
def hostname(h):
    out = good(h.call(['--isolate','--hostname','team-langar']))
    fields = out.decode().split()
    require(len(fields) == 3 and fields[2] == 'team-langar', 'hostname not applied or malformed probe output')

@case(3, 'default_hostname', 15)
def default_hostname(h):
    fields = good(h.call(['--isolate'])).decode().split()
    require(len(fields) == 3 and fields[2] == 'langar', 'expected default hostname langar')

@case(3, 'host_unchanged', 15)
def host_unchanged(h):
    before = Path('/proc/sys/kernel/hostname').read_text()
    good(h.call(['--isolate','--hostname','private-name']))
    require(Path('/proc/sys/kernel/hostname').read_text() == before, 'host hostname changed')
    p = h.launch(['--isolate'])
    try:
        read_line(p); read_line(p)
        child = Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()
        require(len(child) == 1, 'missing isolated child')
        require(os.readlink(f'/proc/{child[0]}/ns/uts') != p.namespaces['uts'], 'workload did not create a private UTS namespace')
        p.communicate(b'x', timeout=5)
    finally: finish(p)

@case(3, 'isolated_wait', 10)
def isolated_wait(h):
    p = h.launch(['--isolate'])
    try:
        read_line(p); require(read_line(p) == b'READY\n', 'missing checkpoint')
        require(p.poll() is None, 'launcher returned before workload')
        out, err = p.communicate(b'x', timeout=5)
        require(p.returncode == 0 and not out and not err, 'bad release/status')
    finally:
        finish(p)
    good(h.call(['--isolate'], [str(h.probe), 'exit', '42']), b'', status=42)
    for command, expected in ((['/langar-no-such-command'], 127), ([str(h.directory)], 126)):
        code, out, err, _ = h.call(['--isolate'], command)
        require(code == expected and not out and err, f'isolated exec failure must return {expected}')

@case(3, 'namespace_cli', 5)
def namespace_cli(h):
    for opts in (['--hostname','x'], ['--isolate','--hostname',''], ['--isolate','--isolate']):
        status, out, err, _ = h.call(opts)
        require(status == 2 and not out and err, 'invalid namespace CLI must return 2')

def previous(h):
    # Re-run earlier functional features with the explicitly changed HW8 topology.
    regression(h)
    for stage in range(3, h.hw):
        for name, _, fn in CASES[stage]:
            if name not in ('hw2_regression', 'previous_features'):
                fn(h)

























def tree_hash(root):
    import hashlib
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file(): h.update(p.read_bytes())
    return h.hexdigest()








COUNTS = {n: len(c) for n,c in CASES.items()}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assignment', type=int, choices=range(3,4), required=True)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--cc', default='gcc')
    p.add_argument('--json', type=Path)
    a = p.parse_args()
    def interrupted(_sig, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    results = []
    try:
        if sys.platform != 'linux' or os.geteuid() != 0:
            raise RuntimeError('HW3-HW8 judge requires Linux root in the lab environment; build unprivileged, then use sudo -n python3 judge/test_semester.py ...')
        subprocess.run(['unshare','--mount','--uts','--pid','--fork','true'],check=True,capture_output=True,timeout=5)
        binary = a.binary.resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK): raise RuntimeError('build q2/langar first')
        with tempfile.TemporaryDirectory(prefix='langar-tests-') as directory:
            h = Harness(binary, directory, a.cc, a.assignment)
            for name, points, fn in CASES[a.assignment]:
                error = None
                try: fn(h)
                except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as exc: error = str(exc)
                earned = points if error is None else 0
                results.append(dict(id=name,points=points,earned=earned,passed=error is None,error=error))
                print(f'{"PASS" if error is None else "FAIL"} {name}: {earned}/{points}',flush=True)
                if error: print(' ',error,flush=True)
    except KeyboardInterrupt:
        print('Judge interrupted; active workload cleaned up.', file=sys.stderr)
        return 130
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Environment/setup error:',exc,file=sys.stderr); return 2
    report = dict(assignment=f'hw{a.assignment:02d}-q2',score=sum(x['earned'] for x in results),
                  total=sum(x['points'] for x in results),results=results)
    print(f'Functional score: {report["score"]}/{report["total"]}')
    if a.json: a.json.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return 0 if all(x['passed'] for x in results) else 1

if __name__ == '__main__': sys.exit(main())
