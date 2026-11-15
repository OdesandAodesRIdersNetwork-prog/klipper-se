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
8. Rehearse conflict-safe 18-file filesystem transaction in marked scratch root only.
9. On a separate fresh CB1: independently verify installed software and supervised calibration.
10. Re-run all 17 physical tests before claiming reproducibility.
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
    echo 'REFUSED: --apply remains disabled; Stage 7 validates scratch-only transactions, not CB1 installation.' >&2
    echo 'Real provisioning, supervised target-only calibration, firmware flash and 17-test fresh acceptance remain gated.' >&2
    exit 3
    ;;
  *)
    echo "Usage: $0 --check | --plan | --host-preflight USERNAME | --sources-plan | --apply" >&2
    echo 'Safe subcommands are listed above; --apply is deliberately disabled.' >&2
    exit 2
    ;;
esac
