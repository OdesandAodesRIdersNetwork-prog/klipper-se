#!/usr/bin/env python3
"""Offline end-to-end payload verification and simulated deployment rollback."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def load_script(name, module):
    spec = importlib.util.spec_from_file_location(module, ROOT / name)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded

assembly = load_script('assemble-offline.py', 'v3se_stage_assembly')
sandbox = load_script('simulate-deployment.py', 'v3se_simulation')

def execute(script, *args):
    return subprocess.run([sys.executable, str(ROOT / script), *[str(x) for x in args]],
                          capture_output=True, text=True)

def must_fail(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (ValueError, RuntimeError):
        return
    raise AssertionError('unsafe operation was unexpectedly accepted')

with tempfile.TemporaryDirectory(prefix='v3se-stage5-test-') as td:
    root = Path(td)
    host = root / 'host'; printer = root / 'printer'; payload = root / 'payload'
    a = execute('render-templates.py', '--user', 'testuser', '--home', '/home/testuser', '--output', host)
    assert a.returncode == 0, a.stderr
    b = execute('render-printer-config.py', '--mode', 'connection-check',
                '--mcu-serial', '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0', '--output', printer)
    assert b.returncode == 0, b.stderr
    prepared = assembly.assemble(host, printer, payload)
    assert len(prepared['files']) == 18
    assert prepared['mode'] == 'connection-check'
    verified, blobs = sandbox.verify(payload)
    assert len(blobs) == len(sandbox.FILES) == 18
    assert verified['status'] == 'OFFLINE_STAGING_ONLY_NOT_INSTALLABLE'
    result = execute('simulate-deployment.py', '--verify', '--payload', payload)
    assert result.returncode == 0, result.stderr
    dry = root / 'fake-root'
    evidence = sandbox.simulate(payload, user='testuser', home='/home/testuser', output=dry)
    assert evidence['status'] == 'SIMULATED_INSTALL_NOT_RUNNING'
    assert evidence['mode'] == 'connection-check'
    assert (dry / 'etc/systemd/system/klipper.service').is_file()
    assert (dry / 'home/testuser/printer_data/config/macros.cfg').is_file()
    assert (dry / 'home/testuser/printer_data/config/macro.cfg').is_file()
    assert (dry / 'share/klipper-se/v3se-stm32f103xe.config').is_file()
    assert 'kinematics: none' in (dry / 'home/testuser/printer_data/config/printer.cfg').read_text()
    assert not (dry / 'run').exists()
    must_fail(sandbox.simulate, payload, user='testuser', home='/home/testuser', output=dry)
    must_fail(sandbox.simulate, payload, user='wrong', home='/home/testuser', output=root / 'wrong-user')
    assert not (root / 'wrong-user').exists()
    must_fail(sandbox.simulate, payload, user='testuser', home='/home/testuser', output=Path('/etc/v3se-simulation'))
    assert not Path('/etc/v3se-simulation').exists()
    failing = root / 'fail-root'
    must_fail(sandbox.simulate, payload, user='testuser', home='/home/testuser',
              output=failing, inject_failure_after=7)
    assert not failing.exists(), 'partial deployment was not rolled back'
    # Modified contents must invalidate the recorded SHA256.
    config_path = payload / 'user/printer_data/config/macros.cfg'
    saved = config_path.read_bytes()
    config_path.write_bytes(saved + b'\n# poisoned')
    must_fail(sandbox.verify, payload)
    assert not (root / 'tamper-output').exists()
    config_path.write_bytes(saved)
    # Repeated path and traversal cannot be authorized by editing the manifest.
    manifest_file = payload / 'MANIFEST.json'
    original_manifest = manifest_file.read_text()
    tampered = json.loads(original_manifest)
    tampered['files'][0]['path'] = '../etc/shadow'
    manifest_file.write_text(json.dumps(tampered))
    must_fail(sandbox.verify, payload)
    manifest_file.write_text(original_manifest)
    # A source symlink is rejected even if the target bytes have the original hash.
    old_file = payload / 'metadata/versions.env'
    clean = old_file.read_bytes()
    old_file.unlink()
    copy = root / 'target-env'
    copy.write_bytes(clean)
    old_file.symlink_to(copy)
    must_fail(sandbox.verify, payload)
    old_file.unlink()
    old_file.write_bytes(clean)
    # Simulated deployment must never claim that hardware calibration happened.
    assert 'physical' not in evidence['status'].lower()
    assert sandbox.verify(payload)[0]['mode'] == 'connection-check'
print('PASS: 18-file payload, SHA256 verification, sandbox staging, conflict refusal, rollback, anti-tampering and symlink gates')
