"""Render MapLibre SDF glyph ranges (.pbf) from TrueType fonts.

MapLibre draws map labels from signed-distance-field glyphs served as protobuf
ranges of 256 codepoints. We generate them here so the product carries no
runtime dependency on a font CDN.

Format (Mapbox glyphs.proto):
  message glyphs { repeated fontstack stacks = 1; }
  message fontstack { required string name=1; required string range=2;
                      repeated glyph glyphs=3; }
  message glyph { required uint32 id=1; optional bytes bitmap=2;
                  required uint32 width=3; required uint32 height=4;
                  required sint32 left=5; required sint32 top=6;
                  required uint32 advance=7; }
"""
from __future__ import annotations

import math
import os
import struct
import sys

import freetype

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "backend", "data", "fonts")
OUT_DIR = os.path.join(FONT_DIR, "glyphs")

SIZE = 24         # rasterisation size, matches Mapbox convention
BUFFER = 3        # SDF padding around each glyph
CUTOFF = 0.25     # SDF zero level
RADIUS = 8.0      # distance range in pixels
RANGES = [(0, 255), (256, 511), (768, 1023), (7680, 7935), (8192, 8447)]

FONTS = {
    "Noto Sans Regular": "NotoSans-Regular.ttf",
    "Noto Sans Medium": "NotoSans-Regular.ttf",
    "Noto Sans Bold": "NotoSans-Bold.ttf",
}


# --- minimal protobuf writer ------------------------------------------------
def _varint(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _zigzag(v: int) -> int:
    return (v << 1) ^ (v >> 31)


def _bytes_field(field: int, data: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(data)) + data


def _uint_field(field: int, v: int) -> bytes:
    return _tag(field, 0) + _varint(v)


def _sint_field(field: int, v: int) -> bytes:
    return _tag(field, 0) + _varint(_zigzag(v))


# --- SDF --------------------------------------------------------------------
INF = 1e20


def _edt1d(f, n):
    d = [0.0] * n
    v = [0] * n
    z = [0.0] * (n + 1)
    k = 0
    v[0] = 0
    z[0] = -INF
    z[1] = INF
    for q in range(1, n):
        s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
        while s <= z[k]:
            k -= 1
            s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
        k += 1
        v[k] = q
        z[k] = s
        z[k + 1] = INF
    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        d[q] = (q - v[k]) ** 2 + f[v[k]]
    return d


def _edt(grid, w, h):
    """Squared euclidean distance transform (Felzenszwalb & Huttenlocher)."""
    for x in range(w):
        col = [grid[y * w + x] for y in range(h)]
        res = _edt1d(col, h)
        for y in range(h):
            grid[y * w + x] = res[y]
    for y in range(h):
        row = grid[y * w:(y + 1) * w]
        res = _edt1d(row, w)
        grid[y * w:(y + 1) * w] = res
    return grid


def make_sdf(alpha: list[int], w: int, h: int) -> bytes:
    """Turn an 8-bit coverage bitmap into a Mapbox-style SDF bitmap."""
    inner = [0.0 if a > 127 else INF for a in alpha]
    outer = [0.0 if a <= 127 else INF for a in alpha]
    _edt(inner, w, h)
    _edt(outer, w, h)
    out = bytearray(w * h)
    for i in range(w * h):
        d = math.sqrt(outer[i]) - math.sqrt(inner[i])
        v = round(255 - 255 * (d / RADIUS + CUTOFF))
        out[i] = max(0, min(255, v))
    return bytes(out)


def render_font(path: str, name: str) -> dict[int, bytes]:
    face = freetype.Face(path)
    face.set_pixel_sizes(0, SIZE)
    glyphs: dict[int, bytes] = {}
    for lo, hi in RANGES:
        for cp in range(lo, hi + 1):
            idx = face.get_char_index(cp)
            if idx == 0:
                continue
            try:
                face.load_glyph(idx, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_NO_HINTING)
            except Exception:
                continue
            bm = face.glyph.bitmap
            advance = round(face.glyph.advance.x / 64.0)
            gw, gh = bm.width, bm.rows
            body = b""
            body += _uint_field(1, cp)
            if gw and gh:
                w2, h2 = gw + 2 * BUFFER, gh + 2 * BUFFER
                alpha = [0] * (w2 * h2)
                for y in range(gh):
                    row = bm.buffer[y * bm.pitch:y * bm.pitch + gw]
                    for x in range(gw):
                        alpha[(y + BUFFER) * w2 + (x + BUFFER)] = row[x]
                body += _bytes_field(2, make_sdf(alpha, w2, h2))
                body += _uint_field(3, gw)
                body += _uint_field(4, gh)
                body += _sint_field(5, face.glyph.bitmap_left - BUFFER)
                body += _sint_field(6, face.glyph.bitmap_top + BUFFER)
            else:
                body += _uint_field(3, 0)
                body += _uint_field(4, 0)
                body += _sint_field(5, 0)
                body += _sint_field(6, 0)
            body += _uint_field(7, advance)
            glyphs.setdefault(lo, b"")
            glyphs[lo] += _bytes_field(3, body)
    return glyphs


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    for stack, filename in FONTS.items():
        path = os.path.join(FONT_DIR, filename)
        if not os.path.exists(path):
            print(f"  skip {stack}: {filename} missing")
            continue
        out_dir = os.path.join(OUT_DIR, stack)
        os.makedirs(out_dir, exist_ok=True)
        per_range = render_font(path, stack)
        for lo, hi in RANGES:
            body = per_range.get(lo, b"")
            fontstack = _bytes_field(1, stack.encode()) \
                + _bytes_field(2, f"{lo}-{hi}".encode()) + body
            blob = _bytes_field(1, fontstack)
            with open(os.path.join(out_dir, f"{lo}-{hi}.pbf"), "wb") as f:
                f.write(blob)
        print(f"  {stack}: {len(RANGES)} ranges, "
              f"{sum(len(v) for v in per_range.values())} bytes of glyph data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
