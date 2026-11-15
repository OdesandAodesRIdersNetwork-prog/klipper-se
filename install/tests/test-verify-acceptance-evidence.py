#!/usr/bin/env python3
"""Fake operator evidence fixtures, not a physical-acceptance demonstration."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v3se_evidence_fixture', HERE / 'verify-acceptance-evidence.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fails(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError('unsafe or incomplete acceptance evidence unexpectedly passed')

with tempfile.TemporaryDirectory(prefix='v3se-acceptance-schema-') as temp:
    root = Path(temp)
    measurements = root / 'fake-measurements.json'
    values = {'bltouch_z_offset': 2.0, 'counts_per_gram': 90.0,
              'reference_tare_counts': 123456}
    for heater in ('extruder', 'bed'):
        for term in ('kp', 'ki', 'kd'):
            values[f'{heater}_pid_{term}'] = 1.0
    measurements.write_text(json.dumps({'confirmation': 'MEASURED_ON_THIS_PRINTER',
        'printer_label': 'Synthetic unit test fixture only',
        'measurement_notes': 'Not obtained by hardware measurement',
        'values': values}))
    record = {'schema': 1, 'acknowledgement': m.ACKNOWLEDGEMENT,
              'target_printer': 'Synthetic Ender-3 V3 SE unit test',
              'target_cb1': 'Synthetic separate CB1 fixture',
              'operator': 'Synthetic test operator', 'test_date': '2026-11-15',
              'source_commit': m.ACCEPTED_SOURCE,
              'firmware_version': 'FAKE TEST VERSION ONLY',
              'firmware_binary_sha256': 'f' * 64,
              'measurement_sha256': hashlib.sha256(measurements.read_bytes()).hexdigest(),
              'manual_firmware_flash_observation': 'Synthetic acceptance file; no SD flash was performed',
              'display_z_offset_menu': {'status': 'PASS',
                 'observation': 'Synthetic menu verification for parser unit tests only'},
              'tests': [{'id': i, 'result': 'PASS',
                         'observation': f'Synthetic check {i} was never performed on real hardware'}
                        for i in range(1, 18)]}
    result = m.verify(record, measurements)
    assert result['status'].startswith('OPERATOR_RECORD_COMPLETE')
    assert result['not_an_install_or_release_approval']
    record['tests'][3]['result'] = 'NOT RUN'
    fails(m.verify, record, measurements)
    record['tests'][3]['result'] = 'PASS'
    record['tests'][4]['id'] = 4
    fails(m.verify, record, measurements)
    record['tests'][4]['id'] = 5
    record['display_z_offset_menu']['status'] = 'NOT RUN'
    fails(m.verify, record, measurements)
    record['display_z_offset_menu']['status'] = 'PASS'
    record['measurement_sha256'] = '0' * 64
    fails(m.verify, record, measurements)
    record['measurement_sha256'] = hashlib.sha256(measurements.read_bytes()).hexdigest()
    record['acknowledgement'] = 'REFERENCED_MY_OTHER_PRINTER'
    fails(m.verify, record, measurements)
    record['acknowledgement'] = m.ACKNOWLEDGEMENT
    record_file = root / 'record.json'
    record_file.write_text(json.dumps(record))
    assert m.document(record_file) == record
    record_file.write_text('{"schema":1,"schema":2}')
    fails(m.document, record_file)
print('PASS: strict 17-test operator evidence schema, separate display gate, nine-value digest and clear not-a-release status')
