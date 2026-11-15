# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): the JavaScript number and JSON behaviour plugins/reverse/core/*.ts relies on
# SPDX-License-Identifier: AGPL-3.0-only
#
# What the TypeScript engine gets from the language and Python does not do
# the same way: Math.round (half up, not to even), `%` (the dividend's sign),
# Number#toFixed and String(number), and JSON.stringify / JSON.parse. The
# records are kept byte for byte as the original writes them, so the JSON
# here is the original's: no spaces, whole numbers with no ".0", exponents
# as JavaScript spells them, non-finite numbers as null.

import json
import math
from decimal import ROUND_HALF_UP, Decimal

MAX_SAFE_INTEGER = 2 ** 53 - 1


def js_round(x):
    """Math.round: halves go up, toward +infinity."""
    if not math.isfinite(x):
        return x
    return float(math.floor(x + 0.5)) if abs(x) < 2 ** 52 else float(x)


def fmod(a, b):
    """JavaScript's `%`: the sign of the dividend."""
    if b == 0 or not math.isfinite(a):
        return math.nan
    if math.isinf(b):
        return a
    return math.fmod(a, b)


def safe_integer(v):
    """Number.isSafeInteger."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if isinstance(v, float) and (not math.isfinite(v) or v != int(v)):
        return False
    return abs(v) <= MAX_SAFE_INTEGER


def is_number(v):
    """typeof v === 'number'."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_finite_number(v):
    """typeof v === 'number' && Number.isFinite(v)."""
    return is_number(v) and math.isfinite(v)


def num_str(x):
    """String(x) for a number: the shortest digits that read back, an
    exponent past 1e21 or under 1e-6, and no ".0" on a whole number."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        if abs(x) <= MAX_SAFE_INTEGER:
            return str(x)
        x = float(x)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    r = repr(float(x))
    sign = ""
    if r[0] == "-":
        sign, r = "-", r[1:]
    if "e" in r:
        mant, exp = r.split("e")
        e = int(exp)
    else:
        mant, e = r, 0
    if "." in mant:
        whole, frac = mant.split(".")
    else:
        whole, frac = mant, ""
    if frac == "0":
        frac = ""
    digits = (whole + frac).lstrip("0")
    # The decimal exponent n: value = 0.d1d2... x 10^n
    lead = len(whole.lstrip("0")) if whole.strip("0") else -(len(frac) - len(frac.lstrip("0")))
    n = lead + e
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    exp = n - 1
    es = ("+" if exp >= 0 else "-") + str(abs(exp))
    return sign + digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + es


def to_fixed(x, places):
    """Number#toFixed: the exact value of the double rounded half away
    from zero, as JavaScript does it."""
    if not math.isfinite(x):
        return num_str(x)
    if abs(x) >= 1e21:
        return num_str(x)
    d = Decimal(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    s = format(d, "f")
    if s.startswith("-") and float(x) == 0:
        s = s[1:]
    return s


def fixed_number(x, places):
    """Number(x.toFixed(places)): a number with no zeros carried behind it."""
    return float(to_fixed(x, places))


def precision_number(x, digits):
    """Number(x.toPrecision(digits)): the exact value of the double to that
    many significant figures, halves away from zero."""
    if not math.isfinite(x) or x == 0:
        return x
    d = Decimal(x)
    q = Decimal(1).scaleb(d.adjusted() - digits + 1)
    r = d.quantize(q, rounding=ROUND_HALF_UP)
    if r.adjusted() > d.adjusted():
        r = d.quantize(q * 10, rounding=ROUND_HALF_UP)
    return float(r)


# ---- JSON --------------------------------------------------------------------------


def _str(s):
    return json.dumps(s, ensure_ascii=False)


def stringify(value):
    """JSON.stringify(value) with no indent: what the original writes."""
    out = []
    _write(value, out)
    return "".join(out)


def _write(v, out):
    if v is None:
        out.append("null")
    elif v is True:
        out.append("true")
    elif v is False:
        out.append("false")
    elif isinstance(v, str):
        out.append(_str(v))
    elif isinstance(v, (int, float)):
        out.append(num_str(v) if math.isfinite(v) else "null")
    elif isinstance(v, dict):
        out.append("{")
        first = True
        for k, x in v.items():
            if x is UNDEFINED:
                continue
            if not first:
                out.append(",")
            first = False
            out.append(_str(str(k)))
            out.append(":")
            _write(x, out)
        out.append("}")
    elif isinstance(v, (list, tuple)):
        out.append("[")
        for i, x in enumerate(v):
            if i:
                out.append(",")
            _write(None if x is UNDEFINED else x, out)
        out.append("]")
    elif hasattr(v, "tolist"):
        _write(v.tolist(), out)
    else:
        raise TypeError(f"cannot write {type(v).__name__} as JSON")


class _Undefined:
    def __repr__(self):
        return "undefined"


UNDEFINED = _Undefined()


def _int(s):
    i = int(s)
    return i if abs(i) <= MAX_SAFE_INTEGER else float(s)


def _refuse(name):
    raise ValueError(f"Unexpected token {name} in JSON")


def _index_key(k):
    """Whether a key is an array index, which a JavaScript object lists
    first, in numeric order, whatever order it was written in."""
    return k.isdigit() and k.isascii() and (k == "0" or k[0] != "0") and int(k) < 2 ** 32 - 1


def js_object(pairs):
    """A dict in the order a JavaScript object keeps its keys."""
    d = {}
    for k, v in pairs:
        d[k] = v
    if any(_index_key(k) for k in d):
        idx = sorted((k for k in d if _index_key(k)), key=int)
        d = {**{k: d[k] for k in idx}, **{k: v for k, v in d.items() if not _index_key(k)}}
    return d


def parse(text):
    """JSON.parse: no NaN or Infinity, integers past 2^53 read as doubles,
    keys in a JavaScript object's order."""
    return json.loads(text, parse_int=_int, parse_constant=_refuse, object_pairs_hook=js_object)


def clone(value):
    """JSON.parse(JSON.stringify(value))."""
    return parse(stringify(value))
