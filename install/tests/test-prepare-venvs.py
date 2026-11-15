#!/usr/bin/env python3
"""Offline, fake-executor tests of scratch-only Klippy/Moonraker environment provisioning."""
import importlib.util
from pathlib import Path
import os
from unittest.mock import patch
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('stage7_python_envs', ROOT / 'prepare-venvs.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def must_refuse(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError('unsafe operation was unexpectedly permitted')


with tempfile.TemporaryDirectory(prefix='v3se-pyenv-fixtures-') as tmp:
    stage = Path(tmp) / 'sources'
    (stage / 'klipper-port/scripts').mkdir(parents=True)
    (stage / 'moonraker/scripts').mkdir(parents=True)
    (stage / 'klipper-port/scripts/klippy-requirements.txt').write_text('greenlet==2.0.2\n')
    (stage / 'moonraker/scripts/moonraker-requirements.txt').write_text('--find-links=python_wheels\n')
    unique = str(os.getpid())
    output = Path('/tmp') / ('v3se-python-fixture-' + unique)
    assert not output.exists(), 'scratch test requires new directory'
    pins = {'V3SE_SOURCE_COMMIT': 'accepted', 'MOONRAKER_COMMIT': 'pinned'}
    with patch.object(MODULE.STAGING, 'read_locked', return_value=pins), \
         patch.object(MODULE.STAGING, 'verify_all', return_value={'verified': True}):
        target, plan = MODULE.describe(stage, output)
        assert target == output and not output.exists()
        assert [x['venv'] for x in plan['environments']] == ['klippy-env', 'moonraker-env']
        assert plan['install_approved'] is False and plan['network_on_build'] is True
        must_refuse(MODULE.describe, stage, Path('/home/randy/klippy-env'))
        must_refuse(MODULE.describe, stage, Path('/etc/v3se-pyenv'))
        must_refuse(MODULE.describe, stage, stage / 'v3se-overlap')
        wrong = stage / 'moonraker/scripts/moonraker-requirements.txt'
        wrong.unlink()
        wrong.symlink_to('/etc/passwd')
        must_refuse(MODULE.describe, stage, output)
        wrong.unlink()
        wrong.write_text('--find-links=python_wheels\n')
        calls = []

        def fake_run(command, *, cwd, env, timeout, check):
            assert check is True and env['PIP_NO_INPUT'] == '1'
            calls.append((command, cwd))
            if command[0] == 'virtualenv':
                (Path(command[-1]) / 'bin').mkdir(parents=True)
                (Path(command[-1]) / 'bin/python').write_text('fake')
            elif len(calls) == 4:
                raise RuntimeError('injected package installation failure')

        with patch.object(MODULE.os, 'geteuid', return_value=1000), \
             patch.object(MODULE.sys, 'version_info', (3, 11, 0)), \
             patch.object(MODULE.shutil, 'which', return_value='/usr/bin/virtualenv'):
            try:
                MODULE.build(stage, output, executor=fake_run)
            except RuntimeError:
                pass
            else:
                raise AssertionError('failure injection not propagated')
            assert not output.exists(), 'failed venv staging must roll back entire scratch tree'
            calls.clear()

            def success_run(command, *, cwd, env, timeout, check):
                calls.append((command, cwd))
                if command[0] == 'virtualenv':
                    (Path(command[-1]) / 'bin').mkdir(parents=True)
                    (Path(command[-1]) / 'bin/python').write_text('fake')

            receipt = MODULE.build(stage, output, executor=success_run)
            assert receipt['mode'] == 'SCRATCH_VENVS_BUILT_NOT_DEPLOYED'
            assert (output / 'VENV_STAGE.json').is_file()
            assert len(calls) == 4 and calls[-1][1] == str(stage / 'moonraker/scripts')
            assert calls[0][0][:3] == ['virtualenv', '--no-download', '--python=python3.11']
            must_refuse(MODULE.describe, stage, output)
        import shutil
        shutil.rmtree(output)
print('PASS: pinned scratch env plan, protected roots, symlink refusal, fake virtualenv/pip, rollback, receipt')
