# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reExpression.test.ts, reExpressionDepth.test.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The expression language of the number fields: what it reads, what it
# refuses and how it says so, and the two readings that do not evaluate -
# the names an expression uses, and a name rewritten. Then expressions and
# parameter tables deep enough to run out of stack, as a project file can
# hold them: an error of the expression, never a throw.
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scanrulerfc.reverse.expression import (  # noqa: E402
    ANGLE, LENGTH, UNITLESS, evaluate, evaluate_for, format_value, is_plain_number, plain_number, references, rename_in, valid_name,
)
from scanrulerfc.reverse.parameters import evaluate_parameters  # noqa: E402


def scope(vars_):
    return lambda name: vars_.get(name)


def none(_name):
    return None


def mm(v):
    return {"value": v, "dim": LENGTH}


def deg(v):
    return {"value": v, "dim": ANGLE}


def num(v):
    return {"value": v, "dim": UNITLESS}


def value(src, s=none):
    r = evaluate(src, s)
    if not r["ok"]:
        raise AssertionError(f"{src}: {r['error']}")
    return r["value"]


def error(src, s=none):
    r = evaluate(src, s)
    if r["ok"]:
        raise AssertionError(f"{src} evaluated to {r['value']}")
    return r["error"]


class Matches:
    def assertMatch(self, got, want):
        for k, v in want.items():
            self.assertIn(k, got)
            self.assertEqual(got[k], v, k)


class Arithmetic(unittest.TestCase):
    def test_order(self):
        self.assertEqual(value("2 + 3 * 4"), 14)
        self.assertEqual(value("(2 + 3) * 4"), 20)
        self.assertAlmostEqual(value("25.4 / 12"), 2.11667, 5)
        self.assertEqual(value("10 - 2 - 3"), 5)
        self.assertEqual(value("24 / 4 / 2"), 3)
        self.assertEqual(value("2 ^ 3 ^ 2"), 512)
        self.assertEqual(value(".5 + 1e1"), 10.5)

    def test_unary_minus(self):
        self.assertEqual(value("-2 ^ 2"), -4)
        self.assertEqual(value("(-2) ^ 2"), 4)
        self.assertEqual(value("2 ^ -1"), 0.5)
        self.assertEqual(value("-2 * -3"), 6)
        self.assertEqual(value("+4"), 4)
        self.assertEqual(value("--4"), 4)

    def test_functions_in_degrees(self):
        self.assertAlmostEqual(value("sin(30)"), 0.5, 2)
        self.assertAlmostEqual(value("cos(60 deg)"), 0.5, 2)
        self.assertAlmostEqual(value("tan(45)"), 1, 2)
        self.assertAlmostEqual(value("asin(0.5)"), 30, 2)
        self.assertAlmostEqual(value("acos(0.5)"), 60, 2)
        self.assertAlmostEqual(value("atan(1)"), 45, 2)
        self.assertAlmostEqual(value("atan2(1, 1)"), 45, 2)
        self.assertEqual(value("sqrt(16)"), 4)
        self.assertEqual(value("abs(-3)"), 3)
        self.assertEqual(value("min(3, 1, 2)"), 1)
        self.assertEqual(value("max(3, 1, 2)"), 3)
        self.assertEqual(value("floor(2.7)"), 2)
        self.assertEqual(value("ceil(2.2)"), 3)
        self.assertEqual(value("round(2.5)"), 3)
        self.assertEqual(value("pow(2, 10)"), 1024)
        self.assertAlmostEqual(value("2 * pi"), 6.2832, 4)
        self.assertAlmostEqual(value("e"), 2.7183, 4)

    def test_units(self):
        self.assertAlmostEqual(value("1 in"), 25.4, 2)
        self.assertAlmostEqual(value("1in"), 25.4, 2)
        self.assertEqual(value("2 cm"), 20)
        self.assertEqual(value("0.5 m"), 500)
        self.assertEqual(value("10 mm"), 10)
        self.assertAlmostEqual(value("pi rad"), 180, 2)
        self.assertEqual(value("30°"), 30)
        self.assertEqual(evaluate("1 in", none)["dim"], LENGTH)
        self.assertEqual(evaluate("1 rad", none)["dim"], ANGLE)

    def test_scope(self):
        s = scope({"width": mm(40), "count": num(4)})
        self.assertEqual(value("width / 2", s), 20)
        self.assertEqual(value("width + 10", s), 50)
        self.assertEqual(value("width / count", s), 10)
        self.assertEqual(value("threadlength+10", scope({"threadlength": mm(25)})), 35)


class Refusals(unittest.TestCase, Matches):
    def test_what_and_where(self):
        self.assertMatch(evaluate("", none), {"ok": False, "error": "nothing to read"})
        self.assertMatch(evaluate("2 +", none), {"ok": False, "at": [3, 3]})
        self.assertIn("where a number was expected", error("2 + * 3"))
        self.assertIn("not closed", error("(2 + 3"))
        self.assertIn("“)”", error("2 + 3)"))
        self.assertIn("where an operator was expected", error("2 3"))
        self.assertIn("“#”", error("2 # 3"))
        self.assertMatch(evaluate("width", none), {"ok": False, "error": "there is no parameter “width”", "at": [0, 5]})
        self.assertIn("no function “foo”", error("foo(2)"))
        self.assertIn("is a function", error("sin"))
        self.assertIn("takes one argument", error("sin(1, 2)"))
        self.assertEqual(error("1 / 0"), "divides by zero")
        self.assertIn("negative", error("sqrt(-1)"))
        self.assertIn("operator was expected", error("2,5"))

    def test_kinds_apart(self):
        s = scope({"width": mm(40), "height": mm(20), "turn": deg(30), "count": num(4)})
        self.assertEqual(error("width + turn", s), "a length and an angle cannot be added")
        self.assertEqual(error("width - count", s), "a length and a number cannot be subtracted")
        self.assertMatch(evaluate("width * height", s), {"ok": True, "dim": {"mm": 2, "deg": 0}})
        self.assertMatch(evaluate("width / height", s), {"ok": True, "dim": UNITLESS})
        self.assertMatch(evaluate("width * count", s), {"ok": True, "dim": LENGTH})
        self.assertMatch(evaluate("sin(turn) * width", s), {"ok": True, "dim": LENGTH})
        self.assertMatch(evaluate("atan(width / height)", s), {"ok": True, "dim": ANGLE})
        self.assertMatch(evaluate("sqrt(width * height)", s), {"ok": True, "dim": LENGTH})
        self.assertIn("no kind of quantity", error("sqrt(width)", s))
        self.assertEqual(error("sin(width)", s), "sin() takes an angle, not a length")
        self.assertEqual(error("asin(width)", s), "asin() takes a plain number, not a length")
        self.assertIn("cannot be raised", error("width ^ 0.5", s))
        self.assertMatch(evaluate("width ^ 2", s), {"ok": True, "dim": {"mm": 2, "deg": 0}})
        self.assertIn("a power must be a plain number", error("2 ^ width", s))
        self.assertIn("cannot be compared in min()", error("min(width, turn)", s))
        self.assertIn("atan2()", error("atan2(width, count)", s))
        self.assertMatch(evaluate("max(width, 10)", s), {"ok": True, "value": 40, "dim": LENGTH})

    def test_not_a_number(self):
        self.assertIn("does not come out", error("10 ^ 400"))


class EvaluateFor(unittest.TestCase, Matches):
    s = staticmethod(scope({"width": mm(40), "turn": deg(30), "count": num(4), "ratio": num(0.5)}))

    def test_bare_number_in_field_unit(self):
        s = self.s
        self.assertMatch(evaluate_for("10", "length", s), {"ok": True, "value": 10, "dim": LENGTH})
        self.assertMatch(evaluate_for("10", "angle", s), {"ok": True, "value": 10, "dim": ANGLE})
        self.assertMatch(evaluate_for("25.4/12", "length", s), {"ok": True, "dim": LENGTH})
        self.assertMatch(evaluate_for("2*3", "integer", s), {"ok": True, "value": 6})

    def test_field_kind(self):
        s = self.s
        self.assertMatch(evaluate_for("width / 2", "length", s), {"ok": True, "value": 20})
        self.assertMatch(evaluate_for("width + 10", "length", s), {"ok": True, "value": 50})
        self.assertMatch(evaluate_for("turn * 2", "angle", s), {"ok": True, "value": 60})
        self.assertMatch(evaluate_for("width", "angle", s), {"ok": False, "error": "comes out as a length; an angle is wanted here"})
        self.assertMatch(evaluate_for("count", "length", s), {"ok": False, "error": "comes out as a number; a length is wanted here — a number with a unit, “10 mm”, makes it one"})
        self.assertMatch(evaluate_for("count * 2 mm", "length", s), {"ok": True, "value": 8})
        self.assertMatch(evaluate_for("width * width", "length", s), {"ok": False, "error": "comes out as an area (mm²); a length is wanted here"})
        self.assertMatch(evaluate_for("width", "number", s), {"ok": False, "error": "comes out as a length; a number is wanted here"})
        self.assertMatch(evaluate_for("width / 10 mm", "integer", s), {"ok": True, "value": 4})
        self.assertMatch(evaluate_for("ratio * 2", "number", s), {"ok": True, "value": 1})

    def test_whole(self):
        s = self.s
        self.assertMatch(evaluate_for("7.3", "integer", s, whole=True), {"ok": False, "error": "comes out 7.3, not whole — round(), floor() or ceil() make it so"})
        self.assertMatch(evaluate_for("round(7.3)", "integer", s, whole=True), {"ok": True, "value": 7})
        self.assertMatch(evaluate_for("7.3", "integer", s), {"ok": True, "value": 7.3})
        self.assertMatch(evaluate_for("6.0000000001", "integer", s, whole=True), {"ok": True})


class Reading(unittest.TestCase):
    def test_references(self):
        self.assertEqual(references("width + height * width"), ["width", "height"])
        self.assertEqual(references("sin(turn) * 2 mm + pi"), ["turn"])
        self.assertEqual(references("25.4 / 12"), [])
        self.assertEqual(references("width +"), ["width"])
        self.assertEqual(references("width # height"), ["width", "height"])

    def test_rename(self):
        self.assertEqual(rename_in("thread + threadlength*2", "thread", "pitch"), "pitch + threadlength*2")
        self.assertEqual(rename_in("width/2 + width", "width", "w"), "w/2 + w")
        self.assertEqual(rename_in("sin(width)", "sin", "cos"), "sin(width)")
        self.assertEqual(rename_in("width +", "width", "w"), "w +")
        self.assertEqual(rename_in("a + b", "c", "d"), "a + b")

    def test_plain_number(self):
        self.assertTrue(is_plain_number("25"))
        self.assertTrue(is_plain_number(" 2.5 "))
        self.assertFalse(is_plain_number("25 mm"))
        self.assertFalse(is_plain_number("-25"))
        self.assertFalse(is_plain_number("25/2"))
        self.assertFalse(is_plain_number("width"))
        self.assertEqual(plain_number("12.5"), 12.5)
        self.assertIsNone(plain_number("12.5/2"))

    def test_valid_name(self):
        self.assertTrue(valid_name("width"))
        self.assertTrue(valid_name("_w2"))
        self.assertFalse(valid_name("2w"))
        self.assertFalse(valid_name("thread length"))
        self.assertFalse(valid_name("sin"))
        self.assertFalse(valid_name("mm"))
        self.assertFalse(valid_name("pi"))
        self.assertFalse(valid_name(""))
        self.assertFalse(valid_name("width\n"))

    def test_format_value(self):
        self.assertEqual(format_value(35, "length"), "35 mm")
        self.assertEqual(format_value(2.116666, "length"), "2.117 mm")
        self.assertEqual(format_value(30, "angle"), "30°")
        self.assertEqual(format_value(6.9, "integer"), "7")
        self.assertEqual(format_value(0.5, "number"), "0.5")


class Depth(unittest.TestCase):
    def test_deep_expression_refused_not_thrown(self):
        deep = "(" * 200_000 + "1" + ")" * 200_000
        self.assertFalse(evaluate(deep, none)["ok"])
        nested = "(" * 1000 + "1" + ")" * 1000
        r = evaluate(nested, none)
        self.assertEqual((r["ok"], r["error"]), (False, "nests too deeply"))
        r = evaluate("-" * 1000 + "1", none)
        self.assertEqual((r["ok"], r["error"]), (False, "nests too deeply"))

    def test_long_chain_of_parameters(self):
        n = 30_000
        chain = [{"id": i + 1, "name": f"p{i}", "kind": "number", "expression": "1" if i == 0 else f"p{i - 1} + 1"} for i in range(n)]
        chain.reverse()
        table = evaluate_parameters(chain)
        r = table["readings"][0]
        self.assertEqual((r["name"], r["value"], r["error"]), (f"p{n - 1}", n, None))

    def test_loop_still_said(self):
        table = evaluate_parameters([
            {"id": 1, "name": "a", "kind": "number", "expression": "b + 1"},
            {"id": 2, "name": "b", "kind": "number", "expression": "a + 1"},
            {"id": 3, "name": "c", "kind": "number", "expression": "2"},
        ])
        self.assertEqual([r["error"] for r in table["readings"]], ["goes round in a loop: a → b → a", "goes round in a loop: a → b → a", None])


if __name__ == "__main__":
    unittest.main()
