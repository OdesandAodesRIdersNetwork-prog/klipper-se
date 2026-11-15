# Host service and recovery templates for Klipper-SE

**Status: staging assets only; no printer or CB1 deployment has been performed.**

## Source basis and scope

These files are deliberately minimal, user/path-parameterized equivalents of the accepted host contract, not promised byte-for-byte copies of the live CB1 files. The accepted recovery event is an add event on the CH341 USB-serial adapter with vendor `1a86`, product `7523`. The old `v3se-mcu-recover.path` watcher must **not** be installed.

`install/render-templates.py` creates a staging directory only. For example, from the repository checkout, on any host with Python 3:

```bash
python3 install/render-templates.py --user testuser --home /home/testuser --output /tmp/v3se-stage-example
bash install/tests/test-render.sh
bash install/tests/test-recovery.sh
```

Do not run staging with a production output target. It refuses existing output and protected directories. It does not install services, run apt, alter udev, or restart anything.

## Planned installation destinations

| Staged output | Future installation destination |
|---|---|
| `systemd/klipper.service` | `/etc/systemd/system/klipper.service` |
| `systemd/moonraker.service` | `/etc/systemd/system/moonraker.service` |
| `systemd/v3se-mcu-recover.service` | `/etc/systemd/system/v3se-mcu-recover.service` |
| `printer_data/systemd/klipper.env` | `<home>/printer_data/systemd/klipper.env` |
| `printer_data/systemd/moonraker.env` | `<home>/printer_data/systemd/moonraker.env` |
| `printer_data/config/moonraker.conf` | `<home>/printer_data/config/moonraker.conf` |
| `home/v3se-mcu-recover.sh` | `<home>/v3se-mcu-recover.sh` |
| `home/mainsail/config.json` | `<home>/mainsail/config.json` |
| `udev/99-v3se-mcu-recover.rules` | `/etc/udev/rules.d/99-v3se-mcu-recover.rules` |
| `nginx/sites-available/mainsail` | `/etc/nginx/sites-available/mainsail` |
| `nginx/conf.d/upstreams.conf` | `/etc/nginx/conf.d/upstreams.conf` |
| `nginx/conf.d/common_vars.conf` | `/etc/nginx/conf.d/common_vars.conf` |

The eventual installer must check for conflicting existing files/ports, package ownership, the Debian Nginx default site, correct `www-data` directory traversal, systemd syntax, Moonraker authentication, and Nginx syntax **before** enabling a service. It must not copy the entire original `/etc/nginx` tree.

## Recovery safety contract

The recovery script waits three seconds after the udev start, confirms the expected by-id device is present, retrieves `GET /printer/info` from local Moonraker, and requires both `state == shutdown` and a message containing `Lost communication with MCU`. Only then does it make `POST /printer/gcode/script` with `FIRMWARE_RESTART`. All other states fail closed. The test uses a mock `curl` executable and does not touch Moonraker.

The accepted printer's actual recovery script may differ in wording or shell details. This newly authored equivalent must be checked in an isolated blank-CB1 deployment and through a power-off/on physical acceptance test before being called accepted. The udev line itself is the exact observed rule.

## Blockers kept explicit

The `--apply` installer action remains disabled. Machine-specific first-boot safety, staged config generation, no-conflict deployment, reliable dependency download/build, and actual blank-CB1 + printer physical validation are still required. Template unit tests do not establish real installation compatibility.
