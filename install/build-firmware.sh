#!/usr/bin/env bash
# Explicit action only, NEVER flashes MCU. Runs only in a disposable clean checkout.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$here/common.sh"
usage() { echo "Usage: $0 --check SOURCE_DIR | --build SOURCE_DIR" >&2; exit 2; }
[[ "$#" -eq 2 ]] || usage
mode="$1"; src="$2"
[[ "$mode" == '--check' || "$mode" == '--build' ]] || usage
[[ -d "$src/.git" ]] || fail "Expected separate Git clone at: $src"
[[ "$(git -C "$src" rev-parse HEAD)" == "$V3SE_SOURCE_COMMIT" ]] || fail 'Runtime tree must be accepted source commit, NOT packaging branch'
[[ -z "$(git -C "$src" status --porcelain)" ]] || fail 'Runtime Git checkout is not clean'
config="$here/firmware/v3se-stm32f103xe.config"
sha256_matches "$config" "$V3SE_MCU_CONFIG_SHA256"
command -v arm-none-eabi-gcc >/dev/null || fail 'Install GNU ARM cross-compiler before build'
if [[ "$mode" == '--check' ]]; then
  info 'Accepted source and exact MCU config verified. Build not started.'
  exit 0
fi
[[ ! -e "$src/.config" ]] || fail "Refusing to replace existing .config at $src"
cp -- "$config" "$src/.config"
( cd "$src" && make olddefconfig && sha256sum -c <(printf '%s  %s\n' "$V3SE_MCU_CONFIG_SHA256" .config) && make -j"$(nproc)" )
require_file "$src/out/klipper.bin"
sha256sum "$src/out/klipper.bin"
info 'Firmware built. Flash manually by SD card only; see docs/V3SE_FLASH_SD.md.'
