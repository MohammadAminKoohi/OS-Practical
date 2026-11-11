"""Deterministic tiny OCI fixtures, built locally without a registry."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import tarfile

def tar(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        for name, value in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o755 if name == 'bin/probe' else 0o644
            if isinstance(value, tuple):
                kind, target = value
                info.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
                info.linkname = target
                archive.addfile(info)
            elif value is None:
                info.type = tarfile.DIRTYPE; info.mode = 0o755; archive.addfile(info)
            else:
                info.size = len(value); archive.addfile(info, io.BytesIO(value))
    return data.getvalue()

def image(path, probe, *, config=None, layers=None, arch=None, corrupt=False):
    path.mkdir()
    blobs = path / 'blobs/sha256'; blobs.mkdir(parents=True)
    def store(data, media):
        digest = hashlib.sha256(data).hexdigest(); (blobs / digest).write_bytes(data)
        return dict(mediaType=media, digest='sha256:'+digest, size=len(data))
    if layers is None:
        layers = [[('bin', None), ('bin/probe', probe.read_bytes()), ('proc', None),
                   ('work', None), ('work/value', b'base\n'), ('tmp', None)]]
    descriptors, diffids = [], []
    for entries in layers:
        data = tar(entries); diffids.append('sha256:'+hashlib.sha256(data).hexdigest())
        descriptors.append(store(gzip.compress(data, mtime=0), 'application/vnd.oci.image.layer.v1.tar+gzip'))
    conf = dict(architecture=arch or {'x86_64':'amd64','aarch64':'arm64'}[platform.machine()],
                os='linux', config=config or {'Cmd':['/bin/probe','identity']},
                rootfs=dict(type='layers', diff_ids=diffids))
    cd = store(json.dumps(conf).encode(), 'application/vnd.oci.image.config.v1+json')
    manifest = dict(schemaVersion=2, mediaType='application/vnd.oci.image.manifest.v1+json', config=cd, layers=descriptors)
    md = store(json.dumps(manifest).encode(), 'application/vnd.oci.image.manifest.v1+json')
    (path / 'index.json').write_text(json.dumps(dict(schemaVersion=2, manifests=[md])))
    (path / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
    if corrupt:
        (blobs / descriptors[0]['digest'][7:]).write_bytes(b'corrupt')
    return path
