# Machine-specific calibration (mandatory operator stage)

**Status:** workflow requirements recorded; full fresh-printer calibration procedure has not yet been independently validated. Do not treat this document as authorization to move the toolhead or heat a new machine.

Do not transplant the accepted printer's `counts_per_gram`, `reference_tare_counts`, `[bltouch] z_offset`, PID coefficients, mesh, or generated SAVE_CONFIG section. The shipping `printer.cfg.in` uses unresolved placeholders; they must stay unresolved until target-specific measurements are available. Never invent generic numeric strain or PID values.

Before attempting auto Z, prove the CR Touch is the global homing/mesh probe, verify the strain sensor wiring, proper sensor scaling and tare, and verify the accepted waveform trigger and frozen 32-sample event are available. Heater PID tuning must finish before the first print acceptance. Run target Auto-Z with the accepted nozzle-preparation and median-of-three/two-point procedure, then create the target CR Touch mesh. Inspect proposed Z offset and first-layer clearance before any deliberate SAVE_CONFIG. A successful command response is not, by itself, physical acceptance.

**Open engineering gate:** define and validate how an uncalibrated fresh printer can safely start up to acquire initial strain and Z measurements without requiring someone else's calibration defaults. Until solved, the installer must stop before generating a runnable production configuration.
