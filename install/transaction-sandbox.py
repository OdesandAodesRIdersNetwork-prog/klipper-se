#!/usr/bin/env python3
"""Stage 7 sandbox-only host deployment transaction; NEVER installs on a real host.

Use a newly initialized /tmp or /mnt/data scratch root with a strict marker.
A validated 18-file Stage 5 payload is required for CLI --plan and --rehearse.
The only permitted mutations are new files under that inert scratch root.
Existing files are never replaced. On error, only transaction-owned files and
new directories are removed; unrelated sandbox content remains unchanged.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
MARKER = '.v3se-stage7-sandbox.json'
MARKER_BYTES = b'{"mode":"V3SE_SANDBOX_ONLY","schema":1}\n'
USER_RE = re.compile(r'[a-z_][a-z0-9_-]{0,31}\Z')
ALLOWED_PARENTS = (Path('/tmp'), Path('/mnt/data'))


def refuse(message):
    raise ValueError(message)


def plain_path(path):
    p = Path(path).expanduser().absolute()
    if p != p.resolve(strict=False):
        refuse('symlink or noncanonical path refused: ' + str(p))
    return p


def scratch_root(value, *, must_exist):
    p = plain_path(value)
    if p.parent not in ALLOWED_PARENTS:
        refuse('sandbox must be a direct child of /tmp or /mnt/data')
    if p == Path('/') or p.name in ('.', '..'):
        refuse('unsafe sandbox root')
    if must_exist:
        if not p.is_dir() or p.is_symlink():
            refuse('sandbox root missing or symlinked')
        token = p / MARKER
        if token.is_symlink() or not token.is_file() or token.read_bytes() != MARKER_BYTES:
            refuse('missing or invalid sandbox-only marker')
        if p.stat().st_uid != os.geteuid() or token.stat().st_uid != os.geteuid():
            refuse('sandbox root and marker must belong to invoking user')
    elif p.exists() or p.is_symlink():
        refuse('sandbox root already exists')
    return p


def initialize(path):
    root = scratch_root(path, must_exist=False)
    root.mkdir(mode=0o700)
    try:
        (root / MARKER).write_bytes(MARKER_BYTES)
        (root / MARKER).chmod(0o600)
    except BaseException:
        (root / MARKER).unlink(missing_ok=True)
        root.rmdir()
        raise
    return root


def loader():
    spec = importlib.util.spec_from_file_location('v3se_stage7_payload_verifier', HERE / 'simulate-deployment.py')
    if spec is None or spec.loader is None:
        refuse('cannot load mandatory Stage 5 payload verification')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified_payload(path):
    sandbox = loader()
    manifest, contents = sandbox.verify(Path(path))
    return manifest, contents, sandbox.FILES


def planned_entries(root, *, user, contents, mapping):
    if not USER_RE.fullmatch(user):
        refuse('invalid service username')
    if set(contents) != set(mapping) or not mapping:
        refuse('payload does not match strict destination allowlist')
    entries = []
    for source_name in sorted(contents):
        relative = Path(mapping[source_name].format(user=user))
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            refuse('unsafe destination mapping')
        dest = root / relative
        if dest == root or root not in dest.parents:
            refuse('destination outside scratch root')
        if dest.is_symlink() or os.path.lexists(dest):
            refuse('existing target (never overwrite): ' + str(relative))
        for parent in (root, *reversed(list(dest.parents)[:-1])):
            if root != parent and root not in parent.parents:
                continue
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                refuse('non-directory or symlinked parent: ' + str(parent))
        if not isinstance(contents[source_name], bytes):
            refuse('unverified payload bytes')
        entries.append((source_name, dest, contents[source_name]))
    return entries


def preview(root, *, user, contents, mapping):
    root = scratch_root(root, must_exist=True)
    entries = planned_entries(root, user=user, contents=contents, mapping=mapping)
    return {'status': 'SANDBOX_PLAN_ONLY', 'installation_approved': False,
            'sandbox_root': str(root), 'files': len(entries),
            'destinations': [str(dst.relative_to(root)) for _, dst, _ in entries]}


def _open_root(root):
    """Open verified sandbox by directory descriptor; do not follow final symlink."""
    root = scratch_root(root, must_exist=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(root, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
            refuse('sandbox descriptor does not refer to the owned root')
        marker_fd = os.open(MARKER, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0), dir_fd=fd)
        with os.fdopen(marker_fd, 'rb') as marker:
            if marker.read(len(MARKER_BYTES) + 1) != MARKER_BYTES:
                refuse('sandbox marker changed between planning and transaction')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _relative_parent(root, target):
    relative = target.relative_to(root)
    if not relative.parts or any(part in ('', '.', '..') for part in relative.parts):
        refuse('unsafe relative transaction target')
    return relative.parts[:-1], relative.parts[-1]


def _descend_owned(root_fd, segments, created_directories):
    """All traversals are anchored to an open directory fd with O_NOFOLLOW."""
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0)
    parent = os.dup(root_fd)
    try:
        for component in segments:
            if component in ('', '.', '..') or '/' in component:
                refuse('invalid directory component')
            try:
                child = os.open(component, flags, dir_fd=parent)
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=parent)
                child = os.open(component, flags, dir_fd=parent)
                st = os.fstat(child)
                created_directories.append((os.dup(parent), component, st.st_dev, st.st_ino))
            os.close(parent)
            parent = child
        return parent
    except BaseException:
        os.close(parent)
        raise


def _exclusive_write(parent_fd, name, data, mode, created_files):
    if name in ('', '.', '..') or '/' in name:
        refuse('invalid file component')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    st = os.fstat(fd)
    created_files.append((os.dup(parent_fd), name, st.st_dev, st.st_ino))
    with os.fdopen(fd, 'wb') as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(data)


def _rollback_owned(files, dirs):
    """Remove only same-inode objects created by the current transaction."""
    for journal in (reversed(files), reversed(dirs)):
        for parent_fd, name, device, inode in journal:
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if current.st_dev != device or current.st_ino != inode:
                    continue  # Another object now occupies this name. NEVER remove it.
                # File journals carry regular files, directory journals carry dirs.
                if stat.S_ISDIR(current.st_mode):
                    os.rmdir(name, dir_fd=parent_fd)
                elif stat.S_ISREG(current.st_mode):
                    os.unlink(name, dir_fd=parent_fd)
            except (OSError, FileNotFoundError):
                pass  # Do not expand cleanup to unrelated or moved objects.


def _close_journals(files, dirs):
    for parent_fd, _, _, _ in files + dirs:
        os.close(parent_fd)


def rehearse(root, *, user, contents, mapping, fail_after=0):
    root = scratch_root(root, must_exist=True)
    entries = planned_entries(root, user=user, contents=contents, mapping=mapping)
    if not isinstance(fail_after, int) or fail_after < 0:
        refuse('invalid failure injection count')
    # The path-based plan is advisory; the descriptor-anchored traversal below
    # rechecks every component at the exact time each file is created.
    root_fd = _open_root(root)
    created_files = []
    created_dirs = []
    try:
        for i, (source, target, data) in enumerate(entries, start=1):
            dirs, name = _relative_parent(root, target)
            parent_fd = _descend_owned(root_fd, dirs, created_dirs)
            try:
                _exclusive_write(parent_fd, name, data,
                                 0o700 if source == 'user/v3se-mcu-recover.sh' else 0o600,
                                 created_files)
            finally:
                os.close(parent_fd)
            if fail_after and i == fail_after:
                raise RuntimeError('injected Stage 7 partial-transaction failure')
        evidence = {'status': 'INERT_SANDBOX_TRANSACTION_ONLY',
                    'installation_approved': False, 'user': user,
                    'files_created': len(created_files),
                    'payload_digest': hashlib.sha256(b''.join(contents[k] for k in sorted(contents))).hexdigest(),
                    'warning': 'No host provisioning, services, firmware, calibration or printer access occurred.'}
        _exclusive_write(root_fd, 'STAGE7_REHEARSAL.json',
                         (json.dumps(evidence, sort_keys=True, indent=2) + '\n').encode(),
                         0o600, created_files)
        return evidence
    except BaseException:
        _rollback_owned(created_files, created_dirs)
        raise
    finally:
        _close_journals(created_files, created_dirs)
        os.close(root_fd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--init', action='store_true')
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--rehearse', action='store_true')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--payload', type=Path)
    p.add_argument('--user')
    args = p.parse_args()
    try:
        if args.init:
            if args.user or args.payload:
                refuse('--init takes only --root')
            result = {'status': 'SANDBOX_CREATED_NOT_INSTALLED', 'path': str(initialize(args.root))}
        else:
            if not args.user or not args.payload:
                refuse('--plan/--rehearse require --payload and --user')
            manifest, contents, mapping = verified_payload(args.payload)
            if manifest['mode'] != 'connection-check':
                refuse('Stage 7 only rehearses the non-motion connection-check profile')
            if args.plan:
                result = preview(args.root, user=args.user, contents=contents, mapping=mapping)
            else:
                result = rehearse(args.root, user=args.user, contents=contents, mapping=mapping)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as err:
        print('STAGE7 REFUSED: ' + str(err), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
