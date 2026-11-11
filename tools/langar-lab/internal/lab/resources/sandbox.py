"""Trusted Linux launcher: student code never sees the judge or report paths."""
import json
import ctypes
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


class Process:
    def __init__(self, command, *, readonly=(), writable=(), cwd='/tmp', **kwargs):
        if os.geteuid() != 0:
            raise RuntimeError('Run the course judge with sudo; sandboxed code runs as nobody')
        # Root delegates only nobody's UID/GID; no host policy changes are needed.
        keeper = subprocess.Popen([sys.executable, '-I', '-c',
                                   'import ctypes,os,time; libc=ctypes.CDLL(None,use_errno=True); '
                                   'r=libc.unshare(0x10000000); '
                                   'assert r == 0, os.strerror(ctypes.get_errno()); '
                                   'print("ready", flush=True); time.sleep(30)'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(keeper.stdout, selectors.EVENT_READ)
                if not selector.select(5) or keeper.stdout.readline() != b'ready\n':
                    raise RuntimeError('Cannot delegate a Linux user namespace')
            proc = Path(f'/proc/{keeper.pid}')
            (proc / 'uid_map').write_text('0 65534 1\n')
            (proc / 'setgroups').write_text('deny\n')
            (proc / 'gid_map').write_text('0 65534 1\n')
            userns = os.open(proc / 'ns/user', os.O_RDONLY)
        finally:
            keeper.terminate(); keeper.wait(); keeper.stdout.close(); keeper.stderr.close()
        info_r, info_w = os.pipe()
        block_r, block_w = os.pipe()
        args = ['/usr/bin/bwrap', '--unshare-pid',
                '--unshare-uts', '--unshare-ipc', '--unshare-net', '--as-pid-1',
                '--uid', '0', '--gid', '0', '--cap-add', 'ALL',
                '--die-with-parent', '--info-fd', str(info_w), '--block-fd', str(block_r)]
        for name in ('/usr', '/bin', '/sbin', '/lib', '/lib64', '/etc'):
            if Path(name).exists(): args += ['--ro-bind', name, name]
        args += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/var/tmp']
        for name in readonly: args += ['--ro-bind', str(name), str(name)]
        for name in writable: args += ['--bind', str(name), str(name)]
        args += ['--chdir', str(cwd), '--', *map(str, command)]
        libc = ctypes.CDLL(None, use_errno=True)
        def enter():
            os.setgroups([])
            if libc.setns(userns, 0x10000000):
                raise OSError(ctypes.get_errno(), 'setns user namespace')
            os.setresgid(0, 0, 0)
            os.setresuid(0, 0, 0)
        self.process = None
        try:
            self.process = subprocess.Popen(args, preexec_fn=enter, pass_fds=(info_w, block_r, userns), start_new_session=True, **kwargs)
            self.group_pid = self.process.pid
            os.close(info_w); info_w = None
            os.close(block_r); block_r = None
            data = b''; deadline = time.monotonic() + 10
            with selectors.DefaultSelector() as selector:
                selector.register(info_r, selectors.EVENT_READ)
                while True:
                    if not selector.select(max(0, deadline-time.monotonic())):
                        raise RuntimeError('Sandbox startup timed out')
                    chunk = os.read(info_r, 4096)
                    if not chunk: break
                    data += chunk
                    if len(data) > 16384: raise RuntimeError('Invalid sandbox startup metadata')
            if not data:
                _, err = self.process.communicate(timeout=2)
                raise RuntimeError('Bubblewrap startup failed: '+str(err))
            self.pid = json.loads(data)['child-pid']
            self.namespace_pid = 1
            self.namespaces = {name: os.readlink(f'/proc/{self.pid}/ns/{name}')
                               for name in ('pid', 'uts', 'mnt')}
            os.write(block_w, b'x')
        except BaseException:
            if self.process is not None:
                try: os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                self.process.wait()
            raise
        finally:
            for fd in (info_r, info_w, block_r, block_w, userns):
                if fd is not None: os.close(fd)

    def __getattr__(self, name):
        return getattr(self.process, name)

    def send_signal(self, sig):
        os.kill(self.pid, sig)

    def terminate(self):
        self.send_signal(signal.SIGTERM)
