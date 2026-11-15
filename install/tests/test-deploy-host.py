#!/usr/bin/env python3
"""Offline fixture tests for real-shaped host transaction. No live host mutation."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parents[1]

def load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

host = load('deploy-host.py', 'v3se_host_transaction_fixture')
assembler = load('assemble-offline.py', 'v3se_assembly_fixture')


def command(name, *args):
    p = subprocess.run([sys.executable, str(HERE / name), *map(str, args)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def fail(f, *args, **kwargs):
    try:
        f(*args, **kwargs)
    except (ValueError, RuntimeError, FileExistsError, NotADirectoryError):
        return
    raise AssertionError('unexpectedly accepted unsafe condition')

with TemporaryDirectory(prefix='v3se-host-transaction-') as td:
    top = Path(td)
    hs, ps, package = top / 'host-stage', top / 'printer-stage', top / 'payload'
    command('render-templates.py', '--user', 'testuser', '--home', '/home/testuser', '--output', hs)
    command('render-printer-config.py', '--mode', 'connection-check',
            '--mcu-serial', '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0', '--output', ps)
    assembler.assemble(hs, ps, package)
    manifest, content = host.verify(package)
    assert manifest['mode'] == 'connection-check'
    root = top / 'fake-host'
    (root / 'home/testuser').mkdir(parents=True)
    (root / 'etc/systemd/system').mkdir(parents=True)
    (root / 'etc/nginx/conf.d').mkdir(parents=True)
    (root / 'etc/nginx/sites-available').mkdir(parents=True)
    (root / 'etc/udev/rules.d').mkdir(parents=True)
    # Existing unrelated files are retained, and the exact deployment is idempotently refused.
    other = root / 'etc/nginx/conf.d/unrelated.conf'
    other.write_text('leave-me-alone\n')
    specs = host.specs('testuser', content)
    assert len(specs) == 18
    assert not host.inspect(root, 'testuser', specs)
    fail(host.specs, 'randy/../../etc', content)
    injected = top / 'rollback-host'
    shutil.copytree(root, injected)
    fail(host.transaction, injected, 'testuser', content, fail_after=8, uid=os.getuid(), gid=os.getgid())
    assert (injected / 'etc/nginx/conf.d/unrelated.conf').read_text() == 'leave-me-alone\n'
    assert not (injected / 'etc/systemd/system/klipper.service').exists()
    assert not (injected / 'home/testuser/printer_data').exists()
    good = host.transaction(root, 'testuser', content, uid=os.getuid(), gid=os.getgid())
    assert good['files'] == 18 and good['connection_only'] is True
    assert 'kinematics: none' in (root / 'home/testuser/printer_data/config/printer.cfg').read_text()
    assert (root / 'home/testuser/.v3se-install-inputs/HOST_FILE_DEPLOYMENT.json').is_file()
    import stat
    assert stat.S_IMODE((root / 'home/testuser/mainsail').stat().st_mode) == 0o755
    assert stat.S_IMODE((root / 'home/testuser/mainsail/config.json').stat().st_mode) == 0o644
    assert stat.S_IMODE((root / 'home/testuser/printer_data/config/printer.cfg').stat().st_mode) == 0o600
    assert (root / 'etc/nginx/conf.d/unrelated.conf').read_text() == 'leave-me-alone\n'
    fail(host.transaction, root, 'testuser', content, uid=os.getuid(), gid=os.getgid())
    # Pre-existing file refusal cannot remove or overwrite unrelated contents.
    saved = root / 'home/testuser/printer_data/config/printer.cfg'
    saved.write_text('user-existing!')
    fail(host.transaction, root, 'testuser', content, uid=os.getuid(), gid=os.getgid())
    assert saved.read_text() == 'user-existing!'
    # Symlinked /etc ancestors and home are refused before writes.
    symlink_host = top / 'link-host'
    shutil.copytree(injected, symlink_host)
    (symlink_host / 'etc/nginx/sites-available').rmdir()
    (symlink_host / 'etc/nginx/sites-available').symlink_to('/etc')
    fail(host.inspect, symlink_host, 'testuser', specs) if False else None
    assert any('unsafe ancestor' in x for x in host.inspect(symlink_host, 'testuser', specs))
    fail(host.transaction, symlink_host, 'testuser', content, uid=os.getuid(), gid=os.getgid())
    # Manipulation of manifest must be rejected by the payload verifier.
    manifest_file = package / 'MANIFEST.json'
    raw = manifest_file.read_text()
    manifest_file.write_text(raw.replace('OFFLINE_STAGING_ONLY_NOT_INSTALLABLE', 'APPROVED'))
    fail(host.verify, package)
print('PASS: 18-file fresh-host transaction, rollback, conflicts, symlink refusal and connection-only protection')
