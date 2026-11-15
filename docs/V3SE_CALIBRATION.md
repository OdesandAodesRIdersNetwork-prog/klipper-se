# Machine-specific calibration (mandatory supervised operator stage)

**Status:** No blank-CB1/new-printer end-to-end calibration workflow has passed physical testing. This document is not authorization to move the toolhead, enable heaters or run a print.

Do not transplant the accepted printer's HX711 scaling or tare, CR Touch Z offset, PID coefficients, mesh or generated SAVE_CONFIG block. The `printer.cfg.in` file requires measured values. They are never filled from the accepted machine.

The new `connection-check` profile intentionally contains no steppers, heater or probe. It permits only offline review and, after separate human approval and testing, an MCU communication check. It does **not** acquire calibrations.

A separate supervised and validated method must collect heater PID values, strain-gauge scaling and tare, and a safe initial CR Touch/nozzle Z relationship. Once those target readings are recorded, `render-printer-config.py` can stage a full configuration candidate. Only then can qualified physical procedures establish the accepted event-derived Auto-Z, create the target 5×5 mesh and validate first-layer clearance. A successful command response is not, by itself, physical acceptance.

See `docs/V3SE_CALIBRATION_VALUES.md` and `docs/V3SE_FIRST_BOOT_CALIBRATION_DESIGN.md` for the stage-only tools and remaining physical gate. Do not enable `install.sh --apply` until the entire blank-printer path is proven.
