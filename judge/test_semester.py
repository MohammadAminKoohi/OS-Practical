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
from fixtures import image
spec = importlib.util.spec_from_file_location('baseline', HERE / 'hw2.py')
baseline = importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
rootfs_tool = HERE.parent / 'tools/make_rootfs.py'
if not rootfs_tool.is_file(): rootfs_tool = HERE / 'tools/make_rootfs.py'
spec = importlib.util.spec_from_file_location('rootfs', rootfs_tool)
rootfs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rootfs)
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

@case(4, 'previous_features', 20)
def previous4(h): previous(h)

@case(4, 'cpu_affinity', 20)
def affinity(h):
    cpu = min(os.sched_getaffinity(0))
    out = good(h.call(['--cpus',str(cpu)], [str(h.runtime),'resources']))
    require(out.split()[0] == f'{cpu},'.encode(), 'affinity mask not applied')

@case(4, 'address_space_limit', 20)
def address_limit(h):
    out = good(h.call(['--as-limit-mib','64'], [str(h.runtime),'resources']))
    require([int(x) for x in out.split()[1:]] == [64*1024*1024]*2, 'RLIMIT_AS soft and hard limits must both be 64 MiB')

@case(4, 'bounded_allocation', 15)
def allocation(h):
    good(h.call(['--as-limit-mib','64'], [str(h.runtime),'allocate','128']), b'DENIED\n')
    good(h.call(['--as-limit-mib','64'], [str(h.runtime),'allocate','8']), b'OK\n')

@case(4, 'combined_controls', 15)
def combined(h):
    cpu = min(os.sched_getaffinity(0))
    mask, soft, hard = good(h.call(['--isolate','--cpus',str(cpu),'--as-limit-mib','64'],
                              [str(h.runtime),'resources'])).split()
    require(mask == f'{cpu},'.encode() and int(soft) == int(hard) == 64*1024*1024, 'combined controls failed')
    parent_mask = os.sched_getaffinity(0)
    before = next(line for line in Path('/proc/self/limits').read_text().splitlines() if line.startswith('Max address space'))
    p = h.launch(['--cpus',str(cpu),'--as-limit-mib','64'])
    try:
        read_line(p); read_line(p)
        current = next(line for line in Path(f'/proc/{p.pid}/limits').read_text().splitlines() if line.startswith('Max address space'))
        require(os.sched_getaffinity(p.pid) == parent_mask and current == before,
                'resource settings changed the launcher instead of only the workload')
        p.communicate(b'x',timeout=5)
    finally: finish(p)

@case(4, 'invalid_resource_options', 10)
def invalid_resources(h):
    for opts, expected in ((['--as-limit-mib','-1'],2), (['--as-limit-mib','0'],2),
                           (['--cpus','1,'],1), (['--cpus','invalid'],1), (['--cpus','999999'],1)):
        status, out, err, _ = h.call(opts)
        require(status == expected and not out and err, f'invalid resources {opts} need status {expected}')

@case(5, 'previous_features', 20)
def previous5(h): previous(h)

@case(5, 'private_mount_namespace', 20)
def mount_namespace(h):
    p = h.launch(['--isolate'])
    try:
        read_line(p); read_line(p)
        children = Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()
        require(children, 'missing init child')
        require(os.readlink(f'/proc/{children[0]}/ns/mnt') != p.namespaces['mnt'], 'mount namespace unchanged')
        p.communicate(b'x', timeout=5)
    finally: finish(p)

@case(5, 'private_procfs', 30)
def procfs(h):
    pid, proc_pid = good(h.call(['--isolate'], [str(h.runtime),'proc'])).split()
    require(int(pid) == h.ns_pid and pid == proc_pid, '/proc/self PID differs from getpid')

@case(5, 'host_mounts_unchanged', 20)
def host_mounts(h):
    before = Path('/proc/self/mountinfo').read_bytes()
    good(h.call(['--isolate']))
    require(Path('/proc/self/mountinfo').read_bytes() == before, 'host mount table changed')

@case(5, 'isolated_exec_failure', 10)
def exec_failure(h):
    code, out, err, _ = h.call(['--isolate'], ['/langar-missing-command'])
    require(code == 127 and not out and err, 'isolated missing exec must return 127')

@case(6, 'previous_features', 20)
def previous6(h): previous(h)

@case(6, 'rootfs_contents', 20)
def root_contents(h): good(h.rootcall(['/bin/cat','/etc/marker']), b'inside-langar\n')

@case(6, 'host_path_hidden', 15)
def host_hidden(h):
    marker = h.fresh('host') / 'host-only'; marker.write_text('host')
    code, _, _, _ = h.rootcall(['/bin/cat',str(marker)])
    require(code != 0, 'host-only absolute path was visible')

@case(6, 'root_working_directory', 10)
def root_cwd(h): good(h.rootcall(['/bin/pwd']), b'/\n')

@case(6, 'dynamic_executable', 10)
def dynamic(h): good(h.rootcall(['/bin/dynamic-echo','linked']), b'linked\n')

@case(6, 'rootfs_procfs', 15)
def root_proc(h):
    pid, proc_pid = good(h.rootcall(['/bin/probe','proc'])).split()
    require(pid == proc_pid and int(pid) == h.ns_pid, 'rootfs /proc incorrect')

@case(6, 'rootfs_failures', 10)
def bad_root(h):
    code, out, err, _ = h.call(['--isolate','--rootfs',h.directory/'does-not-exist'])
    require(code == 1 and not out and err, 'invalid rootfs setup must fail with 1')
    code, out, err, _ = h.rootcall(['/missing'])
    require(code == 127 and not out and err, 'rootfs missing exec must return 127')

@case(7, 'previous_features', 20)
def previous7(h): previous(h)

@case(7, 'image_default_command', 10)
def image_default(h):
    img = h.newimage()
    out = good(h.imagecall(img)); require(int(out.split()[0]) == h.ns_pid, 'default Cmd not executed')

@case(7, 'image_config_and_overrides', 20)
def image_config(h):
    img = h.newimage(config={'Entrypoint':['/bin/probe'], 'Cmd':['env','COURSE_VALUE'],
                             'Env':['COURSE_VALUE=image-value'], 'WorkingDir':'/work'})
    good(h.imagecall(img), b'image-value\n')
    good(h.imagecall(img, ['env','PATH']), b'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n')
    # Check cwd with supplied probe mode added below, and absence of host env.
    good(h.imagecall(img, ['cwd']), b'/work\n')
    code, _, _, _ = h.imagecall(img, ['env','LANGAR_STATE_DIR'])
    require(code == 4, 'host environment leaked into image')

@case(7, 'layer_changes_and_whiteouts', 20)
def layers(h):
    entries = [('bin',None),('bin/probe',h.runtime.read_bytes()),('proc',None),('work',None),
               ('work/deleted',b'gone'),('work/replaced',b'old'),('opaque',None),('opaque/old',b'old')]
    upper = [('work/replaced',b'new'),('opaque/new',b'new'),('opaque/.wh..wh..opq',b''),
             ('work/.wh.deleted',b''),('work/link',('symlink','replaced')),('work/hard',('hardlink','work/replaced'))]
    img = h.newimage(layers=[entries,upper], config={'Cmd':['/bin/probe','layer-check']})
    good(h.imagecall(img), b'LAYERS-OK\n')

@case(7, 'independent_writable_runs', 15)
def writable(h):
    img = h.newimage(config={'Cmd':['/bin/probe','write-check']})
    before = tree_hash(img)
    for _ in range(2): good(h.imagecall(img), b'base\n')
    require(tree_hash(img) == before, 'immutable image modified')
    processes = [h.start(['run','--isolate','--image',str(img),'--'],env=h.env) for _ in range(2)]
    try:
        for proc in processes:
            out, err = proc.communicate(timeout=8)
            require(proc.returncode == 0 and out == b'base\n' and not err, 'concurrent image writes interfered')
    finally:
        for proc in processes: finish(proc)

@case(7, 'invalid_images_and_cleanup', 15)
def invalid_images(h):
    for kw in ({'arch':'unsupported'}, {'corrupt':True}, {'config':{'User':'1000','Cmd':['/bin/probe','identity']}},
               {'layers':[[('../escape',b'invalid')]]}):
        code, out, err, _ = h.imagecall(h.newimage(**kw))
        require(code == 1 and not out and err, 'invalid image must fail setup with status 1')
    require(not list(h.state.iterdir()), 'per-run state leaked after image execution/failure')

def tree_hash(root):
    import hashlib
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file(): h.update(p.read_bytes())
    return h.hexdigest()

@case(8, 'previous_features', 20)
def previous8(h): previous(h)

@case(8, 'init_and_workload_topology', 10)
def topology(h): pid_namespace(h)

@case(8, 'termination_signal_forwarding', 15)
def forwarding(h):
    for sig, expected in ((signal.SIGTERM,23),(signal.SIGINT,24)):
        p = h.launch(['--isolate'], [str(h.runtime),'signal'])
        try:
            require(read_line(p) == b'READY\n', 'not ready')
            p.send_signal(sig); out, err = p.communicate(timeout=5)
            require(p.returncode == expected and out == f'GOT {sig}\n'.encode() and not err, 'signal not forwarded/status lost')
        finally: finish(p)

@case(8, 'process_group_forwarding', 10)
def group_forward(h):
    p = h.launch(['--isolate'], [str(h.runtime),'group'])
    try:
        require(read_line(p) == b'READY\n', 'group not ready')
        p.terminate(); out, err = p.communicate(timeout=5)
        require(p.returncode == 31 and out == b'GRANDCHILD-SIGNAL\n' and not err, 'descendant did not receive group signal')
    finally: finish(p)

@case(8, 'orphan_reaping', 20)
def orphan(h):
    p = h.launch(['--isolate'], [str(h.runtime),'orphan'])
    try:
        require(read_line(p) == b'REAPED\n', 'orphan remains zombie while main is alive')
        require(read_line(p) == b'READY\n' and p.poll() is None, 'main did not remain alive')
        out, err = p.communicate(b'x', timeout=5)
        require(p.returncode == 42 and not out and not err, 'main status not retained')
    finally: finish(p)

@case(8, 'main_status_and_signal_mask', 10)
def main_status(h):
    good(h.call(['--isolate'],[str(h.runtime),'exit-other']), b'', status=42)
    good(h.call(['--isolate'],[str(h.runtime),'mask']), b'0 0 0\n')

@case(8, 'forced_shutdown_and_cleanup', 15)
def forced(h):
    p = h.launch(['--isolate'], [str(h.runtime),'ignore'])
    try:
        require(read_line(p) == b'READY\n', 'not ready')
        p.terminate(); out, err = p.communicate(timeout=5)
        require(p.returncode == 137 and not out and not err, 'bounded forced termination must return 137')
    finally: finish(p)
    invalid_images(h)

COUNTS = {n: len(c) for n,c in CASES.items()}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assignment', type=int, choices=range(3,9), required=True)
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
