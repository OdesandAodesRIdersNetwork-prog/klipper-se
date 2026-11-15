#!/usr/bin/env bash
# Klipper-SE fresh-CB1 installer entrypoint. Safe plans only until hardware proof.
# Do NOT change the --apply refusal before physical clean-install acceptance.
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
usage() {
  echo "Usage: $0 --check | --plan | --host-preflight USER | --sources-plan | --packages-plan USER | --groups-plan USER | --host-files-plan USER PAYLOAD | --runtime-plan USER PINNED_SOURCES | --services-plan USER | --apply" >&2
  exit 2
}
case "${1:---help}" in
  --check)
    [[ "$#" == 1 ]] || usage
    exec bash "$here/verify-packaging.sh"
    ;;
  --plan)
    [[ "$#" == 1 ]] || usage
    cat <<'PHASES'
Fresh-CB1 Klipper-SE installation sequence (not a released installer):
01. On a SEPARATE, blank Bookworm ARM64 CB1: run read-only host preflight.
02. Review and explicitly run separately gated apt phase, then group phase.
03. Fetch/verify pinned Klipper-SE, Moonraker, mainsail-config and Mainsail source.
04. Render connection-check-only host/printer templates and assemble 18-file payload.
05. Run --host-files-plan and rehearse a disposable host transaction first.
06. On blank CB1 only, separately deploy host files (root, explicit confirmation).
07. Install pinned source, Python environments and Mainsail assets as service user.
08. Build firmware from exact MCU .config; STOP for MANUAL SD flashing and identity.
09. After serial identity review, explicitly activate connection-only services.
10. STOP: derive and supervise all nine target-specific calibration values.
11. Validate first full hardware config, PID, mesh, stock screen, MCU recovery.
12. Prove all 17 physical acceptance checks; only then consider release.
No stage auto-flashes, issues G-code or authorizes print-ready operation.
PHASES
    ;;
  --host-preflight)
    [[ "$#" == 2 ]] || usage
    exec python3 "$here/preflight-cb1.py" --user "$2"
    ;;
  --sources-plan)
    [[ "$#" == 1 ]] || usage
    exec python3 "$here/stage-dependencies.py" --plan
    ;;
  --packages-plan)
    [[ "$#" == 2 ]] || usage
    exec python3 "$here/provision-packages.py" --plan --user "$2"
    ;;
  --groups-plan)
    [[ "$#" == 2 ]] || usage
    exec python3 "$here/provision-groups.py" --plan --user "$2"
    ;;
  --host-files-plan)
    [[ "$#" == 3 ]] || usage
    exec python3 "$here/deploy-host.py" --plan --user "$2" --payload "$3"
    ;;
  --runtime-plan)
    [[ "$#" == 3 ]] || usage
    exec python3 "$here/materialize-runtime.py" --plan --user "$2" --sources "$3"
    ;;
  --services-plan)
    [[ "$#" == 2 ]] || usage
    exec python3 "$here/activate-services.py" --plan --user "$2"
    ;;
  --apply)
    echo 'REFUSED: full installer --apply is disabled until a fresh CB1 and stock V3 SE are physically validated.' >&2
    echo 'Individual candidate phases are documented but must not be run on the accepted printer.' >&2
    exit 3
    ;;
  *) usage ;;
esac
