# Safe first-boot calibration gate (design, not an enabled installer)

Do not copy the accepted test printer's `SAVE_CONFIG` block, 5x5 mesh, Z offset, HX711 counts-per-gram, reference tare, or PID values to another machine. `install/printer/printer.cfg.in` deliberately keeps machine-specific `@...@` markers unresolved. A rendered but uncalibrated template is **not** safe to print with.

## Required staging transition before any `--apply`

1. Verify stock Ender-3 V3 SE hardware, correct serial ID, accepted MCU build source/config, and firmware identity. Flash manually by SD card; do not reboot, flash, or run `SAVE_CONFIG` automatically.
2. Define a documented non-printing bootstrap configuration that can start without pretending calibration measurements exist. It must not silently install the accepted machine's Z or heater tuning. This bootstrap is **not yet implemented**.
3. With appropriate physical supervision, obtain or verify each target-unit strain-gauge calibration value, CR Touch/nozzle Z offset, hotend/bed PID, and bed mesh using the accepted calibration workflow. Avoid nozzle-to-bed contact without appropriate calibration and temperature conditions.
4. Render the full production config from measured target-unit values, validate the config and all include paths, then start services in defined order.
5. Verify the full 17-point acceptance set, including power-cycle MCU recovery and the stock display transport. The known inherited Prepare > Z-offset display command needs its own later repair and physical retest; do not silently change production source during packaging.

A future installer must stop explicitly if any measured value is missing, if any `@...@` remains, or if a source-identity/hash gate fails. No value inferred from the accepted printer qualifies as a default for another printer.

## Installer state

`install/install.sh --apply` deliberately refuses to run. This design document is **not** authorization to enable it. Approval, implementation, static validation, blank-CB1 installation, and physical acceptance are separate gates.
