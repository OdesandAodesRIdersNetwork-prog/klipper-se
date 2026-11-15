# Klipper-SE Stage 5: offline package and deployment rehearsal

**Status: OFFLINE ONLY. NOT A WORKING CB1 INSTALLER.** The accepted runtime branch remains `v3se-klipper-port` at `ab759b0026ca69396446bf13b7a9767c59619297`. None of these tools can access a printer, install packages or start services. `install/install.sh --apply` remains deliberately disabled.

## What this stage closes

The original 13-file offline bundle was incomplete: full `printer.cfg` includes both `macros.cfg` and `macro.cfg`. Stage 5 adds those files and locks them to the accepted contents. The offline payload also includes the exact MCU `.config`, source/version pins, and the Bookworm package list. The resulting **18-file** manifest includes paths, byte lengths and SHA256 checksums.

A scratch-only simulated deployment verifies those hashes, the pinned macro identities, the accepted MCU configuration and source commit, the profile's connection-only shape, and the parameterized systemd service user. It refuses existing output, symlinks, modified files, extra/unlisted destinations and system-home directories. If writing the inert sandbox fails, it removes the partial sandbox.

The output is a model of where the staged files would go, not a deployable filesystem. It contains no external Python virtualenv, source clones, Mainsail release, working systemd process, permitted device, true user IDs, or calibration state.

## Single command to reproduce the review

RUN AS `randy` or any non-root development user, from the **packaging branch** repository root. Choose a brand-new scratch output path, not an existing printer or system directory:

```bash
python3 install/rehearse-offline.py \
  --user testuser \
  --home /home/testuser \
  --mcu-serial /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --output /tmp/v3se-stage5-review-new
```

This performs staging, offline bundling, verification and simulation. Review `payload/MANIFEST.json` and `sandbox-root/SIMULATION.json` inside the new output. No physical connection to a CB1 is required. `testuser` and the serial name in this example are **only example strings for rendered paths**, not automatically validated device credentials.

Alternatively, validate an already-created 18-file offline payload without writing files:

```bash
python3 install/simulate-deployment.py \
  --verify --payload /path/to/offline/payload
```

## Automated negative tests

The offline test suite exercises modified file contents and mismatched hashes, malformed paths and duplicate destinations, symlinked source inputs, preexisting output, forbidden `/etc` and `/home` outputs, wrong service user, missing macro/build inputs, and a mid-deployment failure that must erase the scratch simulation. The test suite never enables a real service. Run:

```bash
python3 install/tests/test-assemble-offline.py
python3 install/tests/test-package-sandbox.py
python3 install/tests/test-rehearse-offline.py
bash install/install.sh --check
```

A passing `--check` still exits **4**, meaning the installer remains blocked pending physical proof.

## Still required before clean-install acceptance

A supported fresh Armbian/Debian 12 CB1 must be validated with pinned external sources and dependency bootstrap, correct OS accounts/serial permissions, a conflict-safe real deployment with rollback, functional Klipper/Moonraker/Mainsail/Nginx and recovery, and manual STM32 SD flashing. Next, a *supervised and physically verified* procedure must obtain target-specific PID, HX711 and CR Touch calibration values and generate a fresh bed mesh. No accepted printer's calibration can be copied, and no safety-sensitive number can be invented to bypass the gate. Finally, repeat the accepted 17 physical tests and separately address the inherited display Z-offset menu path.
