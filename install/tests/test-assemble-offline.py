#!/usr/bin/env python3
"""Offline package-assembly safety checks. No system configuration writes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
modspec = importlib.util.spec_from_file_location('v3se_assembly', ROOT / 'assemble-offline.py')
mod = importlib.util.module_from_spec(modspec)
modspec.loader.exec_module(mod)
SERIAL = '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'

def command(*args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True)

with tempfile.TemporaryDirectory(prefix='v3se-assembly-test-') as tmp:
    root = Path(tmp)
    host = root / 'host'
    printer = root / 'printer'
    a = command(ROOT / 'render-templates.py', '--user', 'testuser', '--home', '/home/testuser', '--output', host)
    assert a.returncode == 0, a.stderr
    b = command(ROOT / 'render-printer-config.py', '--mode', 'connection-check', '--mcu-serial', SERIAL, '--output', printer)
    assert b.returncode == 0, b.stderr
    out = root / 'payload'
    manifest = mod.assemble(host, printer, out)
    assert manifest['mode'] == 'connection-check'
    assert len(manifest['files']) == len(mod.HOST) + 1 + len(mod.MACRO_SOURCES) + len(mod.BUILD_INPUTS)
    assert all((out / x['path']).is_file() for x in manifest['files'])
    assert 'NOT_INSTALLABLE' in (out / 'MANIFEST.json').read_text()
    for mandatory in ('user/printer_data/config/macros.cfg',
                      'user/printer_data/config/macro.cfg',
                      'metadata/versions.env', 'metadata/packages-bookworm.txt',
                      'metadata/v3se-stm32f103xe.config'):
        assert (out / mandatory).is_file(), mandatory

    try:
        mod.assemble(host, printer, out)
        assert False, 'overwriting existing payload was not refused'
    except ValueError:
        pass
    try:
        mod.assemble(host, printer, host / 'nested')
        assert False, 'writing into source staging tree was not refused'
    except ValueError:
        pass
    t = host / 'nginx' / 'conf.d' / 'common_vars.conf'
    t.unlink()
    t.symlink_to('/etc/passwd')
    try:
        mod.assemble(host, printer, root / 'unsafe')
        assert False, 'source symlink was not refused'
    except ValueError:
        pass
    assert not (root / 'unsafe').exists()
print('PASS: complete 18-file payload, digest manifest, macro/build inputs, no overwrite, no source overlap, no symlink escape')
