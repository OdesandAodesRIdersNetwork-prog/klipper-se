#!/usr/bin/env bash
# Staging-only checks; no service, printer, package or permission modification.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck disable=SC1091
source install/versions.env
bad=0
check() { if [[ -f "$1" ]]; then printf 'OK    %s\n' "$1"; else printf 'MISSING %s\n' "$1"; bad=1; fi; }
for f in install/versions.env install/packages-bookworm.txt install/common.sh \
  install/install.sh install/build-firmware.sh install/verify-install.sh \
  install/printer/printer.cfg.in install/printer/first-boot.cfg.in \
  install/printer/target-measurements.example.json install/printer/macro.cfg \
  install/render-printer-config.py install/plan-deployment.py \
  install/assemble-offline.py install/tests/test-assemble-offline.py \
  install/preflight-cb1.py install/tests/test-preflight-cb1.py \
  install/stage-dependencies.py install/tests/test-stage-dependencies.py \
  install/transaction-sandbox.py install/tests/test-transaction-sandbox.py \
  install/prepare-venvs.py install/tests/test-prepare-venvs.py \
  docs/V3SE_STAGE7_PINNED_PYTHON_ENVS.md \
  install/provision-packages.py install/tests/test-provision-packages.py \
  docs/V3SE_STAGE7_APT_PROVISIONING.md \
  install/provision-groups.py install/tests/test-provision-groups.py \
  docs/V3SE_STAGE7_GROUP_PROVISIONING.md \
  install/deploy-host.py install/tests/test-deploy-host.py \
  install/materialize-runtime.py install/tests/test-materialize-runtime.py \
  install/activate-services.py install/tests/test-activate-services.py \
  docs/V3SE_CONNECTED_INSTALL_RUNBOOK.md \
  install/verify-acceptance-evidence.py install/tests/test-verify-acceptance-evidence.py \
  docs/V3SE_RELEASE_EVIDENCE.md \
  install/simulate-deployment.py install/tests/test-package-sandbox.py \
  install/rehearse-offline.py install/tests/test-rehearse-offline.py \
  install/firmware/v3se-stm32f103xe.config \
  docs/V3SE_CLEAN_INSTALL.md docs/V3SE_FLASH_SD.md docs/V3SE_CALIBRATION.md \
  docs/V3SE_CALIBRATION_VALUES.md docs/V3SE_ACCEPTANCE_CHECKLIST.md \
  docs/V3SE_OFFLINE_REHEARSAL.md docs/V3SE_STAGE6_PREFLIGHT_AND_SOURCES.md \
  docs/V3SE_RECOVERY.md docs/V3SE_SERVICE_TEMPLATES.md \
  docs/V3SE_FIRST_BOOT_CALIBRATION_DESIGN.md \
  install/render-templates.py install/tests/test-render.sh \
  install/tests/test-recovery.sh install/tests/test-printer-gate.py \
  install/tests/test-deployment.py \
  install/systemd/klipper.service.in install/systemd/klipper.env.in \
  install/systemd/moonraker.service.in install/systemd/moonraker.env.in \
  install/systemd/v3se-mcu-recover.service.in \
  install/recovery/v3se-mcu-recover.sh.in \
  install/udev/99-v3se-mcu-recover.rules \
  install/moonraker/moonraker.conf.in install/mainsail/config.json.in \
  install/nginx/mainsail.site.in install/nginx/upstreams.conf.in \
  install/nginx/common_vars.conf; do check "$f"; done

count="$(grep -vE '^\s*(#|$)' install/packages-bookworm.txt | wc -l | tr -d ' ')"
if [[ "$count" != 17 ]]; then echo "ERROR: expected 17 top-level apt packages, saw $count"; bad=1; fi
if grep -q '^#\*#' install/printer/printer.cfg.in; then
  echo 'ERROR: machine-generated SAVE_CONFIG tail in full template'; bad=1
fi
for needle in 'counts_per_gram: 88.83' 'reference_tare_counts: 260114' 'z_offset: 1.431'; do
  if grep -Fq "$needle" install/printer/printer.cfg.in; then
    echo "ERROR: accepted printer calibration leaked: $needle"; bad=1
  fi
done
for marker in '@COUNTS_PER_GRAM@' '@REFERENCE_TARE_COUNTS@' '@BLTOUCH_Z_OFFSET@' '@EXTRUDER_PID_KP@' '@BED_PID_KP@'; do
  if ! grep -Fq "$marker" install/printer/printer.cfg.in; then
    echo "ERROR: missing required calibration placeholder $marker"; bad=1
  fi
done
if [[ -f install/firmware/v3se-stm32f103xe.config ]]; then
  hash="$(sha256sum install/firmware/v3se-stm32f103xe.config | awk '{print $1}')"
  if [[ "$hash" != "$V3SE_MCU_CONFIG_SHA256" ]]; then
    echo 'ERROR: accepted MCU .config SHA256 mismatch'; bad=1
  fi
else
  echo 'ERROR: required accepted MCU .config is missing'; bad=1
fi
if [[ "$bad" -ne 0 ]]; then exit 1; fi
for f in install/install.sh install/common.sh install/build-firmware.sh \
         install/recovery/v3se-mcu-recover.sh.in; do bash -n "$f" || bad=1; done
bash install/tests/test-render.sh || bad=1
bash install/tests/test-recovery.sh || bad=1
python3 install/tests/test-printer-gate.py || bad=1
python3 install/tests/test-deployment.py || bad=1
python3 install/tests/test-assemble-offline.py || bad=1
python3 install/tests/test-package-sandbox.py || bad=1
python3 install/tests/test-rehearse-offline.py || bad=1
python3 install/tests/test-preflight-cb1.py || bad=1
python3 install/tests/test-stage-dependencies.py || bad=1
python3 install/tests/test-transaction-sandbox.py || bad=1
python3 install/tests/test-prepare-venvs.py || bad=1
python3 install/tests/test-provision-packages.py || bad=1
python3 install/tests/test-provision-groups.py || bad=1
python3 install/tests/test-deploy-host.py || bad=1
python3 install/tests/test-materialize-runtime.py || bad=1
python3 install/tests/test-activate-services.py || bad=1
python3 install/tests/test-verify-acceptance-evidence.py || bad=1
if [[ "$bad" -ne 0 ]]; then exit 1; fi
printf '%s\n' 'Offline packaging and safety staging tests PASS.'
printf '%s\n' 'BLOCKED: installation --apply, supervised calibration acquisition and blank-CB1/physical acceptance are not implemented or validated.'
exit 4
