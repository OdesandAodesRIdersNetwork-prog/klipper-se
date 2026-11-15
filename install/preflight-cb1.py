#!/usr/bin/env python3
"""READ-ONLY fresh-CB1 admission report; never installs or changes anything.

This is a diagnostic, not an authorization to install. Missing apt packages are
expected on some new images. Existing printer/service paths are a hard conflict.
"""
import argparse
import grp
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PKGS = HERE / 'packages-bookworm.txt'
USER_RE = re.compile(r'[a-z_][a-z0-9_-]{0,31}\Z')
SERVICE_PATHS = (
    'klipper-port', 'klippy-env', 'moonraker', 'moonraker-env', 'mainsail',
    'mainsail-config', 'printer_data',
)
SYSTEM_PATHS = (
    '/etc/systemd/system/klipper.service',
    '/etc/systemd/system/moonraker.service',
    '/etc/systemd/system/v3se-mcu-recover.service',
    '/etc/systemd/system/v3se-mcu-recover.path',
    '/etc/udev/rules.d/99-v3se-mcu-recover.rules',
    '/etc/nginx/sites-available/mainsail',
    '/etc/nginx/conf.d/upstreams.conf',
    '/etc/nginx/conf.d/common_vars.conf',
)
REQUIRED_TOOLS = ('python3', 'git', 'virtualenv', 'arm-none-eabi-gcc', 'nginx',
                  'curl', 'systemctl', 'udevadm', 'dpkg-query', 'apt-get')


def read_os_release(path):
    data = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        data[key] = value.strip().strip('"').strip("'")
    return data


def package_names(path=PKGS):
    packages = [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
                if line.strip() and not line.strip().startswith('#')]
    if len(packages) != 17 or len(packages) != len(set(packages)) or not all(
            re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', x) for x in packages):
        raise ValueError('unexpected or invalid Bookworm package manifest')
    return packages


def run_readonly(command):
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def snapshot(user):
    if not USER_RE.fullmatch(user):
        raise ValueError('invalid service username')
    osr = read_os_release(Path('/etc/os-release'))
    try:
        entry = pwd.getpwnam(user)
        user_home = entry.pw_dir
        user_uid = entry.pw_uid
    except KeyError:
        user_home = None
        user_uid = None
    packages = package_names()
    missing = []
    for package in packages:
        p = run_readonly(['dpkg-query', '-W', '-f=${Status}', package])
        if p is None or p.returncode != 0 or p.stdout.strip() != 'install ok installed':
            missing.append(package)
    try:
        dialout_gid = grp.getgrnam('dialout').gr_gid
        group_ids = os.getgrouplist(user, entry.pw_gid) if user_uid is not None else []
        dialout_member = dialout_gid in group_ids
    except KeyError:
        dialout_member = False
    tools = [name for name in REQUIRED_TOOLS if shutil.which(name) is None]
    conflicts = []
    if user_home is not None:
        for relative in SERVICE_PATHS:
            path = Path(user_home) / relative
            if os.path.lexists(path):
                conflicts.append(str(path))
    for path in SYSTEM_PATHS:
        if os.path.lexists(path):
            conflicts.append(path)
    serial_dir = Path('/dev/serial/by-id')
    serial_present = serial_dir.is_dir() and any(serial_dir.iterdir())
    return {
        'os_id': osr.get('ID', ''),
        'os_like': osr.get('ID_LIKE', ''),
        'os_version': osr.get('VERSION_ID', ''),
        'architecture': platform.machine(),
        'python_version': '.'.join(map(str, sys.version_info[:3])),
        'systemd_active': Path('/run/systemd/system').is_dir(),
        'user': user,
        'user_home': user_home,
        'user_uid': user_uid,
        'missing_packages': missing,
        'missing_tools': tools,
        'existing_installation_paths': sorted(conflicts),
        'serial_device_visible': bool(serial_present),
        'dialout_access_group_member': dialout_member,
    }


def assess(s):
    hard = []
    pending = []
    if s['architecture'] not in ('aarch64', 'arm64'):
        hard.append('CB1 must run a supported aarch64/arm64 OS')
    distro = (s['os_id'] == 'debian' or 'debian' in s['os_like'].split())
    if not distro or s['os_version'] != '12':
        hard.append('supported first target is Armbian/Debian 12 Bookworm')
    if s['user_home'] != '/home/' + s['user'] or not s['user_uid'] or s['user_uid'] < 1000:
        hard.append('existing normal service account /home/<user> is required')
    if s['existing_installation_paths']:
        hard.append('existing Klipper/Moonraker/Mainsail/service paths detected; never overwrite')
    try:
        py = tuple(int(x) for x in s['python_version'].split('.')[:2])
    except (ValueError, TypeError):
        py = (0, 0)
    if py != (3, 11):
        hard.append('first proof targets Python 3.11 on Debian 12')
    if not s['systemd_active']:
        pending.append('systemd is not running')
    if s['missing_packages']:
        pending.append('17-package manifest has packages not yet installed')
    if s['missing_tools']:
        pending.append('required commands unavailable: ' + ', '.join(s['missing_tools']))
    if not s['dialout_access_group_member']:
        pending.append('service user lacks dialout group membership or group is absent')
    if not s['serial_device_visible']:
        pending.append('USB serial ID not yet visible; verify after firmware flash/power-up')
    status = 'HOST_CONFLICT_OR_UNSUPPORTED' if hard else ('PREREQUISITES_PENDING' if pending else 'READ_ONLY_PREREQUISITES_PRESENT')
    return {
        'schema': 1,
        'mode': 'READ_ONLY_FRESH_CB1_PREFLIGHT',
        'status': status,
        'hard_blockers': hard,
        'pending_prerequisites': pending,
        'evidence': s,
        'safe_to_install': False,
        'explanation': 'This report makes no changes and cannot authorize --apply or physical operation.',
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user', required=True)
    a = p.parse_args()
    try:
        report = assess(snapshot(a.user))
    except (OSError, ValueError) as exc:
        print('V3SE CB1 PREFLIGHT: ' + str(exc), file=sys.stderr)
        return 3
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['hard_blockers'] else 4 if report['pending_prerequisites'] else 0

if __name__ == '__main__':
    sys.exit(main())
