#!/usr/bin/env python3
"""Stage install templates in a specified directory. Never installs/restarts services.

This tool only writes under a new, user-chosen staging directory, refuses
an existing destination, and does not create or modify system locations.
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATES = {
    "systemd/klipper.service.in": "systemd/klipper.service",
    "systemd/klipper.env.in": "printer_data/systemd/klipper.env",
    "systemd/moonraker.service.in": "systemd/moonraker.service",
    "systemd/moonraker.env.in": "printer_data/systemd/moonraker.env",
    "systemd/v3se-mcu-recover.service.in": "systemd/v3se-mcu-recover.service",
    "recovery/v3se-mcu-recover.sh.in": "home/v3se-mcu-recover.sh",
    "moonraker/moonraker.conf.in": "printer_data/config/moonraker.conf",
    "mainsail/config.json.in": "home/mainsail/config.json",
    "nginx/mainsail.site.in": "nginx/sites-available/mainsail",
    "nginx/upstreams.conf.in": "nginx/conf.d/upstreams.conf",
}
COPY_FILES = {
    "udev/99-v3se-mcu-recover.rules": "udev/99-v3se-mcu-recover.rules",
    "nginx/common_vars.conf": "nginx/conf.d/common_vars.conf",
}
PATTERN = re.compile(r"@[A-Z_]+@")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--output", type=pathlib.Path, required=True)
    args = p.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", args.user):
        p.error("user must be a Linux-safe account name")
    home = pathlib.Path(args.home)
    if not home.is_absolute() or str(home) in ("/", "/root") or ".." in home.parts:
        p.error("home must be an absolute, non-root path without '..'")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(home)):
        p.error("home contains unsupported characters")
    data = str(home / "printer_data")
    values = {
        "@USER@": args.user,
        "@HOME@": str(home),
        "@PRINTER_DATA@": data,
        "@MOONRAKER_PORT@": "7125",
        "@MAINSAIL_PORT@": "80",
        "@MOONRAKER_URL@": "http://127.0.0.1:7125",
        "@MCU_SERIAL_BY_ID@": "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",
    }
    target = args.output.resolve(strict=False)
    # Never write staging files into a real system/service or printer tree.
    forbidden = (pathlib.Path("/etc"), pathlib.Path("/usr"), home,
                 pathlib.Path("/boot"), pathlib.Path("/var"))
    for directory in forbidden:
        if target == directory or directory in target.parents:
            p.error("output is within a protected live/system path")
    if target.exists():
        p.error("output already exists; refusing overwrite")
    rendered = {}
    for src, dest in TEMPLATES.items():
        raw = (HERE / src).read_text(encoding="utf-8")
        for key, value in values.items():
            raw = raw.replace(key, value)
        if PATTERN.search(raw):
            p.error("unresolved placeholder in " + src)
        rendered[dest] = raw
    for src, dest in COPY_FILES.items():
        rendered[dest] = (HERE / src).read_text(encoding="utf-8")
    target.mkdir(parents=True, exist_ok=False)
    for name, body in rendered.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if name == "home/v3se-mcu-recover.sh":
            path.chmod(0o755)
    print("STAGED ONLY: %d files written to %s" % (len(rendered), target))
    print("No system paths, running services, firmware, or printer files changed.")


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print("V3SE: " + str(exc), file=sys.stderr)
        sys.exit(1)
