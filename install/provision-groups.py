#!/usr/bin/env python3
"""Guarded fresh-CB1 serial and Moonraker group membership bootstrap.

--plan is read-only. --configure is a real root-only account database
mutation: it MUST be run ONLY on a separate blank CB1, NEVER the accepted
reference printer. This does not enable or install Klipper services.
"""
import argparse
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('v3se_group_preflight', HERE / 'preflight-cb1.py')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)
CONFIRM = 'FRESH_CB1_GROUPS_ONLY'
MOONRAKER_GROUP = 'moonraker-admin'
SERIAL_GROUP = 'dialout'


def refuse(message):
    raise ValueError(message)


def group_snapshot(user):
    """Read only /etc identity and current group database, no process changes."""
    entry = pwd.getpwnam(user)
    current_ids = set(os.getgrouplist(user, entry.pw_gid))
    memberships = {}
    for group in (SERIAL_GROUP, MOONRAKER_GROUP):
        try:
            g = grp.getgrnam(group)
        except KeyError:
            memberships[group] = {'present': False, 'member': False, 'members': []}
        else:
            memberships[group] = {'present': True, 'member': g.gr_gid in current_ids,
                                  'members': sorted(g.gr_mem)}
    return memberships


def evaluate(snapshot, group_info):
    report = PREFLIGHT.assess(snapshot)
    blockers = list(report['hard_blockers'])
    if not snapshot['systemd_active']:
        blockers.append('systemd must be running before group setup')
    if snapshot['missing_packages']:
        blockers.append('finish 17-package bootstrap before group setup')
    if not group_info[SERIAL_GROUP]['present']:
        blockers.append('stock serial group dialout does not exist')
    other_members = set(group_info[MOONRAKER_GROUP]['members']) - {snapshot['user']}
    if other_members:
        blockers.append('existing moonraker-admin group is used by another account')
    cmds = []
    if not group_info[MOONRAKER_GROUP]['present']:
        cmds.append(['groupadd', '--system', MOONRAKER_GROUP])
    missing = [name for name in (SERIAL_GROUP, MOONRAKER_GROUP)
               if not group_info[name]['member']]
    if missing:
        cmds.append(['usermod', '--append', '--groups', ','.join(missing), snapshot['user']])
    return {'schema': 1, 'mode': 'FRESH_CB1_GROUPS_ONLY',
            'user': snapshot['user'], 'user_home': snapshot['user_home'],
            'host_report': report['status'], 'hard_blockers': blockers,
            'group_status': group_info, 'would_run': cmds,
            'would_change_accounts': bool(cmds),
            'installer_apply_enabled': False,
            'rollback': 'NO AUTOMATIC ACCOUNT/GROUP ROLLBACK: inspect any partial failure',
            'warning': 'Changes to service-user groups may require log out / log in; no services are started'}


def plan(user, *, snapshot_func=None, groups_func=None):
    if snapshot_func is None:
        snapshot_func = PREFLIGHT.snapshot
    if groups_func is None:
        groups_func = group_snapshot
    snapshot = snapshot_func(user)
    result = evaluate(snapshot, groups_func(user))
    return result, (2 if result['hard_blockers'] else 0)


def configure(user, *, confirm, euid=None, snapshot_func=None,
              groups_func=None, runner=None):
    if confirm != CONFIRM:
        refuse('explicit fresh-CB1 group confirmation required')
    if euid is None:
        euid = os.geteuid()
    if euid != 0:
        refuse('group configuration requires root on a fresh CB1')
    before, status = plan(user, snapshot_func=snapshot_func, groups_func=groups_func)
    if status:
        refuse('fresh-host admission blocked: ' + '; '.join(before['hard_blockers']))
    if runner is None:
        runner = subprocess.run
    for cmd in before['would_run']:
        runner(cmd, check=True, timeout=30)
    after, status = plan(user, snapshot_func=snapshot_func, groups_func=groups_func)
    if status:
        refuse('host became unsupported after group commands')
    if (not after['group_status'][SERIAL_GROUP]['member'] or
            not after['group_status'][MOONRAKER_GROUP]['member']):
        refuse('group commands completed but required memberships not confirmed')
    if after['would_run']:
        refuse('group setup still reports pending actions after command execution')
    after['mode'] = 'FRESH_CB1_GROUPS_CONFIGURED_NOT_PRINTER_ACCEPTED'
    return after


def main():
    p = argparse.ArgumentParser(description=__doc__)
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument('--plan', action='store_true')
    m.add_argument('--configure', action='store_true')
    p.add_argument('--user', required=True)
    p.add_argument('--confirm', default='')
    a = p.parse_args()
    try:
        if a.plan:
            if a.confirm:
                refuse('--plan does not accept --confirm')
            report, code = plan(a.user)
        else:
            report = configure(a.user, confirm=a.confirm)
            code = 0
        print(json.dumps(report, indent=2, sort_keys=True))
        return code
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as exc:
        print('V3SE GROUP PHASE REFUSED/FAILED: ' + str(exc), file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
