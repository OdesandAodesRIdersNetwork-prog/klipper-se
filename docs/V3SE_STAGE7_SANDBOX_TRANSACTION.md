# V3 SE Stage 7: conflict-safe host transaction rehearsal

**Status: offline scratch-only development checkpoint. Not a CB1 installer.**

The production-accepted Klipper-SE commit `ab759b0026ca69396446bf13b7a9767c59619297` remains frozen. This Stage 7 work adds **no** changes to `klippy/`, `src/`, existing production configuration or the accepted printer.

## Why this checkpoint exists

Stage 5 verified an 18-file package and simulated its installation under a *new* scratch root. Stage 6 added fresh-host preflight and pinned external source staging. A real installer also must refuse conflicts in a *pre-existing* filesystem, preserve unrelated files, and remove only transaction-owned files when something fails. Stage 7 adds that intermediate test without claiming a working installer.

`install/transaction-sandbox.py` requires a fresh, explicitly marked **inert test directory directly under `/tmp` or `/mnt/data`**. A human must create the test sandbox. The script refuses existing files, unexpected source paths, unmarked roots, symlinked destinations/ancestors, and any attempt to use a real home or `/etc` as a root. The 18-file payload is verified by the established Stage 5 cryptographic verifier before the CLI can plan or rehearse. The only accepted printer mode for this exercise is the no-motion, no-heater `connection-check` profile.

The transaction writes new files exclusively inside the marked test root, uses exclusive file creation, records a non-installable receipt, and rolls back **only** transaction-owned files and newly created directories. It never deletes the marked sandbox itself or unrelated files. This models failure recovery, not real root-owned system file installation. For truly hostile concurrent filesystem changes, a future production implementation will require descriptor-anchored pathname safety and separate real-host security review.

## Offline usage (RUN AS a regular user, not root)

First create the previously validated 18-file connection-check payload with `install/rehearse-offline.py` or the Stage 4 assembler. Then:

```bash
python3 install/transaction-sandbox.py --init --root /tmp/v3se-stage7-unique-new
python3 install/transaction-sandbox.py --plan \
  --root /tmp/v3se-stage7-unique-new \
  --user YOUR_LINUX_USERNAME --payload /tmp/your-existing-stage5-payload
python3 install/transaction-sandbox.py --rehearse \
  --root /tmp/v3se-stage7-unique-new \
  --user YOUR_LINUX_USERNAME --payload /tmp/your-existing-stage5-payload
python3 install/tests/test-transaction-sandbox.py
```

The payload does **not** include user-specific calibration copied from the development machine. The test script's synthetic unit fixture verifies destination conflicts, existing-file preservation, symlink refusal, wrong destinations, partial rollback and successful completion.

## Still NOT implemented

No apt/pip provisioning, real source installation, runtime service enabling, privileged ownership/permissions deployment, production-grade symlink-race protection, first-boot assisted calibration, firmware flashing or fresh-CB1 physical 17-test acceptance. `install/install.sh --apply` must continue to exit 3. The packaging check must continue to return the expected exit 4 after its offline tests pass.

Next, design a separate explicit blank-host-only provisioning sequence with an additional real-host admission and rollback protocol, then determine a safe supervised calibration acquisition path. Do not enable the real installer merely because the sandbox transaction passes.
