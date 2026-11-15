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
1. Verify Debian 12/Armbian aarch64 base and explicit dependencies.
2. Select non-root user/home; refuse any existing unbacked-up installation.
3. Fetch pinned accepted Klipper-SE runtime commit independently of packaging branch.
4. Create printer_data tree, Klippy virtualenv, and verify requirements.
5. Verify exact accepted MCU .config, build firmware; STOP for manual SD flashing.
6. Deploy machine-specific-safe config and macros only after calibration inputs exist.
7. Install pinned Moonraker, Mainsail, mainsail-config, Nginx, and recovery.
8. Verify software, calibrate target printer, then re-run all 17 physical tests.
PHASES
    ;;
  --apply)
    echo 'REFUSED: this packaging branch is not a validated or enabled host installer.' >&2
    echo 'Safe first-boot calibration, conflict-safe deployment, blank-CB1 and physical validation remain required.' >&2
    exit 3
    ;;
  *)
    echo "Usage: $0 --check | --plan | --apply" >&2
    echo 'Only --check and --plan are available in the current staging checkpoint.' >&2
    exit 2
    ;;
esac
