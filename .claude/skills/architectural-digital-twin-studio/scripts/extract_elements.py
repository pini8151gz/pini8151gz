#!/usr/bin/env python3
"""Step 2b – openings, door swings, stair treads and lift symbols from the PDF.

  extract_elements.py plan.pdf --page 5 --walls work/floor/walls.json --out work/floor/elements.json \
      [--line-layer "fill #000000"] [--erase-layer "fill #ffffff"]

Uses the same wall layer and erase layer as extract_walls.py (read from
walls.json), so it needs no new choices in the normal case.

- Openings: every piece of wall fill that a later-painted eraser removed is
  an opening. Its width runs along the wall, its depth across it.
- Door swing: for each opening, a quarter arc of radius = opening width is
  tested from each jamb, to each side of the wall. The hypothesis whose arc is
  most covered by line work on the plan (dashed arcs count) is the door: hinge
  jamb + the side it opens to. No arc found → window (exterior) or plain
  opening, decided in build_model.py.
- Thin straight line work (centre lines) is exported for build_model.py to
  find stair treads (parallel, evenly spaced) and lift symbols (an X).
All coordinates in PDF points; build_model.py converts them with the scale.
"""
import argparse
import math

from shapely.geometry import LineString, Point, box
from shapely.prepared import prep
from shapely.strtree import STRtree

from adt_common import (drawing_polygons, from_geojson, iter_polygons, layer_key, load_page,
                        read_json, thickness, union, write_json)


def centre_line(p):
    r = p.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return None
    c = list(r.exterior.coords)[:4]
    l01, l12 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
    if l01 >= l12:
        a, b, cc, dd, L, w = c[0], c[1], c[2], c[3], l01, l12
    else:
        a, b, cc, dd, L, w = c[1], c[2], c[3], c[0], l12, l01
    return ((a[0] + dd[0]) / 2, (a[1] + dd[1]) / 2), ((b[0] + cc[0]) / 2, (b[1] + cc[1]) / 2), L, w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--walls", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--line-layer", action="append", help='default "fill #000000"')
    ap.add_argument("--erase-layer", action="append", help="default: the erase layers used for the walls")
    ap.add_argument("--min-opening", type=float, default=6.0, help="pt – narrowest opening kept (≈ 0.4 m at 1:200)")
    a = ap.parse_args()

    W = read_json(a.walls)
    wall_layers = W["layers"]
    erase_layers = a.erase_layer or W["params"].get("erase_layers") or ["fill #ffffff"]
    line_layers = a.line_layer or ["fill #000000"]
    min_t = W["params"]["min_thickness_pt"]
    walls_final = from_geojson(W["walls"])
    doc, page, drawings = load_page(a.pdf, a.page - 1)

    pieces, erasers, thin = [], [], []
    for seq, d in enumerate(drawings):
        k = layer_key(d)
        if k in wall_layers:
            for p in drawing_polygons(d):
                if thickness(p) >= min_t and p.area >= W["params"]["min_area_pt2"]:
                    pieces.append((seq, p))
        elif k in erase_layers:
            erasers.extend((seq, p) for p in drawing_polygons(d) if p.area > 0)
        if k in line_layers:
            for p in drawing_polygons(d):
                if p.area > 0 and thickness(p) <= 0.6:
                    thin.append(p)

    # ---- openings = wall fill removed by later erasers
    tree = STRtree([p for _, p in pieces])
    cut = []
    for seq, e in erasers:
        for i in tree.query(e):
            s_, wp = pieces[i]
            if s_ < seq and wp.intersects(e):
                g = wp.intersection(e)
                if g.area > 0.5:
                    cut.append(g)
    cuts = union(cut).buffer(0.3, join_style="mitre").buffer(-0.3, join_style="mitre")
    wall_prep = prep(walls_final.buffer(0.2))
    thin_tree = STRtree(thin)

    def covered(x, y, tol=0.45):
        P = Point(x, y)
        for j in thin_tree.query(P.buffer(tol)):
            if thin[j].distance(P) <= tol:
                return True
        return False

    openings = []
    for op in iter_polygons(cuts):
        r = op.minimum_rotated_rectangle
        if r.geom_type != "Polygon":
            continue
        c = list(r.exterior.coords)[:4]
        cx, cy = r.centroid.x, r.centroid.y
        axes = []
        for (p0, p1) in ((c[0], c[1]), (c[1], c[2])):
            L = math.dist(p0, p1)
            ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            axes.append((L, ux, uy))
        # the width axis is the one with wall material just beyond both ends
        best = None
        for i, (L, ux, uy) in enumerate(axes):
            o = axes[1 - i][0]
            ends = [(cx + ux * (L / 2 + 0.8), cy + uy * (L / 2 + 0.8)), (cx - ux * (L / 2 + 0.8), cy - uy * (L / 2 + 0.8))]
            hits = sum(wall_prep.contains(Point(*e)) for e in ends)
            score = hits * 10 + L / max(o, 1e-6)
            if best is None or score > best[0]:
                best = (score, L, o, ux, uy, hits)
        _, width, depth, ux, uy, hits = best
        if width < a.min_opening:
            continue
        nx, ny = -uy, ux
        # ---- door swing test
        door = None
        for side_u in (1, -1):          # hinge at +u or -u jamb
            hx, hy = cx + ux * side_u * width / 2, cy + uy * side_u * width / 2
            for side_n in (1, -1):      # opens toward +n or -n
                for rf in (0.9, 1.0, 1.1):
                    rr = width * rf
                    n_ok = 0
                    N = 18
                    for k in range(1, N):
                        t = (k / N) * math.pi / 2
                        # arc from the closed leaf (along -u from the hinge) to the open leaf (along n)
                        dx = -side_u * ux * math.cos(t) + side_n * nx * math.sin(t)
                        dy = -side_u * uy * math.cos(t) + side_n * ny * math.sin(t)
                        px, py = hx + dx * rr, hy + dy * rr
                        # offset from the wall face: hinge sits on the face of the wall
                        px += side_n * nx * depth / 2
                        py += side_n * ny * depth / 2
                        n_ok += covered(px, py)
                    frac = n_ok / (N - 1)
                    if door is None or frac > door["arc_coverage"]:
                        door = {"arc_coverage": round(frac, 3), "hinge_u": side_u, "opens_n": side_n, "radius_pt": round(rr, 3)}
        is_door = door is not None and door["arc_coverage"] >= 0.35
        openings.append({
            "center": [round(cx, 3), round(cy, 3)], "axis": [round(ux, 5), round(uy, 5)],
            "width_pt": round(width, 3), "depth_pt": round(depth, 3), "wall_both_ends": hits == 2,
            "door": door if is_door else None,
            "arc_best_coverage": door["arc_coverage"] if door else 0,
            "polygon": [[round(x, 3), round(y, 3)] for x, y in op.exterior.coords],
        })

    # ---- thin straight line work for treads / lift symbols
    lines = []
    for p in thin:
        cl = centre_line(p)
        if cl and cl[2] >= 8 and cl[3] <= 0.6:
            lines.append([round(cl[0][0], 3), round(cl[0][1], 3), round(cl[1][0], 3), round(cl[1][1], 3)])

    nd = sum(1 for o in openings if o["door"])
    write_json(a.out, {"source_pdf": W["source_pdf"], "page": a.page, "units": "pt",
                       "openings": openings, "lines": lines,
                       "stats": {"openings": len(openings), "doors": nd, "lines": len(lines)}})
    print(f"openings: {len(openings)} ({nd} with a door swing), line segments: {len(lines)}")


if __name__ == "__main__":
    main()
