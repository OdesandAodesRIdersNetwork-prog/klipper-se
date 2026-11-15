#!/usr/bin/env bash
# Common read-only packaging helpers. No system mutations.
set -euo pipefail
V3SE_INSTALL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$V3SE_INSTALL_DIR/versions.env"
fail() { printf 'V3SE ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf 'V3SE: %s\n' "$*"; }
require_file() { [[ -f "$1" ]] || fail "Missing required file: $1"; }
sha256_matches() {
  local file="$1" expected="$2" actual
  require_file "$file"
  actual="$(sha256sum "$file" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || fail "SHA256 mismatch for $file: $actual (expected $expected)"
}
read_only_host_preflight() {
  [[ "$(uname -m)" == aarch64 ]] || fail 'Requires supported aarch64 CB1 for installation (host-only check).'
  [[ -d /run/systemd/system ]] || fail 'Systemd system not detected.'
  command -v udevadm >/dev/null || fail 'udev is required.'
  command -v virtualenv >/dev/null || fail 'python3-virtualenv not installed.'
  command -v arm-none-eabi-gcc >/dev/null || fail 'ARM GCC missing.'
}
