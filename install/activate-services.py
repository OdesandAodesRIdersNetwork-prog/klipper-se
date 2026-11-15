#!/usr/bin/env python3
"""Fresh-CB1 connection-only service activation after MANUAL firmware flash.

Never selects a printer-ready config. No motion, calibration or printing commands.
Requires both staged host/runtime receipts and a live CH341 by-id MCU link.
The production acceptance printer is not an allowed target.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CONFIRM = 'FRESH_CB1_FLASHED_CONNECTION_ONLY'
UNITS = ('klipper.service', 'moonraker.service')
RECOVERY_UNIT = 'v3se-mcu-recover.service'
NGINX_SITE = Path('/etc/nginx/sites-available/mainsail')
NGINX_ENABLED = Path('/etc/nginx/sites-enabled/mainsail')
NGINX_DEFAULT = Path('/etc/nginx/sites-enabled/default')
NGINX_DEFAULT_TARGET = Path('/etc/nginx/sites-available/default')


def load(module, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / module)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNTIME = load('materialize-runtime.py', 'v3se_activation_runtime_receipt')


def refuse(text):
    raise ValueError(text)


def read_receipts(home, user):
    host = RUNTIME.host_receipt(home, user)
    path = home / '.v3se-install-inputs/RUNTIME_ASSETS.json'
    if path.is_symlink() or not path.is_file():
        refuse('runtime assets receipt missing')
    record = json.loads(path.read_text())
    if (record.get('status') != 'RUNTIME_ASSETS_INSTALLED_NOT_STARTED' or
            record.get('schema') != 1 or record.get('connection_only') is not True or
            record.get('safe_to_print') is not False or record.get('user') != user):
        refuse('runtime assets receipt not ready for connection-only startup')
    for path in (home / 'klipper-port/klippy/klippy.py',
                 home / 'moonraker/moonraker/moonraker.py',
                 home / 'klippy-env/bin/python', home / 'moonraker-env/bin/python',
                 home / 'mainsail/index.html', home / 'printer_data/config/mainsail.cfg'):
        if not path.exists():
            refuse('runtime asset missing: ' + str(path))
    if host['connection_only'] is not True:
        refuse('host receipt lacks connection-only protection')
    return record


def assess(user, *, service_active=None, root=Path('/')):
    """Read-only host plan. A non-real root is only for offline fixtures."""
    entry = pwd.getpwnam(user)
    home = root / entry.pw_dir.lstrip('/')
    if root == Path('/') and entry.pw_dir != '/home/' + user:
        refuse('normal /home/<user> account required')
    record = read_receipts(home, user)
    paths = {
        'nginx_available': root / str(NGINX_SITE).lstrip('/'),
        'nginx_enabled': root / str(NGINX_ENABLED).lstrip('/'),
        'nginx_default': root / str(NGINX_DEFAULT).lstrip('/'),
        'nginx_default_target': root / str(NGINX_DEFAULT_TARGET).lstrip('/'),
    }
    blockers = []
    if not paths['nginx_available'].is_file() or paths['nginx_available'].is_symlink():
        blockers.append('Mainsail Nginx site missing or symlinked')
    if os.path.lexists(paths['nginx_enabled']):
        blockers.append('Nginx Mainsail enabled site already exists')
    default = paths['nginx_default']
    disable_default = False
    if os.path.lexists(default):
        if not default.is_symlink() or default.resolve(strict=False) != paths['nginx_default_target']:
            blockers.append('Nginx default is not exact packaged default link')
        else:
            disable_default = True
    enabled_dir = paths['nginx_enabled'].parent
    if not enabled_dir.is_dir() or enabled_dir.is_symlink():
        blockers.append('Nginx sites-enabled directory unavailable')
    else:
        other = [p.name for p in enabled_dir.iterdir() if p.name != 'default']
        if other:
            blockers.append('other enabled Nginx sites present: ' + ','.join(sorted(other)))
    for unit in (*UNITS, RECOVERY_UNIT):
        path = root / 'etc/systemd/system' / unit
        if not path.is_file() or path.is_symlink():
            blockers.append('required systemd unit absent or symlinked: ' + unit)
    if service_active:
        blockers.extend('pre-existing active service: ' + name
                        for name in UNITS if service_active(name))
    return {'schema': 1, 'status': 'READ_ONLY_CONNECTION_ACTIVATION_PLAN',
            'user': user, 'connection_only': True,
            'mainsail_default_link_disable_required': disable_default,
            'service_units': list(UNITS), 'blockers': blockers,
            'safe_to_print': False, 'runtime_commit': record['klipper']}


def run(cmd, *, runner=subprocess.run):
    runner(list(cmd), check=True, timeout=90)


def activate(user, *, runner=subprocess.run, root=Path('/'), service_active=None):
    # root is injectable only by offline unit tests. The CLI always passes '/'.
    root = Path(root).absolute()
    if root.resolve(strict=True) != root or not root.is_dir():
        refuse('invalid activation root')
    if os.geteuid() != 0:
        refuse('service activation requires root')
    if platform.machine() not in ('aarch64', 'arm64') or sys.version_info[:2] != (3, 11):
        refuse('real activation only supported on fresh Bookworm ARM64/Python 3.11')
    entry = pwd.getpwnam(user)
    home = root / entry.pw_dir.lstrip('/')
    if home.is_symlink() or home.stat().st_uid != entry.pw_uid:
        refuse('service home owner mismatch')
    if not (home.stat().st_mode & stat.S_IXOTH):
        refuse('Nginx cannot traverse service home; review permissions separately')
    # Firmware must already be flashed on the separate stock printer. Verify
    # communication visibility again immediately before permitting services.
    serial = root / 'dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'
    if not serial.exists():
        refuse('manual-flashed stock MCU serial-by-id not visible')
    if service_active is None:
        def service_active(service):
            result = subprocess.run(['systemctl', 'is-active', '--quiet', service],
                                    check=False, timeout=10)
            return result.returncode == 0
    plan = assess(user, service_active=service_active, root=root)
    site = root / str(NGINX_SITE).lstrip('/')
    enabled_site = root / str(NGINX_ENABLED).lstrip('/')
    default_site = root / str(NGINX_DEFAULT).lstrip('/')
    default_target = root / str(NGINX_DEFAULT_TARGET).lstrip('/')
    if plan['blockers']:
        refuse('; '.join(plan['blockers']))
    enabled = []
    default_removed = False
    mainsail_link = False
    try:
        if plan['mainsail_default_link_disable_required']:
            default_site.unlink()
            default_removed = True
        enabled_site.symlink_to(site)
        mainsail_link = True
        run(['nginx', '-t'], runner=runner)
        run(['systemctl', 'daemon-reload'], runner=runner)
        run(['udevadm', 'control', '--reload-rules'], runner=runner)
        for unit in UNITS:
            # Record the attempted unit before the action, so an error after a
            # partial start still causes the rollback to stop/disable it.
            enabled.append(unit)
            run(['systemctl', 'enable', '--now', unit], runner=runner)
        run(['systemctl', 'enable', '--now', 'nginx'], runner=runner)
        run(['systemctl', 'reload', 'nginx'], runner=runner)
        result = {'schema': 1, 'status': 'SERVICES_STARTED_CONNECTION_ONLY',
                  'service_user': user, 'safe_to_print': False,
                  'serial_by_id': '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0', 'manual_flash_operator_confirmed': True,
                  'physical_acceptance': 'NOT_PERFORMED'}
        receipt = home / '.v3se-install-inputs/CONNECTION_SERVICES.json'
        with receipt.open('x') as f:
            json.dump(result, f, indent=2, sort_keys=True)
            f.write('\n')
        os.chown(receipt, entry.pw_uid, entry.pw_gid)
        return result
    except BaseException:
        # Best effort rollback of service activation. Never delete any of the
        # staging assets, configuration, or unrelated system files.
        for unit in reversed(enabled):
            try:
                run(['systemctl', 'disable', '--now', unit], runner=runner)
            except (OSError, subprocess.SubprocessError):
                pass
        if mainsail_link and enabled_site.is_symlink() and enabled_site.resolve(strict=False) == site:
            enabled_site.unlink()
        if default_removed and not os.path.lexists(default_site):
            default_site.symlink_to(default_target)
        try:
            run(['nginx', '-t'], runner=runner)
            run(['systemctl', 'reload', 'nginx'], runner=runner)
        except (OSError, subprocess.SubprocessError):
            pass
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument('--plan', action='store_true')
    m.add_argument('--activate', action='store_true')
    p.add_argument('--user', required=True)
    p.add_argument('--confirm', default='')
    a = p.parse_args()
    try:
        if a.plan:
            if a.confirm:
                refuse('read-only plan does not accept confirmation')
            result = assess(a.user)
        else:
            if a.confirm != CONFIRM:
                refuse('manual flash confirmation token required')
            result = activate(a.user)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if not result.get('blockers') else 2
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as err:
        print('V3SE SERVICE ACTIVATION REFUSED/FAILED: ' + str(err), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
