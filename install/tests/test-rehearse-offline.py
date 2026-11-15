#!/usr/bin/env python3
"""End-to-end offline rehearsal (no physical host access)."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / 'rehearse-offline.py'
ARGS = ('--user', 'testuser', '--home', '/home/testuser',
        '--mcu-serial', '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0')

def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)

with tempfile.TemporaryDirectory(prefix='v3se-stage5-rehearse-') as tmp:
    root = Path(tmp)
    target = root / 'rehearsed'
    proc = run(*ARGS, '--output', str(target))
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert (target / 'payload/MANIFEST.json').exists()
    assert (target / 'sandbox-root/SIMULATION.json').exists()
    data = json.loads((target / 'sandbox-root/SIMULATION.json').read_text())
    assert data['status'] == 'SIMULATED_INSTALL_NOT_RUNNING'
    assert data['files'] == 18
    assert data['mode'] == 'connection-check'
    assert not (target / 'sandbox-root/run').exists()
    again = run(*ARGS, '--output', str(target))
    assert again.returncode != 0 and (target / 'payload/MANIFEST.json').exists(), 'output overwrite was not refused'
    malformed = root / 'malformed'
    bad = run('--user', 'testuser', '--home', '/home/testuser',
              '--mcu-serial', '/dev/serial/by-id/../../bad', '--output', str(malformed))
    assert bad.returncode != 0 and not malformed.exists(), 'bad serial left a partial tree'
    denied = run(*ARGS, '--output', '/etc/v3se-rehearsal')
    assert denied.returncode != 0
print('PASS: single-command offline rehearsal, complete 18-file simulation, no overwrite and rollback on invalid serial')
