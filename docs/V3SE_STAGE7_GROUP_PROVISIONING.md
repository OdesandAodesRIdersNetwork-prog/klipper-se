# Stage 7: Fresh-CB1 service group setup

**Status: offline mocked tests passed. No real Linux group database was changed. Not a finished installer.**

The separate `install/provision-groups.py` handles serial-device access through `dialout` and the accepted Moonraker service's `moonraker-admin` group. It refuses an unsupported OS, an existing Klipper/Moonraker/Mainsail installation, a missing normal service user, stopped systemd, incomplete 17-package bootstrap, a missing distro `dialout` group, or a `moonraker-admin` group with other existing users.

## Read-only plan

RUN AS a normal Linux user on a separately imaged **blank CB1**, not the accepted printer:

```bash
python3 install/provision-groups.py --plan --user YOUR_LINUX_USERNAME
```

This prints the planned `groupadd` and `usermod` actions. It does not modify accounts or run services.

## Explicit root action, not yet validated on a real CB1

RUN AS root **only after approving the fresh-CB1 integration procedure**:

```bash
sudo python3 install/provision-groups.py --configure \
  --user YOUR_LINUX_USERNAME --confirm FRESH_CB1_GROUPS_ONLY
```

This repeats fresh-host preflight, creates `moonraker-admin` as a system group if necessary, then adds the existing service user to only its missing `dialout`/`moonraker-admin` groups. It verifies memberships afterwards and does not create the user. A group membership change may require a new login/session.

**Partial account database mutations are not automatically rolled back.** For example, if `groupadd` succeeds and `usermod` fails, stop and inspect or reimage the separate CB1. Do not try automatic group deletion.

The offline fixture test `python3 install/tests/test-provision-groups.py` uses synthetic host/group data and fake commands. It tests host conflict refusal, root/confirmation, simulated success, idempotence and partial-failure reporting. Actual Bookworm group behaviour is untested, as are service deployment, source/environment installs, firmware flashing, target-specific calibration and fresh-printer 17/17 physical acceptance.

The accepted production source is unchanged; main `install/install.sh --apply` remains disabled with exit 3.
