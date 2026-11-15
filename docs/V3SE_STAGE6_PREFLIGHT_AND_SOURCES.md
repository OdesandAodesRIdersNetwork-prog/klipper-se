# V3SE Stage 6: fresh CB1 preflight and pinned external source staging

**Status: tested offline; NOT an enabled install.** The accepted regular Klipper-SE runtime still comes from `ab759b0026ca69396446bf13b7a9767c59619297` on the existing `v3se-klipper-port` branch. The packaging branch does not change it. No live CB1 or stock printer has been used for Stage 6 acceptance.

## 1. Read-only CB1 readiness report

On a **new CB1**, as a normal Linux user (not `root`), run from the packaging branch repository:

```bash
bash install/install.sh --host-preflight YOUR_LINUX_USERNAME
```

The JSON report checks Debian 12/Armbian Bookworm, ARM64 architecture, Python 3.11, running systemd, the existing normal account `/home/<user>`, all 17 declared Debian packages, required host command availability, `dialout` group membership, by-id serial visibility, and existence of installation paths and services that must not be overwritten.

Its exit codes are `0` for prerequisite evidence present, `4` when prerequisites remain to be installed or a serial link is not yet present, `2` for a wrong OS/user or an existing installation conflict, and `3` for malformed input/probe errors. **Even exit 0 is not permission to run `--apply`:** the report always sets `safe_to_install: false`. A blank CB1 will often need package, group and firmware steps before all checks pass. Do not run this fresh-install preflight against the already accepted production CB1 as evidence that its files should be replaced.

A nonzero result may be normal while setting up a new image. It is deliberately non-mutating and does not install apt packages, create users, enable udev or flash firmware.

## 2. Verify fixed external release identities without network access

```bash
bash install/install.sh --sources-plan
```

This confirms the accepted repository/commit pairs and Mainsail v2.19.0 release ZIP checksum against an independently review-locked identity list. It does not fetch anything or change system files. A modified `versions.env` fails closed instead of silently upgrading production dependencies.

## 3. Stage pinned external sources in a fresh scratch directory

On a machine with internet access and normal-user permissions:

```bash
python3 install/stage-dependencies.py --fetch \
  --output /tmp/v3se-pinned-sources-new
python3 install/stage-dependencies.py --verify \
  --output /tmp/v3se-pinned-sources-new
```

The `--fetch` command **does perform network requests and creates files under the supplied scratch directory only**. It clones the specified Klipper-SE runtime branch, Moonraker and mainsail-config; then checks out each exact pinned SHA and verifies clean source checkouts and expected remote origins. It separately downloads the Mainsail v2.19.0 ZIP with a bounded download and verifies SHA256 **before** it can become a staged release. The ZIP is left unextracted for later reviewed installation. A failed clone, wrong commit, wrong ZIP hash, or interrupted step removes the incomplete scratch stage. Existing destinations and system/printer-home paths are refused. No source code is executed, no Python environments are created, and no services are installed by this stage.

The `--verify` command rereads the staging metadata, Git commit/remote identity and ZIP hash without changing the stage. This step checks source **identity**, not whether the dependencies will build on a blank CB1 or whether the software will start safely.

## 4. Offline fixture and packaging tests

```bash
python3 install/tests/test-preflight-cb1.py
python3 install/tests/test-stage-dependencies.py
bash install/install.sh --check
```

The source-staging test uses temporary **local git repositories** and mock ZIP bytes. It does not download real external dependencies. It tests exact SHA pinning, modified-archive detection, staging conflicts, protected paths and rollback. The CB1 readiness test uses synthetic input and does not probe the real OS. The full `--check` command exits `4` after passing its offline tests by design: actual installation remains blocked.

## Release blockers not closed by Stage 6

The first real blank-CB1 software acquisition, actual packages and Python environments, safe installation/ownership of services, SD-card firmware flashing, calibrated intermediate config pathway, supervised calibration and target mesh, and all 17 physical acceptance tests remain outstanding. The known stock-display Z-offset menu repair is still a separate later change requiring physical revalidation. Do not reuse any values or state from the accepted printer to bypass these gates.
