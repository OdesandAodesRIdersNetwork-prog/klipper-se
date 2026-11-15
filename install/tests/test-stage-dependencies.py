#!/usr/bin/env python3
"""Offline local-git fixtures for pinned source staging and rollback safety."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3se_dependency_stage', HERE / 'stage-dependencies.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def cmd(*args):
    p = subprocess.run(['git', *map(str,args)], text=True, capture_output=True, check=True)
    return p.stdout.strip()


def local_repo(path):
    path.mkdir()
    cmd('init', '-q', path)
    cmd('-C', path, 'config', 'user.name', 'V3SE Test')
    cmd('-C', path, 'config', 'user.email', 'v3se-test@example.invalid')
    (path/'source.txt').write_text('only test content\n', encoding='utf-8')
    cmd('-C', path, 'add', 'source.txt')
    cmd('-C', path, 'commit', '-qm', 'fixture')
    return cmd('-C', path, 'rev-parse', 'HEAD')

with tempfile.TemporaryDirectory(prefix='v3se-source-fixtures-') as temp:
    root = Path(temp)
    pins = dict(m.read_locked())
    for name, repo_key, sha_key, branch_key in m.SOURCE_MAP:
        src = root / ('origin-'+name)
        sha = local_repo(src)
        pins[repo_key] = str(src)
        pins[sha_key] = sha
        if branch_key:
            # A local fixture's default branch varies; create explicit test branch.
            cmd('-C', src, 'branch', 'v3se-klipper-port')
    zipdata = b'Test ZIP bytes only; not a real release.'
    pins['MAINSAIL_ZIP_SHA256'] = hashlib.sha256(zipdata).hexdigest()
    def offline_download(url, output):
        output.write_bytes(zipdata)
    output = root / 'stage'
    m.stage_all(output, pins, zip_fetch=offline_download)
    rec = m.verify_all(output, pins)
    assert len(rec['sources']) == 3
    assert rec['installation_approved'] is False
    try:
        m.stage_all(output, pins, zip_fetch=offline_download)
    except ValueError:
        pass
    else:
        raise AssertionError('existing destination accepted')
    with (output/'mainsail-v2.19.0.zip').open('ab') as f:
        f.write(b'tamper')
    try:
        m.verify_all(output, pins)
    except ValueError:
        pass
    else:
        raise AssertionError('modified archive passed verification')
    # A deliberately bad source commit must leave no partial directory.
    wrong = dict(pins)
    wrong['MOONRAKER_COMMIT'] = '0'*40
    dest = root/'bad-stage'
    try:
        m.stage_all(dest, wrong, zip_fetch=offline_download)
    except ValueError:
        assert not dest.exists(), 'stage failure did not roll back'
    else:
        raise AssertionError('wrong source commit accepted')
    # A corrupted Mainsail archive must be rejected and the tree removed.
    dest2 = root/'bad-zip'
    try:
        m.stage_all(dest2, pins, zip_fetch=lambda url,p: p.write_bytes(b'wrong bytes'))
    except ValueError:
        assert not dest2.exists(), 'Mainsail hash failure did not roll back'
    else:
        raise AssertionError('incorrect Mainsail archive accepted')
    assert m.read_locked()['V3SE_SOURCE_COMMIT'] == m.LOCKED['V3SE_SOURCE_COMMIT']
    try:
        m.scratch_dir(Path('/home/randy/anything'))
    except ValueError:
        pass
    else:
        raise AssertionError('protected /home path accepted')
print('PASS: pinned offline source staging, SHA verification, rollback and path refusal')
