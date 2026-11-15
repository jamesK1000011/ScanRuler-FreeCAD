# SPDX-License-Identifier: AGPL-3.0-only
# The original's UI fonts, as ScanRuler by Stefan Hermann (CNC Kitchen) ships
# them in public/fonts/: Barlow and Barlow Semi Condensed (headers, keys,
# text) and B612 Mono (readings). All three are under the SIL Open Font
# License 1.1; their licence texts sit beside them in scanrulerfc/fonts/
# (OFL-*.txt) and travel with them. They are loaded into Qt's font database
# for this process only, not installed on the system.

import os

FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")

# family -> (files, licence text), in the original's order of use.
FAMILIES = {
    "Barlow": (("barlow-400.woff2", "barlow-500.woff2", "barlow-600.woff2", "barlow-700.woff2"), "OFL-barlow.txt"),
    "Barlow Semi Condensed": (("barlow-semi-condensed-500.woff2", "barlow-semi-condensed-600.woff2"), "OFL-barlowsemicondensed.txt"),
    "B612 Mono": (("b612-mono-400.woff2", "b612-mono-700.woff2"), "OFL-b612mono.txt"),
}
# What each family stands in for when it cannot be loaded.
FALLBACK = {"Barlow": "sans-serif", "Barlow Semi Condensed": "sans-serif", "B612 Mono": "monospace"}
ROLES = {"text": "Barlow", "caps": "Barlow Semi Condensed", "reading": "B612 Mono"}

_loaded = {}


def files():
    """Every font and licence file, as paths."""
    out = []
    for fs, lic in FAMILIES.values():
        out.extend(os.path.join(FONTS, f) for f in fs)
        out.append(os.path.join(FONTS, lic))
    return out


def load():
    """Add the fonts to Qt's database once; {family: the family name Qt
    reports, or the fallback where Qt could not read the file}. WOFF2 needs a
    FreeType with Brotli on Linux and Windows; macOS's Core Text reads it.
    Without a QApplication (FreeCADCmd, a test run) Qt's font database must
    not be touched — real FreeCAD's Qt aborts the process — so the
    fallbacks are answered and nothing is kept, to load once one exists."""
    if _loaded:
        return dict(_loaded)
    try:
        from PySide import QtGui, QtWidgets
    except ImportError:
        return dict(FALLBACK)
    if QtWidgets.QApplication.instance() is None:
        return dict(FALLBACK)

    for fam, (fs, _lic) in FAMILIES.items():
        got = None
        for f in fs:
            fid = QtGui.QFontDatabase.addApplicationFont(os.path.join(FONTS, f))
            if fid >= 0:
                names = QtGui.QFontDatabase.applicationFontFamilies(fid)
                got = got or (names[0] if names else fam)
        _loaded[fam] = got or FALLBACK[fam]
    return dict(_loaded)


def family(role):
    """The family for a role ("text", "caps", "reading") once loaded."""
    fam = ROLES[role]
    return _loaded.get(fam, fam)
