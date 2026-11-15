#!/usr/bin/env python3
"""Assemble a reviewable Klipper-SE installer payload in a NEW scratch directory.

No privileged paths or services are written. This tool never deploys a printer.
Host and printer inputs must already be rendered by the stage-only renderers.
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
MARKER = re.compile(r"@[A-Z][A-Z0-9_]*@")
HOST = {
    'systemd/klipper.service': 'host/systemd/klipper.service',
    'systemd/moonraker.service': 'host/systemd/moonraker.service',
    'systemd/v3se-mcu-recover.service': 'host/systemd/v3se-mcu-recover.service',
    'udev/99-v3se-mcu-recover.rules': 'host/udev/99-v3se-mcu-recover.rules',
    'nginx/sites-available/mainsail': 'host/nginx/sites-available/mainsail',
    'nginx/conf.d/upstreams.conf': 'host/nginx/conf.d/upstreams.conf',
    'nginx/conf.d/common_vars.conf': 'host/nginx/conf.d/common_vars.conf',
    'printer_data/systemd/klipper.env': 'user/printer_data/systemd/klipper.env',
    'printer_data/systemd/moonraker.env': 'user/printer_data/systemd/moonraker.env',
    'printer_data/config/moonraker.conf': 'user/printer_data/config/moonraker.conf',
    'home/mainsail/config.json': 'user/mainsail/config.json',
    'home/v3se-mcu-recover.sh': 'user/v3se-mcu-recover.sh',
}

def require_plain_file(root, name):
    candidate = root / name
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError('missing or symlinked input: ' + str(candidate))
    if candidate.resolve(strict=True) != candidate.absolute():
        raise ValueError('input traverses symlink: ' + str(candidate))
    data = candidate.read_bytes()
    if MARKER.search(data.decode('utf-8')):
        raise ValueError('unresolved template marker: ' + name)
    return data

def check_output(path, inputs):
    original = path.expanduser().absolute()
    output = original.resolve(strict=False)
    if original != output:
        raise ValueError('output path contains a symlink or noncanonical segment')
    if output == Path('/') or output.exists() or output.is_symlink():
        raise ValueError('output must be a new, unused directory')
    if not output.parent.is_dir():
        raise ValueError('parent of output must exist')
    protected = ('/home', '/root', '/etc', '/usr', '/boot', '/var', '/dev', '/proc', '/sys', '/run', '/opt')
    for part in protected:
        root = Path(part)
        if output == root or root in output.parents:
            raise ValueError('refusing write under system/printer-home tree: ' + part)
    for inp in inputs:
        if output == inp or inp in output.parents or output in inp.parents:
            raise ValueError('output must not overlap an input tree')
    return output

def assemble(host_dir, printer_dir, output):
    host_dir = host_dir.resolve(strict=True)
    printer_dir = printer_dir.resolve(strict=True)
    if not host_dir.is_dir() or not printer_dir.is_dir():
        raise ValueError('stage inputs must be directories')
    target = check_output(output, (host_dir, printer_dir, HERE))
    content = {dest: require_plain_file(host_dir, src) for src, dest in HOST.items()}
    printer = require_plain_file(printer_dir, 'printer.cfg')
    content['user/printer_data/config/printer.cfg'] = printer
    # The connection-check profile intentionally has no configured heaters/motors.
    text = printer.decode('utf-8')
    is_connection = 'kinematics: none' in text
    if is_connection:
        sections = re.findall(r'^\[([^]]+)\]', text, re.M)
        if sections != ['mcu', 'printer']:
            raise ValueError('unsafe connection-only profile sections')
    else:
        for section in ('[mcu]', '[printer]', '[extruder]', '[heater_bed]', '[bltouch]', '[strain_gauge_z_cal]'):
            if section not in text:
                raise ValueError('calibrated profile missing required section: ' + section)
    manifest = {
        'schema': 1,
        'status': 'OFFLINE_STAGING_ONLY_NOT_INSTALLABLE',
        'mode': 'connection-check' if is_connection else 'calibrated-candidate',
        'files': [
            {'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
            for name, data in sorted(content.items())
        ],
        'warning': 'Do not copy these files into a live machine until the installation and physical safety gates pass.',
    }
    # All input validation is completed before writing anything.
    target.mkdir(mode=0o700)
    try:
        for name, data in content.items():
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            dest.chmod(0o600)
        (target / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        (target / 'MANIFEST.json').chmod(0o600)
    except BaseException:
        shutil.rmtree(target)
        raise
    print('OFFLINE PACKAGE CREATED:', target)
    print('Mode:', manifest['mode'], '; files:', len(content), '; NOT DEPLOYED')
    return manifest

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-stage', required=True, type=Path)
    p.add_argument('--printer-stage', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    try:
        assemble(a.host_stage, a.printer_stage, a.output)
    except (OSError, UnicodeError, ValueError) as e:
        print('V3SE ASSEMBLY: ' + str(e), file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
