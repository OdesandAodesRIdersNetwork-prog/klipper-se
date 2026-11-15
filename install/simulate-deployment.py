#!/usr/bin/env python3
"""Verify and simulate a Klipper-SE offline payload under a NEW scratch root.

NEVER deploys to a live CB1, runs apt, adjusts permissions, flashes firmware,
or controls services. The output is an unprivileged, inert filesystem model.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
MARKER = re.compile(rb'@[A-Z][A-Z0-9_]*@')
USER_RE = re.compile(r'[a-z_][a-z0-9_-]{0,31}\Z')
SHA_RE = re.compile(r'[0-9a-f]{64}\Z')
# Strict allowlist means a forged manifest cannot add arbitrary system paths.
FILES = {
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
    'metadata/versions.env': 'share/klipper-se/versions.env',
    'metadata/packages-bookworm.txt': 'share/klipper-se/packages-bookworm.txt',
    'metadata/v3se-stm32f103xe.config': 'share/klipper-se/v3se-stm32f103xe.config',
}
EXPECTED_MCU_CONFIG_SHA256 = 'ee38872bc64d4595af07445078013b5e366b796d360781b07c99c60a574e7777'
EXPECTED_MACRO_HASHES = {
    'user/printer_data/config/macros.cfg': 'c04bc6a5a5b24592aefe68b2b06bd14ecb78f1e930d2109b9c5e471af9677442',
    'user/printer_data/config/macro.cfg': '96b2e4320532870a673ff2c6d1e33431f67e9b35bb6d7cc7981f9848de2b8d3e',
}
EXPECTED_RUNTIME_SOURCE_COMMIT = b'V3SE_SOURCE_COMMIT=ab759b0026ca69396446bf13b7a9767c59619297'



def refuse(message):
    raise ValueError(message)


def canonical(path, *, exists):
    original = path.expanduser().absolute()
    resolved = original.resolve(strict=exists)
    if original != resolved:
        refuse('symlinked or noncanonical path refused: ' + str(original))
    return resolved


def valid_root(output, payload):
    target = canonical(output, exists=False)
    if target.exists() or target.is_symlink():
        refuse('simulation output must not exist')
    if not target.parent.is_dir() or target.parent.is_symlink():
        refuse('simulation parent must already exist and be an ordinary directory')
    for base in ('/home', '/root', '/etc', '/usr', '/boot', '/var', '/dev',
                 '/proc', '/sys', '/run', '/opt'):
        root = Path(base)
        if target == root or root in target.parents:
            refuse('simulation cannot write into system or user home: ' + base)
    if target == Path('/') or target == payload or target in payload.parents or payload in target.parents:
        refuse('simulation output overlaps payload or protected root')
    return target


def verify(payload):
    stage = canonical(payload, exists=True)
    if not stage.is_dir() or stage.is_symlink():
        refuse('payload must be a plain directory')
    record = stage / 'MANIFEST.json'
    if record.is_symlink() or not record.is_file():
        refuse('missing or symlinked MANIFEST.json')
    if record.stat().st_size > 100_000:
        refuse('manifest too large')
    manifest = json.loads(record.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 or manifest.get('status') != 'OFFLINE_STAGING_ONLY_NOT_INSTALLABLE':
        refuse('not a recognized inert packaging manifest')
    if manifest.get('mode') not in ('connection-check', 'calibrated-candidate'):
        refuse('unrecognized printer configuration mode')
    rows = manifest.get('files')
    if not isinstance(rows, list) or len(rows) != len(FILES):
        refuse('manifest file count is not the exact expected set')
    actual_paths = []
    payload_bytes = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'path', 'size', 'sha256'}:
            refuse('malformed manifest file entry')
        name = row['path']
        if not isinstance(name, str) or name not in FILES or name in actual_paths:
            refuse('unlisted or repeated path in manifest: ' + str(name))
        actual_paths.append(name)
        if not isinstance(row['size'], int) or isinstance(row['size'], bool) or row['size'] < 0 or row['size'] > 10_000_000:
            refuse('invalid staged file size: ' + name)
        if not isinstance(row['sha256'], str) or not SHA_RE.fullmatch(row['sha256']):
            refuse('invalid hash field: ' + name)
        path = stage / name
        if path.is_symlink() or not path.is_file() or canonical(path, exists=True) != path.absolute():
            refuse('missing or symlinked bundled file: ' + name)
        data = path.read_bytes()
        if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            refuse('file hash/length mismatch: ' + name)
        if MARKER.search(data):
            refuse('unresolved placeholder: ' + name)
        payload_bytes[name] = data
    if set(actual_paths) != set(FILES):
        refuse('manifest omits required file')
    if hashlib.sha256(payload_bytes['metadata/v3se-stm32f103xe.config']).hexdigest() != EXPECTED_MCU_CONFIG_SHA256:
        refuse('MCU .config digest does not match accepted release')
    for name, expected in EXPECTED_MACRO_HASHES.items():
        if hashlib.sha256(payload_bytes[name]).hexdigest() != expected:
            refuse('macro digest does not match accepted release: ' + name)
    if EXPECTED_RUNTIME_SOURCE_COMMIT not in payload_bytes['metadata/versions.env'].splitlines():
        refuse('runtime commit pin does not match accepted release')
    printer = payload_bytes['user/printer_data/config/printer.cfg'].decode('utf-8')
    sections = re.findall(r'^\[([^]]+)\]', printer, re.M)
    if manifest['mode'] == 'connection-check':
        if sections != ['mcu', 'printer'] or 'kinematics: none' not in printer:
            refuse('connection-check profile cannot enable motion or heating')
    elif 'kinematics: cartesian' not in printer or any(x not in sections for x in ('mcu', 'printer', 'extruder', 'heater_bed', 'bltouch', 'strain_gauge_z_cal')):
        refuse('calibrated candidate missing required hardware profile sections')
    return manifest, payload_bytes


def validate_user(user, home):
    if not USER_RE.fullmatch(user):
        refuse('invalid Linux service user')
    expected = Path('/home') / user
    if home != str(expected):
        refuse('simulation currently models a conventional /home/<user> service account only')


def simulate(payload, *, user, home, output, inject_failure_after=0):
    validate_user(user, home)
    stage = canonical(payload, exists=True)
    manifest, files = verify(stage)
    target = valid_root(output, stage)
    unit = files['host/systemd/klipper.service'].decode('utf-8')
    moonraker = files['host/systemd/moonraker.service'].decode('utf-8')
    recover = files['host/systemd/v3se-mcu-recover.service'].decode('utf-8')
    if any('User=' + user + '\n' not in x for x in (unit, moonraker, recover)):
        refuse('rendered systemd units do not match intended service user')
    if home not in unit or home not in moonraker:
        refuse('rendered systemd paths do not match intended service home')
    # No network, systemd, apt, file ownership, firmware or host side effects.
    target.mkdir(mode=0o700)
    try:
        for index, (name, data) in enumerate(sorted(files.items()), start=1):
            relative = FILES[name].format(user=user)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as handle:
                handle.write(data)
            destination.chmod(0o700 if name == 'user/v3se-mcu-recover.sh' else 0o600)
            if inject_failure_after and index == inject_failure_after:
                raise RuntimeError('injected transactional failure for offline rollback test')
        evidence = {
            'status': 'SIMULATED_INSTALL_NOT_RUNNING',
            'user': user,
            'home': home,
            'mode': manifest['mode'],
            'files': len(files),
            'warning': 'This does not install dependencies, create services, establish safe calibration, or verify a CB1.',
        }
        (target / 'SIMULATION.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    except BaseException:
        shutil.rmtree(target)
        raise
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--verify', action='store_true', help='manifest and digest check, no writes')
    group.add_argument('--simulate', action='store_true', help='write only to a fresh scratch root, never a real host')
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--user')
    parser.add_argument('--home')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.verify:
            if args.output or args.user or args.home:
                refuse('--verify accepts only --payload')
            manifest, content = verify(args.payload)
            print('VERIFIED OFFLINE PAYLOAD:', len(content), 'files; mode:', manifest['mode'])
        else:
            if not args.output or not args.user or not args.home:
                refuse('--simulate requires --user, --home and a new --output directory')
            evidence = simulate(args.payload, user=args.user, home=args.home, output=args.output)
            print('SIMULATED ONLY:', json.dumps(evidence, sort_keys=True))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print('V3SE SANDBOX: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
