#!/usr/bin/env python3
"""Supplied OCI v1.1.1 decoder and contained file operations; no layer policy.
Students call whiteout/remove/clear/copy primitives in the order they implement.
Selected Linux images: sha256, tar/gzip, root User, regular/dir/link entries.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import struct
import sys
import tarfile

MAX_BLOB = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024

def relative(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\x00' in name:
        raise ValueError('unsafe archive path: ' + repr(name))
    return str(p) if str(p) != '.' else ''

def inside(root, name, follow=True):
    """Resolve image symlinks as if root were /; never follow a host absolute link."""
    todo = list(PurePosixPath(name).parts)
    current = []
    hops = 0
    while todo:
        item = todo.pop(0)
        if item in ('', '.', '/'):
            continue
        if item == '..':
            if current:
                current.pop()
            continue
        candidate = root.joinpath(*current, item)
        if candidate.is_symlink() and (follow or todo):
            hops += 1
            if hops > 40:
                raise ValueError('symlink loop')
            target = os.readlink(candidate)
            if target.startswith('/'):
                current = []
            todo = list(PurePosixPath(target).parts) + todo
        else:
            current.append(item)
    return root.joinpath(*current)

def remove(root, name, clear=False):
    p = inside(root, relative(name), follow=False)
    if p == root and not clear:
        raise ValueError('cannot delete root')
    if clear:
        # Opaque directories may traverse an image-local symlink in an ancestor.
        if p.is_symlink():
            p.unlink()
        elif p.exists():
            if p.is_dir():
                for child in p.iterdir():
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            else:
                p.unlink()
        p.mkdir(parents=True, exist_ok=True)
    elif p.is_symlink() or p.is_file():
        p.unlink()
    elif p.exists():
        shutil.rmtree(p)

def blob(image, descriptor):
    digest = descriptor['digest']
    if not digest.startswith('sha256:') or len(digest) != 71:
        raise ValueError('only sha256 descriptors supported')
    hexpart = digest[7:]
    if any(c not in '0123456789abcdef' for c in hexpart):
        raise ValueError('invalid digest')
    p = image / 'blobs' / 'sha256' / hexpart
    if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_BLOB:
        raise ValueError('invalid blob')
    data = p.read_bytes()
    if len(data) != descriptor['size'] or hashlib.sha256(data).hexdigest() != hexpart:
        raise ValueError('descriptor size or digest mismatch')
    return data

def string(value):
    if not isinstance(value, str) or '\x00' in value:
        raise ValueError('invalid config string')
    data = value.encode('utf-8')
    return struct.pack('<I', len(data)) + data

def strings(items):
    if not isinstance(items, list) or len(items) > 4096:
        raise ValueError('invalid config array')
    return struct.pack('<I', len(items)) + b''.join(string(x) for x in items)

def layer_file(state, index):
    spec = json.loads((state / 'plan.json').read_text())
    return Path(spec['layers'][index])

def scan_layer(path):
    with tarfile.open(path, 'r:') as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > MAX_EXPANDED or len(members) > 100000:
            raise ValueError('layer too large')
        names = set()
        for m in members:
            name = relative(m.name)
            if name in names:
                raise ValueError('duplicate layer path')
            names.add(name)
            if not (m.isdir() or m.isfile() or m.issym() or m.islnk()):
                raise ValueError('unsupported layer entry type')
            if m.islnk():
                relative(m.linkname)
        return members

def prepare(image, state):
    image = image.resolve()
    if json.loads((image / 'oci-layout').read_text())['imageLayoutVersion'] != '1.0.0':
        raise ValueError('unsupported OCI layout')
    index = json.loads((image / 'index.json').read_text())
    manifests = index['manifests']
    if len(manifests) != 1:
        raise ValueError('provide one native manifest (use supplied importer)')
    manifest = json.loads(blob(image, manifests[0]))
    config = json.loads(blob(image, manifest['config']))
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if config['os'] != 'linux' or config['architecture'] != arch:
        raise ValueError('image platform does not match Linux host')
    cfg = config.get('config') or {}
    if cfg.get('User', '') not in ('', '0', 'root', '0:0', 'root:root'):
        raise ValueError('non-root image User is outside the course subset')
    cwd = cfg.get('WorkingDir') or '/'
    if not cwd.startswith('/'):
        raise ValueError('WorkingDir must be absolute')
    env = cfg.get('Env') or []
    if any(not isinstance(x, str) or '=' not in x or not x.split('=', 1)[0] for x in env):
        raise ValueError('invalid Env')
    layers = manifest['layers']
    diffids = config['rootfs']['diff_ids']
    if config['rootfs']['type'] != 'layers' or len(layers) != len(diffids):
        raise ValueError('rootfs DiffID count mismatch')
    if len(layers) > 128:
        raise ValueError('too many layers')
    paths = []
    for i, (descriptor, diffid) in enumerate(zip(layers, diffids)):
        raw = blob(image, descriptor)
        media = descriptor['mediaType']
        if media == 'application/vnd.oci.image.layer.v1.tar+gzip':
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
                parts = []; total = 0
                while True:
                    part = zipped.read(1024*1024)
                    if not part: break
                    total += len(part)
                    if total > MAX_EXPANDED: raise ValueError('expanded layer too large')
                    parts.append(part)
                data = b''.join(parts)
        elif media == 'application/vnd.oci.image.layer.v1.tar':
            data = raw
        else:
            raise ValueError('supported compression: tar or gzip')
        if len(data) > MAX_EXPANDED or 'sha256:' + hashlib.sha256(data).hexdigest() != diffid:
            raise ValueError('uncompressed DiffID mismatch')
        target = state / f'layer-{i}.tar'
        target.write_bytes(data)
        members = scan_layer(target)
        records = []
        for m in members:
            name = relative(m.name)
            p = PurePosixPath(name)
            if p.name == '.wh..wh..opq':
                records.append(b'1' + str(p.parent).encode() + b'\x00')
            elif p.name.startswith('.wh.'):
                victim = str(p.parent / p.name[4:])
                if not p.name[4:]:
                    raise ValueError('empty whiteout')
                records.append(b'0' + victim.encode() + b'\x00')
        (state / f'whiteouts-{i}').write_bytes(b''.join(records))
        paths.append(str(target))
    (state / 'plan.json').write_text(json.dumps({'layers': paths}))
    with (state / 'config.bin').open('wb') as f:
        f.write(struct.pack('<I', len(layers)))
        f.write(string(cwd))
        f.write(strings(env))
        f.write(strings(cfg.get('Entrypoint') or []))
        f.write(strings(cfg.get('Cmd') or []))
    (state / 'rootfs').mkdir()

def copy_layer(state, number):
    root = state / 'rootfs'
    path = layer_file(state, number)
    with tarfile.open(path, 'r:') as archive:
        deferred = []
        directories = []
        for m in archive.getmembers():
            name = relative(m.name)
            if not name or PurePosixPath(name).name.startswith('.wh.'):
                continue
            p = inside(root, name, follow=False)
            p.parent.mkdir(parents=True, exist_ok=True)
            if m.isdir():
                if p.is_symlink() or (p.exists() and not p.is_dir()):
                    remove(root, name)
                p.mkdir(exist_ok=True)
                directories.append((name, m.mode & 0o777))
                p.chmod(0o755)  # allow extraction before final directory modes
            elif m.islnk():
                deferred.append((name, relative(m.linkname)))
            else:
                remove(root, name)
                if m.issym():
                    p.symlink_to(m.linkname)
                elif m.isfile():
                    with archive.extractfile(m) as source, p.open('wb') as dest:
                        shutil.copyfileobj(source, dest)
                    p.chmod(m.mode & 0o777)
                else:
                    raise ValueError('unsupported entry type')
        while deferred:
            remaining = []
            for name, target in deferred:
                src = inside(root, target, follow=False)
                if not src.exists() or src.is_symlink() or src.is_dir():
                    remaining.append((name, target)); continue
                remove(root, name)
                os.link(src, inside(root, name, follow=False))
            if len(remaining) == len(deferred):
                raise ValueError('unresolved hardlink')
            deferred = remaining
        for name, mode in reversed(directories):
            inside(root, name).chmod(mode)

def main():
    action, *args = sys.argv[1:]
    if action == 'prepare':
        prepare(Path(args[0]), Path(args[1]))
    elif action == 'copy':
        copy_layer(Path(args[0]), int(args[1]))
    elif action in ('remove', 'clear'):
        remove(Path(args[0]), args[1], clear=action == 'clear')
    elif action == 'cleanup':
        state = Path(args[0])
        if state.name.startswith('langar-image-') and state.is_dir() and not state.is_symlink():
            shutil.rmtree(state)
        else:
            raise ValueError('invalid owned workspace')
    else:
        raise ValueError('invalid action')

if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, MemoryError, tarfile.TarError) as exc:
        print('image helper:', exc, file=sys.stderr)
        sys.exit(1)
