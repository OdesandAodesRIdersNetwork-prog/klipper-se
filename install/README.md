# Klipper-SE packaging stage (NOT AN ENABLED INSTALLER)

The accepted runtime source remains pinned to commit `ab759b0026ca69396446bf13b7a9767c59619297`. The packaging branch adds installer assets only. `install.sh --apply` always refuses with exit 3. `--check` runs offline validation but returns exit 4 intentionally until full blank-CB1/physical acceptance is proven. It does not install software or operate the printer.

## Package contents

- Pinned Klipper-SE, Moonraker, Mainsail and mainsail-config versions.
- Verified accepted STM32F103 MCU `.config`, printer hardware template and accepted slicer-facing macros.
- Moonraker, Mainsail, Klipper, Nginx, systemd and udev templates and a fail-closed recovery script.
- **Connection-check-only printer profile:** `install/printer/first-boot.cfg.in`, which contains neither steppers, heaters, probe nor display. This is untested on new hardware and must not be used to print or calibrate.
- **Measured-values renderer:** `install/render-printer-config.py`, which refuses to stage a complete config without all nine explicit target-unit measurements and confirmation.
- **Offline package assembler:** `install/assemble-offline.py` combines the rendered host and printer staging trees, both accepted macro files, exact MCU config, version pins and host package list into an unused scratch directory with an 18-file SHA256 manifest. It cannot deploy anything and refuses symlinked source files and overwritten destinations.
- **Read-only conflict planner:** `install/plan-deployment.py`, which reports prospective file locations and rejects pre-existing live installations.

- **Scratch-only deployment simulator:** `install/simulate-deployment.py` verifies the 18-file bundle against the manifest plus the accepted macro/MCU/source pins. It can write an inert filesystem model under a brand-new scratch root and will roll back on failures. It cannot touch system paths.
- **End-to-end rehearsal:** `install/rehearse-offline.py` runs both renderers, the assembler, integrity validation and sandbox simulation with one command. No live install or printer changes.

## Offline staging and tests

RUN AS `randy` or another unprivileged user, not root:

```bash
python3 install/rehearse-offline.py --user testuser --home /home/testuser \
  --mcu-serial /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --output /tmp/v3se-rehearsal-new

python3 install/render-printer-config.py --mode connection-check \
  --mcu-serial /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --output /tmp/v3se-connection-review

python3 install/render-templates.py --user testuser \
  --home /home/testuser --output /tmp/v3se-host-review
python3 install/plan-deployment.py --user testuser \
  --home /home/testuser --stage /tmp/v3se-host-review

python3 install/tests/test-printer-gate.py
python3 install/tests/test-deployment.py
python3 install/tests/test-assemble-offline.py
python3 install/tests/test-package-sandbox.py
python3 install/tests/test-rehearse-offline.py
bash install/tests/test-render.sh
bash install/tests/test-recovery.sh
bash install/install.sh --check
```

Always choose fresh staging paths. Files are never installed into `printer_data`, `/etc`, or any actual service directories by these staging scripts. Sample measurements are intentionally invalid and contain **no real printer calibration**. See `docs/V3SE_CALIBRATION_VALUES.md` and `docs/V3SE_OFFLINE_REHEARSAL.md`.

## Stage 6: external-source and fresh-host gates

The new **read-only** fresh-CB1 preflight is `install/preflight-cb1.py`, available via `bash install/install.sh --host-preflight USERNAME`. It checks the supported OS, required commands/packages, serial access and existing-installation conflicts without modifying any state. The exit status is never installation authorization.

`install/stage-dependencies.py --plan` checks the review-locked release identities without network access. Its **explicit** `--fetch --output /tmp/NEWPATH` option makes network requests and writes only into a brand-new scratch directory, cloning the three pinned Git source revisions and checksum-verifying the pinned Mainsail ZIP. `--verify --output ...` rereads that stage without changes. None of these commands installs packages or starts services. See `docs/V3SE_STAGE6_PREFLIGHT_AND_SOURCES.md`.

## Remaining before installation can be enabled

The blank-CB1 software acquisition/installation script, supervised intermediate calibration pathway to acquire the nine values, safe permissions and conflict-controlled deployment, required service checks, SD-card flash and physical 17-test acceptance are not yet complete. The stage-only tools must not be interpreted as an approved printer setup. Historical Kalico recovery is not a first-install dependency.

## Stage 7: conflict-safe host transaction sandbox

`install/transaction-sandbox.py` adds a marked scratch-root transaction rehearsal after the existing 18-file payload verification. It plans the exact allowlisted destinations, refuses any existing files or symlinked parents, and rolls back only files and directories created by a failed rehearsal. Unrelated scratch-root files and the root marker remain untouched. It refuses real user homes and system roots. Run `python3 install/tests/test-transaction-sandbox.py` for local unit fixtures; see `docs/V3SE_STAGE7_SANDBOX_TRANSACTION.md` for the full safe workflow.

**This is not a privileged installer.** It still never executes apt/pip, starts services, flashes firmware or acquires target calibration. The `--apply` refusal (exit 3) and offline `--check` expected exit 4 remain unchanged.
