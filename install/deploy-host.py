#!/usr/bin/env python3
"""Fresh-CB1, new-files-only host file deployment. NO service start or firmware flash.

CLI --plan is read-only; --deploy requires root, an explicit token, complete
fresh-CB1 preflight, a verified 18-file *connection-check* payload and a
second operator-verified clean host. Existing files are never overwritten.

This script is NOT called by install.sh --apply (which remains disabled).
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
CONFIRM = 'FRESH_CB1_CONNECTION_ONLY_DEPLOY'
USER_RE = re.compile(r'[a-z_][a-z0-9_-]{0,31}\Z')
SOURCE_FILE_MAP = {
    'host/systemd/klipper.service': 'etc/systemd/system/klipper.service',
    'host/systemd/moonraker.service': 'etc/systemd/system/moonraker.service',
    'host/systemd/v3se-mcu-recover.service': 'etc/systemd/system/v3se-mcu-recover.service',
    'host/udev/99-v3se-mcu-recover.rules': 'etc/udev/rules.d/99-v3se-mcu-recover.rules',
    'host/nginx/sites-available/mainsail': 'etc/nginx/sites-available/mainsail',
    'host/nginx/conf.d/upstreams.conf': 'etc/nginx/conf.d/upstreams.conf',
    'host/nginx/conf.d/common_vars.conf': 'etc/nginx/conf.d/common_vars.conf',
    'user/printer_data/systemd/klipper.env': 'home/{user}/printer_data/systemd/klipper.env',
    'user/printer_data/systemd/moonraker.env': 'home/{user}/printer_data/systemd/moonraker.env',
    'user/printer_data/config/moonraker.conf': 'home/{user}/printer_data/config/moonraker.conf',
    'user/printer_data/config/printer.cfg': 'home/{user}/printer_data/config/printer.cfg',
    'user/printer_data/config/macros.cfg': 'home/{user}/printer_data/config/macros.cfg',
    'user/printer_data/config/macro.cfg': 'home/{user}/printer_data/config/macro.cfg',
    'user/mainsail/config.json': 'home/{user}/mainsail/config.json',
    'user/v3se-mcu-recover.sh': 'home/{user}/v3se-mcu-recover.sh',
    'metadata/versions.env': 'home/{user}/.v3se-install-inputs/versions.env',
    'metadata/packages-bookworm.txt': 'home/{user}/.v3se-install-inputs/packages-bookworm.txt',
    'metadata/v3se-stm32f103xe.config': 'home/{user}/.v3se-install-inputs/v3se-stm32f103xe.config',
}
RECEIPT = 'home/{user}/.v3se-install-inputs/HOST_FILE_DEPLOYMENT.json'


def load(filename, module):
    spec = importlib.util.spec_from_file_location(module, HERE / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


SANDBOX = load('simulate-deployment.py', 'v3se_payload_reader')
PREFLIGHT = load('preflight-cb1.py', 'v3se_host_reader')


def refuse(reason):
    raise ValueError(reason)


def validate_user(user):
    if not USER_RE.fullmatch(user):
        refuse('invalid service username')
    return user


def verify(payload):
    manifest, contents = SANDBOX.verify(payload)
    if manifest['mode'] != 'connection-check' or set(contents) != set(SOURCE_FILE_MAP):
        refuse('deployment requires exact 18-file connection-check payload')
    return manifest, contents


def specs(user, content):
    validate_user(user)
    entries = []
    for source in sorted(SOURCE_FILE_MAP):
        rel = SOURCE_FILE_MAP[source].format(user=user)
        parts = tuple(Path(rel).parts)
        if not parts or '..' in parts or any(p in ('', '.') for p in parts):
            refuse('invalid deployment destination')
        is_user = parts[0] == 'home'
        # Nginx runs as www-data: only public Mainsail frontend config is
        # readable by that account. Printer data and env files stay private.
        if source == 'user/v3se-mcu-recover.sh':
            mode = 0o700
        elif source == 'user/mainsail/config.json':
            mode = 0o644
        else:
            mode = 0o600 if is_user else 0o644
        entries.append((parts, content[source], mode, is_user))
    return entries


def inspect(root, user, entries):
    """Non-mutating advisory conflict/symlink pass for test roots and real /."""
    root = Path(root).absolute()
    if root.resolve(strict=True) != root or not root.is_dir():
        refuse('host root is symlinked, missing or not a directory')
    home = root / 'home' / user
    if home.resolve(strict=True) != home or not home.is_dir() or home.is_symlink():
        refuse('service home must exist without symlinks')
    conflicts = []
    for parts, _, _, _ in entries:
        path = root.joinpath(*parts)
        for idx in range(1, len(parts)):
            parent = root.joinpath(*parts[:idx])
            if parent.is_symlink() or (os.path.lexists(parent) and not parent.is_dir()):
                conflicts.append('unsafe ancestor: ' + str(parent))
        if os.path.lexists(path):
            conflicts.append('existing destination: ' + str(path))
    return sorted(set(conflicts))


def _descend(fd, parts, created_dirs, *, create, user_owner, uid, gid):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    cur = os.dup(fd)
    try:
        for index, part in enumerate(parts):
            if part in ('', '.', '..') or '/' in part:
                refuse('invalid path component')
            try:
                child = os.open(part, flags, dir_fd=cur)
            except FileNotFoundError:
                if not create:
                    raise
                frontend_public = (len(parts) >= 3 and parts[0] == 'home'
                                   and parts[2] == 'mainsail' and index >= 2)
                os.mkdir(part, 0o755 if not user_owner or frontend_public else 0o700, dir_fd=cur)
                st = os.stat(part, dir_fd=cur, follow_symlinks=False)
                created_dirs.append((os.dup(cur), part, st.st_dev, st.st_ino))
                child = os.open(part, flags, dir_fd=cur)
                if user_owner:
                    os.fchown(child, uid, gid)
            os.close(cur)
            cur = child
        return cur
    except BaseException:
        os.close(cur)
        raise


def _write(fd, name, data, mode, *, chown, uid, gid, journal):
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=fd)
    try:
        st = os.fstat(handle)
        journal.append((os.dup(fd), name, st.st_dev, st.st_ino))
        os.fchmod(handle, mode)
        if chown:
            os.fchown(handle, uid, gid)
        with os.fdopen(handle, 'wb') as f:
            handle = -1
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if handle != -1:
            os.close(handle)


def _rollback(files, dirs):
    for kind, seq in (('file', files), ('dir', dirs)):
        for pfd, name, device, ino in reversed(seq):
            try:
                st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
                if (st.st_dev, st.st_ino) != (device, ino):
                    continue
                if kind == 'file' and stat.S_ISREG(st.st_mode):
                    os.unlink(name, dir_fd=pfd)
                elif kind == 'dir' and stat.S_ISDIR(st.st_mode):
                    os.rmdir(name, dir_fd=pfd)
            except (OSError, FileNotFoundError):
                continue


def _close(files, dirs):
    for fd, *_ in files + dirs:
        os.close(fd)


def transaction(root, user, contents, *, fail_after=0, uid=None, gid=None):
    """Testable file transaction. CLI supplies only '/' and true root/CB1 gates."""
    entries = specs(user, contents)
    blockers = inspect(root, user, entries)
    if blockers:
        refuse('refusing pre-existing or unsafe files: ' + '; '.join(blockers))
    if uid is None or gid is None:
        account = pwd.getpwnam(user)
        uid, gid = account.pw_uid, account.pw_gid
    root_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    created_files, created_dirs = [], []
    try:
        for i, (parts, data, mode, is_user) in enumerate(entries, start=1):
            parent = _descend(root_fd, parts[:-1], created_dirs, create=True,
                              user_owner=is_user, uid=uid, gid=gid)
            try:
                _write(parent, parts[-1], data, mode, chown=is_user,
                       uid=uid, gid=gid, journal=created_files)
            finally:
                os.close(parent)
            if fail_after and fail_after == i:
                raise RuntimeError('injected host file transaction failure')
        receipt_parts = Path(RECEIPT.format(user=user)).parts
        receipt = {'schema': 1, 'status': 'HOST_FILES_WRITTEN_NO_SERVICES_RUNNING',
                   'connection_only': True, 'user': user, 'files': len(entries),
                   'does_not_authorize_printing': True,
                   'payload_digest': hashlib.sha256(b''.join(contents[k] for k in sorted(contents))).hexdigest()}
        parent = _descend(root_fd, receipt_parts[:-1], created_dirs, create=True,
                          user_owner=True, uid=uid, gid=gid)
        try:
            _write(parent, receipt_parts[-1], (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode(),
                   0o600, chown=True, uid=uid, gid=gid, journal=created_files)
        finally:
            os.close(parent)
        return receipt
    except BaseException:
        _rollback(created_files, created_dirs)
        raise
    finally:
        _close(created_files, created_dirs)
        os.close(root_fd)


def require_fresh_cb1(user):
    # Identity check is done again immediately before any root file mutation.
    state = PREFLIGHT.snapshot(user)
    assessment = PREFLIGHT.assess(state)
    if assessment['hard_blockers']:
        refuse('fresh-CB1 admission blocked: ' + '; '.join(assessment['hard_blockers']))
    if state['missing_packages'] or not state['systemd_active'] or not state['dialout_access_group_member']:
        refuse('apt, systemd and serial access must be ready before host files')
    if not state['user_home'] or state['user_home'] != '/home/' + user:
        refuse('service account home mismatch')
    entry = pwd.getpwnam(user)
    home = Path(state['user_home'])
    st = home.stat()
    if home.is_symlink() or st.st_uid != entry.pw_uid or st.st_gid != entry.pw_gid:
        refuse('service home must be owned by designated service account')
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        refuse('service home is group/world writable')
    if not st.st_mode & stat.S_IXOTH:
        refuse('Nginx requires world traverse permission on service home; review first')
    if os.path.lexists('/etc/nginx/sites-enabled/mainsail'):
        refuse('pre-existing Nginx mainsail enabled site conflict')
    return entry


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--deploy', action='store_true')
    p.add_argument('--user', required=True)
    p.add_argument('--payload', type=Path, required=True)
    p.add_argument('--confirm', default='')
    a = p.parse_args()
    try:
        _, content = verify(a.payload)
        if a.plan:
            if a.confirm:
                refuse('read-only plan does not accept confirmation token')
            entries = specs(a.user, content)
            result = {'status': 'READ_ONLY_HOST_DEPLOY_PLAN', 'files': len(entries),
                      'destinations': ['/' + '/'.join(parts) for parts, *_ in entries],
                      'conflicts': inspect(Path('/'), a.user, entries),
                      'install_approved': False}
        else:
            if a.confirm != CONFIRM or os.geteuid() != 0:
                refuse('deploy requires root plus exact fresh-CB1 confirmation')
            require_fresh_cb1(a.user)
            result = transaction(Path('/'), a.user, content)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print('V3SE HOST DEPLOY REFUSED/FAILED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
