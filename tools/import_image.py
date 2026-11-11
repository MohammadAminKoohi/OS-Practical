#!/usr/bin/env python3
"""Supplied transport wrapper. Run in Linux; downloading is not student work.
Requires skopeo. Output is one native-platform OCI manifest. Pin by digest for
reproducible use. Do not run this tool with sudo; the runtime uses sudo later.
"""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('reference', help='e.g. docker.io/library/alpine@sha256:...')
    p.add_argument('directory', type=Path)
    a = p.parse_args()
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if sys.platform != 'linux' or not arch:
        p.error('run inside native Linux or the course VM (amd64/arm64)')
    if not shutil.which('skopeo'):
        p.error('install skopeo: sudo apt install skopeo')
    if a.directory.exists():
        p.error('destination must not already exist')
    a.directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.directory.parent, prefix='.langar-import-') as tmp:
        target = Path(tmp) / 'image'
        subprocess.run(['skopeo', '--override-os', 'linux', '--override-arch', arch,
                        'copy', '--format', 'oci', 'docker://' + a.reference,
                        'oci:' + str(target) + ':course'], check=True)
        index = json.loads((target / 'index.json').read_text())
        receipt = dict(reference=a.reference, platform='linux/'+arch,
                       manifest=index['manifests'][0]['digest'])
        (target / 'import-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
        target.rename(a.directory)
    print('Imported', receipt['manifest'], 'to', a.directory)
    return 0

if __name__ == '__main__':
    sys.exit(main())
