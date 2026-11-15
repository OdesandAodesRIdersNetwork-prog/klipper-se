# Stage 7: Fresh-CB1 Debian package provisioning

**Status: offline fixture tests passed. No real CB1 apt run. Not a finished installer.**

The separate `install/provision-packages.py` phase uses the fixed 17-package `install/packages-bookworm.txt` manifest. It refuses a changed, missing, extra, duplicated, or reordered package, an unsupported Debian 12/Armbian ARM64/Python 3.11 host, a missing normal `/home/<user>` service account, stopped systemd, or any existing Klipper/Moonraker/Mainsail or V3 SE service path. Serial-by-id visibility and `dialout` membership are later prerequisites and may still be pending at this early stage.

## Read-only plan on a separately imaged, blank CB1

RUN AS the normal Linux account:

```bash
python3 install/provision-packages.py --plan --user YOUR_LINUX_USERNAME
```

The JSON report states the required package names, exact commands, missing packages, blockers, and manifest SHA256. It changes nothing.

## Explicit install phase, NOT yet authorized for the project acceptance run

RUN AS root **only on a separate brand-new CB1 after approval of the actual integration procedure**:

```bash
sudo python3 install/provision-packages.py --install \
  --user YOUR_LINUX_USERNAME --confirm FRESH_CB1_APT_PACKAGES_ONLY
```

This command is a genuine apt mutation, not a simulator. It executes `apt-get update` and `apt-get install --yes --no-install-recommends` with the 17 exact packages. It checks installed status afterward and reports resolved Debian versions. Debian repository package versions are not immutably pinned at this stage. It must never be run on the accepted CB1 or any existing Klipper host.

**APT rollback cannot be guaranteed.** A failed install can leave partially installed packages. Apt may start default distro services, including Nginx. Failures require inspection or reimaging the separate clean CB1 rather than assuming filesystem-style rollback.

## What the offline tests prove and do not prove

`python3 install/tests/test-provision-packages.py` uses synthetic host evidence and a fake command runner. It verifies root/confirmation refusal, fixed package identity, conflict detection, apt command ordering, post-install version reporting, and propagated apt failures. It does **not** install real packages, verify ARM64 binary compatibility, or start Moonraker/Klipper.

`install/install.sh --apply` stays disabled (exit 3). This package phase does not create services, alter `printer_data`, flash firmware, calibrate the target printer, or authorize print-ready operation. Real Bookworm ARM64 execution, supervised first-boot calibration, firmware flashing, recovery, and 17/17 fresh-install acceptance remain separate gates.
