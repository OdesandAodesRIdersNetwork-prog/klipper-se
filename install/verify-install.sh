#!/usr/bin/env bash
# Read-only host evidence probe. Never changes systemd, printer, or config.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$here/common.sh"
user="${1:-${SUDO_USER:-$USER}}"
[[ "$user" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail 'Provide an existing Linux username as the first argument.'
getent passwd "$user" >/dev/null || fail "Unknown user: $user"
home="$(getent passwd "$user" | cut -d: -f6)"
[[ -d "$home/printer_data/config" ]] || fail "Missing $home/printer_data/config"
for p in "$home/klipper-port" "$home/moonraker" "$home/mainsail" "$home/mainsail-config"; do
  [[ -d "$p" ]] || fail "Missing $p"
done
[[ "$(git -C "$home/klipper-port" rev-parse HEAD)" == "$V3SE_SOURCE_COMMIT" ]] || fail 'Unexpected Klipper runtime commit'
[[ "$(git -C "$home/moonraker" rev-parse HEAD)" == "$MOONRAKER_COMMIT" ]] || fail 'Unexpected Moonraker commit'
[[ "$(git -C "$home/mainsail-config" rev-parse HEAD)" == "$MAINSAIL_CONFIG_COMMIT" ]] || fail 'Unexpected mainsail-config commit'
[[ "$(cat "$home/mainsail/.version")" == "$MAINSAIL_VERSION" ]] || fail 'Unexpected Mainsail release'
for f in printer.cfg macros.cfg macro.cfg moonraker.conf mainsail.cfg; do
  [[ -e "$home/printer_data/config/$f" ]] || fail "Missing config $f"
done
info 'Read-only source/path preflight passed. NOT a substitute for startup, calibration, or 17 physical acceptance tests.'
