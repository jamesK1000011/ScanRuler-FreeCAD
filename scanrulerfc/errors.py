# SPDX-License-Identifier: AGPL-3.0-only
"""ScanRuler for FreeCAD's refusals: a code (invalid_input, not_found,
invalid_state, unavailable, failed) and a message that says what to do
next. The same attributes as Agent Link's ToolError; its family layer
(agentlink_families) turns one into the other where a tool answers Agent
Link, so the agent reads the same refusal either way."""


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# What a handler catches as a refusal: its own, and the host's when it has
# one (Agent Link's session.body refuses with Agent Link's ToolError). The
# family layer adds Agent Link's; read it as errors.REFUSED at the except,
# so the host's is seen.
REFUSED = (ToolError,)

