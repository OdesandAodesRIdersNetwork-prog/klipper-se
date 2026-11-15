# Klipper-SE clean installation on a new CB1

**Status: packaging staging only, not a runnable installer yet.** `install/install.sh --apply` intentionally refuses to change a host until the full required templates and calibration gates are implemented and statically validated. No CB1 should be installed from this initial commit.

## Source contract

The installation package is delivered through a *separate packaging branch*. It must fetch and run the exact accepted Klipper-SE source commit (`ab759b0026ca69396446bf13b7a9767c59619297`), not the packaging branch HEAD. This intentionally separates host/MCU behavior from packaging work. Version pins are in `install/versions.env`.

KIAUH is **not required**. Minimal steps will be internalized. Do not use mutable `latest` URLs; download Mainsail v2.19.0 by tagged URL and verify its SHA256 before extraction.

## Order and prerequisites

1. Supported Armbian/Debian 12 aarch64 CB1, systemd, udev, coreutils, grep and appropriate privileged access.
2. Install explicit top-level package set in `install/packages-bookworm.txt` (17 packages), verifying package availability on a clean image.
3. Pick a non-root service user and create `printer_data/{config,logs,gcodes,comms,systemd}` under their home; do not copy old sockets or runtime state.
4. Check out the pinned Klipper-SE runtime source separately; create `klippy-env` using Debian Python 3.11-compatible `virtualenv`; install `scripts/klippy-requirements.txt`.
5. Verify exact accepted MCU `.config` hash, build firmware and **stop** for documented manual SD flash. The exact resolved file is now included at `install/firmware/v3se-stm32f103xe.config` and its hash is checked before use.
6. Render the hardware profile only from target-machine measured calibration data. Do **not** paste the accepted printer's `SAVE_CONFIG` tail or PID/mesh/Z/strain values.
7. Add stock display, macros and Klipper systemd service; install pinned Moonraker Python/system requirements, service, Mainsail, mainsail-config, and Nginx templates.
8. Stage the accepted CH341 udev rule and the fail-closed recovery script; do not enable them until the isolated CB1 installation and physical recovery tests pass.
9. Run read-only software checks, target-unit calibration, and the complete physical acceptance tests.

## Stage-only host templates

The host config renderer `install/render-templates.py` creates a new local staging directory and refuses existing destinations or system paths. The proposed file layout and security boundaries are documented in `docs/V3SE_SERVICE_TEMPLATES.md`. Its tests do not prove a successful blank-CB1 installation.

`bash install/install.sh --check` returns exit 4 intentionally after successful offline staging checks because the first-boot calibration and deployment safety gates are still incomplete.

## Safety and release gate

Do not put new hardware into a print-ready state without valid target strain calibration, correct initial Z offset, target PID calibration and a new bed mesh. The current `printer.cfg.in` contains explicit `@...@` placeholders **on purpose**: it is not valid Klipper config until calibrated and rendered. This package must not silently substitute values from Randy's machine or auto-run `SAVE_CONFIG`.

The existing accepted printer and original `v3se-klipper-port` branch remain unchanged. Only the separate packaging branch receives new assets.

## Initial commands (read-only)

RUN AS `randy` or the regular CB1 installation user:

```bash
bash install/install.sh --plan
bash install/install.sh --check
```

**Do not run `--apply` until a later reviewed and tested packaging checkpoint explicitly enables it.**
