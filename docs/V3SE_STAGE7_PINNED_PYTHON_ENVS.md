# Stage 7: pinned Klippy and Moonraker Python environment staging

Status: **scratch environment provisioning implemented; real CB1 installation NOT enabled or validated.**
Accepted production source remains `ab759b0026ca69396446bf13b7a9767c59619297`. Keep the separate packaging branch isolated. Never run these commands against the accepted CB1 as an installation procedure.

## Purpose

After Stage 6 `stage-dependencies.py` has fetched and verified the exact locked Git revisions and the Mainsail archive, `prepare-venvs.py` can create **real, separate** Klippy and Moonraker Python environments under a brand-new scratch directory. It reads the accepted Klipper `scripts/klippy-requirements.txt` and pinned Moonraker `scripts/moonraker-requirements.txt`, not the development CB1's `pip freeze` or venvs. Both environments are fresh. The Moonraker pip step runs from its `scripts/` directory so relative `--find-links=python_wheels` resolves as intended.

## Commands

RUN AS a normal non-root Linux user on a disposable build host or separate fresh CB1 (not the accepted CB1):

```bash
python3 install/stage-dependencies.py --verify --output /tmp/v3se-sources-NEW
python3 install/prepare-venvs.py --plan --sources /tmp/v3se-sources-NEW \
  --output /tmp/v3se-envs-NEW
python3 install/prepare-venvs.py --build --sources /tmp/v3se-sources-NEW \
  --output /tmp/v3se-envs-NEW
```

`--plan` reads pinned source metadata and requirements and produces JSON. It does not write files. `--build` invokes `virtualenv --no-download` and **pip install, which can access the network and execute dependency build code**. It requires Python 3.11, installed `virtualenv`, non-root execution and an unused, direct child of `/tmp` or `/mnt/data` named `v3se-*`. Both environments and pip/virtualenv caches are placed in that one scratch directory; failed operations remove the created tree when its identity still matches. It rejects existing destinations, symlinks in requirements, changed Git revisions and mismatched Mainsail digests. On success, `VENV_STAGE.json` records exact source commits and requirements hashes. Nothing is copied to `/home`, `/etc`, systemd, the MCU or the printer.

## Verification status and outstanding gates

The offline fixture test `python3 install/tests/test-prepare-venvs.py` passes with fake `virtualenv`/`pip` calls and a simulated failure on the fourth subprocess. That is **not proof that actual pip dependencies resolve on Bookworm ARM64**. Before a real fresh-CB1 installation, test a real pinned network fetch and a real scratch venv build on that separate machine; verify imports and package versions; design safe non-scratch deployment, account and group provisioning, service transactions and rollback; then do manual SD firmware flashing, supervised calibration, MCU recovery and 17/17 physical acceptance. `install.sh --apply` remains disabled.
