#!/usr/bin/env bash
# Controlled, NOT-YET-ENABLED installer. --check / --plan are non-mutating.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
case "${1:---help}" in
  --check)
    bash "$here/verify-packaging.sh"
    ;;
  --plan)
    cat <<'PHASES'
1. Run read-only fresh-CB1 preflight; verify Debian 12/Armbian aarch64 and explicit dependencies.
2. Select non-root user/home; refuse any existing unbacked-up installation.
3. Stage and verify pinned Klipper-SE/Moonraker/Mainsail sources independently of packaging branch.
4. Create printer_data tree, Klippy virtualenv, and verify requirements.
5. Verify exact accepted MCU .config, build firmware; STOP for manual SD flashing.
6. Deploy machine-specific-safe config and macros only after calibration inputs exist.
7. Install pinned Moonraker, Mainsail, mainsail-config, Nginx, and recovery.
8. Verify software, calibrate target printer, then re-run all 17 physical tests.
PHASES
    ;;
  --host-preflight)
    if [[ "$#" -ne 2 ]]; then echo 'Usage: install.sh --host-preflight USERNAME' >&2; exit 2; fi
    exec python3 "$here/preflight-cb1.py" --user "$2"
    ;;
  --sources-plan)
    if [[ "$#" -ne 1 ]]; then echo 'Usage: install.sh --sources-plan' >&2; exit 2; fi
    exec python3 "$here/stage-dependencies.py" --plan
    ;;
  --apply)
    echo 'REFUSED: first packaging commit is a reviewed scaffold, not a complete or tested installer.' >&2
    echo 'Exact MCU .config, recovery/service templates, and safe first-boot calibration workflow must be implemented first.' >&2
    exit 3
    ;;
  *)
    echo "Usage: $0 --check | --plan | --host-preflight USERNAME | --sources-plan | --apply" >&2
    echo 'Only --check and --plan are available in this initial packaging commit.' >&2
    exit 2
    ;;
esac
