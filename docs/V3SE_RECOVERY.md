# Recovery and rollback policy

For a blank CB1, the clean-install path uses pinned source, a verifiable build, and a documented manual SD flash. It does not depend on Randy's historical bundle or any Kalico rollback tree.

The accepted reference printer retains its original recovery bundle `V3SE-KLIPPER-SE-FINAL-ACCEPTED-2026-11-01.bundle` (SHA256 `82288553f7cd658dc4918761b11d13d9b54590d3c12931c72ffcae4df2e797a2`) and the Kalico fallback branch `91da524b...`. Neither may be overwritten or considered part of the new installation.

Automatic recovery needs the accepted CH341 udev rule (VID `1a86`, PID `7523`), systemd `v3se-mcu-recover.service` and `v3se-mcu-recover.sh`. The old `v3se-mcu-recover.path` is obsolete and must not be installed. The source contract and event rule are documented. The new templated script waits three seconds, checks the by-id device, verifies Moonraker is in the specific lost-MCU shutdown, and only then requests FIRMWARE_RESTART. This is a **new fail-closed implementation**, not a byte-exact copy; offline fixtures pass but physical reconnection acceptance remains outstanding. See `docs/V3SE_SERVICE_TEMPLATES.md`.

If any clone, checksum, service, firmware or calibration gate fails, stop rather than relaxing validation. Check relevant logs and retain evidence. Do not issue `SAVE_CONFIG` or flash firmware as an automatic recovery action.
