# Ported from ScanRuler by CNC Kitchen (Stefan Hermann): src/core/units.ts (the length and area words plugins/reverse/core/*.ts writes)
# SPDX-License-Identifier: AGPL-3.0-only
#
# A length or an area as the original writes it: "12.700 mm" / "0.5000 in",
# "645.2 mm²" / "1.000 in²"; never a "-0.0".

from ._js import to_fixed

MM_PER_INCH = 25.4


def length_decimals(mm_decimals, units):
    return max(3, mm_decimals + 1) if units == "in" else mm_decimals


def _fmt(value, units, mm_decimals, power, bare=False, signed=False):
    v = value / (MM_PER_INCH ** power if units == "in" else 1)
    places = length_decimals(mm_decimals, units)
    text = to_fixed(v, places)
    if float(text) == 0:
        text = to_fixed(0, places)
    elif signed and v > 0:
        text = "+" + text
    return text if bare else f"{text} {units}{'²' if power == 2 else '³' if power == 3 else ''}"


def fmt_len(mm, units="mm", mm_decimals=3, bare=False, signed=False):
    return _fmt(mm, units, mm_decimals, 1, bare, signed)


def fmt_area(mm2, units="mm", mm_decimals=1, bare=False, signed=False):
    return _fmt(mm2, units, mm_decimals, 2, bare, signed)


def fmt_vol(mm3, units="mm", mm_decimals=1, bare=False, signed=False):
    return _fmt(mm3, units, mm_decimals, 3, bare, signed)
