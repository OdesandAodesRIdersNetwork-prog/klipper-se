#!/usr/bin/env python3
"""Offline services activation tests in a fake root. No systemctl/nginx/udevadm."""
import importlib.util
from pathlib import Path
import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3se_activate_fixture', HERE / 'activate-services.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

with tempfile.TemporaryDirectory(prefix='v3se-service-activation-fixture-') as td:
    fake = Path(td)
    home = fake / 'home/testuser'
    home.mkdir(parents=True)
    home.chmod(0o755)
    (home / '.v3se-install-inputs').mkdir()
    (home / 'printer_data/config').mkdir(parents=True)
    (home / 'printer_data/config/printer.cfg').write_text('[mcu]\nserial: fake\n[printer]\nkinematics: none\n')
    hr = {'schema': 1, 'status': 'HOST_FILES_WRITTEN_NO_SERVICES_RUNNING',
          'connection_only': True, 'user': 'testuser', 'files': 18,
          'does_not_authorize_printing': True, 'payload_digest': 'c'*64}
    (home / '.v3se-install-inputs/HOST_FILE_DEPLOYMENT.json').write_text(json.dumps(hr))
    rr = {'schema': 1, 'status': 'RUNTIME_ASSETS_INSTALLED_NOT_STARTED',
          'connection_only': True, 'safe_to_print': False,
          'user': 'testuser', 'klipper': 'test-only'}
    (home / '.v3se-install-inputs/RUNTIME_ASSETS.json').write_text(json.dumps(rr))
    for path in ('klipper-port/klippy/klippy.py', 'moonraker/moonraker/moonraker.py',
                 'klippy-env/bin/python', 'moonraker-env/bin/python', 'mainsail/index.html'):
        f = home / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('fixture')
    (home / 'printer_data/config/mainsail.cfg').symlink_to(home / 'mainsail/index.html')
    for name in ('klipper.service', 'moonraker.service', 'v3se-mcu-recover.service'):
        d = fake / 'etc/systemd/system'
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text('[Unit]\nDescription=TEST\n')
    (fake / 'etc/nginx/sites-available').mkdir(parents=True)
    (fake / 'etc/nginx/sites-enabled').mkdir(parents=True)
    mainsail = fake / 'etc/nginx/sites-available/mainsail'
    mainsail.write_text('TEST')
    default_file = fake / 'etc/nginx/sites-available/default'
    default_file.write_text('DEFAULT')
    default_link = fake / 'etc/nginx/sites-enabled/default'
    default_link.symlink_to(default_file)
    serial = fake / 'dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'
    serial.parent.mkdir(parents=True)
    serial.write_text('fake connector')
    ident = SimpleNamespace(pw_dir='/home/testuser', pw_uid=os.getuid(), pw_gid=os.getgid())
    with patch.object(m.pwd, 'getpwnam', return_value=ident), \
         patch.object(m.os, 'geteuid', return_value=0), \
         patch.object(m.platform, 'machine', return_value='aarch64'), \
         patch.object(m.sys, 'version_info', (3, 11, 0)):
        plan = m.assess('testuser', root=fake, service_active=lambda name: False)
        assert not plan['blockers'] and plan['mainsail_default_link_disable_required']
        # Failure while enabling Moonraker cleans the new site and puts the distro default back.
        calls = []
        def failing(cmd, *, check, timeout):
            calls.append(cmd)
            if cmd[:3] == ['systemctl', 'enable', '--now'] and cmd[-1] == 'moonraker.service':
                raise subprocess.CalledProcessError(1, cmd)
        try:
            m.activate('testuser', runner=failing, root=fake,
                       service_active=lambda _: False)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError('failure was not raised')
        assert default_link.is_symlink()
        assert not (fake / 'etc/nginx/sites-enabled/mainsail').exists()
        assert not (home / '.v3se-install-inputs/CONNECTION_SERVICES.json').exists()
        assert any(x[:3] == ['systemctl', 'disable', '--now'] for x in calls)
        calls.clear()
        def runner(cmd, *, check, timeout):
            calls.append(cmd)
        done = m.activate('testuser', runner=runner, root=fake,
                          service_active=lambda _: False)
        assert done['status'] == 'SERVICES_STARTED_CONNECTION_ONLY'
        assert done['safe_to_print'] is False
        assert (fake / 'etc/nginx/sites-enabled/mainsail').is_symlink()
        assert not default_link.exists() and not default_link.is_symlink()
        assert (home / '.v3se-install-inputs/CONNECTION_SERVICES.json').exists()
        assert any(x == ['systemctl', 'enable', '--now', 'klipper.service'] for x in calls)
        assert any(x == ['systemctl', 'enable', '--now', 'nginx'] for x in calls)
        assert m.assess('testuser', root=fake)['blockers']  # cannot re-activate
print('PASS: offline connection-only service plan, default-site protection, rollback, nonprinting status')
