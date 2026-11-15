# Fresh CB1 + stock Ender-3 V3 SE physical acceptance

The existing accepted reference completed **17/17 PASS**, but that result belongs to the reference machine. A clean install must capture new evidence on the target hardware. Do not auto-run physical steps, and do not claim PASS based on service startup.

| # | Physical check | Status on new machine |
|---|---|---|
| 01 | Stock screen starts; encoder, menu, Leveling navigation work | NOT RUN |
| 02 | Long virtual-SD filename displays safely and browser remains responsive | NOT RUN |
| 03 | Display frames do not cause MCU timeout; preserve 40-char / 40-byte protections | NOT RUN |
| 04 | CR Touch homes/probes via `G28`; strain sensor is not global probe | NOT RUN |
| 05 | Factory-like nozzle preparation: 60C bed; 180C, 200C, 140C nozzle stages | NOT RUN |
| 06 | PRTouch waveform, not generic 20g fallback, triggers production contact | NOT RUN |
| 07 | Exact chronological 32-sample MCU frozen FIFO and timestamps | NOT RUN |
| 08 | Event-derived contact Z, not generic trigger / raw 20g estimate | NOT RUN |
| 09 | Median-of-three nozzle contact values | NOT RUN |
| 10 | CR Touch + nozzle event at two symmetric physical positions | NOT RUN |
| 11 | Factory final formula: average two offsets minus 0.070mm | NOT RUN |
| 12 | `FULL_CALIBRATE` follows accepted Auto-Z / mesh sequence | NOT RUN |
| 13 | CR Touch bed mesh matches declared geometry | NOT RUN |
| 14 | First-layer print passes without live Z correction | NOT RUN |
| 15 | Mainboard-only power cycle with CB1 kept on | NOT RUN |
| 16 | Automatic reconnection and stock screen return | NOT RUN |
| 17 | Host and MCU build/source identities consistent | NOT RUN |

The inherited stock-screen Prepare -> Z-offset action references obsolete `PRTOUCH_PROBE_OFFSET`. Repair and targeted revalidation are a **separate source-change phase**. Keep this known issue visible; do not silently imply that menu action passed by virtue of the 17 historical tests.
