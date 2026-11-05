#!/usr/bin/env python3
"""Step 3 – fix the drawing scale from dimensions printed on the plan.

The scale written in a title block (e.g. 1:100) describes the original sheet,
not this PDF, so never use it. Instead, read dimension strings on the zoomed
tiles and give the two approximate end points of each one (in pt, from the grid)
together with the stated length. Each end is snapped to the nearest wall face
that crosses the measuring line, so small reading errors do not matter.

  calibrate.py work/floor/walls.json --out work/floor/scale.json \
     --pair "150.5,190,221.5,190,4850,bedroom 25+90+370" \
     --pair "195,181.5,195,219.8,2600,bedroom 260" \
     [--snap walls|none] [--faces clear|nearest] [--radius 2.0] [--tolerance-mm 40]

Use at least three dimensions, from different parts of the plan and in both
directions. The scale is the median; every dimension is then re-measured with it
and its error is reported. If any error is above the tolerance the scale is
marked UNRESOLVED and the build should stop until it is explained.
"""
import argparse
import math
import statistics

from shapely.geometry import Point
from shapely.prepared import prep

from adt_common import from_geojson, iter_polygons, read_json, write_json


def edges_of(geom):
    for p in iter_polygons(geom):
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.coords)
            for i in range(len(c) - 1):
                yield c[i], c[i + 1]


def snap(p, u, edges, radius, inside=None, inward=1):
    """Move p along direction u to the closest crossing wall face.

    With `inside` (a prepared walls geometry), only faces with wall behind
    them and free space in front (`inward` = +1 toward p2, -1 toward p1) count,
    i.e. the room-facing face of the wall – what a clear-span dimension measures.
    """
    best = None
    px, py = p
    ux, uy = u
    for (ax, ay), (bx, by) in edges:
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L < 1e-6 or abs((ex * ux + ey * uy) / L) > 0.5:
            continue  # face must cross the measuring line (be roughly perpendicular)
        den = ux * ey - uy * ex
        if abs(den) < 1e-9:
            continue
        t = ((ax - px) * ey - (ay - py) * ex) / den
        s = ((ax - px) * uy - (ay - py) * ux) / den
        if -1e-6 <= s <= 1 + 1e-6 and abs(t) <= radius and (best is None or abs(t) < abs(best)):
            if inside is not None:
                eps = 0.05
                fx, fy = px + ux * (t + inward * eps), py + uy * (t + inward * eps)
                bx_, by_ = px + ux * (t - inward * eps), py + uy * (t - inward * eps)
                if inside.contains(Point(fx, fy)) or not inside.contains(Point(bx_, by_)):
                    continue
            best = t
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("walls")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pair", action="append", required=True,
                    help='"x1,y1,x2,y2,real_mm[,label]" in pt')
    ap.add_argument("--snap", choices=["walls", "none"], default="walls")
    ap.add_argument("--faces", choices=["clear", "nearest"], default="clear",
                    help="clear: snap to the room-facing wall face (clear span); nearest: any face")
    ap.add_argument("--radius", type=float, default=2.0, help="max snap distance in pt")
    ap.add_argument("--tolerance-mm", type=float, default=40.0,
                    help="allowed error per dimension, in mm ...")
    ap.add_argument("--tolerance-pct", type=float, default=1.5,
                    help="... or in percent of the stated length, whichever is larger")
    a = ap.parse_args()

    w = read_json(a.walls)
    wg = from_geojson(w["walls"])
    if w.get("walls_from_hatch"):
        # snap only to faces drawn in the PDF, not to hatch envelopes
        wg = wg.difference(from_geojson(w["walls_from_hatch"]).buffer(0.05))
    edges = list(edges_of(wg)) if a.snap == "walls" else []
    inside = prep(wg) if a.faces == "clear" else None
    samples = []
    for raw in a.pair:
        parts = [s.strip() for s in raw.split(",")]
        x1, y1, x2, y2, real = map(float, parts[:5])
        label = ",".join(parts[5:]) or f"{real:g} mm"
        L = math.hypot(x2 - x1, y2 - y1)
        u = ((x2 - x1) / L, (y2 - y1) / L)
        t1 = t2 = 0.0
        snapped = [False, False]
        if edges:
            s1 = snap((x1, y1), u, edges, a.radius, inside, +1)
            s2 = snap((x2, y2), u, edges, a.radius, inside, -1)
            if s1 is not None:
                t1, snapped[0] = s1, True
            if s2 is not None:
                t2, snapped[1] = s2, True
        measured = L + t2 - t1
        samples.append({
            "label": label, "stated_mm": real,
            "p1": [round(x1 + u[0] * t1, 3), round(y1 + u[1] * t1, 3)],
            "p2": [round(x2 + u[0] * t2, 3), round(y2 + u[1] * t2, 3)],
            "snapped": snapped, "measured_pt": round(measured, 4),
            "mm_per_pt": real / measured,
        })

    scale = statistics.median(s["mm_per_pt"] for s in samples)
    worst = 0.0
    bad = []
    for s in samples:
        s["remeasured_mm"] = round(s["measured_pt"] * scale, 1)
        s["error_mm"] = round(s["remeasured_mm"] - s["stated_mm"], 1)
        s["error_pct"] = round(100 * s["error_mm"] / s["stated_mm"], 2)
        s["mm_per_pt"] = round(s["mm_per_pt"], 4)
        worst = max(worst, abs(s["error_mm"]))
        allowed = max(a.tolerance_mm, a.tolerance_pct / 100 * s["stated_mm"])
        s["within_tolerance"] = abs(s["error_mm"]) <= allowed
        if not s["within_tolerance"]:
            bad.append(s["label"])

    unsnapped = sum(1 for s in samples for k in s["snapped"] if not k)
    if len(samples) < 2:
        status, why = "UNRESOLVED", "only one dimension – cannot cross-check the scale"
    elif bad:
        status, why = "UNRESOLVED", f"{len(bad)} dimension(s) outside tolerance: {', '.join(bad)}"
    elif len(samples) < 3:
        status, why = "DERIVED", "two dimensions agree; add a third for VERIFIED"
    else:
        status, why = "VERIFIED", f"{len(samples)} dimensions agree within {worst:.0f} mm"
    if unsnapped and status == "VERIFIED":
        status, why = "DERIVED", why + f"; {unsnapped} end(s) not snapped to a wall face"

    result = {
        "mm_per_pt": round(scale, 5),
        "paper_scale_equivalent": f"1:{round(scale / (25.4 / 72))}",
        "status": status, "reason": why,
        "tolerance": {"mm": a.tolerance_mm, "pct": a.tolerance_pct},
        "worst_error_mm": round(worst, 1),
        "samples": samples,
    }
    write_json(a.out, result)
    print(f"scale = {scale:.4f} mm/pt   ({result['paper_scale_equivalent']} on this PDF)   {status}: {why}")
    for s in samples:
        print(f"  {s['label']:<32} stated {s['stated_mm']:>7.0f}  model {s['remeasured_mm']:>8.1f}  "
              f"err {s['error_mm']:>+6.1f} mm ({s['error_pct']:+.1f}%)  snapped={s['snapped']}"
              + ("" if s["within_tolerance"] else "  <-- OUT"))


if __name__ == "__main__":
    main()
