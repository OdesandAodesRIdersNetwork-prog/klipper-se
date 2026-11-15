# Klipper-SE packaging stage (NOT AN ENABLED INSTALLER)

The accepted runtime source remains pinned to commit `ab759b0026ca69396446bf13b7a9767c59619297`. The packaging branch adds installer assets only. `install.sh --apply` always refuses with exit 3. `--check` runs offline validation but returns exit 4 intentionally until full blank-CB1/physical acceptance is proven. It does not install software or operate the printer.

## Package contents

- Pinned Klipper-SE, Moonraker, Mainsail and mainsail-config versions.
- Verified accepted STM32F103 MCU `.config`, printer hardware template and accepted slicer-facing macros.
- Moonraker, Mainsail, Klipper, Nginx, systemd and udev templates and a fail-closed recovery script.
- **Connection-check-only printer profile:** `install/printer/first-boot.cfg.in`, which contains neither steppers, heaters, probe nor display. This is untested on new hardware and must not be used to print or calibrate.
- **Measured-values renderer:** `install/render-printer-config.py`, which refuses to stage a complete config without all nine explicit target-unit measurements and confirmation.
- **Read-only conflict planner:** `install/plan-deployment.py`, which reports prospective file locations and rejects pre-existing live installations.

## Offline staging and tests

```bash
python3 install/render-printer-config.py --mode connection-check \
  --mcu-serial /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --output /tmp/v3se-connection-review

python3 install/render-templates.py --user testuser \
  --home /home/testuser --output /tmp/v3se-host-review
python3 install/plan-deployment.py --user testuser \
  --home /home/testuser --stage /tmp/v3se-host-review

python3 install/tests/test-printer-gate.py
python3 install/tests/test-deployment.py
bash install/tests/test-render.sh
bash install/tests/test-recovery.sh
bash install/install.sh --check
```

Always choose fresh staging paths. Files are never installed into `printer_data`, `/etc`, or any actual service directories by these staging scripts. Sample measurements are intentionally invalid and contain **no real printer calibration**. See `docs/V3SE_CALIBRATION_VALUES.md`.

## Remaining before installation can be enabled

The blank-CB1 software acquisition/installation script, supervised intermediate calibration pathway to acquire the nine values, safe permissions and conflict-controlled deployment, required service checks, SD-card flash and physical 17-test acceptance are not yet complete. The stage-only tools must not be interpreted as an approved printer setup. Historical Kalico recovery is not a first-install dependency.
