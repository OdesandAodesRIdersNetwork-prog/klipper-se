# Clean-install physical-acceptance evidence record

**Status: a read-only schema check, not a physical testing or release authority.** The original accepted CB1 and printer's 17/17 results cannot be reused for a new printer. `install/verify-acceptance-evidence.py` checks that a human has documented the complete **separate fresh-CB1 and stock Ender-3 V3 SE** validation, including the inherited stock-display Prepare > Z-offset menu regression. It does not control hardware or independently validate that any claimed observation is true.

## Required record

Write a JSON object with exactly these fields:

- `schema`: `1`.
- `acknowledgement`: the literal `FRESH_CB1_AND_STOCK_V3SE_PHYSICALLY_TESTED` only after completion.
- `target_printer`, `target_cb1`, `operator`, `test_date` (`YYYY-MM-DD`): specific observed hardware/operator identity and date. Do not reuse or infer identifiers.
- `source_commit`: exactly `ab759b0026ca69396446bf13b7a9767c59619297`.
- `firmware_version`, `firmware_binary_sha256`, `manual_firmware_flash_observation`: observed version and binary provenance from the new build and manual SD flash. The script cannot verify that the flash succeeded.
- `measurement_sha256`: actual SHA256 of the **new printer's** nine-value JSON record, with its confirmation and measurement notes; do not copy the accepted printer's measurements.
- `display_z_offset_menu`: `{"status":"PASS", "observation":"..."}` only after the inherited Prepare > Z-offset menu behavior has been repaired and separately physically retested. This is **not** included in the existing 17 historical acceptance assertions.
- `tests`: a list of exactly 17 objects with `id` (integer 1–17), `result` (`PASS`) and `observation` (specific observed results, ideally test log/time). The checklist lives in `docs/V3SE_ACCEPTANCE_CHECKLIST.md`.

To validate the structure **after** supervised physical acceptance:

```bash
python3 install/verify-acceptance-evidence.py --record /path/to/FRESH_CB1_ACCEPTANCE.json --measurements /path/to/TARGET_MEASUREMENTS.json
```

The output reads `OPERATOR_RECORD_COMPLETE_REQUIRES_INDEPENDENT_HARDWARE_REVIEW` even when all fields are populated. It does **not** say `RELEASE_APPROVED`. A separate human or independent review must reconcile the 17 observations against actual logs and inspect GitHub pin identities, services, screen and firmware. The full installer `--apply` remains locked until genuine clean-install proof, calibration and menu regression acceptance.

## Offline fixture only

`python3 install/tests/test-verify-acceptance-evidence.py` uses entirely fabricated test values and observations to test the parser; it is **not real hardware evidence**. Invalid rows, missing or duplicated test IDs, wrong calibration-file digests, wrong source commits and missing menu acceptance are refused. This file format prevents incomplete documentation from being mistaken for completed release review. It cannot detect deliberately fabricated statements.
