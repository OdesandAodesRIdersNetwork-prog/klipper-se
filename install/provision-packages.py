#!/usr/bin/env python3
"""Explicit fresh-CB1 Debian 12 package bootstrap. Not the V3SE installer.

--plan reads host state only. --install can change apt/system packages and MAY
start distro package services. It is deliberately separate from install.sh,
which keeps --apply disabled. No printer motion/firmware/systemd units deployed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PREFLIGHT_SPEC = importlib.util.spec_from_file_location('v3se_cb1_admission', HERE / 'preflight-cb1.py')
PREFLIGHT = importlib.util.module_from_spec(PREFLIGHT_SPEC)
PREFLIGHT_SPEC.loader.exec_module(PREFLIGHT)
PACKAGE_FILE = HERE / 'packages-bookworm.txt'
EXPECTED_PACKAGES = (
    'ca-certificates', 'git', 'python3-virtualenv', 'python3-dev',
    'libffi-dev', 'build-essential', 'gcc-arm-none-eabi',
    'binutils-arm-none-eabi', 'libnewlib-arm-none-eabi',
    'libopenjp2-7', 'libsodium-dev', 'zlib1g-dev', 'libjpeg-dev',
    'packagekit', 'wireless-tools', 'curl', 'nginx',
)
CONFIRMATION = 'FRESH_CB1_APT_PACKAGES_ONLY'
PACKAGE_RE = re.compile(r'[a-z0-9][a-z0-9+.-]*\Z')


def refuse(reason):
    raise ValueError(reason)


def read_manifest(path=PACKAGE_FILE):
    raw = path.read_bytes()
    if len(raw) > 4096:
        refuse('package manifest exceeds expected size')
    packages = tuple(line.strip() for line in raw.decode('utf-8').splitlines()
                     if line.strip() and not line.lstrip().startswith('#'))
    if packages != EXPECTED_PACKAGES or not all(PACKAGE_RE.fullmatch(p) for p in packages):
        refuse('Bookworm package list changed; review required before apt')
    return packages, hashlib.sha256(raw).hexdigest()


def evaluate(snapshot, packages, digest):
    report = PREFLIGHT.assess(snapshot)
    hard = list(report['hard_blockers'])
    # Package installation is an earlier bootstrap stage than serial and group setup.
    # But the host must already be booted into a supported systemd-based OS.
    if not snapshot['systemd_active']:
        hard.append('systemd must be running before apt provisioning')
    if not os.path.isabs(snapshot['user_home'] or ''):
        hard.append('service user home missing')
    return {
        'schema': 1,
        'mode': 'FRESH_CB1_APT_PHASE_ONLY',
        'service_user': snapshot['user'],
        'host_report_status': report['status'],
        'hard_blockers': hard,
        'pending_requirements': report['pending_prerequisites'],
        'manifest_sha256': digest,
        'packages': list(packages),
        'missing_before': list(snapshot['missing_packages']),
        'would_run': [
            ['apt-get', 'update'],
            ['apt-get', 'install', '--yes', '--no-install-recommends', *packages],
        ],
        'does_not_install_klipper': True,
        'does_not_authorize_installer_apply': True,
        'rollback': 'NO AUTOMATIC APT ROLLBACK: package changes may be partial on failure',
        'warning': 'apt may start distro services such as nginx; use a fresh CB1 only',
    }


def plan(user, *, snapshot_func=None):
    packages, digest = read_manifest()
    if snapshot_func is None:
        snapshot_func = PREFLIGHT.snapshot
    snapshot = snapshot_func(user)
    result = evaluate(snapshot, packages, digest)
    if result['hard_blockers']:
        return result, 2
    return result, 0


def dpkg_version(package):
    p = subprocess.run(['dpkg-query', '-W', '-f=${Version}', package],
                       capture_output=True, text=True, timeout=10, check=False)
    if p.returncode or not p.stdout.strip():
        refuse('installed package version unavailable: ' + package)
    return p.stdout.strip()


def execute(user, *, confirmation, euid=None, runner=None, snapshot_func=None, version_reader=None):
    if confirmation != CONFIRMATION:
        refuse('explicit fresh-CB1 apt confirmation is required')
    if euid is None:
        euid = os.geteuid()
    if euid != 0:
        refuse('apt phase must be executed as root on a fresh CB1')
    report, code = plan(user, snapshot_func=snapshot_func)
    if code:
        refuse('host blocked: ' + '; '.join(report['hard_blockers']))
    if runner is None:
        runner = subprocess.run
    # No arbitrary command or package options are accepted from the caller.
    env = os.environ.copy()
    env['DEBIAN_FRONTEND'] = 'noninteractive'
    env['APT_LISTCHANGES_FRONTEND'] = 'none'
    for command in report['would_run']:
        runner(command, check=True, env=env, timeout=1800)
    # Inspect the real host after apt; missing prerequisites during earlier
    # stages (dialout/serial) do not require this package step to fail.
    if snapshot_func is None:
        snapshot_func = PREFLIGHT.snapshot
    after = snapshot_func(user)
    if after['missing_packages']:
        refuse('apt finished, but required packages still missing: ' + ', '.join(after['missing_packages']))
    if version_reader is None:
        version_reader = dpkg_version
    versions = {p: version_reader(p) for p in report['packages']}
    if not all(isinstance(v, str) and v.strip() and len(v) < 256 for v in versions.values()):
        refuse('invalid installed package version result')
    result = dict(report)
    result['installed_versions'] = versions
    result['mode'] = 'APT_PHASE_COMMANDS_COMPLETED_NOT_PRINTER_ACCEPTED'
    result['missing_after'] = list(after['missing_packages'])
    result['does_not_authorize_installer_apply'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--install', action='store_true')
    parser.add_argument('--user', required=True)
    parser.add_argument('--confirm', default='')
    args = parser.parse_args()
    try:
        if args.plan:
            if args.confirm:
                refuse('--plan never accepts --confirm')
            result, code = plan(args.user)
        else:
            result = execute(args.user, confirmation=args.confirm)
            code = 0
        print(json.dumps(result, indent=2, sort_keys=True))
        return code
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        print('V3SE APT PHASE REFUSED/FAILED: ' + str(exc), file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
