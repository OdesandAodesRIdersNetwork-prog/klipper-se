# Initial packaging staging area

This directory contains **first-phase reviewed scaffolding**, not an enabled installer. `install.sh --apply` is deliberately blocked. `install.sh --check` and `--plan` are safe, non-mutating operations.

## Already packaged

- Exact accepted version pins and Mainsail release checksum.
- Candidate Bookworm top-level Debian package manifest.
- Source-derived `printer.cfg.in` with *mandatory, unresolved per-unit calibration markers*; does not copy the accepted printer's calibration values or SAVE_CONFIG.
- Byte-exact accepted resolved MCU `.config` (`install/firmware/v3se-stm32f103xe.config`), verified against SHA256 in `versions.env`.\n- Exact `macro.cfg` contents observed on the accepted CB1, plus the already-tracked `config/v3se-macros.cfg`.
- Preflight/check/read-only validation scaffolding, guarded firmware build, documentation and acceptance checklist.

## Required before enabling --apply


- Accepted recovery shell script, systemd service and udev rule, with deliberate user/path parameterization.
- Moonraker and Klipper service/env templates, Moonraker config, Mainsail config, Nginx site/upstreams mapping.
- Safe uncalibrated-printer startup/calibration pathway and renderer for per-unit config values.
- Static tests and then isolated blank-CB1 reproducibility proof.

No accepted source code, active branch or running printer state is modified by these files.
