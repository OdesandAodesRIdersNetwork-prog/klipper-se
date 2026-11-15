# Klipper-SE clean installation on a new CB1

**Status: staging tools only. `install/install.sh --apply` is disabled.** This is not a successful blank-CB1 installation procedure yet. No developer machine's calibration state is a supported input.

## Source and dependency contract

The packaging branch is the delivery vehicle, not the runtime source. The eventual installer will fetch accepted regular Klipper-SE commit `ab759b0026ca69396446bf13b7a9767c59619297`, use the exact accepted MCU `.config` from `install/firmware/v3se-stm32f103xe.config` (verify SHA256 in `install/versions.env`) and pin Moonraker, Mainsail and mainsail-config as recorded in that file. KIAUH is historical reference, **not** a clean-install dependency.

The future sequence is: supported Bookworm/Armbian CB1, explicit apt packages, non-root service user/permissions, isolated source and Python environments, validated MCU build, **manual SD-card flashing**, base `printer_data` layout, user/environment templates, Mainsail/Moonraker/Nginx, udev recovery, and physical calibration/acceptance.

## First-boot protection

A new machine has no valid target HX711 sensitivity/tare, CR Touch Z offset, PID coefficients or bed mesh. The tooling separates this into two stages:

1. `render-printer-config.py --mode connection-check` stages a minimal `[mcu]` and `[printer] kinematics: none` configuration with **no heaters or motors**. It is for a potential supervised MCU connection check only, not motion, heating or calibration. A successful render does not enable the host installer.
2. `render-printer-config.py --mode calibrated` requires all **nine** measured target values in a JSON record, explicit target confirmation, and a new output directory. It stages a full printer config candidate but will **not** install it, build a bed mesh, save settings, or run tests.

The actual supervised path to obtain those nine values from a completely uncalibrated machine remains to be physically validated. Do not fabricate PID, Z or strain defaults to bypass the gate. See `docs/V3SE_FIRST_BOOT_CALIBRATION_DESIGN.md` and `docs/V3SE_CALIBRATION_VALUES.md`.

## Offline review only

RUN AS `randy` or another unprivileged build user, **not root**:

```bash
bash install/install.sh --plan
python3 install/tests/test-printer-gate.py
python3 install/tests/test-deployment.py
bash install/install.sh --check
```

The deployment planner may report proposed paths, but **never copies, installs, restarts or configures** any service. It refuses existing destinations; production branch and live reference CB1 are protected. The final validation requires a fresh CB1, the actual stock Ender-3 V3 SE, and the accepted physical test sequence. The old stock display Z-offset menu issue still needs its separate later fix and retest.
