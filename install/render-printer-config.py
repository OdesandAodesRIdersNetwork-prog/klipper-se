#!/usr/bin/env python3
"""OFFLINE ONLY: create a new staging directory for one printer config.

Modes:
  connection-check: no steppers/heaters/probe/display; MCU comms only.
  calibrated: all required target-specific values must be explicitly provided.

This command does not contact a printer, issue G-code, enable services or install.
"""
import argparse
import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "printer"
MCU_RE = re.compile(r"/dev/serial/by-id/[A-Za-z0-9_.:-]+\Z")
PLACEHOLDER = re.compile(r"@[A-Z][A-Z0-9_]*@")
CONFIRMATION = "MEASURED_ON_THIS_PRINTER"

# This is the entire allowed substitution surface, not an open-ended config merger.
FIELDS = {
    "bltouch_z_offset": "BLTOUCH_Z_OFFSET",
    "counts_per_gram": "COUNTS_PER_GRAM",
    "reference_tare_counts": "REFERENCE_TARE_COUNTS",
    "extruder_pid_kp": "EXTRUDER_PID_KP",
    "extruder_pid_ki": "EXTRUDER_PID_KI",
    "extruder_pid_kd": "EXTRUDER_PID_KD",
    "bed_pid_kp": "BED_PID_KP",
    "bed_pid_ki": "BED_PID_KI",
    "bed_pid_kd": "BED_PID_KD",
}


def fail(msg):
    raise ValueError(msg)


def validated_serial(serial):
    if not MCU_RE.fullmatch(serial) or ".." in serial:
        fail("MCU serial must be a single /dev/serial/by-id device name")
    return serial


def safe_target(target):
    # Refuse actual live configs even if a parent is reached through a symlink.
    target = pathlib.Path(target).expanduser().resolve(strict=False)
    protected = ["/etc", "/usr", "/boot", "/var", "/home", "/root", "/proc", "/sys", "/dev"]
    for prefix in protected:
        p = pathlib.Path(prefix)
        if target == p or p in target.parents:
            fail("cannot stage inside a system or printer-home tree")
    if target == pathlib.Path("/") or target.exists() or target.is_symlink():
        fail("output must be an unused, non-system staging directory")
    # Parent must already exist, so a typo cannot generate unexpected trees.
    if not target.parent.is_dir():
        fail("output parent directory must already exist")
    return target


def safe_number(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("%s must be a number measured for this target" % key)
    number = float(value)
    if not math.isfinite(number):
        fail("%s must be finite" % key)
    if key == "reference_tare_counts":
        if not isinstance(value, int) or not -(2 ** 23) <= value < 2 ** 23:
            fail("reference_tare_counts must be an integer in signed HX711 range")
        return str(value)
    if key == "bltouch_z_offset" and not (0.0 < number < 10.0):
        fail("bltouch_z_offset must be positive and below 10 mm")
    if key == "counts_per_gram" and not (0.000001 < abs(number) < 1_000_000):
        fail("counts_per_gram must be nonzero and within sanity bounds")
    if "_pid_" in key and not (0.0 < number < 100_000.0):
        fail("%s must be positive and within sanity bounds" % key)
    return format(number, ".12g")


def load_measurements(path):
    def reject_constant(constant):
        fail("JSON non-finite number is forbidden: " + constant)
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict):
        fail("measurements must be one JSON object")
    mandatory = {"confirmation", "printer_label", "measurement_notes", "values"}
    if set(data) != mandatory:
        fail("measurement record needs exactly confirmation, printer_label, measurement_notes, values")
    if data["confirmation"] != CONFIRMATION:
        fail("explicit target-printer measurement confirmation is required")
    for field in ["printer_label", "measurement_notes"]:
        value = data[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            fail("%s must be a meaningful, short text record" % field)
    v = data["values"]
    if not isinstance(v, dict) or set(v) != set(FIELDS):
        fail("values must contain exactly the nine required target calibration fields")
    return {FIELDS[key]: safe_number(key, v[key]) for key in FIELDS}


def render(mode, serial, measurements=None):
    template = "first-boot.cfg.in" if mode == "connection-check" else "printer.cfg.in"
    raw = (TEMPLATE_DIR / template).read_text(encoding="utf-8")
    replacements = {"MCU_SERIAL_BY_ID": validated_serial(serial)}
    if mode == "calibrated":
        if measurements is None:
            fail("calibrated mode requires --measurements from this target printer")
        replacements.update(load_measurements(measurements))
    elif measurements is not None:
        fail("connection-check mode cannot accept calibration measurements")
    for key, value in replacements.items():
        raw = raw.replace("@" + key + "@", value)
    remaining = PLACEHOLDER.findall(raw)
    if remaining:
        fail("unresolved machine-specific placeholders: " + ", ".join(sorted(set(remaining))))
    if "#*#" in raw:
        fail("SAVE_CONFIG contents are forbidden in staged templates")
    if mode == "connection-check":
        headings = re.findall(r"^\[([^]]+)\]", raw, flags=re.M)
        if headings != ["mcu", "printer"]:
            fail("connection-check template must contain only mcu and printer")
        if "kinematics: none" not in raw:
            fail("connection-check must have no stepper kinematics")
    return raw


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["connection-check", "calibrated"], required=True)
    ap.add_argument("--mcu-serial", required=True)
    ap.add_argument("--measurements", type=pathlib.Path)
    ap.add_argument("--output", type=pathlib.Path, required=True,
                    help="NEW staging directory, never /etc or a printer home")
    args = ap.parse_args()
    target = safe_target(args.output)
    content = render(args.mode, args.mcu_serial, args.measurements)
    # Validate everything before creating the destination. A failed render leaves no output.
    target.mkdir(mode=0o700)
    staged = target / "printer.cfg"
    staged.write_text(content, encoding="utf-8")
    staged.chmod(0o600)
    print("STAGED ONLY: %s at %s" % (args.mode, staged))
    print("No printer, firmware, service, or live configuration was changed.")
    if args.mode == "connection-check":
        print("NO motors, heaters or probe are configured. NOT PRINT-READY.")
    else:
        print("Target measurements were supplied; still NOT physically accepted or auto-deployed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, UnicodeError) as e:
        print("V3SE PRINTER CONFIG: " + str(e), file=sys.stderr)
        sys.exit(2)
