# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/core/expression.ts
# SPDX-License-Identifier: AGPL-3.0-only
#
# The arithmetic a number field takes: `25.4/12`, `threadlength + 10`,
# `sin(30) * r`. A small language of its own - numbers with an optional
# unit, the parameters by name, the four operations and a power, a few
# functions - parsed and evaluated here, and kind-checked as it goes: a
# length and an angle cannot be added, a length times a length is an area
# and no field wants one. A bare number has no kind of its own until it
# meets something that has one, or lands in a field that has.
#
# Every reading of an expression goes through the one tokenizer below, so a
# parameter renamed is renamed everywhere the same way.
#
# A value is {"value": float, "dim": dim}; a dim is {"mm": n, "deg": n} or
# the string "free". An evaluation is {"ok": True, "value", "dim"} or
# {"ok": False, "error", "at": [start, end]}, as the original's.

import math
import re

from ._js import fixed_number, js_round, num_str

UNITLESS = {"mm": 0, "deg": 0}
LENGTH = {"mm": 1, "deg": 0}
ANGLE = {"mm": 0, "deg": 1}
FREE = "free"

PARAMETER_KINDS = ("length", "angle", "integer", "number")


def dim_of_kind(kind):
    """The kind a field of this kind wants."""
    return LENGTH if kind == "length" else ANGLE if kind == "angle" else UNITLESS


UNITS = {
    "mm": (1.0, LENGTH),
    "cm": (10.0, LENGTH),
    "m": (1000.0, LENGTH),
    "in": (25.4, LENGTH),
    "deg": (1.0, ANGLE),
    "rad": (180 / math.pi, ANGLE),
}

CONSTANTS = {"pi": math.pi, "e": math.e}

FUNCTIONS = ("sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sqrt", "abs", "min", "max", "floor", "ceil", "round", "pow")

RESERVED_NAMES = frozenset(list(UNITS) + list(CONSTANTS) + list(FUNCTIONS))

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WHOLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_NUMBER = re.compile(r"([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")
_ASCII_DIGITS = re.compile(r"[0-9]")


def valid_name(name):
    """Whether a name may be a parameter's: a letter or an underscore, then
    letters, digits and underscores - and not a word the language keeps."""
    return bool(_WHOLE_NAME.match(name)) and name not in RESERVED_NAMES


class ExpressionError(Exception):
    def __init__(self, message, at):
        super().__init__(message)
        self.message = message
        self.at = [at[0], at[1]]


# ---- tokens ------------------------------------------------------------------------
# A token is a tuple: ("number", value, at) / ("name", text, at) / ("op", text, at) / ("end", None, at)


def tokenize(src):
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\n\r":
            i += 1
            continue
        num = _NUMBER.match(src, i)
        if num and num.group(0):
            out.append(("number", float(num.group(0)), [i, i + len(num.group(0))]))
            i += len(num.group(0))
            continue
        name = _NAME.match(src, i)
        if name and name.group(0):
            out.append(("name", name.group(0), [i, i + len(name.group(0))]))
            i += len(name.group(0))
            continue
        if c == "°":
            out.append(("name", "deg", [i, i + 1]))
            i += 1
            continue
        if c in "+-*/^(),":
            out.append(("op", c, [i, i + 1]))
            i += 1
            continue
        if c in "×·":
            out.append(("op", "*", [i, i + 1]))
            i += 1
            continue
        if c in "÷:":
            out.append(("op", "/", [i, i + 1]))
            i += 1
            continue
        if c == "−":
            out.append(("op", "-", [i, i + 1]))
            i += 1
            continue
        raise ExpressionError("a comma separates a function’s arguments; the decimal point is a dot" if c == "," else f"“{c}” is not part of an expression", [i, i + 1])
    out.append(("end", None, [n, n]))
    return out


# ---- the tree ------------------------------------------------------------------------
# Nodes are dicts as the original's: number / name / neg / binary / call.

BINARY_POWER = {"+": 10, "-": 10, "*": 20, "/": 20, "^": 30}
NEGATE_POWER = 25
MAX_DEPTH = 200
MAX_LENGTH = 4000


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    def parse(self):
        if self.tokens[0][0] == "end":
            raise ExpressionError("nothing to read", [0, 0])
        node = self.expression(0)
        t = self.peek()
        if t[0] != "end":
            raise ExpressionError("a “)” with no “(” before it" if t[0] == "op" and t[1] == ")" else f"“{self.text(t)}” where an operator was expected", t[2])
        return node

    def peek(self):
        return self.tokens[self.i]

    def next(self):
        t = self.tokens[self.i]
        self.i += 1
        return t

    @staticmethod
    def text(t):
        return num_str(t[1]) if t[0] == "number" else t[1] if t[0] in ("name", "op") else "the end"

    def expression(self, min_power):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExpressionError("nests too deeply", self.peek()[2])
        try:
            return self.operators(min_power)
        finally:
            self.depth -= 1

    def operators(self, min_power):
        left = self.prefix()
        while True:
            t = self.peek()
            if t[0] != "op" or t[1] in ("(", ")", ","):
                break
            power = BINARY_POWER[t[1]]
            if power < min_power:
                break
            self.next()
            right = self.expression(power if t[1] == "^" else power + 1)
            left = {"kind": "binary", "op": t[1], "a": left, "b": right, "at": [left["at"][0], right["at"][1]]}
        return left

    def prefix(self):
        t = self.next()
        kind, val, at = t
        if kind == "number":
            unit = self.peek()
            if unit[0] == "name" and unit[1] in UNITS:
                self.next()
                return {"kind": "number", "value": val, "unit": unit[1], "at": [at[0], unit[2][1]]}
            return {"kind": "number", "value": val, "unit": None, "at": at}
        if kind == "name":
            open_ = self.peek()
            if open_[0] == "op" and open_[1] == "(":
                if val not in FUNCTIONS:
                    raise ExpressionError(f"there is no function “{val}”", at)
                self.next()
                args = []
                if not (self.peek()[0] == "op" and self.peek()[1] == ")"):
                    while True:
                        args.append(self.expression(0))
                        sep = self.peek()
                        if sep[0] == "op" and sep[1] == ",":
                            self.next()
                            continue
                        break
                close = self.next()
                if not (close[0] == "op" and close[1] == ")"):
                    raise ExpressionError(f"“{val}(” is not closed", [at[0], close[2][1]])
                return {"kind": "call", "name": val, "args": args, "at": [at[0], close[2][1]]}
            if val in CONSTANTS and open_[0] == "name" and open_[1] in UNITS:
                self.next()
                return {"kind": "number", "value": CONSTANTS[val], "unit": open_[1], "at": [at[0], open_[2][1]]}
            return {"kind": "name", "name": val, "at": at}
        if kind == "op" and val == "(":
            inner = self.expression(0)
            close = self.next()
            if not (close[0] == "op" and close[1] == ")"):
                raise ExpressionError("a “(” is not closed", [at[0], close[2][1]])
            return inner
        if kind == "op" and val == "-":
            arg = self.expression(NEGATE_POWER)
            return {"kind": "neg", "arg": arg, "at": [at[0], arg["at"][1]]}
        if kind == "op" and val == "+":
            return self.expression(NEGATE_POWER)
        if kind == "end":
            raise ExpressionError("the expression ends where a number was expected", at)
        raise ExpressionError(f"“{self.text(t)}” where a number was expected", at)


# ---- kinds ----------------------------------------------------------------------------


def dim_equal(a, b):
    if a == FREE or b == FREE:
        return a == b
    return a["mm"] == b["mm"] and a["deg"] == b["deg"]


_SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹"


def describe_dim(d):
    """A kind in words: "a length", "an angle", "a number", "an area (mm²)"."""
    if d == FREE:
        return "a number"
    if d["mm"] == 0 and d["deg"] == 0:
        return "a number"
    if d["mm"] == 1 and d["deg"] == 0:
        return "a length"
    if d["mm"] == 0 and d["deg"] == 1:
        return "an angle"
    if d["mm"] == 2 and d["deg"] == 0:
        return "an area (mm²)"
    if d["mm"] == 3 and d["deg"] == 0:
        return "a volume (mm³)"

    def sup(n):
        if n == 1:
            return ""
        return _ASCII_DIGITS.sub(lambda m: _SUP[int(m.group(0))], num_str(n).replace("-", "⁻"))

    parts = []
    if d["mm"] != 0:
        parts.append(f"mm{sup(d['mm'])}")
    if d["deg"] != 0:
        parts.append(f"°{sup(d['deg'])}")
    return f"a {'·'.join(parts)} quantity"


def describe_kind(kind):
    return "a length" if kind == "length" else "an angle" if kind == "angle" else "a whole number" if kind == "integer" else "a number"


def _combine(a, b, f):
    if a == FREE:
        return FREE if b == FREE else {"mm": f(0, b["mm"]), "deg": f(0, b["deg"])}
    if b == FREE:
        return {"mm": f(a["mm"], 0), "deg": f(a["deg"], 0)}
    return {"mm": f(a["mm"], b["mm"]), "deg": f(a["deg"], b["deg"])}


def _near_int(x):
    return abs(x - js_round(x)) < 1e-9


def _power(base, exp, at):
    if base == FREE:
        return FREE
    mm = base["mm"] * exp
    deg = base["deg"] * exp
    if not _near_int(mm) or not _near_int(deg):
        raise ExpressionError(f"{describe_dim(base)} cannot be raised to the power {num_str(exp)}", at)
    return {"mm": int(js_round(mm)), "deg": int(js_round(deg))}


def _same(a, b, what, at):
    if a["dim"] == FREE:
        return b["dim"]
    if b["dim"] == FREE:
        return a["dim"]
    if dim_equal(a["dim"], b["dim"]):
        return a["dim"]
    raise ExpressionError(f"{describe_dim(a['dim'])} and {describe_dim(b['dim'])} cannot {what}", at)


# ---- evaluation ---------------------------------------------------------------------------


def _pow(a, b):
    """Math.pow: Infinity rather than an overflow, NaN rather than a complex number."""
    try:
        r = math.pow(a, b)
    except OverflowError:
        return math.inf
    except (ValueError, ZeroDivisionError):
        if a == 0 and b < 0:
            return math.inf
        return math.nan
    return r


def _evaluate_node(n, scope):
    k = n["kind"]
    if k == "number":
        if n["unit"] is None:
            return {"value": n["value"], "dim": FREE}
        v, d = UNITS[n["unit"]]
        return {"value": n["value"] * v, "dim": d}
    if k == "name":
        name = n["name"]
        if name in CONSTANTS:
            return {"value": CONSTANTS[name], "dim": FREE}
        if name in UNITS:
            v, d = UNITS[name]
            return {"value": v, "dim": d}
        v = scope(name)
        if not v:
            raise ExpressionError(f"“{name}” is a function — it takes its argument in parentheses" if name in FUNCTIONS else f"there is no parameter “{name}”", n["at"])
        if "dim" not in v:
            raise ExpressionError(v["error"], n["at"])
        return v
    if k == "neg":
        v = _evaluate_node(n["arg"], scope)
        return {"value": -v["value"], "dim": v["dim"]}
    if k == "binary":
        a = _evaluate_node(n["a"], scope)
        b = _evaluate_node(n["b"], scope)
        op = n["op"]
        if op == "+":
            return {"value": a["value"] + b["value"], "dim": _same(a, b, "be added", n["at"])}
        if op == "-":
            return {"value": a["value"] - b["value"], "dim": _same(a, b, "be subtracted", n["at"])}
        if op == "*":
            return {"value": a["value"] * b["value"], "dim": _combine(a["dim"], b["dim"], lambda x, y: x + y)}
        if op == "/":
            if b["value"] == 0:
                raise ExpressionError("divides by zero", n["at"])
            return {"value": a["value"] / b["value"], "dim": _combine(a["dim"], b["dim"], lambda x, y: x - y)}
        if op == "^":
            if b["dim"] != FREE and not dim_equal(b["dim"], UNITLESS):
                raise ExpressionError(f"a power must be a plain number, not {describe_dim(b['dim'])}", n["b"]["at"])
            return {"value": _pow(a["value"], b["value"]), "dim": _power(a["dim"], b["value"], n["at"])}
    if k == "call":
        return _call(n, scope)
    raise ExpressionError("cannot be read", n["at"])


RAD = math.pi / 180


def _safe(f, x):
    try:
        return f(x)
    except (ValueError, OverflowError):
        return math.nan


def _call(n, scope):
    args = [_evaluate_node(a, scope) for a in n["args"]]
    name = n["name"]

    def want(count):
        if len(args) != count:
            raise ExpressionError(f"{name}() takes {'one argument' if count == 1 else f'{count} arguments'}", n["at"])

    def angle_in(v, at):
        if v["dim"] != FREE and not dim_equal(v["dim"], ANGLE) and not dim_equal(v["dim"], UNITLESS):
            raise ExpressionError(f"{name}() takes an angle, not {describe_dim(v['dim'])}", at)
        return v["value"] * RAD

    def plain(v, at):
        if v["dim"] != FREE and not dim_equal(v["dim"], UNITLESS):
            raise ExpressionError(f"{name}() takes a plain number, not {describe_dim(v['dim'])}", at)
        return v["value"]

    if name in ("sin", "cos", "tan"):
        want(1)
        f = {"sin": math.sin, "cos": math.cos, "tan": math.tan}[name]
        return {"value": _safe(f, angle_in(args[0], n["args"][0]["at"])), "dim": UNITLESS}
    if name in ("asin", "acos", "atan"):
        want(1)
        f = {"asin": math.asin, "acos": math.acos, "atan": math.atan}[name]
        return {"value": _safe(f, plain(args[0], n["args"][0]["at"])) / RAD, "dim": ANGLE}
    if name == "atan2":
        want(2)
        _same(args[0], args[1], "be compared in atan2()", n["at"])
        return {"value": math.atan2(args[0]["value"], args[1]["value"]) / RAD, "dim": ANGLE}
    if name == "sqrt":
        want(1)
        v = args[0]
        if v["value"] < 0:
            raise ExpressionError("sqrt() of a negative number", n["at"])
        if v["dim"] != FREE and (math.fmod(v["dim"]["mm"], 2) != 0 or math.fmod(v["dim"]["deg"], 2) != 0):
            raise ExpressionError(f"sqrt() of {describe_dim(v['dim'])} is no kind of quantity", n["at"])
        return {"value": math.sqrt(v["value"]), "dim": FREE if v["dim"] == FREE else {"mm": v["dim"]["mm"] // 2, "deg": v["dim"]["deg"] // 2}}
    if name in ("abs", "floor", "ceil", "round"):
        want(1)
        x = args[0]["value"]
        if name == "abs":
            r = abs(x)
        elif not math.isfinite(x):
            r = x
        elif name == "floor":
            r = float(math.floor(x))
        elif name == "ceil":
            r = float(math.ceil(x))
        else:
            r = js_round(x)
        return {"value": r, "dim": args[0]["dim"]}
    if name in ("min", "max"):
        if len(args) == 0:
            raise ExpressionError(f"{name}() takes at least one argument", n["at"])
        dim = args[0]["dim"]
        value = args[0]["value"]
        for a in args[1:]:
            dim = _same({"value": value, "dim": dim}, a, f"be compared in {name}()", n["at"])
            if math.isnan(value) or math.isnan(a["value"]):
                value = math.nan
            else:
                value = min(value, a["value"]) if name == "min" else max(value, a["value"])
        return {"value": value, "dim": dim}
    if name == "pow":
        want(2)
        if args[1]["dim"] != FREE and not dim_equal(args[1]["dim"], UNITLESS):
            raise ExpressionError(f"a power must be a plain number, not {describe_dim(args[1]['dim'])}", n["args"][1]["at"])
        return {"value": _pow(args[0]["value"], args[1]["value"]), "dim": _power(args[0]["dim"], args[1]["value"], n["at"])}
    raise ExpressionError(f"there is no function “{name}”", n["at"])


def evaluate(src, scope):
    """Evaluate an expression against a scope, to whatever kind it comes
    out as. A scope is a function of a name: a value, {"error": why}, or None."""
    if len(src) > MAX_LENGTH:
        return {"ok": False, "error": f"is longer than {MAX_LENGTH} characters", "at": [0, len(src)]}
    try:
        node = _Parser(tokenize(src)).parse()
        v = _evaluate_node(node, scope)
        if not math.isfinite(v["value"]):
            return {"ok": False, "error": "does not come out as a number", "at": node["at"]}
        return {"ok": True, "value": v["value"], "dim": v["dim"]}
    except ExpressionError as e:
        return {"ok": False, "error": e.message, "at": e.at}
    except RecursionError:
        # Parameters reading each other in a chain long enough to run out
        # of stack: an error of the expression, not of the page.
        return {"ok": False, "error": "reads parameters too deeply to evaluate", "at": [0, len(src)]}


def evaluate_for(src, kind, scope, whole=False):
    """Evaluate an expression for a field of the given kind: a bare number
    is read in the field's unit, anything of another kind is refused, and
    for a whole-number field `whole` asks that the result be one."""
    r = evaluate(src, scope)
    if not r["ok"]:
        return r
    want = dim_of_kind(kind)
    if r["dim"] != FREE and not dim_equal(r["dim"], want):
        hint = ""
        if kind in ("length", "angle") and dim_equal(r["dim"], UNITLESS):
            hint = f" — a number with a unit, {'“10 mm”' if kind == 'length' else '“10 deg”'}, makes it one"
        return {"ok": False, "error": f"comes out as {describe_dim(r['dim'])}; {describe_kind(kind)} is wanted here{hint}", "at": [0, len(src)]}
    if kind == "integer" and whole and not _near_int(r["value"]):
        return {"ok": False, "error": f"comes out {format_number(r['value'])}, not whole — round(), floor() or ceil() make it so", "at": [0, len(src)]}
    return {"ok": True, "value": r["value"], "dim": want}


# ---- reading an expression without evaluating it ----------------------------------------


def _tokenize_loosely(src):
    out = []
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*|\(", src):
        txt = m.group(0)
        if txt == "(":
            out.append(("op", "(", [m.start(), m.start() + 1]))
        else:
            out.append(("name", txt, [m.start(), m.end()]))
    out.append(("end", None, [len(src), len(src)]))
    return out


def _tokens_any(src):
    try:
        return tokenize(src)
    except ExpressionError:
        return _tokenize_loosely(src)


def references(src):
    """The parameter names an expression uses, each once, in order of first
    use - read off the tokens, so a broken expression still tells."""
    tokens = _tokens_any(src)
    out = []
    for i, t in enumerate(tokens):
        if t[0] != "name" or t[1] in RESERVED_NAMES:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt and nxt[0] == "op" and nxt[1] == "(":
            continue
        if t[1] not in out:
            out.append(t[1])
    return out


def rename_in(src, frm, to):
    """The expression with every use of a parameter named `frm` written as
    `to` - whole names only - and everything else kept exactly as typed."""
    if frm == to:
        return src
    tokens = _tokens_any(src)
    out = ""
    last = 0
    for i, t in enumerate(tokens):
        if t[0] != "name" or t[1] != frm:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt and nxt[0] == "op" and nxt[1] == "(":
            continue
        out += src[last:t[2][0]] + to
        last = t[2][1]
    return out + src[last:]


def is_plain_number(src):
    """Whether an expression is a bare number and nothing more."""
    try:
        tokens = tokenize(src)
    except ExpressionError:
        return False
    return len(tokens) == 2 and tokens[0][0] == "number"


def plain_number(src):
    """The number a plain-number expression is, or None."""
    try:
        tokens = tokenize(src)
    except ExpressionError:
        return None
    return tokens[0][1] if len(tokens) == 2 and tokens[0][0] == "number" else None


# ---- words -------------------------------------------------------------------------------


def format_number(value, places=3):
    """A number with no zeros carried behind it, to three places."""
    return num_str(fixed_number(value, places))


def _length_decimals(mm_decimals, units):
    return max(3, mm_decimals + 1) if units == "in" else mm_decimals


def format_value(value, kind, units="mm"):
    """A value with its unit, as a row reads it: "35 mm", "30°", "6", "0.5"."""
    if kind == "length":
        shown = value / 25.4 if units == "in" else value
        return f"{format_number(shown, _length_decimals(3, units))} {units}"
    if kind == "angle":
        return f"{format_number(value, 2)}°"
    if kind == "integer":
        return num_str(js_round(value))
    return format_number(value, 4)
