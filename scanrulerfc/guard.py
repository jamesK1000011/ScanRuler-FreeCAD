# SPDX-License-Identifier: AGPL-3.0-only
# Checks that ScanRuler for FreeCAD shares (red team 3, 19 Nov 2026):
#  - ZIP reads (a .scanruler project, a ZIP or 3MF in a pack, the state in a
#    .FCStd): a total unpacked cap, a ratio cap and a member count cap, and
#    each member read in chunks to a byte limit; zlib data inflated to a
#    byte limit;
#  - scan files: a size cap and a triangle cap;
#  - text from a file to the agent: no Unicode format characters (Cf: zero
#    width, direction marks), no tag characters, no control characters,
#    capped;
#  - paths under the home folder shown as ~/... in results and errors.
# Plain Python: no FreeCAD, no Agent Link import.

import os
import re
import struct
import unicodedata
import zipfile
import zlib

MAX_TOTAL = 1024 * 1024 * 1024  # all members of one ZIP, unpacked
MAX_MEMBERS = 10_000
MAX_RATIO = 1000  # unpacked to packed, for a member over 1 MB
RATIO_FLOOR = 1024 * 1024
CHUNK = 1024 * 1024
MAX_SCAN_BYTES = 1024 * 1024 * 1024
MAX_TRIANGLES = 20_000_000
TEXT_CAP = 200


class TooLarge(ValueError):
    """A file refused before it is read: too large, too many members, or
    packed too tightly (a ZIP bomb)."""


def _mb(n):
    return f"{n / (1024 * 1024):.0f} MB"


def zip_check(z, what="the archive", only=None, total=None):
    """The members of the open ZipFile z that are files (only(name) picks
    some), refused before a byte is unpacked when they are more than
    MAX_MEMBERS, unpack to more than total, or one is packed more than
    MAX_RATIO to one."""
    total = MAX_TOTAL if total is None else total
    infos = [i for i in z.infolist() if not i.is_dir() and (only is None or only(i.filename))]
    if len(infos) > MAX_MEMBERS:
        raise TooLarge(f"{what} holds {len(infos)} files, more than {MAX_MEMBERS}: not opened.")
    size = sum(i.file_size for i in infos)
    if size > total:
        raise TooLarge(f"{what} unpacks to {_mb(size)}, more than {_mb(total)}: not opened.")
    for i in infos:
        if i.file_size > RATIO_FLOOR and i.file_size > MAX_RATIO * max(1, i.compress_size):
            raise TooLarge(f"{what}: {text(i.filename, 80)} is packed more than {MAX_RATIO} to one (a ZIP bomb?): not opened.")
    return infos


def zip_read(z, member, what="the archive", limit=None):
    """One member's bytes, read in chunks; refused when it gives more than
    limit bytes (whatever its header says)."""
    limit = MAX_TOTAL if limit is None else limit
    info = member if isinstance(member, zipfile.ZipInfo) else z.getinfo(member)
    if info.file_size > limit:
        raise TooLarge(f"{what}: {text(info.filename, 80)} unpacks to {_mb(info.file_size)}, more than {_mb(limit)}: not read.")
    parts, got = [], 0
    with z.open(info) as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            got += len(b)
            if got > limit:
                raise TooLarge(f"{what}: {text(info.filename, 80)} unpacks to more than {_mb(limit)}: not read.")
            parts.append(b)
    return b"".join(parts)


def zip_members(z, what="the archive", only=None, total=None):
    """{name: bytes} of the members zip_check lets through, read with
    zip_read inside the total."""
    total = MAX_TOTAL if total is None else total
    out, left = {}, total
    for i in zip_check(z, what, only, total):
        b = zip_read(z, i, what, left)
        left -= len(b)
        out[i.filename] = b
    return out


def inflate(data, limit=None, what="the data"):
    """zlib data unpacked to at most limit bytes; more is refused."""
    limit = MAX_TOTAL if limit is None else limit
    d = zlib.decompressobj()
    out = d.decompress(data, limit + 1)
    if len(out) <= limit and not d.unconsumed_tail:
        out += d.flush()
    if len(out) > limit or d.unconsumed_tail:
        raise TooLarge(f"{what} unpacks to more than {_mb(limit)}: not read.")
    return out


def scan_check(path):
    """A scan file refused before it is read: larger than MAX_SCAN_BYTES; a
    binary STL that says more than MAX_TRIANGLES; a 3MF (a ZIP) that fails
    zip_check."""
    size = os.path.getsize(path)
    name = text(os.path.basename(path), 80)
    if size > MAX_SCAN_BYTES:
        raise TooLarge(f"{name}: {_mb(size)}, more than {_mb(MAX_SCAN_BYTES)}: not opened. Reduce it in a mesh program first.")
    low = path.lower()
    if low.endswith(".stl") and size >= 84:
        with open(path, "rb") as f:
            head = f.read(84)
        n = struct.unpack_from("<I", head, 80)[0]
        if size == 84 + 50 * n and n > MAX_TRIANGLES:
            raise TooLarge(f"{name}: {n:,} triangles, more than {MAX_TRIANGLES:,}: not opened. Reduce it in a mesh program first.")
    elif low.endswith(".3mf"):
        try:
            with zipfile.ZipFile(path) as z:
                zip_check(z, name)
        except zipfile.BadZipFile:
            raise TooLarge(f"{name}: not a 3MF (not a ZIP): not opened.") from None


def triangles_check(n, name):
    if n > MAX_TRIANGLES:
        raise TooLarge(f"{text(name, 80)}: {n:,} triangles, more than {MAX_TRIANGLES:,}: not opened. Reduce it in a mesh program first.")


def text(s, cap=TEXT_CAP):
    """Text from a file for the agent: Unicode format characters (category
    Cf: zero-width, direction marks), the tag block (U+E0000 to U+E007F) and
    control characters removed (a control character becomes a space),
    capped at cap characters."""
    if s is None:
        return None
    out = []
    for c in str(s):
        cat = unicodedata.category(c)
        if cat == "Cf" or 0xE0000 <= ord(c) <= 0xE007F:
            continue
        out.append(" " if cat == "Cc" else c)
    t = " ".join("".join(out).split())
    return t[:cap] + ("…" if len(t) > cap else "")


def tilde(obj):
    """Paths under the home folder as ~/... in every string of obj (dicts,
    lists and tuples walked; other values as they are)."""
    h = os.path.expanduser("~").rstrip("/")
    homes = [x for x in dict.fromkeys((h, os.path.realpath(h))) if x and x != "/"]
    if not homes:
        return obj
    pat = re.compile("(?:" + "|".join(re.escape(x) for x in homes) + r")(?![\w.-])")

    def walk(o):
        if isinstance(o, str):
            return pat.sub("~", o) if any(x in o for x in homes) else o
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, tuple):
            return tuple(walk(v) for v in o)
        return o

    return walk(obj)
