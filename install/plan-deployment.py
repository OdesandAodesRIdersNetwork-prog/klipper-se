#!/usr/bin/env python3
"""READ-ONLY planned destinations and conflict checks. NEVER installs files.

Requires a fully rendered staging tree produced by render-templates.py.
This is an advisory safety gate, not an installer and not a guarantee that
permissions, services or firmware will work on the target CB1.
"""
import argparse
import json
import os
import pathlib
import re
import sys

# Each item maps a staged file to the only permitted prospective destination.
HOST_FILES = {
    "systemd/klipper.service": "/etc/systemd/system/klipper.service",
    "systemd/moonraker.service": "/etc/systemd/system/moonraker.service",
    "systemd/v3se-mcu-recover.service": "/etc/systemd/system/v3se-mcu-recover.service",
    "udev/99-v3se-mcu-recover.rules": "/etc/udev/rules.d/99-v3se-mcu-recover.rules",
    "nginx/sites-available/mainsail": "/etc/nginx/sites-available/mainsail",
    "nginx/conf.d/upstreams.conf": "/etc/nginx/conf.d/upstreams.conf",
    "nginx/conf.d/common_vars.conf": "/etc/nginx/conf.d/common_vars.conf",
}
USER_FILES = {
    "printer_data/systemd/klipper.env": "printer_data/systemd/klipper.env",
    "printer_data/systemd/moonraker.env": "printer_data/systemd/moonraker.env",
    "printer_data/config/moonraker.conf": "printer_data/config/moonraker.conf",
    "home/mainsail/config.json": "mainsail/config.json",
    "home/v3se-mcu-recover.sh": "v3se-mcu-recover.sh",
}
MARKERS = re.compile(r"@[A-Z][A-Z0-9_]*@")


def run(args):
    stage = args.stage.resolve(strict=True)
    if not stage.is_dir():
        raise ValueError("stage must be a directory")
    home = args.home.resolve(strict=False)
    if not home.is_absolute() or home in (pathlib.Path("/"), pathlib.Path("/root")) or ".." in args.home.parts:
        raise ValueError("invalid service home")
    if str(home).startswith(("/etc/", "/usr/", "/var/", "/boot/", "/dev/", "/proc/", "/sys/")):
        raise ValueError("home cannot be inside a system directory")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(home)):
        raise ValueError("unsupported service home characters")
    if args.user != home.name or not re.fullmatch(r"[a-z_][a-z0-9_-]*", args.user):
        raise ValueError("service home basename must equal the user")
    if home == stage or home in stage.parents or stage in home.parents:
        raise ValueError("staging path cannot overlap service home")
    blocking_roots = [home / "printer_data", home / "klipper-port", home / "klippy-env", home / "moonraker", home / "moonraker-env", home / "mainsail", home / "mainsail-config"]
    conflicts = []
    for root in blocking_roots:
        if os.path.lexists(root):
            conflicts.append("pre-existing installation path: %s" % root)
    entries = []
    for rel, dst in list(HOST_FILES.items()) + [(k, str(home / v)) for k, v in USER_FILES.items()]:
        source = stage / rel
        if source.is_symlink() or not source.is_file() or source.resolve(strict=False).parent != source.parent.resolve(strict=False):
            raise ValueError("missing or unsafe staged source: %s" % rel)
        data = source.read_text(encoding="utf-8")
        if MARKERS.search(data):
            raise ValueError("unresolved placeholder in staged source: %s" % rel)
        destination = pathlib.Path(dst)
        if os.path.lexists(destination):
            conflicts.append("existing target (no overwrites allowed): %s" % destination)
        entries.append({"staged": rel, "would_install_to": str(destination)})
    result = {
        "mode": "READ_ONLY_PLAN_NEVER_INSTALL",
        "service_user": args.user,
        "service_home": str(home),
        "files": entries,
        "conflicts": sorted(set(conflicts)),
        "safe_to_attempt_install": False,
        "reason": "This tool cannot install; installer --apply is disabled regardless of conflicts.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if conflicts else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--home", required=True, type=pathlib.Path)
    parser.add_argument("--stage", required=True, type=pathlib.Path)
    try:
        sys.exit(run(parser.parse_args()))
    except (ValueError, OSError) as e:
        print("V3SE DEPLOYMENT PLAN: " + str(e), file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
