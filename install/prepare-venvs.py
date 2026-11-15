#!/usr/bin/env python3
"""Build the two pinned Python environments in an isolated NEW scratch directory.

Not an installer. Never touches /home, /etc, live services, firmware, or printer.
--plan is read-only. --build invokes virtualenv and pip in a fresh scratch root,
so it MAY ACCESS THE NETWORK and run package build code. Keep --apply disabled.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('v3se_locked_sources', HERE / 'stage-dependencies.py')
STAGING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGING)
ENVS = (
    ('klippy-env', 'klipper-port', 'scripts/klippy-requirements.txt'),
    ('moonraker-env', 'moonraker', 'scripts/moonraker-requirements.txt'),
)


def refuse(message):
    raise ValueError(message)


def canonical_dir(path):
    raw = Path(path).expanduser().absolute()
    if raw.resolve(strict=True) != raw or not raw.is_dir() or raw.is_symlink():
        refuse('source directory must exist without symlinks')
    return raw


def new_output(path, stage):
    raw = Path(path).expanduser().absolute()
    if raw.resolve(strict=False) != raw or raw.exists() or raw.is_symlink():
        refuse('output must be a nonexistent non-symlink scratch path')
    if raw.parent not in (Path('/tmp'), Path('/mnt/data')):
        refuse('scratch output must be a direct child of /tmp or /mnt/data')
    if not raw.name.startswith('v3se-'):
        refuse('scratch output name must begin v3se-')
    if not raw.parent.is_dir() or raw == stage or raw in stage.parents or stage in raw.parents:
        refuse('scratch output and pinned sources must not overlap')
    return raw


def describe(stage, output):
    stage = canonical_dir(stage)
    pins = STAGING.read_locked()
    STAGING.verify_all(stage, pins)
    output = new_output(output, stage)
    entries = []
    for env_name, source_name, relative_req in ENVS:
        source = canonical_dir(stage / source_name)
        req = source / relative_req
        if (req.is_symlink() or not req.is_file() or
                req.resolve(strict=True) != req.absolute()):
            refuse('missing or symlinked pinned requirements: ' + relative_req)
        data = req.read_bytes()
        entries.append({'venv': env_name, 'source': source_name,
                        'requirements': relative_req,
                        'sha256': hashlib.sha256(data).hexdigest(),
                        'requirements_path': str(req),
                        'working_directory': str(req.parent)})
    return output, {'schema': 1, 'mode': 'SCRATCH_PYTHON_ENVS_ONLY',
                    'install_approved': False,
                    'source_commits': {k: pins[k] for k in
                                       ('V3SE_SOURCE_COMMIT', 'MOONRAKER_COMMIT')},
                    'output': str(output), 'environments': entries,
                    'network_on_build': True}


def build(stage, output, *, executor=subprocess.run):
    target, record = describe(stage, output)
    if os.geteuid() == 0:
        refuse('refuse root: virtualenv and pip must run unprivileged')
    if sys.version_info[:2] != (3, 11):
        refuse('first CB1 proof requires Python 3.11')
    if shutil.which('virtualenv') is None:
        refuse('virtualenv is missing; install declared Bookworm prerequisites first')
    target.mkdir(mode=0o700)
    created = target.stat()
    try:
        for entry in record['environments']:
            destination = target / entry['venv']
            env = dict(os.environ)
            env.update({'PIP_CONFIG_FILE': os.devnull,
                        'PIP_NO_INPUT': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
                        'PIP_CACHE_DIR': str(target / 'pip-cache'),
                        'VIRTUALENV_OVERRIDE_APP_DATA': str(target / 'virtualenv-cache'),
                        'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                        'TMPDIR': str(target)})
            executor(['virtualenv', '--no-download', '--python=python3.11', str(destination)],
                     check=True, cwd=str(target), env=env, timeout=300)
            # The Moonraker requirements contain a relative --find-links=python_wheels.
            executor([str(destination / 'bin/python'), '-m', 'pip', 'install',
                      '--no-input', '-r', entry['requirements_path']],
                     check=True, cwd=entry['working_directory'], env=env, timeout=1200)
        receipt = dict(record)
        receipt['mode'] = 'SCRATCH_VENVS_BUILT_NOT_DEPLOYED'
        (target / 'VENV_STAGE.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        return receipt
    except BaseException:
        # Only delete the new tree if it is still the same directory inode.
        current = target.lstat() if os.path.lexists(target) else None
        if (current is not None and stat.S_ISDIR(current.st_mode) and
                (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino)):
            shutil.rmtree(target)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--build', action='store_true')
    p.add_argument('--sources', required=True, type=Path, help='verified Stage 6 source staging root')
    p.add_argument('--output', required=True, type=Path, help='NEW /tmp/v3se-* scratch directory')
    a = p.parse_args()
    try:
        if a.plan:
            _, result = describe(a.sources, a.output)
        else:
            result = build(a.sources, a.output)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print('V3SE PYTHON STAGING REFUSED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
