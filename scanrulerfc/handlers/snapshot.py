# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: plugins/snapshot/app/shotCommands.ts.
#
# The snapshot tools as a family: the agent reads the shots the person took
# (scanrulerfc/snapshot/handlers.py). No tool takes one.
import functools

from ..snapshot import handlers as H
from . import _bind


def bind(session):
    """{tool name: fn(args)} for one session."""
    return {n: functools.partial(H.HANDLERS[n], session) for n in NAMES}


NAMES = ("scan_snapshot_list", "scan_snapshot_latest", "scan_snapshot_wait")
HANDLERS = _bind.table(bind, NAMES)
