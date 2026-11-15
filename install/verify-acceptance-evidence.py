#!/usr/bin/env python3
"""Read-only verification of operator-provided fresh-printer acceptance records.

A complete record is NOT independent proof that tests were physically run.
Never contacts a printer or authorizes installation, motion or printing.
"""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ACCEPTED_SOURCE = 'ab759b0026ca69396446bf13b7a9767c59619297'
ACKNOWLEDGEMENT = 'FRESH_CB1_AND_STOCK_V3SE_PHYSICALLY_TESTED'
SHA = re.compile(r'[0-9a-f]{64}\Z')


def load_renderer():
    spec = importlib.util.spec_from_file_location('v3se_evidence_target_values', HERE / 'render-printer-config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refuse(reason):
    raise ValueError(reason)


def document(path):
    p = pathlib.Path(path).expanduser().absolute()
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 300_000:
        refuse('acceptance record must be an ordinary, bounded JSON file')
    def reject_duplicate(pairs):
        d = {}
        for key, value in pairs:
            if key in d:
                refuse('duplicate evidence field: ' + key)
            d[key] = value
        return d
    return json.loads(p.read_text(encoding='utf-8'), object_pairs_hook=reject_duplicate)


def checked_text(value, label, minimum=12):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= 1000:
        refuse('missing or vague evidence text: ' + label)
    banned = ('NOT RUN', 'NOT TESTED', 'TODO', 'PLACEHOLDER', 'COPY FROM REFERENCE')
    if any(token in value.upper() for token in banned):
        refuse('placeholder evidence is not permitted: ' + label)
    return value.strip()


def verify(record, measurements_path):
    needed = {'schema', 'acknowledgement', 'target_printer', 'target_cb1',
              'operator', 'test_date', 'source_commit', 'firmware_version',
              'firmware_binary_sha256', 'measurement_sha256',
              'manual_firmware_flash_observation', 'display_z_offset_menu',
              'tests'}
    if not isinstance(record, dict) or set(record) != needed or record['schema'] != 1:
        refuse('acceptance evidence does not match exact schema')
    if record['acknowledgement'] != ACKNOWLEDGEMENT:
        refuse('separate target-hardware acceptance acknowledgement missing')
    if record['source_commit'] != ACCEPTED_SOURCE:
        refuse('runtime source commit does not match accepted Klipper-SE reference')
    for item in ('target_printer', 'target_cb1', 'operator', 'firmware_version',
                 'manual_firmware_flash_observation'):
        checked_text(record[item], item)
    if 'V3 SE' not in record['target_printer']:
        refuse('target printer record must identify an Ender-3 V3 SE')
    if not isinstance(record['test_date'], str) or not re.fullmatch(r'20\d\d-\d\d-\d\d', record['test_date']):
        refuse('test date must be YYYY-MM-DD')
    for key in ('firmware_binary_sha256', 'measurement_sha256'):
        if not isinstance(record[key], str) or not SHA.fullmatch(record[key]):
            refuse('bad SHA256: ' + key)
    measurement_file = pathlib.Path(measurements_path).expanduser().absolute()
    if not measurement_file.is_file() or measurement_file.is_symlink():
        refuse('target measurements JSON missing or symlinked')
    digest = hashlib.sha256(measurement_file.read_bytes()).hexdigest()
    if digest != record['measurement_sha256']:
        refuse('target measurement file does not match recorded SHA256')
    # All nine machine-specific numbers and confirmation must be present.
    renderer = load_renderer()
    converted = renderer.load_measurements(measurement_file)
    if len(converted) != 9:
        refuse('target measurement field count is not nine')
    display = record['display_z_offset_menu']
    if not isinstance(display, dict) or set(display) != {'status', 'observation'}:
        refuse('display menu regression evidence is required')
    if display['status'] != 'PASS':
        refuse('inherited Prepare > Z-offset menu regression not proven')
    checked_text(display['observation'], 'display_z_offset_menu')
    tests = record['tests']
    if not isinstance(tests, list) or len(tests) != 17:
        refuse('exactly 17 independently observed physical checks required')
    observed = set()
    for item in tests:
        if not isinstance(item, dict) or set(item) != {'id', 'result', 'observation'}:
            refuse('malformed test evidence row')
        number = item['id']
        if type(number) is not int or number not in range(1, 18) or number in observed:
            refuse('test ID missing, repeated or out of range')
        if item['result'] != 'PASS':
            refuse('all target physical tests must pass')
        checked_text(item['observation'], 'test ' + str(number), minimum=20)
        observed.add(number)
    return {'status': 'OPERATOR_RECORD_COMPLETE_REQUIRES_INDEPENDENT_HARDWARE_REVIEW',
            'mode': 'READ_ONLY', 'physical_tests_attested': len(observed),
            'target_printer': record['target_printer'],
            'source_commit': ACCEPTED_SOURCE,
            'measurements_sha256': digest,
            'not_an_install_or_release_approval': True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--record', type=pathlib.Path, required=True)
    p.add_argument('--measurements', type=pathlib.Path, required=True)
    a = p.parse_args()
    try:
        result = verify(document(a.record), a.measurements)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print('V3SE ACCEPTANCE RECORD REFUSED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
