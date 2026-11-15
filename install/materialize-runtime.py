#!/usr/bin/env python3
"""Populate fresh-CB1 source, Python and Mainsail assets AFTER host file deployment.

Real writes require an explicit token and a verified connection-check host receipt.
Never touches /etc, the MCU, services or accepted reference printer.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import pwd
import re
import shutil
import stat
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
CONFIRM = 'FRESH_CB1_RUNTIME_SOURCES_ONLY'
MAX_ZIP_ENTRIES = 10000
MAX_UNCOMPRESSED = 120 * 1024 * 1024


def load(file, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAGE = load('stage-dependencies.py', 'v3se_materialize_sources')
USER_RE = re.compile(r'[a-z_][a-z0-9_-]{0,31}\Z')


def refuse(msg):
    raise ValueError(msg)


def valid_home(home, user):
    if not USER_RE.fullmatch(user):
        refuse('invalid service username')
    h = Path(home).absolute()
    if h.resolve(strict=True) != h or not h.is_dir() or h.is_symlink():
        refuse('service home must be an existing unsymlinked directory')
    return h


def host_receipt(home, user):
    path = home / '.v3se-install-inputs/HOST_FILE_DEPLOYMENT.json'
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path.absolute():
        refuse('verified first-boot host deployment receipt is missing')
    row = json.loads(path.read_text())
    if (row.get('schema') != 1 or row.get('status') != 'HOST_FILES_WRITTEN_NO_SERVICES_RUNNING'
            or row.get('connection_only') is not True or row.get('user') != user
            or row.get('does_not_authorize_printing') is not True
            or row.get('files') != 18):
        refuse('host receipt cannot authorize runtime preparation')
    p = home / 'printer_data/config/printer.cfg'
    if p.is_symlink() or not p.is_file():
        refuse('first boot connection-only printer config missing')
    sections = [line.strip() for line in p.read_text().splitlines()
                if line.startswith('[') and line.rstrip().endswith(']')]
    if sections != ['[mcu]', '[printer]'] or 'kinematics: none' not in p.read_text():
        refuse('printer config is not MCU-only connection-check profile')
    return row


def source_plan(sources, user, home):
    home = valid_home(home, user)
    pins = STAGE.read_locked()
    STAGE.verify_all(Path(sources), pins)
    receipt = host_receipt(home, user)
    expected = ['klipper-port', 'moonraker', 'mainsail-config', 'klippy-env', 'moonraker-env']
    blockers = []
    for rel in expected:
        if os.path.lexists(home / rel):
            blockers.append('target exists: ' + rel)
    web = home / 'mainsail'
    if not web.is_dir() or web.is_symlink() or web.resolve(strict=True) != web:
        blockers.append('Mainsail directory from host transaction missing or unsafe')
    else:
        entries = {f.name for f in web.iterdir()}
        if entries != {'config.json'} or (web / 'config.json').is_symlink():
            blockers.append('Mainsail directory contains unexpected data: ' + repr(sorted(entries)))
    conf = home / 'printer_data/config'
    if os.path.lexists(conf / 'mainsail.cfg'):
        blockers.append('mainsail.cfg already exists')
    return {'schema': 1, 'mode': 'RUNTIME_ASSETS_PLAN_NOT_INSTALLED',
            'service_user': user, 'source_stage': str(Path(sources).absolute()),
            'install_home': str(home), 'expected_source_commit': pins['V3SE_SOURCE_COMMIT'],
            'expected_moonraker_commit': pins['MOONRAKER_COMMIT'],
            'mainsail_version': pins['MAINSAIL_VERSION'],
            'host_receipt_digest': receipt['payload_digest'],
            'blockers': blockers, 'safe_to_print': False}


def checked(command, *, cwd=None, env=None, timeout=900, executor=subprocess.run):
    return executor([str(x) for x in command], cwd=str(cwd) if cwd else None,
                    env=env, check=True, timeout=timeout)


def git_env():
    env = dict(os.environ)
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1',
                'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_LFS_SKIP_SMUDGE': '1'})
    return env


def checkout_from_stage(stage_dir, target, url, commit, *, executor=subprocess.run):
    # A new clone ensures full independence from the temporary source stage.
    env = git_env()
    checked(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-local', '--no-checkout',
             '--quiet', str(stage_dir), str(target)], env=env, executor=executor)
    checked(['git', '-C', target, '-c', 'core.hooksPath=/dev/null',
             'checkout', '--quiet', '--detach', commit], env=env, executor=executor)
    checked(['git', '-C', target, 'remote', 'set-url', 'origin', url], env=env, executor=executor)
    actual = subprocess.run(['git', '-C', str(target), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    if actual != commit:
        refuse('materialized checkout does not match pinned source commit')


def validate_archive(archive):
    """Disallow ZIP bombs, traversal, links, duplicates and unsupported entries."""
    total = 0
    names = set()
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist()) > MAX_ZIP_ENTRIES:
            refuse('Mainsail archive contains too many entries')
        for entry in z.infolist():
            name = entry.filename
            relative = PurePosixPath(name)
            if (not name or '\\' in name or name.startswith('/') or
                    '..' in relative.parts or '.' in relative.parts or
                    not relative.parts or any(part == '' for part in relative.parts)):
                refuse('unsafe Mainsail ZIP path')
            normalized = '/'.join(relative.parts)
            if normalized in names:
                refuse('repeated Mainsail archive entry')
            names.add(normalized)
            mode = (entry.external_attr >> 16) & 0o170000
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                refuse('Mainsail archive has a symbolic link or unsupported entry')
            total += entry.file_size
            if total > MAX_UNCOMPRESSED:
                refuse('Mainsail archive exceeds uncompressed limit')
        return [(e.filename, e.is_dir()) for e in z.infolist()]


def frontend_extract(archive, dest, *, created_files, created_dirs):
    """The existing config.json is intentionally preserved, not overwritten."""
    validate_archive(archive)
    if not dest.is_dir() or dest.is_symlink():
        refuse('existing managed Mainsail directory is required')
    with zipfile.ZipFile(archive) as z:
        for e in z.infolist():
            parts = PurePosixPath(e.filename).parts
            if parts == ('config.json',):
                continue
            path = dest.joinpath(*parts)
            if e.is_dir():
                if not path.exists():
                    path.mkdir(mode=0o755)
                    created_dirs.append(path)
                elif path.is_symlink() or not path.is_dir():
                    refuse('unsafe existing frontend directory')
                continue
            parent = dest
            for part in parts[:-1]:
                parent = parent / part
                if not parent.exists():
                    parent.mkdir(mode=0o755)
                    created_dirs.append(parent)
                elif parent.is_symlink() or not parent.is_dir():
                    refuse('unsafe Mainsail parent')
            if os.path.lexists(path):
                refuse('frontend extraction refuses existing file: ' + str(path))
            with z.open(e) as source, path.open('xb') as target:
                created_files.append(path)
                shutil.copyfileobj(source, target)
            path.chmod(0o644)


def install(sources, user, home, *, executor=subprocess.run):
    plan = source_plan(sources, user, home)
    if plan['blockers']:
        refuse('conflicting files before runtime install: ' + '; '.join(plan['blockers']))
    if os.geteuid() == 0:
        refuse('runtime source installation must run as the service user, not root')
    if sys.version_info[:2] != (3, 11):
        refuse('Python 3.11 required for first CB1 proof')
    if shutil.which('virtualenv') is None:
        refuse('virtualenv missing')
    account = pwd.getpwnam(user)
    if (os.geteuid() != account.pw_uid or
            str(Path(home)) != account.pw_dir):
        refuse('run as the selected service account with its normal home')
    if platform.machine() not in ('aarch64', 'arm64'):
        refuse('runtime install is for fresh ARM64 CB1 only')
    stage = Path(sources).absolute()
    home = Path(home).absolute()
    pins = STAGE.read_locked()
    created_paths, files, dirs = [], [], []
    try:
        for dirname, url_key, sha_key, _ in STAGE.SOURCE_MAP:
            target = home / dirname
            if os.path.lexists(target):
                refuse('runtime directory appeared: ' + dirname)
            # Claim the empty target ourselves before invoking Git. Only rollback
            # if the exact directory inode still belongs to this transaction.
            target.mkdir(mode=0o700)
            st = target.stat()
            created_paths.append((target, st.st_dev, st.st_ino))
            checkout_from_stage(stage / dirname, target, pins[url_key], pins[sha_key],
                                executor=executor)
        for envname, source, requirements in (
                ('klippy-env', 'klipper-port', 'scripts/klippy-requirements.txt'),
                ('moonraker-env', 'moonraker', 'scripts/moonraker-requirements.txt')):
            target = home / envname
            if os.path.lexists(target):
                refuse('Python environment target appeared: ' + envname)
            target.mkdir(mode=0o700)
            st = target.stat()
            created_paths.append((target, st.st_dev, st.st_ino))
            env = dict(os.environ)
            env.update({'PIP_NO_INPUT': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
                        'PIP_CONFIG_FILE': os.devnull, 'PYTHONNOUSERSITE': '1',
                        'PYTHONDONTWRITEBYTECODE': '1',
                        'PIP_CACHE_DIR': str(target / '.v3se-pip-cache'),
                        'VIRTUALENV_OVERRIDE_APP_DATA': str(target / '.v3se-venv-cache'),
                        'TMPDIR': str(target)})
            checked(['virtualenv', '--no-download', '--python=python3.11', target], env=env, executor=executor)
            checked([target / 'bin/python', '-m', 'pip', 'install', '--no-input', '-r',
                     home / source / requirements], cwd=(home / source / 'scripts'),
                    env=env, timeout=1800, executor=executor)
        # Moonraker/Klipper need writable runtime directories. These are not
        # populated from the developer's live printer and never contain meshes.
        for relative in ('printer_data/logs', 'printer_data/gcodes', 'printer_data/comms'):
            folder = home / relative
            if os.path.lexists(folder):
                if folder.is_symlink() or not folder.is_dir():
                    refuse('runtime directory is unsafe: ' + relative)
            else:
                folder.mkdir(mode=0o700)
                dirs.append(folder)
        web = home / 'mainsail'
        archive = stage / 'mainsail-v2.19.0.zip'
        frontend_extract(archive, web, created_files=files, created_dirs=dirs)
        version = web / '.version'
        if os.path.lexists(version):
            if version.read_text().strip() != pins['MAINSAIL_VERSION']:
                refuse('Mainsail release version mismatch')
        else:
            version.write_text(pins['MAINSAIL_VERSION'] + '\n')
            files.append(version)
        symlink = home / 'printer_data/config/mainsail.cfg'
        if os.path.lexists(symlink):
            refuse('mainsail.cfg installation path appeared')
        target = home / 'mainsail-config/mainsail.cfg'
        if not target.is_file():
            refuse('pinned mainsail-config entry point missing')
        symlink.symlink_to(target)
        files.append(symlink)
        record = {'schema': 1, 'status': 'RUNTIME_ASSETS_INSTALLED_NOT_STARTED',
                  'user': user, 'home': str(home), 'connection_only': True,
                  'klipper': pins['V3SE_SOURCE_COMMIT'],
                  'moonraker': pins['MOONRAKER_COMMIT'],
                  'mainsail_config': pins['MAINSAIL_CONFIG_COMMIT'],
                  'mainsail': pins['MAINSAIL_VERSION'],
                  'safe_to_print': False}
        receipt = home / '.v3se-install-inputs/RUNTIME_ASSETS.json'
        receipt.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
        files.append(receipt)
        return record
    except BaseException:
        for item in reversed(files):
            try:
                item.unlink()
            except FileNotFoundError:
                pass
        for item in reversed(dirs):
            try:
                item.rmdir()
            except OSError:
                pass
        for item, dev, ino in reversed(created_paths):
            if item.exists() and not item.is_symlink() and item.is_dir():
                st = item.lstat()
                if (st.st_dev, st.st_ino) == (dev, ino):
                    shutil.rmtree(item)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument('--plan', action='store_true')
    m.add_argument('--install', action='store_true')
    p.add_argument('--user', required=True)
    p.add_argument('--sources', required=True, type=Path)
    p.add_argument('--confirm', default='')
    a = p.parse_args()
    try:
        entry = pwd.getpwnam(a.user)
        if a.plan:
            if a.confirm:
                refuse('plan cannot accept confirmation token')
            result = source_plan(a.sources, a.user, entry.pw_dir)
        else:
            if a.confirm != CONFIRM:
                refuse('explicit fresh-CB1 runtime confirmation required')
            result = install(a.sources, a.user, entry.pw_dir)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if not result.get('blockers') else 2
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            json.JSONDecodeError, zipfile.BadZipFile, KeyError) as exc:
        print('V3SE RUNTIME INSTALL REFUSED/FAILED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
