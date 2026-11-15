#!/usr/bin/env python3
"""One-command, OFFLINE ONLY rehearsal of the connection-check packaging path.

Creates stages, 18-file checksum payload, verifies it, and simulates an inert
filesystem deployment beneath a NEW scratch directory. NO system/CB1 changes.
"""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent

def load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

assembly = load('assemble-offline.py', 'v3se_assembly')
sandbox = load('simulate-deployment.py', 'v3se_sandbox')

def run(args):
    sandbox.validate_user(args.user, args.home)
    # Output must not be inside the installation user's home, /etc, etc.
    destination = sandbox.valid_root(args.output, HERE)
    destination.mkdir(mode=0o700)
    try:
        stages = (
            ('host-stage', 'render-templates.py', ['--user', args.user, '--home', args.home]),
            ('printer-stage', 'render-printer-config.py', [
                '--mode', 'connection-check', '--mcu-serial', args.mcu_serial]),
        )
        for folder, script, options in stages:
            subprocess.run([sys.executable, str(HERE / script), *options,
                            '--output', str(destination / folder)], check=True)
        payload = destination / 'payload'
        manifest = assembly.assemble(destination / 'host-stage',
                                     destination / 'printer-stage', payload)
        sandbox.verify(payload)
        evidence = sandbox.simulate(payload, user=args.user, home=args.home,
                                    output=destination / 'sandbox-root')
    except BaseException:
        shutil.rmtree(destination)
        raise
    print('PASS: offline rehearsal of', manifest['mode'], 'on', evidence['files'], 'files')
    print('REVIEW ONLY:', destination)
    print('No services, firmware, apt packages, user files or printer were changed.')
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user', required=True)
    p.add_argument('--home', required=True)
    p.add_argument('--mcu-serial', required=True)
    p.add_argument('--output', type=Path, required=True)
    try:
        return run(p.parse_args())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('V3SE REHEARSAL: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
