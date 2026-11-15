#!/usr/bin/env python3
"""Self-contained scratch host transaction tests, requiring no printer or packages."""
import importlib.util
from pathlib import Path
import os
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / 'transaction-sandbox.py'
spec = importlib.util.spec_from_file_location('stage7_transaction', SCRIPT)
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


def must_refuse(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (ValueError, RuntimeError, OSError):
        return
    raise AssertionError('failed to refuse unsafe operation')


# Allowed file mapping is only a strict subset of the accepted 18 destinations.
mapping = {
    'host/systemd/klipper.service': 'etc/systemd/system/klipper.service',
    'user/printer_data/config/printer.cfg': 'home/{user}/printer_data/config/printer.cfg',
    'metadata/versions.env': 'share/klipper-se/versions.env',
}
contents = {key: (key + '\n').encode() for key in mapping}
with tempfile.TemporaryDirectory(prefix='v3se-stage7-test-') as temp:
    # Create a direct child of /tmp, never inside a real user's home.
    root = Path(temp)  # marker test uses this already-existent temp root
    test_root = Path('/tmp') / ('v3se-stage7-check-' + root.name)
    assert not test_root.exists()
    try:
        tx.initialize(test_root)
        (test_root / 'unrelated.txt').write_text('important independent file\n')
        plan = tx.preview(test_root, user='testuser', contents=contents, mapping=mapping)
        assert plan['installation_approved'] is False and plan['files'] == 3
        must_refuse(tx.rehearse, test_root, user='testuser', contents=contents,
                    mapping=mapping, fail_after=2)
        assert (test_root / 'unrelated.txt').read_text() == 'important independent file\n'
        assert sorted(x.name for x in test_root.iterdir()) == [tx.MARKER, 'unrelated.txt']
        report = tx.rehearse(test_root, user='testuser', contents=contents, mapping=mapping)
        assert report['files_created'] == 3 and report['installation_approved'] is False
        for name, relative in mapping.items():
            assert (test_root / relative.format(user='testuser')).read_bytes() == contents[name]
        must_refuse(tx.preview, test_root, user='testuser', contents=contents, mapping=mapping)
        assert (test_root / 'unrelated.txt').read_text() == 'important independent file\n'
        assert (test_root / 'STAGE7_REHEARSAL.json').is_file()
    finally:
        # This is a known, test-created, throwaway root. Never delete user files.
        import shutil
        if test_root.exists():
            shutil.rmtree(test_root)

    conflict = Path('/tmp') / ('v3se-stage7-conflict-' + root.name)
    try:
        tx.initialize(conflict)
        (conflict / 'etc/systemd/system').mkdir(parents=True)
        (conflict / 'etc/systemd/system/klipper.service').write_text('existing')
        must_refuse(tx.preview, conflict, user='testuser', contents=contents, mapping=mapping)
        assert (conflict / 'etc/systemd/system/klipper.service').read_text() == 'existing'
    finally:
        import shutil
        if conflict.exists():
            shutil.rmtree(conflict)

    symlink_root = Path('/tmp') / ('v3se-stage7-symlink-' + root.name)
    try:
        tx.initialize(symlink_root)
        (symlink_root / 'etc').symlink_to('/etc')
        must_refuse(tx.rehearse, symlink_root, user='testuser', contents=contents, mapping=mapping)
        assert (symlink_root / 'etc').is_symlink()
    finally:
        import shutil
        if symlink_root.exists():
            shutil.rmtree(symlink_root)

    must_refuse(tx.initialize, Path('/home/testuser/never-create-this'))
    must_refuse(tx.initialize, Path('/etc/never-create-this'))
    must_refuse(tx.initialize, Path('/tmp') / '..' / 'etc' / 'never-create-this')
    must_refuse(tx.preview, Path('/tmp/no-stage7-marker'), user='testuser', contents=contents, mapping=mapping)
    must_refuse(tx.preview, Path('/etc'), user='testuser', contents=contents, mapping=mapping)
    must_refuse(tx.planned_entries, Path('/tmp/some-root'), user='invalid user',
                contents=contents, mapping=mapping)
print('PASS: Stage7 scratch-only plan, conflict refusal, symlink protection, rollback and unrelated-file preservation')
