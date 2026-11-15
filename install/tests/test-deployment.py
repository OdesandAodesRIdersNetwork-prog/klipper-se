#!/usr/bin/env python3
"""Offline deployment planner tests: valid staging and refusal on conflicts."""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def checked_run(*args):
    return subprocess.run([sys.executable, str(ROOT / "plan-deployment.py"), *map(str, args)], capture_output=True, text=True)


def main():
    with tempfile.TemporaryDirectory(prefix="v3se-deploy-") as temp:
        p = pathlib.Path(temp)
        h = p / "fakeuser"
        stage = p / "staged"
        render = subprocess.run([sys.executable, str(ROOT / "render-templates.py"), "--user", "fakeuser", "--home", str(h), "--output", str(stage)], capture_output=True, text=True)
        if render.returncode:
            raise AssertionError(render.stderr)
        good = checked_run("--user", "fakeuser", "--home", h, "--stage", stage)
        if good.returncode:
            raise AssertionError(good.stderr + good.stdout)
        parsed = json.loads(good.stdout)
        if len(parsed["files"]) != 12 or parsed["safe_to_attempt_install"] is not False:
            raise AssertionError("misrepresented deployment plan")
        h.mkdir()
        (h / "printer_data").mkdir()
        bad = checked_run("--user", "fakeuser", "--home", h, "--stage", stage)
        if bad.returncode != 2 or "pre-existing installation path" not in bad.stdout:
            raise AssertionError("planner did not refuse pre-existing printer_data")
        (h / "printer_data").rmdir()
        staged_file = stage / "systemd/klipper.service"
        staged_file.unlink()
        staged_file.symlink_to("/etc/passwd")
        unsafe = checked_run("--user", "fakeuser", "--home", h, "--stage", stage)
        if unsafe.returncode != 3 or "unsafe staged source" not in unsafe.stderr:
            raise AssertionError("planner followed unsafe staged symlink")
        wronguser = checked_run("--user", "randy", "--home", h, "--stage", stage)
        if wronguser.returncode != 3:
            raise AssertionError("planner accepted account/home mismatch")
    print("PASS: 12 planned destinations, existing-install refusal, symlink and identity guards")


if __name__ == "__main__":
    main()
