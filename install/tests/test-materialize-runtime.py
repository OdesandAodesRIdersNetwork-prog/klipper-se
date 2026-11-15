#!/usr/bin/env python3
"""Offline end-to-end source/frontend fixture: no network, apt, systemd or printer."""
import importlib.util
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_fixture', HERE / 'materialize-runtime.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fails(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except (ValueError, FileExistsError):
        return
    raise AssertionError('unsafe operation accepted')


def git(*args, cwd=None):
    return subprocess.run(['git', *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()

with tempfile.TemporaryDirectory(prefix='v3se-runtime-fixture-') as td:
    root = Path(td)
    home = root / 'home'
    (home / '.v3se-install-inputs').mkdir(parents=True)
    (home / 'printer_data/config').mkdir(parents=True)
    (home / 'mainsail').mkdir()
    (home / 'mainsail/config.json').write_text('{"ok": true}')
    (home / 'printer_data/config/printer.cfg').write_text('[mcu]\nserial: fake\n\n[printer]\nkinematics: none\n')
    receipt = {'schema': 1, 'status': 'HOST_FILES_WRITTEN_NO_SERVICES_RUNNING',
               'connection_only': True, 'user': 'testuser', 'files': 18,
               'does_not_authorize_printing': True, 'payload_digest': 'a' * 64}
    (home / '.v3se-install-inputs/HOST_FILE_DEPLOYMENT.json').write_text(json.dumps(receipt))
    sources = root / 'staged'
    sources.mkdir()
    refs = {}
    for dirname, url_key, sha_key, branch in m.STAGE.SOURCE_MAP:
        src = sources / dirname
        src.mkdir()
        git('init', '-q', cwd=src)
        git('config', 'user.email', 'test@example.com', cwd=src)
        git('config', 'user.name', 'Test', cwd=src)
        if dirname == 'mainsail-config':
            (src / 'mainsail.cfg').write_text('[include client.cfg]\n')
        else:
            (src / 'scripts').mkdir()
            req = 'klippy-requirements.txt' if dirname == 'klipper-port' else 'moonraker-requirements.txt'
            (src / 'scripts' / req).write_text('sample==0.1\n')
        git('add', '-A', cwd=src)
        git('commit', '-qm', 'fixture', cwd=src)
        refs[sha_key] = git('rev-parse', 'HEAD', cwd=src)
        refs[url_key] = 'https://example.com/' + dirname + '.git'
    refs['MAINSAIL_VERSION'] = 'v2.19.0'
    with zipfile.ZipFile(sources / 'mainsail-v2.19.0.zip', 'w') as z:
        z.writestr('index.html', '<html>test</html>')
        z.writestr('assets/test.js', 'console.log("ok")')
        z.writestr('config.json', '{"overwritten": true}')
    with patch.object(m.STAGE, 'read_locked', return_value=refs), \
         patch.object(m.STAGE, 'verify_all', return_value={'ok': True}):
        p = m.source_plan(sources, 'testuser', home)
        assert not p['blockers'] and p['expected_source_commit'] == refs['V3SE_SOURCE_COMMIT']
        assert m.validate_archive(sources / 'mainsail-v2.19.0.zip')
        # ZIP traversal and symlink are rejected prior to extraction.
        bad_zip = root / 'bad.zip'
        with zipfile.ZipFile(bad_zip, 'w') as z:
            z.writestr('../etc/passwd', 'bad')
        fails(m.validate_archive, bad_zip)
        calls = []
        def fake_exec(command, *, cwd, env, check, timeout):
            calls.append(command)
            if command[0] == 'virtualenv':
                t = Path(command[-1])
                (t / 'bin').mkdir(parents=True)
                (t / 'bin/python').write_text('#fake python')
                return
            if len(command) > 1 and command[1] == '-m':
                return
            return subprocess.run(command, cwd=cwd, env=env, check=check,
                                  timeout=timeout, capture_output=True)
        account = SimpleNamespace(pw_uid=1000, pw_dir=str(home))
        with patch.object(m.os, 'geteuid', return_value=1000), \
             patch.object(m.sys, 'version_info', (3, 11, 0)), \
             patch.object(m.platform, 'machine', return_value='aarch64'), \
             patch.object(m.shutil, 'which', return_value='/usr/bin/virtualenv'), \
             patch.object(m.pwd, 'getpwnam', return_value=account):
            record = m.install(sources, 'testuser', home, executor=fake_exec)
        assert record['status'] == 'RUNTIME_ASSETS_INSTALLED_NOT_STARTED'
        assert len([cmd for cmd in calls if cmd[0]=='virtualenv']) == 2
        assert (home / 'klipper-port/scripts/klippy-requirements.txt').is_file()
        assert (home / 'moonraker/scripts/moonraker-requirements.txt').is_file()
        assert (home / 'mainsail/index.html').is_file()
        assert (home / 'mainsail/assets/test.js').is_file()
        assert (home / 'mainsail/config.json').read_text() == '{"ok": true}'
        assert (home / 'mainsail/.version').read_text().strip() == 'v2.19.0'
        assert (home / 'printer_data/config/mainsail.cfg').is_symlink()
        assert m.source_plan(sources, 'testuser', home)['blockers']
print('PASS: pinned staged local Git checkouts, preserved frontend config, two venvs, receipt, symlink and ZIP traversal protection')
