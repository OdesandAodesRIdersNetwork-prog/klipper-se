#!/usr/bin/env python3
"""Stage pinned Klipper-SE dependencies into a NEW scratch directory only.

--plan is read-only. --fetch creates ONLY a fresh scratch tree, clones three
source repositories at exact commits, and stores a checksum-verified Mainsail
release ZIP (does not extract it). --verify rechecks a previously staged tree.
No apt, pip, systemd, firmware, printer or live-home modification is possible.
This staging command is not a host installer or release acceptance test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
LOCK_FILE = HERE / 'versions.env'
# Review-locked identities: never silently accept edited repository pins.
LOCKED = {
    'V3SE_SOURCE_REPO': 'https://github.com/OdesandAodesRIdersNetwork-prog/klipper-se.git',
    'V3SE_SOURCE_BRANCH': 'v3se-klipper-port',
    'V3SE_SOURCE_COMMIT': 'ab759b0026ca69396446bf13b7a9767c59619297',
    'MOONRAKER_REPO': 'https://github.com/Arksine/moonraker.git',
    'MOONRAKER_COMMIT': 'b559b9a81161f958a43c2f527b6ad96f73310d5d',
    'MAINSAIL_CONFIG_REPO': 'https://github.com/mainsail-crew/mainsail-config.git',
    'MAINSAIL_CONFIG_COMMIT': 'ff3869a621db17ce3ef660adbbd3fa321995ac42',
    'MAINSAIL_VERSION': 'v2.19.0',
    'MAINSAIL_ZIP_URL': 'https://github.com/mainsail-crew/mainsail/releases/download/v2.19.0/mainsail.zip',
    'MAINSAIL_ZIP_SHA256': 'c4d9d96f89851c6ae0709c2f20725447f3fe8c57cf193869b0083441bd93378a',
}
MAX_ZIP_BYTES = 20 * 1024 * 1024
SOURCE_MAP = (
    ('klipper-port', 'V3SE_SOURCE_REPO', 'V3SE_SOURCE_COMMIT', 'V3SE_SOURCE_BRANCH'),
    ('moonraker', 'MOONRAKER_REPO', 'MOONRAKER_COMMIT', None),
    ('mainsail-config', 'MAINSAIL_CONFIG_REPO', 'MAINSAIL_CONFIG_COMMIT', None),
)


def refuse(message):
    raise ValueError(message)


def read_locked(path=LOCK_FILE):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Z][A-Z0-9_]*)=([^\s]+)', line)
        if not match or match[1] in values:
            refuse('malformed or duplicate version pin')
        values[match[1]] = match[2]
    for key, expected in LOCKED.items():
        if values.get(key) != expected:
            refuse('immutable version pin mismatch: ' + key)
    return values


def scratch_dir(value):
    raw = Path(value).expanduser().absolute()
    resolved = raw.resolve(strict=False)
    if raw != resolved:
        refuse('symlinked/noncanonical staging path forbidden')
    if resolved.exists() or resolved.is_symlink():
        refuse('staging destination must not exist')
    if not resolved.parent.is_dir() or resolved.parent.is_symlink():
        refuse('staging destination parent must be a real existing directory')
    for base in ('/home', '/root', '/etc', '/usr', '/boot', '/var', '/dev',
                 '/proc', '/sys', '/run', '/opt'):
        b = Path(base)
        if resolved == b or b in resolved.parents:
            refuse('never stage inside system/printer tree: ' + base)
    if resolved == Path('/') or resolved == HERE or HERE in resolved.parents:
        refuse('never stage inside packaging source')
    return resolved


def git_env():
    env = dict(os.environ)
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['GIT_CONFIG_NOSYSTEM'] = '1'
    env['GIT_CONFIG_GLOBAL'] = os.devnull
    env['GIT_LFS_SKIP_SMUDGE'] = '1'
    return env


def git_command(args, *, timeout=240):
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *map(str, args)],
                            text=True, capture_output=True, check=False,
                            env=git_env(), timeout=timeout)
    if result.returncode:
        refuse('git operation failed: ' + ' '.join(map(str, args[:2])) + ': ' + result.stderr[-700:])
    return result.stdout.strip()


def stage_repo(dest, url, sha, branch=None):
    cmd = ['clone', '--quiet', '--no-checkout']
    if branch:
        cmd.extend(['--branch', branch])
    git_command([*cmd, url, dest])
    git_command(['-C', dest, 'checkout', '--quiet', '--detach', sha])
    check_repo(dest, url, sha)


def check_repo(dest, url, sha):
    if dest.is_symlink() or not dest.is_dir() or (dest / '.git').is_symlink():
        refuse('missing or symlinked staged repository: ' + dest.name)
    if git_command(['-C', dest, 'rev-parse', 'HEAD']) != sha:
        refuse('source checkout SHA mismatch: ' + dest.name)
    if git_command(['-C', dest, 'remote', 'get-url', 'origin']) != url:
        refuse('source origin mismatch: ' + dest.name)
    if git_command(['-C', dest, 'status', '--porcelain']):
        refuse('staged checkout must be clean: ' + dest.name)


def fetch_zip(url, output):
    req = urllib.request.Request(url, headers={'User-Agent': 'Klipper-SE-pinned-source-stage/1'})
    with urllib.request.urlopen(req, timeout=60) as response, output.open('xb') as dest:
        written = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_ZIP_BYTES:
                refuse('Mainsail release exceeds staging download size cap')
            dest.write(chunk)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def stage_all(dest, pins, *, repo_fetch=stage_repo, zip_fetch=fetch_zip):
    target = scratch_dir(dest)
    target.mkdir(mode=0o700)
    try:
        sources = {}
        for dirname, url_key, sha_key, branch_key in SOURCE_MAP:
            repo_fetch(target / dirname, pins[url_key], pins[sha_key],
                       pins[branch_key] if branch_key else None)
            check_repo(target / dirname, pins[url_key], pins[sha_key])
            sources[dirname] = {'origin': pins[url_key], 'commit': pins[sha_key]}
        release = target / 'mainsail-v2.19.0.zip'
        zip_fetch(pins['MAINSAIL_ZIP_URL'], release)
        if release.is_symlink() or not release.is_file() or release.stat().st_size > MAX_ZIP_BYTES:
            refuse('Mainsail ZIP missing/oversized/symlinked')
        actual = digest(release)
        if actual != pins['MAINSAIL_ZIP_SHA256']:
            refuse('Mainsail ZIP SHA256 mismatch')
        record = {
            'schema': 1,
            'mode': 'SOURCE_STAGING_ONLY_NOT_INSTALLED',
            'sources': sources,
            'mainsail': {'url': pins['MAINSAIL_ZIP_URL'], 'version': pins['MAINSAIL_VERSION'],
                         'file': release.name, 'bytes': release.stat().st_size, 'sha256': actual},
            'installation_approved': False,
        }
        (target / 'STAGED_SOURCES.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        return record
    except BaseException:
        shutil.rmtree(target)
        raise


def verify_all(path, pins):
    target = Path(path).expanduser().absolute()
    if target.resolve(strict=True) != target or not target.is_dir():
        refuse('stage root must be a real directory without symlink ancestors')
    manifest = target / 'STAGED_SOURCES.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 10000:
        refuse('missing or unsafe staging manifest')
    stored = json.loads(manifest.read_text(encoding='utf-8'))
    if stored.get('schema') != 1 or stored.get('mode') != 'SOURCE_STAGING_ONLY_NOT_INSTALLED' or stored.get('installation_approved') is not False:
        refuse('invalid or installable staging manifest')
    expected_names = {item[0] for item in SOURCE_MAP}
    if set(stored.get('sources', {})) != expected_names:
        refuse('unexpected staged repository list')
    for dirname, url_key, sha_key, _ in SOURCE_MAP:
        if stored['sources'][dirname] != {'origin': pins[url_key], 'commit': pins[sha_key]}:
            refuse('staged source metadata changed: ' + dirname)
        check_repo(target / dirname, pins[url_key], pins[sha_key])
    release = target / 'mainsail-v2.19.0.zip'
    if release.is_symlink() or not release.is_file() or release.stat().st_size > MAX_ZIP_BYTES:
        refuse('missing or unsafe staged Mainsail archive')
    expected = {'url': pins['MAINSAIL_ZIP_URL'], 'version': pins['MAINSAIL_VERSION'],
                'file': release.name, 'bytes': release.stat().st_size,
                'sha256': pins['MAINSAIL_ZIP_SHA256']}
    if stored.get('mainsail') != expected or digest(release) != pins['MAINSAIL_ZIP_SHA256']:
        refuse('Mainsail staged checksum/metadata mismatch')
    return stored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--plan', action='store_true', help='print pinned identities, no network or writes')
    group.add_argument('--fetch', action='store_true', help='network fetch to NEW scratch directory only')
    group.add_argument('--verify', action='store_true', help='read-only verify existing scratch source stage')
    parser.add_argument('--output', type=Path, help='NEW scratch dir for fetch; existing stage dir for verify')
    args = parser.parse_args()
    try:
        pins = read_locked()
        if args.plan:
            if args.output:
                refuse('--plan does not accept --output')
            print(json.dumps({'mode': 'READ_ONLY_SOURCE_PIN_PLAN',
                              'pins': {k: pins[k] for k in LOCKED},
                              'installation_approved': False}, indent=2, sort_keys=True))
            return 0
        if args.output is None:
            refuse('--fetch and --verify require --output')
        if args.fetch:
            if os.geteuid() == 0:
                refuse('run as a regular user, not root')
            record = stage_all(args.output, pins)
        else:
            record = verify_all(args.output, pins)
        print(json.dumps(record, indent=2, sort_keys=True))
        print('SOURCES ONLY: not installed, not connected to printer, --apply disabled')
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print('V3SE PINNED STAGING: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
