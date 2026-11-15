# Safe first-boot calibration gate (partly implemented, not approved on hardware)

## Stage 1: connection-check profile

`install/render-printer-config.py --mode connection-check` now produces a **staged** minimal Klipper profile containing only `[mcu]` and `[printer] kinematics: none`. The accepted regular Klipper source provides this no-stepper kinematics implementation. There are no heater, motor, extruder, probe, display or strain sections in that profile.

It is designed solely to help validate the MCU communication path after the separately documented manual SD-card firmware flash. It has **not** been physically tested on a blank CB1; do not use it for movement, heating or calibration. Generating the file does not start Klipper or touch the running printer.

## Stage 2: target-measured production candidate

`install/render-printer-config.py --mode calibrated` will stage a production configuration only when all nine target-specific numeric fields and an explicit `MEASURED_ON_THIS_PRINTER` record are provided. It rejects missing data, non-finite values, non-numeric or out-of-range entries, injected text, an existing destination, and protected system/live paths. It never imports Randy's machine values or a `SAVE_CONFIG` tail.

That makes the file a **candidate**, not a proven operational installation. The renderer cannot verify accuracy of measurements or physical nozzle safety. Do not deploy or print without supervision and the complete final acceptance protocol.

## Still open: measurement acquisition on a truly blank printer

A new machine needs a verified supervised method for collecting heater PID, strain-gauge sensitivity/tare, initial CR Touch/nozzle offset and the bed mesh. The connection-check config deliberately does not expose heaters or motors, so by itself it cannot collect these values. We must document and test the separate temporary calibration setup before enabling the host installer. No values may be copied from the accepted machine or invented as defaults.

## Release gates

1. Pinned CB1 software packages and firmware identity verified.
2. Host installation refuses path conflicts and protects existing installations.
3. Connection-check stage is tested on a new CB1 and stock printer.
4. Supervised target-specific acquisition of all nine values is validated.
5. Full config renders with no unresolved markers, all includes and services present, and no imported machine-specific state.
6. Target bed mesh and physical 17-point acceptance pass, including MCU power-cycle recovery and stock display behaviour.
7. The inherited display Prepare > Z-offset action is repaired and separately revalidated before the final complete release.

`install/install.sh --apply` stays **disabled**. The new staging and planning scripts provide no installation authority.
