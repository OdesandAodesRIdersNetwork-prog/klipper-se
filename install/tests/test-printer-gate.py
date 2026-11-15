#!/usr/bin/env python3
"""Offline tests for connection-only and calibrated config staging."""
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

INSTALL = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = INSTALL / "render-printer-config.py"
SERIAL = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
SPEC = importlib.util.spec_from_file_location("v3se_printer_renderer", SCRIPT)
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)

VALUES = {
    "bltouch_z_offset": 1.567,
    "counts_per_gram": 94.2,
    "reference_tare_counts": 239867,
    "extruder_pid_kp": 27.1,
    "extruder_pid_ki": 1.42,
    "extruder_pid_kd": 121.3,
    "bed_pid_kp": 62.4,
    "bed_pid_ki": 0.85,
    "bed_pid_kd": 1187.4,
}


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def ensure(condition, message):
    if not condition:
        raise AssertionError(message)


def must_fail(action, message):
    try:
        action()
    except (ValueError, OSError, UnicodeError):
        return
    raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory(prefix="v3se-gate-") as tmp:
        root = pathlib.Path(tmp)
        boot = root / "connection"
        result = run("--mode", "connection-check", "--mcu-serial", SERIAL, "--output", boot)
        ensure(result.returncode == 0, result.stderr)
        text = (boot / "printer.cfg").read_text()
        ensure("[mcu]" in text and "kinematics: none" in text, "connection-only config missing MCU/none")
        for forbidden in ("[extruder]", "[heater_bed]", "[stepper_x]", "[bltouch]", "[strain_gauge_z_cal]", "[include", "[e3v3se_display]"):
            ensure(forbidden not in text, "connection-only config contains unsafe section: " + forbidden)
        ensure((boot / "printer.cfg").stat().st_mode & 0o777 == 0o600, "staged config permissions wrong")
        ensure(run("--mode", "connection-check", "--mcu-serial", SERIAL, "--output", boot).returncode != 0, "overwrote prior stage")
        for bad in ("/etc/v3se-test", "/home/randy/printer_data", "/dev/shm/nosuchparent/v3se"):
            must_fail(lambda bad=bad: RENDERER.safe_target(bad), "accepted unsafe stage: " + bad)
        ensure(run("--mode", "connection-check", "--mcu-serial", "../../bad\n[extruder]", "--output", root / "bad-serial").returncode != 0, "serial injection was accepted")
        record = {
            "confirmation": "MEASURED_ON_THIS_PRINTER",
            "printer_label": "test-fixture-only-not-real-hardware",
            "measurement_notes": "synthetic offline values, not suitable for a real printer",
            "values": VALUES,
        }
        path = root / "measurements.json"
        path.write_text(json.dumps(record))
        complete = root / "calibrated"
        result = run("--mode", "calibrated", "--mcu-serial", SERIAL, "--measurements", path, "--output", complete)
        ensure(result.returncode == 0, result.stderr)
        rendered = (complete / "printer.cfg").read_text()
        for name in ("[extruder]", "[heater_bed]", "[stepper_x]", "[bltouch]", "[strain_gauge_z_cal]", "[e3v3se_display]"):
            ensure(name in rendered, "production section missing: " + name)
        ensure(not re.search(r"@[A-Z][A-Z0-9_]*@", rendered) and "#*#" not in rendered, "unresolved placeholders or SAVE_CONFIG tail")
        ensure("counts_per_gram: 94.2" in rendered and "z_offset: 1.567" in rendered, "wrong measurement injection")
        ensure("counts_per_gram: 88.83" not in rendered, "development calibration was copied")
        must_fail(lambda: RENDERER.render("calibrated", SERIAL), "allowed missing measurements")
        for name, mutation in [
            ("wrong-confirm", lambda d: d.update(confirmation="yes")),
            ("bad-counts", lambda d: d["values"].update(counts_per_gram=0)),
            ("bad-pid", lambda d: d["values"].update(bed_pid_kp=-1)),
            ("bad-tare", lambda d: d["values"].update(reference_tare_counts=0.25)),
            ("missing-pid", lambda d: d["values"].pop("bed_pid_kd")),
            ("bad-z", lambda d: d["values"].update(bltouch_z_offset=90)),
            ("injection", lambda d: d["values"].update(extruder_pid_ki="1.0\n[extruder]")),
            ("extra", lambda d: d.update(install_now=True)),
        ]:
            obj = json.loads(json.dumps(record))
            mutation(obj)
            other = root / (name + ".json")
            out = root / (name + "-render")
            other.write_text(json.dumps(obj))
            must_fail(lambda other=other: RENDERER.render("calibrated", SERIAL, other), "invalid calibration accepted: " + name)
            ensure(not out.exists(), "invalid calibration caused an output directory: " + name)
        nan = root / "nan.json"
        nan.write_text(path.read_text().replace("94.2", "NaN", 1))
        must_fail(lambda: RENDERER.render("calibrated", SERIAL, nan), "accepted JSON NaN")
        must_fail(lambda: RENDERER.render("connection-check", SERIAL, path), "boot allowed measurements")
    print("PASS: non-motion first boot, nine target-unit fields, strict rendering and refuse-overwrite safety")


if __name__ == "__main__":
    main()
