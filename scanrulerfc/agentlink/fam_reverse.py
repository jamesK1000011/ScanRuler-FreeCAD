# SPDX-License-Identifier: AGPL-3.0-only
# Agent Link's reverse tools: declared in data/tools.json, answered by
# reverse/handlers.py (through handlers/reverse.py). Not LEAN: the group is
# deferred, so a session that never asks for it lists none of its tools.
# Loaded by Agent Link only (through agentlink_families).
from . import _bridge
from ..handlers import reverse as H
from ..reverse.handlers import GROUP, INFO  # noqa: F401 — the family's name and line


def tools(session):
    return _bridge.tools(GROUP, H, session)
