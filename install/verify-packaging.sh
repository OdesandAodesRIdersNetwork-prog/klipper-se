#!/usr/bin/env bash
# Offline, read-only staging validator. Does not install or control services.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck disable=SC1091
source install/versions.env
bad=0
incomplete=0
check() { if [[ -f "$1" ]]; then printf 'OK    %s\n' "$1"; else printf 'MISSING %s\n' "$1"; bad=1; fi; }
for f in install/versions.env install/packages-bookworm.txt install/common.sh \
  install/install.sh install/build-firmware.sh install/verify-install.sh \
  install/printer/printer.cfg.in install/printer/macro.cfg \
  docs/V3SE_CLEAN_INSTALL.md docs/V3SE_FLASH_SD.md \
  docs/V3SE_CALIBRATION.md docs/V3SE_ACCEPTANCE_CHECKLIST.md docs/V3SE_RECOVERY.md
 do check "$f"; done
if [[ "$(grep -vE '^\s*(#|$)' install/packages-bookworm.txt | wc -l | tr -d ' ')" != 17 ]]; then
  echo 'ERROR: Bookworm top-level package count is not 17'; bad=1
fi
if grep -q '^#\*#' install/printer/printer.cfg.in; then
  echo 'ERROR: Machine-generated SAVE_CONFIG block appears in template'; bad=1
fi
for needle in 'counts_per_gram: 88.83' 'reference_tare_counts: 260114' 'z_offset: 1.431'; do
  if grep -Fq "$needle" install/printer/printer.cfg.in; then
    echo "ERROR: machine-specific calibration leaked: $needle"; bad=1
  fi
done
if ! grep -Fq '@COUNTS_PER_GRAM@' install/printer/printer.cfg.in; then
  echo 'ERROR: target-unit calibration marker missing'; bad=1
fi
if [[ -f install/firmware/v3se-stm32f103xe.config ]]; then
  actual="$(sha256sum install/firmware/v3se-stm32f103xe.config | awk '{print $1}')"
  [[ "$actual" == "$V3SE_MCU_CONFIG_SHA256" ]] || { echo 'ERROR: MCU .config hash mismatch'; bad=1; }
else
  echo 'BLOCKED: exact accepted MCU .config not yet captured (no substitute allowed).'; incomplete=1
fi
if [[ ! -f install/recovery/v3se-mcu-recover.sh.in ]]; then
  echo 'BLOCKED: exact accepted recovery script not yet captured/templated.'; incomplete=1
fi
if [[ ! -f install/systemd/v3se-mcu-recover.service.in ]]; then
  echo 'BLOCKED: exact accepted recovery service not yet captured/templated.'; incomplete=1
fi
if [[ "$bad" -ne 0 ]]; then exit 1; fi
if [[ "$incomplete" -ne 0 ]]; then
  echo 'Static staged-file checks passed, but required production assets remain missing.'
  exit 4
fi
printf 'Static staging checks PASS. Further live compatibility and physical acceptance still required.\n'
