#!/usr/bin/env bash
# Non-mutating with respect to any printer/OS config: uses disposable temp dir.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
python3 "$here/render-templates.py" --user testuser --home /home/testuser --output "$tmp/staged"
test -f "$tmp/staged/systemd/klipper.service"
test -f "$tmp/staged/printer_data/config/moonraker.conf"
test -x "$tmp/staged/home/v3se-mcu-recover.sh"
test -f "$tmp/staged/udev/99-v3se-mcu-recover.rules"
! grep -rE '@[A-Z_]+@|/home/randy' "$tmp/staged"
grep -q 'User=testuser' "$tmp/staged/systemd/klipper.service"
grep -q 'User=testuser' "$tmp/staged/systemd/v3se-mcu-recover.service"
grep -q '/home/testuser/mainsail' "$tmp/staged/nginx/sites-available/mainsail"
bash -n "$tmp/staged/home/v3se-mcu-recover.sh"
if python3 "$here/render-templates.py" --user testuser --home /home/testuser --output "$tmp/staged" >/dev/null 2>&1; then
    echo 'FAIL: staging overwrote existing output'; exit 1
fi
if python3 "$here/render-templates.py" --user testuser --home /home/testuser --output /etc/klipper-v3se >/dev/null 2>&1; then
    echo 'FAIL: staging accepted system path'; exit 1
fi
printf 'PASS: user/path rendering, safety guards, no leaked machine values, shell syntax\n'
