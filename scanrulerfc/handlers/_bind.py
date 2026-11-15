# SPDX-License-Identifier: AGPL-3.0-only
# How a family's handlers are bound to a context: each family module has
# bind(ctx) -> {tool name: fn(args)} (closures over the context, as the
# tools always were) and HANDLERS = table(bind, NAMES), {name: fn(ctx, args)}.
# A context's closures are made once and kept on it, so a family's state
# between calls is the same whoever calls (Agent Link, or the add-on's own
# runner).
import functools

ATTR = "_scanrulerfc_bound"


def bound(ctx, bind):
    """bind(ctx), made once per context."""
    got = getattr(ctx, ATTR, None)
    if got is None:
        got = {}
        try:
            setattr(ctx, ATTR, got)
        except AttributeError:  # a context that takes no attributes: made each time
            pass
    if bind not in got:
        got[bind] = bind(ctx)
    return got[bind]


def _call(bind, name, ctx, args):
    return bound(ctx, bind)[name](args)


def table(bind, names):
    """{name: fn(ctx, args)} for the names bind(ctx) answers."""
    return {n: functools.partial(_call, bind, n) for n in names}
