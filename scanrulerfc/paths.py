# SPDX-License-Identifier: AGPL-3.0-only
# A file path a tool is given, as Agent Link's export_file takes one: ~
# expanded, and a relative name in the session's output folder (Agent
# Link's session.out_dir, its outDir, ~/AgentLink by default; the add-on's
# own runner's beside the saved document, else ~/ScanRuler), else the
# working folder. "rev_box.step" written by export_file is then found by
# reverse_import_step. Agent Link's guard checks a path the same way, so
# what it allowed is what the tool opens.
import functools
import os

# The inputs that hold a file path (every one in data/tools.json), or a list of them.
KEYS = ("path", "export", "import", "files")


def out_dir_of(ctx):
    try:
        d = getattr(ctx, "out_dir", None)
    except Exception:  # noqa: BLE001 — a folder that cannot be made
        d = None
    return d if isinstance(d, str) and d else None


def resolve(ctx, p):
    """p with ~ expanded, joined to the session's output folder when relative."""
    if not isinstance(p, str) or not p.strip():
        return p
    q = os.path.expanduser(p.strip())
    if os.path.isabs(q):
        return q
    return os.path.join(out_dir_of(ctx) or os.getcwd(), q)


def resolve_args(ctx, args):
    """args with each file path input resolved (a new dict; args as given
    when there is none)."""
    if not isinstance(args, dict) or not any(k in args for k in KEYS):
        return args
    out = dict(args)
    for k in KEYS:
        v = out.get(k)
        if isinstance(v, str):
            out[k] = resolve(ctx, v)
        elif isinstance(v, list):
            out[k] = [resolve(ctx, x) if isinstance(x, str) else x for x in v]
    return out


def resolving(fn, ctx):
    """fn(args) with its file paths resolved against ctx's folder."""

    @functools.wraps(fn)
    def run(args=None, *more):
        return fn(resolve_args(ctx, args), *more)

    return run
