# SPDX-License-Identifier: AGPL-3.0-only
# No tool of this add-on has the name of one of Agent Link's own: Agent
# Link keeps its core tool and leaves the add-on's out ("an extension's
# snapshot_list (snapshot) is left out — app has that name"), so the agent
# would never reach it. Read from Agent Link's source wherever it is on the
# path, and from its registered tools where FreeCAD runs too.
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
if os.environ.get("FREECAD_LIB"):
    sys.path.append(os.environ["FREECAD_LIB"])
try:
    import agentlink

    AL = os.path.dirname(os.path.abspath(agentlink.__file__))
except ImportError:
    AL = None
try:
    import FreeCAD  # noqa: F401
    import Part  # noqa: F401

    HAVE_FC = True
except ImportError:
    HAVE_FC = False


def ours():
    with open(os.path.join(ROOT, "scanrulerfc", "data", "tools.json"), encoding="utf-8") as f:
        return {k: v["group"] for k, v in json.load(f)["entries"].items()}


def core_in_source():
    """The names of the tools Agent Link itself defines (Tool("name", …)
    in agentlink/tools.py and agentlink/families/)."""
    files = [os.path.join(AL, "tools.py")] + [os.path.join(AL, "families", n) for n in os.listdir(os.path.join(AL, "families")) if n.endswith(".py")]
    out = set()
    for p in files:
        with open(p, encoding="utf-8") as f:
            out.update(re.findall(r'\bTool\(\s*"([a-z][a-z0-9_]*)"', f.read()))
    # A newer Agent Link keeps most of its tools as data (agentlink/data/tools.json).
    data = os.path.join(AL, "data", "tools.json")
    if os.path.isfile(data):
        with open(data, encoding="utf-8") as f:
            out.update(json.load(f).get("entries", {}))
    return out


@unittest.skipUnless(AL, "Agent Link is not importable here")
class NoClash(unittest.TestCase):
    def test_no_name_of_agent_links_core(self):
        core = core_in_source()
        self.assertIn("snapshot_latest", core)  # what this test is for
        self.assertEqual(sorted(set(ours()) & core), [])

    @unittest.skipUnless(HAVE_FC, "needs FreeCAD")
    def test_every_tool_registered_as_ours(self):
        from agentlink.tools import Session, build_server

        server = build_server(Session(out_dir=tempfile.mkdtemp()), lean=False)
        for name, group in ours().items():
            with self.subTest(name):
                self.assertIn(name, server.tools)
                self.assertEqual(server.tools[name].group, group)


if __name__ == "__main__":
    unittest.main()
