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


def rehearse(root, *, user, contents, mapping, fail_after=0):
    root = scratch_root(root, must_exist=True)
    entries = planned_entries(root, user=user, contents=contents, mapping=mapping)
    if not isinstance(fail_after, int) or fail_after < 0:
        refuse('invalid failure injection count')
    created_files = []
    created_dirs = []
    try:
        for i, (source, target, data) in enumerate(entries, start=1):
            parent_chain = []
            cur = target.parent
            while cur != root:
                parent_chain.append(cur)
                cur = cur.parent
            for directory in reversed(parent_chain):
                if directory.is_symlink():
                    refuse('parent changed to symlink during transaction')
                if not directory.exists():
                    directory.mkdir(mode=0o700)
                    created_dirs.append(directory)
                elif not directory.is_dir():
                    refuse('parent changed to non-directory during transaction')
            if target.is_symlink() or os.path.lexists(target):
                refuse('target appeared during transaction, refusing overwrite')
            # exclusive create; never follow an existing target or truncate a file
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            descriptor = os.open(target, flags, 0o600)
            created_files.append(target)
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
            target.chmod(0o700 if source == 'user/v3se-mcu-recover.sh' else 0o600)
            if fail_after and i == fail_after:
                raise RuntimeError('injected Stage 7 partial-transaction failure')
        evidence = {'status': 'INERT_SANDBOX_TRANSACTION_ONLY',
                    'installation_approved': False, 'user': user,
                    'files_created': len(created_files),
                    'payload_digest': hashlib.sha256(b''.join(contents[k] for k in sorted(contents))).hexdigest(),
                    'warning': 'No host provisioning, services, firmware, calibration or printer access occurred.'}
        receipt = root / 'STAGE7_REHEARSAL.json'
        with receipt.open('xb') as f:
            f.write((json.dumps(evidence, sort_keys=True, indent=2) + '\n').encode())
        created_files.append(receipt)
        return evidence
    except BaseException:
        # Roll back this transaction's new objects only. Never delete the root,
        # marker or any unrelated scratch-root content.
        for p in reversed(created_files):
            p.unlink(missing_ok=True)
        for p in reversed(created_dirs):
            try:
                p.rmdir()
            except OSError:
                pass
        raise


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
