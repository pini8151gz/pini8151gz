"""Shared helpers for the Architectural Digital Twin Studio scripts.

Everything here works in PDF points (1/72 inch) with the origin at the page's
top-left corner and y pointing down, exactly as PyMuPDF reports drawings.
Conversion to millimetres happens only in build_model.py, from a calibrated
scale, so nothing upstream can silently invent a size.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pymupdf
from shapely.geometry import LineString, Polygon, MultiPolygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid


def color_key(rgb) -> str | None:
    """Turn a PyMuPDF colour tuple into a stable '#rrggbb' key."""
    if rgb is None:
        return None
    vals = list(rgb)[:3]
    if len(vals) == 1:
        vals = vals * 3
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in vals)


def _bezier(p0, p1, p2, p3, n=8):
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        out.append((
            mt**3 * p0.x + 3 * mt**2 * t * p1.x + 3 * mt * t**2 * p2.x + t**3 * p3.x,
            mt**3 * p0.y + 3 * mt**2 * t * p1.y + 3 * mt * t**2 * p2.y + t**3 * p3.y,
        ))
    return out


def drawing_subpaths(d):
    """Split one PyMuPDF drawing into subpaths (lists of (x, y))."""
    paths, cur = [], []

    def flush():
        nonlocal cur
        if len(cur) >= 2:
            paths.append(cur)
        cur = []

    for it in d["items"]:
        op = it[0]
        if op == "l":
            a, b = it[1], it[2]
            if cur and math.dist(cur[-1], (a.x, a.y)) > 1e-3:
                flush()
            if not cur:
                cur.append((a.x, a.y))
            cur.append((b.x, b.y))
        elif op == "c":
            a = it[1]
            if cur and math.dist(cur[-1], (a.x, a.y)) > 1e-3:
                flush()
            if not cur:
                cur.append((a.x, a.y))
            cur.extend(_bezier(*it[1:5]))
        elif op == "re":
            flush()
            r = it[1]
            paths.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
        elif op == "qu":
            flush()
            q = it[1]
            paths.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])
    flush()
    return paths


def drawing_polygons(d):
    """Return shapely polygons for a drawing: filled subpaths as areas,
    stroked subpaths as bands of the stroke width."""
    polys = []
    subs = drawing_subpaths(d)
    if d.get("fill") is not None:
        for s in subs:
            if len(s) >= 3:
                p = Polygon(s)
                if not p.is_valid:
                    p = make_valid(p)
                if not p.is_empty and p.area > 0:
                    polys.append(p)
    elif d.get("color") is not None and (d.get("width") or 0) > 0:
        w = d["width"]
        for s in subs:
            ls = LineString(s)
            if ls.length > 0:
                polys.append(ls.buffer(w / 2, cap_style="flat", join_style="mitre"))
    return polys


def layer_key(d):
    """Group drawings into 'layers' by how they are painted."""
    if d.get("fill") is not None:
        return f"fill {color_key(d['fill'])}"
    return f"stroke {color_key(d.get('color'))} w{round(d.get('width') or 0, 2)}"


def load_page(pdf_path, page_index):
    doc = pymupdf.open(pdf_path)
    page = doc[page_index]
    return doc, page, page.get_drawings()


def thickness(poly) -> float:
    """Typical thickness of a band-like polygon: area / half perimeter."""
    half = poly.length / 2
    return poly.area / half if half else 0.0


def to_geojson(geom):
    return mapping(geom)


def from_geojson(obj):
    return shape(obj)


def iter_polygons(geom):
    if geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from geom.geoms
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from iter_polygons(g)


def union(polys):
    return make_valid(unary_union(polys)) if polys else Polygon()


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
