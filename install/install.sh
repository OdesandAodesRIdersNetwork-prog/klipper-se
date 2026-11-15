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
1. Confirm a separate blank CB1; run read-only preflight and refuse existing install paths.
2. Review the fixed Bookworm apt plan; run the separately confirmed apt phase on fresh CB1 only.
3. Review dialout and moonraker-admin plan; separately configure service-user groups.
4. Stage and verify pinned Klipper-SE, Moonraker, Mainsail and mainsail-config sources.
5. Build separate Klippy/Moonraker scratch Python environments; verify imports and packages.
6. Build accepted MCU firmware; STOP for manual SD flashing and subsequent identity verification.
7. Rehearse inert 18-file connection-check payload transaction in a disposable scratch root.
8. Implement/test a safe host deployment and services transaction (NOT YET ENABLED).
9. Acquire target-unit values via supervised safe calibration (NOT YET VALIDATED).
10. Recheck service/display/recovery and run all 17 physical tests on the new printer.
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
  --packages-plan)
    if [[ "$#" -ne 2 ]]; then echo 'Usage: install.sh --packages-plan USERNAME' >&2; exit 2; fi
    exec python3 "$here/provision-packages.py" --plan --user "$2"
    ;;
  --groups-plan)
    if [[ "$#" -ne 2 ]]; then echo 'Usage: install.sh --groups-plan USERNAME' >&2; exit 2; fi
    exec python3 "$here/provision-groups.py" --plan --user "$2"
    ;;
  --apply)
    echo 'REFUSED: --apply remains disabled; Stage 7 validates scratch-only transactions, not CB1 installation.' >&2
    echo 'Real provisioning, supervised target-only calibration, firmware flash and 17-test fresh acceptance remain gated.' >&2
    exit 3
    ;;
  *)
    echo "Usage: $0 --check | --plan | --host-preflight USERNAME | --sources-plan | --packages-plan USERNAME | --groups-plan USERNAME | --apply" >&2
    echo 'Safe subcommands are listed above; --apply is deliberately disabled.' >&2
    exit 2
    ;;
esac
