# Klipper-SE clean-install runbook: release candidate, not yet physical acceptance

**Scope:** a separately imaged CB1 running Debian 12/Armbian Bookworm ARM64 and a stock Ender-3 V3 SE. **Never use the accepted development CB1 as an installation target.** This is a candidate procedure to be physically tested, not a verified reproducible release. The main `install/install.sh --apply` remains disabled. Regular Klipper-SE source is pinned to `ab759b0026ca69396446bf13b7a9767c59619297`. The separate Kalico rollback repository is **not** installed.

## Ground rules

The scripts below have different privilege levels. `RUN AS normal user` never means `sudo`. `RUN AS root` is only for a separately imaged blank CB1 after reviewing each command's action and the specific file paths. None of these stages flashes firmware, issues motion/heat G-code, imports saved calibration values or claims physical acceptance. Initial `printer.cfg` is MCU-only `[mcu]` plus `[printer] kinematics: none`, so it **cannot move motors or heat**.

1. **Read-only preflight.** RUN AS normal user: `bash install/install.sh --host-preflight YOURUSER` and `bash install/install.sh --sources-plan`. Confirm Debian 12, ARM64, Python 3.11, normal user `/home/YOURUSER` and *no previous printer installation or systemd/Nginx V3 SE files*. Missing packages, serial and group membership are normal before their later stages, but any existing installation path is a blocker.
2. **Packages.** RUN AS normal user: `bash install/install.sh --packages-plan YOURUSER`. RUN AS root, new CB1 only: `sudo python3 install/provision-packages.py --install --user YOURUSER --confirm FRESH_CB1_APT_PACKAGES_ONLY`. This changes apt packages and might start distro Nginx. It has **no automatic rollback**; if apt is interrupted, inspect or reimage the blank CB1. Recheck package versions.
3. **Groups.** RUN AS normal user: `bash install/install.sh --groups-plan YOURUSER`. RUN AS root, new CB1 only: `sudo python3 install/provision-groups.py --configure --user YOURUSER --confirm FRESH_CB1_GROUPS_ONLY`. This changes the existing user's `dialout` and `moonraker-admin` memberships, not its password or home. It has no automatic rollback; a new session may be necessary.
4. **Pinned source stage.** RUN AS normal user: `python3 install/stage-dependencies.py --fetch --output /tmp/v3se-source-stage-NEW` then `python3 install/stage-dependencies.py --verify --output /tmp/v3se-source-stage-NEW`. Requires Internet; checks exact Klipper-SE, Moonraker and mainsail-config Git commits and exact Mainsail v2.19.0 ZIP SHA256. The sources are staged under `/tmp`, not in the live printer home. Keep them through step 7.
5. **Render and assemble the MCU-only profile.** RUN AS normal user, with fresh scratch paths:

   ```bash
   python3 install/render-templates.py --user YOURUSER --home /home/YOURUSER --output /tmp/v3se-host-stage-NEW
   python3 install/render-printer-config.py --mode connection-check --mcu-serial /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 --output /tmp/v3se-printer-stage-NEW
   python3 install/assemble-offline.py --host-stage /tmp/v3se-host-stage-NEW --printer-stage /tmp/v3se-printer-stage-NEW --output /tmp/v3se-payload-NEW
   python3 install/simulate-deployment.py --verify --payload /tmp/v3se-payload-NEW
   bash install/install.sh --host-files-plan YOURUSER /tmp/v3se-payload-NEW
   ```

   The assembled payload's recorded status remains `OFFLINE_STAGING_ONLY_NOT_INSTALLABLE`; the separately gated host transaction is still a candidate. Review all 18 intended paths and ensure no existing files or symlinked parents. Run the sandbox rehearsal tests before any real host changes.
6. **Host file transaction.** RUN AS root, **only on the verified new CB1**, after reviewing the plan and with explicit confirmation:

   ```bash
   sudo python3 install/deploy-host.py --deploy --user YOURUSER --payload /tmp/v3se-payload-NEW --confirm FRESH_CB1_CONNECTION_ONLY_DEPLOY
   ```

   Writes *new files only* for systemd, udev, Nginx, machine-safe config, macros, and pinned metadata. It uses directory-descriptor paths, rejects existing destinations and writes a receipt. On an exception it attempts identity-checked rollback of files it created. This is **not** a guarantee of recovery from power failure or a hostile concurrent root process. It does not enable/start any service.
7. **Runtime sources, venvs and frontend.** RUN AS the **normal service user**, not root:

   ```bash
   python3 install/materialize-runtime.py --plan --user YOURUSER --sources /tmp/v3se-source-stage-NEW
   python3 install/materialize-runtime.py --install --user YOURUSER --sources /tmp/v3se-source-stage-NEW --confirm FRESH_CB1_RUNTIME_SOURCES_ONLY
   ```

   The script verifies the host receipt and strict connection-only config, copies pinned Git sources into their final home paths, creates Klippy/Moonraker Python 3.11 environments **in their final paths** and invokes pip, which can access the network. It extracts only bounded, sanitized Mainsail ZIP members, preserving the already-installed `mainsail/config.json`, writes `.version` and links `printer_data/config/mainsail.cfg` to pinned mainsail-config. Do not move an already-created virtual environment to a different path. Any failed stage requires evidence review before retrying; reimage if uncertain.
8. **Firmware.** RUN AS normal user in the accepted runtime source tree (not packaging source): `bash install/build-firmware.sh --check /home/YOURUSER/klipper-port`, followed by `--build` **only on a clean checkout with no existing `.config`**. Build uses the exact accepted resolved MCU `.config` SHA256. **STOP for manual SD-card flashing** as described in `docs/V3SE_FLASH_SD.md`. Confirm the SD copy checksum, firmware version and matching MCU serial device after power cycle. The script never flashes. Be aware the build creates `.config` and artifacts only in the fresh source clone.
9. **Connection-only service activation.** RUN AS normal user: `bash install/install.sh --services-plan YOURUSER`. After a separate operator confirms the MCU was flashed, the by-id device is visible, Nginx can traverse `/home/YOURUSER`, and no existing services are running, RUN AS root only on new CB1:

   ```bash
   sudo python3 install/activate-services.py --activate --user YOURUSER --confirm FRESH_CB1_FLASHED_CONNECTION_ONLY
   ```

   The script validates receipts, preserves/restores the distro default Nginx symlink, tests Nginx configuration and starts only Klipper, Moonraker and Nginx. Udev rules are reloaded. On failure it attempts to disable newly started services and restore the default site. **A service start is not proof of firmware identity, physical calibration or print readiness.** Independently verify Klipper connects to the expected MCU and that the Mainsail HTTP/API paths work. Do not run G28, heating, Auto-Z or printing with the connection-only profile.
10. **Supervised target calibration remains a hard STOP.** There is no safe, physically proven sequence yet to obtain all nine printer-specific numbers starting from the MCU-only profile. Do not copy the accepted printer's PID, HX711, CR Touch or mesh state. `docs/V3SE_FIRST_BOOT_CALIBRATION_DESIGN.md` defines why temporary heater/sensor/motion stages require a separate physical proof. The full renderer refuses missing target measurements. This blocker prevents release claims.
11. **Full target config and acceptance, after the calibration protocol is physically validated.** Render with `install/render-printer-config.py --mode calibrated --measurements TARGET.json` using only actual target measurements and the required confirmation. Validate includes, full hardware identity, heater safeguards, mesh and stock display; then run all 17 steps in `docs/V3SE_ACCEPTANCE_CHECKLIST.md`. Record test results and actual hardware evidence. Service startup or 17/17 PASS on the older printer does not substitute for these tests.

## Release boundary

These installation phases have passed **offline synthetic fixtures**, including conflict, symlink, rollback, Git source, fake pip, ZIP traversal and simulated service failure paths. **Real apt, ARM64 Python package resolution, Nginx/systemd, SD flashing, supervised calibration, MCU recovery and the 17 physical tests on the fresh hardware remain untested.** The repository is a candidate, not a validated release. Keep `install/install.sh --apply` locked until the acceptance contract has actually been met.

## Final acceptance evidence and release decision

After the nine target measurements have been genuinely acquired, the menu Z-offset regression is fixed and revalidated, and all 17 target-hardware physical checks pass, use `docs/V3SE_RELEASE_EVIDENCE.md` and `install/verify-acceptance-evidence.py` to validate the completeness of the operator's record. The tool reports a **record complete, independent review still required** status and cannot substitute for real test logs, measurements or the physical hardware. The full `--apply` gate remains intentionally locked in this release candidate.
