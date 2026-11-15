# Klipper-SE target-unit calibration values

**Staging contract only.** The accepted Ender-3 V3 SE values are not suitable defaults for another printer. This document does not authorize toolhead motion, heating, flashing or a print.

The reference JSON at `install/printer/target-measurements.example.json` is **deliberately invalid**: its placeholders and `NOT_YET_MEASURED` confirmation must be replaced using measurements from the exact target printer. Do not use arbitrary example numbers. The real measurements must include:

- CR Touch/nozzle `bltouch_z_offset` in mm.
- HX711 `counts_per_gram` and integer `reference_tare_counts`.
- Six target-measured PID coefficients: extruder `kp`, `ki`, `kd`; bed `kp`, `ki`, `kd`.
- A meaningful printer label, measurement notes, and the exact acknowledgement string `MEASURED_ON_THIS_PRINTER`.

The validator checks these data are present, finite, within broad sanity bounds, and numerically safe to insert in Klipper configuration. **It cannot verify that a human measured them correctly.** Those measurements, the target 5×5 mesh, and the full physical acceptance still require real supervision and testing.

## Two separate commands

From the repository root, using a harmless device string for an offline demonstration:

```bash
# Connection-check mode: creates ONLY [mcu] and [printer] with kinematics none.
python3 install/render-printer-config.py \
  --mode connection-check \
  --mcu-serial /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --output /tmp/v3se-connection-review

# Calibrated mode: requires the filled-in JSON from the actual target printer.
python3 install/render-printer-config.py \
  --mode calibrated \
  --mcu-serial /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --measurements /path/to/target-measurements.json \
  --output /tmp/v3se-calibration-review
```

The output directories must not already exist. Neither mode installs files into the CB1 config directory. `--mode connection-check` intentionally declares **no motors, heaters, probe or display**. It is only a candidate MCU connection-check profile, not a physical safety certification. Do not try `G28`, `AUTO_Z`, `PID_CALIBRATE`, `BED_MESH_CALIBRATE`, or printing in that mode. Normal calibration cannot happen until a separate supervised setup protocol for temporary heater/sensor/probe access is verified.

`--mode calibrated` stages a complete source-derived `printer.cfg` with substitutions, but it does not verify firmware, pin wiring, macros, local includes, geometry, mesh or source compatibility. **A successful stage is not permission to deploy or print.** It will not create a mesh or `SAVE_CONFIG` block.

## Outstanding prerequisite before enabling the installer

The real blank-CB1 procedure must define and validate a supervised path from connection-only mode through hotend/bed PID tuning, strain scaling/tare, CR Touch offset and mesh creation. No target calibration value may be invented to bypass an uninitialized machine. The physical 17-point acceptance and the known display menu repair remain separate gates.
