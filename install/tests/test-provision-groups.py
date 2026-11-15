#!/usr/bin/env python3
"""Offline identity fixtures. Never calls groupadd, usermod or queries real user."""
import importlib.util
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3se_groups_under_test', HERE / 'provision-groups.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

base = dict(os_id='debian', os_like='', os_version='12', architecture='aarch64',
            python_version='3.11.2', systemd_active=True, user='testuser',
            user_home='/home/testuser', user_uid=1000, missing_packages=[],
            missing_tools=[], existing_installation_paths=[],
            serial_device_visible=False, dialout_access_group_member=False)
state = dict(base)

memberships = {
    'dialout': {'present': True, 'member': False, 'members': []},
    'moonraker-admin': {'present': False, 'member': False, 'members': []},
}

def get_host(user):
    assert user == 'testuser'
    return dict(state)

def get_groups(user):
    assert user == 'testuser'
    return {k: dict(v) for k, v in memberships.items()}

def must_refuse(f, *args, **kwargs):
    try:
        f(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError('unsafe change unexpectedly allowed')

kwargs = {'snapshot_func': get_host, 'groups_func': get_groups}
initial, status = g.plan('testuser', **kwargs)
assert status == 0
assert initial['would_run'] == [
    ['groupadd', '--system', 'moonraker-admin'],
    ['usermod', '--append', '--groups', 'dialout,moonraker-admin', 'testuser']]
assert initial['installer_apply_enabled'] is False
must_refuse(g.configure, 'testuser', confirm='', euid=0, **kwargs)
must_refuse(g.configure, 'testuser', confirm=g.CONFIRM, euid=1000, **kwargs)

for key, val in (
        ('architecture', 'x86_64'), ('os_version', '13'),
        ('python_version', '3.12.0'), ('systemd_active', False),
        ('missing_packages', ['nginx']),
        ('existing_installation_paths', ['/etc/systemd/system/klipper.service'])):
    state[key] = val
    result, rc = g.plan('testuser', **kwargs)
    assert rc == 2 and result['hard_blockers'], key
    must_refuse(g.configure, 'testuser', confirm=g.CONFIRM, euid=0, **kwargs)
    state[key] = base[key]

memberships['dialout']['present'] = False
assert g.plan('testuser', **kwargs)[1] == 2
memberships['dialout']['present'] = True
memberships['moonraker-admin'].update(present=True, members=['other-user'])
assert g.plan('testuser', **kwargs)[1] == 2
memberships['moonraker-admin'].update(present=False, members=[])

calls = []
def mock_runner(cmd, *, check, timeout):
    assert check and timeout == 30
    calls.append(cmd)
    if cmd[0] == 'groupadd':
        memberships['moonraker-admin']['present'] = True
    elif cmd[0] == 'usermod':
        memberships['moonraker-admin']['member'] = True
        memberships['dialout']['member'] = True

result = g.configure('testuser', confirm=g.CONFIRM, euid=0,
                     runner=mock_runner, **kwargs)
assert result['mode'] == 'FRESH_CB1_GROUPS_CONFIGURED_NOT_PRINTER_ACCEPTED'
assert len(calls) == 2 and result['would_run'] == []
assert g.plan('testuser', **kwargs)[0]['would_run'] == []
assert g.configure('testuser', confirm=g.CONFIRM, euid=0,
                   runner=mock_runner, **kwargs)['mode'] == result['mode']
assert len(calls) == 2  # idempotent

# When groupadd succeeds but usermod fails, never claim rollback/acceptance.
memberships['moonraker-admin'].update(present=False, member=False)
memberships['dialout']['member'] = False
calls.clear()
def failure_runner(cmd, *, check, timeout):
    calls.append(cmd)
    if cmd[0] == 'groupadd':
        memberships['moonraker-admin']['present'] = True
    else:
        raise subprocess.CalledProcessError(1, cmd)
try:
    g.configure('testuser', confirm=g.CONFIRM, euid=0,
                runner=failure_runner, **kwargs)
except subprocess.CalledProcessError:
    pass
else:
    raise AssertionError('partial mutation error was suppressed')
assert len(calls) == 2
assert memberships['moonraker-admin']['present'] is True
print('PASS: fresh-CB1 dialout/moonraker-admin plan, refusal, mocked user/group actions, idempotence and partial-failure reporting')
