# Klipper-SE packaging staging assets (not yet deployable)

The isolated packaging branch contains the accepted runtime source pins, exact verified MCU `.config`, machine-specific-safe `printer.cfg.in` markers, accepted print macros, and the staged host service/recovery templates. **Nothing here is an enabled installer.**

`bash install/install.sh --plan` prints the installation sequence. `bash install/install.sh --check` checks the package and exercises local renderer/recovery fixtures, then deliberately returns **exit 4** until the real installation gates are complete. `--apply` refuses with exit 3.

## Staging tests

```bash
bash install/tests/test-render.sh
bash install/tests/test-recovery.sh
python3 install/render-templates.py --user testuser --home /home/testuser --output /tmp/v3se-stage-test
```

Choose a fresh output directory. This generates only ordinary files inside the staging destination and **never** installs systemd units, enables udev, starts services, formats media, or touches any connected printer.

Host templates are under `install/systemd/`, `install/recovery/`, `install/udev/`, `install/moonraker/`, `install/mainsail/`, and `install/nginx/`. See `docs/V3SE_SERVICE_TEMPLATES.md` for intended locations and details. The recovery script is a fail-closed, newly parameterized equivalent of the accepted behaviour. The udev rule is the exact accepted rule.

## Before enabling actual installation

The following remain mandatory: reviewed two-stage safe first-boot calibration and target-only measurements; source-pin and package bootstrap; file conflict/backup checks; Nginx and systemd syntax verification on Debian 12/Armbian CB1; Moonraker security/access verification; manual firmware flash; and blank-CB1 plus printer physical acceptance. See `docs/V3SE_FIRST_BOOT_CALIBRATION_DESIGN.md`.

The accepted `v3se-klipper-port` branch and the live printer remain untouched.
