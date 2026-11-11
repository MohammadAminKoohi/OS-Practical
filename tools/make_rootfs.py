#!/usr/bin/env python3
"""Create the supplied native-architecture rootfs fixture inside Linux."""
import argparse
from pathlib import Path
import shutil
import subprocess

def create(root, probe=None):
    root.mkdir(parents=True, exist_ok=False)
    for name in ('bin', 'proc', 'tmp', 'work', 'etc'):
        (root / name).mkdir()
    busybox = shutil.which('busybox')
    if not busybox:
        raise RuntimeError('install busybox-static in Linux')
    # Verify static packaging; Ubuntu busybox-static is the supported fixture.
    detail = subprocess.run(['ldd', busybox], capture_output=True, text=True)
    if detail.returncode == 0:
        raise RuntimeError('busybox must be statically linked (busybox-static)')
    shutil.copy2(busybox, root / 'bin/busybox')
    for name in ('sh', 'echo', 'cat', 'pwd', 'hostname', 'sleep', 'ls', 'env', 'true', 'false'):
        (root / 'bin' / name).symlink_to('busybox')
    (root / 'etc/marker').write_text('inside-langar\n')
    if probe:
        shutil.copy2(probe, root / 'bin/probe')
    # A supplied dynamic executable plus its interpreter/libraries for HW6.
    executable = Path('/bin/echo')
    shutil.copy2(executable, root / 'bin/dynamic-echo')
    output = subprocess.check_output(['ldd', str(executable)], text=True)
    import re
    for name in re.findall(r'(/[^\s()]+)', output):
        source = Path(name)
        dest = root / str(source).lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    (root / 'tmp').chmod(0o1777)
    return root

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    a = p.parse_args()
    create(a.directory)
