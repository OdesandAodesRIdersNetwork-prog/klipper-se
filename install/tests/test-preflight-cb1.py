#!/usr/bin/env python3
"""Pure-fixture admission tests; never probes or changes the real OS."""
import importlib.util
from pathlib import Path

here = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3se_preflight', here / 'preflight-cb1.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

base = dict(os_id='debian', os_like='', os_version='12', architecture='aarch64',
            python_version='3.11.2', systemd_active=True, user='testuser',
            user_home='/home/testuser', user_uid=1000, missing_packages=[],
            missing_tools=[], existing_installation_paths=[], serial_device_visible=True,
            dialout_access_group_member=True)

def report(**changes):
    d = dict(base); d.update(changes); return m.assess(d)

assert report()['status'] == 'READ_ONLY_PREREQUISITES_PRESENT'
assert report()['safe_to_install'] is False
assert report(missing_packages=['nginx'])['status'] == 'PREREQUISITES_PENDING'
assert report(serial_device_visible=False)['status'] == 'PREREQUISITES_PENDING'
assert report(systemd_active=False)['status'] == 'PREREQUISITES_PENDING'
assert report(dialout_access_group_member=False)['status'] == 'PREREQUISITES_PENDING'
assert report(existing_installation_paths=['/etc/systemd/system/klipper.service'])['status'] == 'HOST_CONFLICT_OR_UNSUPPORTED'
assert report(user_home='/root')['status'] == 'HOST_CONFLICT_OR_UNSUPPORTED'
assert report(architecture='x86_64')['status'] == 'HOST_CONFLICT_OR_UNSUPPORTED'
assert report(os_version='13')['status'] == 'HOST_CONFLICT_OR_UNSUPPORTED'
assert report(python_version='3.12.0')['status'] == 'HOST_CONFLICT_OR_UNSUPPORTED'
assert len(m.package_names()) == 17
print('PASS: read-only fresh-CB1 preflight decision gates')
