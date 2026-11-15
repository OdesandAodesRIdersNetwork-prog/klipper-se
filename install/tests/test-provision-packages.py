#!/usr/bin/env python3
"""Pure-fixture tests: NEVER invoke real apt, root or live CB1."""
import importlib.util
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3se_package_phase', HERE / 'provision-packages.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

base = dict(os_id='debian', os_like='', os_version='12', architecture='aarch64',
            python_version='3.11.2', systemd_active=True, user='testuser',
            user_home='/home/testuser', user_uid=1000, missing_packages=['curl'],
            missing_tools=['curl'], existing_installation_paths=[],
            serial_device_visible=False, dialout_access_group_member=False)
state = dict(base)

def snapshot(user):
    assert user == 'testuser'
    return dict(state)

def fails(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError('unsafe condition was permitted')

packages, digest = m.read_manifest()
assert len(packages) == 17 and packages[-1] == 'nginx' and len(digest) == 64
report, rc = m.plan('testuser', snapshot_func=snapshot)
assert rc == 0 and report['missing_before'] == ['curl']
assert report['does_not_authorize_installer_apply'] is True
assert report['would_run'][0] == ['apt-get', 'update']
assert report['would_run'][1][:4] == ['apt-get','install','--yes','--no-install-recommends']
assert 'NO AUTOMATIC APT ROLLBACK' in report['rollback']
assert report['hard_blockers'] == []

fails(m.execute, 'testuser', confirmation='', euid=0, snapshot_func=snapshot)
fails(m.execute, 'testuser', confirmation=m.CONFIRMATION, euid=1000, snapshot_func=snapshot)
for key, value in (
        ('architecture','x86_64'), ('os_version','13'),
        ('python_version','3.12.1'), ('systemd_active',False),
        ('existing_installation_paths',['/home/testuser/printer_data'])):
    state[key] = value
    p, rc = m.plan('testuser', snapshot_func=snapshot)
    assert rc == 2 and p['hard_blockers'], key
    fails(m.execute, 'testuser', confirmation=m.CONFIRMATION,
          euid=0, snapshot_func=snapshot)
    state[key] = base[key]

calls = []
def fake_runner(command, *, check, env, timeout):
    calls.append(command)
    assert check and env['DEBIAN_FRONTEND'] == 'noninteractive'
    assert timeout == 1800
    if len(calls) == 2:
        state['missing_packages'] = []

result = m.execute('testuser', confirmation=m.CONFIRMATION,
                   euid=0, runner=fake_runner, snapshot_func=snapshot,
                   version_reader=lambda p: '1.0-test')
assert result['mode'] == 'APT_PHASE_COMMANDS_COMPLETED_NOT_PRINTER_ACCEPTED'
assert len(calls) == 2 and result['missing_after'] == []
assert result['does_not_authorize_installer_apply'] is True
assert len(result['installed_versions']) == 17

state['missing_packages'] = ['curl']
calls.clear()
def failing_runner(command, *, check, env, timeout):
    calls.append(command)
    raise subprocess.CalledProcessError(3, command)
try:
    m.execute('testuser', confirmation=m.CONFIRMATION,
              euid=0, runner=failing_runner, snapshot_func=snapshot)
except subprocess.CalledProcessError:
    pass
else:
    raise AssertionError('partial apt failure was not surfaced')
assert len(calls) == 1
assert state['missing_packages'] == ['curl']
print('PASS: fixed 17-package apt bootstrap, unsupported/live-host refusal, root/confirmation gate, mocked apt and failure')

# Fail-closed on a modified or duplicated package manifest.
from tempfile import TemporaryDirectory
with TemporaryDirectory(prefix='v3se-apt-fixture-') as temp:
    f = Path(temp) / 'packages.txt'
    f.write_text('curl\n')
    fails(m.read_manifest, f)
    f.write_text('\n'.join(m.EXPECTED_PACKAGES) + '\ncurl\n')
    fails(m.read_manifest, f)
