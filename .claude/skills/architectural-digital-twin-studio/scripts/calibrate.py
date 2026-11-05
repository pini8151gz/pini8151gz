#!/usr/bin/env python3
"""Step 3 – fix the drawing scale from dimensions printed on the plan.

The scale written in a title block (e.g. 1:100) describes the original sheet,
not this PDF, so never use it. Instead, read dimension strings on the zoomed
tiles and give the two approximate end points of each dimension LINE (in pt,
from the grid, on the dimension line itself) with the stated length.

  calibrate.py work/floor/walls.json --out work/floor/scale.json \
     --pair "151,190,221,190,4850,bedroom 25+90+370" \
     --pair "180,182,180,220,2600,bedroom 260" ... \
     [--check "x1,y1,x2,y2,mm,label" ...] \
     [--snap dims|walls|none] [--dim-layer "fill #000000"] [--radius 1.5]

--snap dims (default): each end snaps to the extension line or tick mark of the
  dimension, read from the PDF's vector line work. This measures the drawing
  itself, so the scale does not depend on how thick the extracted walls are.
--snap walls: ends snap to room-facing wall faces (older method; wall-thickness
  bias leaks into the scale – use it only when dimensions have no line work).
--check: clear spans measured between the MODEL's wall faces with the final
  scale. They do not change the scale; they show whether extracted walls are
  too thick or too thin (face bias), which qa_report.py reports.

Use at least three dimensions, from different parts of the plan and in both
directions. The scale is the least-squares fit; every dimension is re-measured
with it. Any dimension above tolerance, or a >1% difference between the
horizontal and vertical scale, makes the scale UNRESOLVED.
"""
import argparse
import math
import statistics

from shapely.geometry import Point
from shapely.prepared import prep

from adt_common import (drawing_polygons, from_geojson, iter_polygons, layer_key,
                        load_page, read_json, thickness, write_json)


def line_work(walls_json, layers, max_thick=0.5):
    """Centre lines of thin strokes on the given layers: dimension lines,
    extension lines and ticks (as filled thin shapes or real strokes)."""
    doc, page, drawings = load_page(walls_json["source_pdf"], walls_json["page"] - 1)
    segs = []
    for d in drawings:
        if layer_key(d) not in layers and not any(layer_key(d).startswith(l + " ") or layer_key(d) == l for l in layers):
            continue
        for p in drawing_polygons(d):
            if p.area <= 0 or thickness(p) > max_thick:
                continue
            r = p.minimum_rotated_rectangle
            if r.geom_type != "Polygon":
                continue
            c = list(r.exterior.coords)[:4]
            l01, l12 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
            if l01 >= l12:
                a_, b_, cc, dd = c[0], c[1], c[2], c[3]
            else:
                a_, b_, cc, dd = c[1], c[2], c[3], c[0]
            if max(l01, l12) < 0.8:
                continue
            segs.append((((a_[0] + dd[0]) / 2, (a_[1] + dd[1]) / 2), ((b_[0] + cc[0]) / 2, (b_[1] + cc[1]) / 2)))
    return segs


def edges_of(geom):
    for p in iter_polygons(geom):
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.coords)
            for i in range(len(c) - 1):
                yield c[i], c[i + 1]


def snap(p, u, edges, radius, inside=None, inward=1, max_dot=0.5):
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
        if L < 1e-6 or abs((ex * ux + ey * uy) / L) > max_dot:
            continue  # must cross the measuring line (perpendicular-ish; 45° ticks allowed for dims)
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


def dims_by_consensus(specs, segs, search):
    """For each dimension point, collect straight thin segments passing within
    `search` pt (candidate dimension lines). Every candidate implies a scale;
    the scale that most dimensions agree with (within 1%) wins, and each
    dimension takes its candidate closest to it. Nothing about the scale is
    assumed beforehand."""
    from shapely.geometry import LineString
    dims = []
    for raw in specs:
        parts = [x.strip() for x in raw.split(",")]
        x, y, real = map(float, parts[:3])
        label = ",".join(parts[3:]) or f"{real:g} mm"
        P = Point(x, y)
        cands = []
        for a_, b_ in segs:
            L = math.dist(a_, b_)
            if L < 4:
                continue
            if LineString([a_, b_]).distance(P) <= search:
                cands.append((a_, b_, L))
        dims.append((label, real, cands, (x, y)))
    hyps = [real / c[2] for _, real, cands, _ in dims for c in cands]
    best = None
    for h in hyps:
        inl, res = 0, 0.0
        for _, real, cands, _ in dims:
            if not cands:
                continue
            e = min(abs(c[2] * h - real) / real for c in cands)
            if e <= 0.01:
                inl += 1
                res += e
        if best is None or inl > best[1] or (inl == best[1] and res < best[2]):
            best = (h, inl, res)
    out = []
    for label, real, cands, (x, y) in dims:
        if not cands or best is None:
            out.append({"label": label, "stated_mm": real, "axis": "?", "p1": [x, y], "p2": [x, y],
                        "snapped": [False, False], "snap_to": "no dimension line found",
                        "measured_pt": float("nan"), "mm_per_pt": float("nan")})
            continue
        a_, b_, L = min(cands, key=lambda c: abs(c[2] * best[0] - real))
        if abs(L * best[0] - real) / real > 0.03:
            out.append({"label": label, "stated_mm": real, "axis": "?", "p1": [x, y], "p2": [x, y],
                        "snapped": [False, False],
                        "snap_to": f"no line near this point agrees with the others (closest implies {real / L:.2f} mm/pt)",
                        "measured_pt": float("nan"), "mm_per_pt": float("nan")})
            continue
        ux, uy = b_[0] - a_[0], b_[1] - a_[1]
        out.append({"label": label, "stated_mm": real, "axis": "x" if abs(ux) >= abs(uy) else "y",
                    "p1": [round(a_[0], 3), round(a_[1], 3)], "p2": [round(b_[0], 3), round(b_[1], 3)],
                    "snapped": [True, True], "snap_to": "dimension line (tick to tick)",
                    "measured_pt": round(L, 4), "mm_per_pt": real / L})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("walls")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dim", action="append", default=[],
                    help='"x,y,real_mm[,label]": a point on or right next to a dimension line (e.g. at its '
                         'number); the matching tick-to-tick segment is found automatically (preferred)')
    ap.add_argument("--pdf", help="the plan PDF, if it moved since extract_walls.py ran")
    ap.add_argument("--dim-search", type=float, default=3.5, help="pt – how far from --dim points to look")
    ap.add_argument("--pair", action="append", default=[],
                    help='"x1,y1,x2,y2,real_mm[,label]" in pt')
    ap.add_argument("--snap", choices=["dims", "walls", "none"], default="dims")
    ap.add_argument("--dim-layer", action="append",
                    help='layer(s) holding dimension line work (default "fill #000000" and black strokes)')
    ap.add_argument("--check", action="append", default=[],
                    help='"x1,y1,x2,y2,real_mm[,label]" clear span between wall faces, for the face-bias check')
    ap.add_argument("--faces", choices=["clear", "nearest"], default="clear",
                    help="for --snap walls and --check: snap to the room-facing wall face (clear span) or any face")
    ap.add_argument("--radius", type=float, default=1.5, help="max snap distance in pt")
    ap.add_argument("--tolerance-mm", type=float, default=40.0,
                    help="allowed error per dimension, in mm ...")
    ap.add_argument("--tolerance-pct", type=float, default=1.5,
                    help="... or in percent of the stated length, whichever is larger")
    a = ap.parse_args()

    w = read_json(a.walls)
    if a.pdf:
        w["source_pdf"] = a.pdf
    wg = from_geojson(w["walls"])
    if w.get("walls_from_hatch"):
        # snap only to faces drawn in the PDF, not to hatch envelopes
        wg = wg.difference(from_geojson(w["walls_from_hatch"]).buffer(0.05))
    wall_edges = list(edges_of(wg))
    inside = prep(wg) if a.faces == "clear" else None
    if a.snap == "dims":
        dim_edges = line_work(w, a.dim_layer or ["fill #000000", "stroke #000000"])

    def measure(raw, mode):
        parts = [s_.strip() for s_ in raw.split(",")]
        x1, y1, x2, y2, real = map(float, parts[:5])
        label = ",".join(parts[5:]) or f"{real:g} mm"
        L = math.hypot(x2 - x1, y2 - y1)
        u = ((x2 - x1) / L, (y2 - y1) / L)
        t1 = t2 = 0.0
        snapped = [False, False]
        if mode == "dims":
            # 1) CAD dimension lines are usually a separate segment from tick to
            #    tick: find the parallel segment whose ends match the given ends.
            best = None
            for (ax, ay), (bx, by) in dim_edges:
                ex, ey = bx - ax, by - ay
                le = math.hypot(ex, ey)
                if le < 0.5 * L or abs((ex * u[0] + ey * u[1]) / le) < 0.995:
                    continue
                if (ex * u[0] + ey * u[1]) < 0:
                    (ax, ay), (bx, by) = (bx, by), (ax, ay)
                if math.dist((ax, ay), (x1, y1)) > a.radius or math.dist((bx, by), (x2, y2)) > a.radius:
                    continue
                off = abs((ax - x1) * u[1] - (ay - y1) * u[0])
                score = off + math.dist((ax, ay), (x1, y1)) + math.dist((bx, by), (x2, y2))
                if best is None or score < best[0]:
                    best = (score, (ax, ay), (bx, by), le)
            if best is not None:
                _, pa, pb, le = best
                return {"label": label, "stated_mm": real, "axis": "x" if abs(u[0]) >= abs(u[1]) else "y",
                        "p1": [round(pa[0], 3), round(pa[1], 3)], "p2": [round(pb[0], 3), round(pb[1], 3)],
                        "snapped": [True, True], "snap_to": "dimension line",
                        "measured_pt": round(le, 4), "mm_per_pt": real / le}
            # 2) otherwise snap each end to the extension line / tick crossing it.
            s1 = snap((x1, y1), u, dim_edges, a.radius, max_dot=0.75)
            s2 = snap((x2, y2), u, dim_edges, a.radius, max_dot=0.75)
        elif mode == "walls":
            s1 = snap((x1, y1), u, wall_edges, a.radius + 0.5, inside, +1)
            s2 = snap((x2, y2), u, wall_edges, a.radius + 0.5, inside, -1)
        else:
            s1 = s2 = None
        if s1 is not None:
            t1, snapped[0] = s1, True
        if s2 is not None:
            t2, snapped[1] = s2, True
        measured = L + t2 - t1
        return {"label": label, "stated_mm": real, "axis": "x" if abs(u[0]) >= abs(u[1]) else "y",
                "p1": [round(x1 + u[0] * t1, 3), round(y1 + u[1] * t1, 3)],
                "p2": [round(x2 + u[0] * t2, 3), round(y2 + u[1] * t2, 3)],
                "snapped": snapped, "snap_to": {"dims": "extension lines / ticks", "walls": "wall faces"}.get(mode, "none"),
                "measured_pt": round(measured, 4), "mm_per_pt": real / measured}

    samples = [measure(r, a.snap) for r in a.pair]
    if a.dim:
        if a.snap != "dims":
            dim_edges = line_work(w, a.dim_layer or ["fill #000000", "stroke #000000"])
        samples += dims_by_consensus(a.dim, dim_edges, a.dim_search)
    if not samples:
        raise SystemExit("give --dim (preferred) or --pair dimensions")
    lsq = lambda ss: sum(x["stated_mm"] * x["measured_pt"] for x in ss) / sum(x["measured_pt"] ** 2 for x in ss)
    found = [x for x in samples if x["measured_pt"] == x["measured_pt"]]
    missing = [x["label"] for x in samples if x not in found]
    samples = found
    scale = lsq(samples)
    axis_scale = {}
    for ax in ("x", "y"):
        ss = [x for x in samples if x["axis"] == ax]
        if len(ss) >= 2:
            axis_scale[ax] = round(lsq(ss), 4)
    aniso = abs(axis_scale["x"] - axis_scale["y"]) / scale * 100 if len(axis_scale) == 2 else None

    worst = 0.0
    bad = []
    for s_ in samples:
        s_["remeasured_mm"] = round(s_["measured_pt"] * scale, 1)
        s_["error_mm"] = round(s_["remeasured_mm"] - s_["stated_mm"], 1)
        s_["error_pct"] = round(100 * s_["error_mm"] / s_["stated_mm"], 2)
        s_["mm_per_pt"] = round(s_["mm_per_pt"], 4)
        worst = max(worst, abs(s_["error_mm"]))
        allowed = max(a.tolerance_mm, a.tolerance_pct / 100 * s_["stated_mm"])
        s_["within_tolerance"] = abs(s_["error_mm"]) <= allowed
        if not s_["within_tolerance"]:
            bad.append(s_["label"])

    unsnapped = sum(1 for s_ in samples for k in s_["snapped"] if not k)
    if len(samples) < 2:
        status, why = "UNRESOLVED", "only one dimension – cannot cross-check the scale"
    elif bad:
        status, why = "UNRESOLVED", f"{len(bad)} dimension(s) outside tolerance: {', '.join(bad)}"
    elif aniso is not None and aniso > 1.0:
        status, why = "UNRESOLVED", f"horizontal and vertical scales differ by {aniso:.1f}% – PDF may be stretched"
    elif len(samples) < 3:
        status, why = "DERIVED", "two dimensions agree; add a third for VERIFIED"
    else:
        what = "dimension lines" if a.snap == "dims" else "dimensions"
        status, why = "VERIFIED", f"{len(samples)} {what} agree within {worst:.0f} mm"
        if missing:
            why += f"; {len(missing)} dimension(s) had no matching line and were not used"
    if unsnapped and status == "VERIFIED":
        status, why = "DERIVED", why + f"; {unsnapped} end(s) not snapped"

    checks = []
    for raw in a.check:
        c = measure(raw, "walls")
        c["model_mm"] = round(c["measured_pt"] * scale, 1)
        c["error_mm"] = round(c["model_mm"] - c["stated_mm"], 1)
        for k in ("mm_per_pt",):
            c.pop(k)
        checks.append(c)
    bias = round(statistics.mean(c["error_mm"] for c in checks if all(c["snapped"])), 1) if any(all(c["snapped"]) for c in checks) else None

    result = {
        "mm_per_pt": round(scale, 5),
        "paper_scale_equivalent": f"1:{round(scale / (25.4 / 72))}",
        "method": a.snap,
        "status": status, "reason": why,
        "tolerance": {"mm": a.tolerance_mm, "pct": a.tolerance_pct},
        "worst_error_mm": round(worst, 1),
        "axis_scale": axis_scale, "anisotropy_pct": round(aniso, 2) if aniso is not None else None,
        "samples": samples,
        "dimensions_not_found": missing,
        "face_checks": checks,
        "face_bias_mm": bias,
    }
    write_json(a.out, result)
    print(f"scale = {scale:.4f} mm/pt   ({result['paper_scale_equivalent']} on this PDF, method {a.snap})   {status}: {why}")
    if axis_scale:
        print(f"  per-axis: {axis_scale}" + (f"  (differ {aniso:.2f}%)" if aniso is not None else ""))
    for s_ in samples:
        print(f"  {s_['label']:<34} stated {s_['stated_mm']:>7.0f}  model {s_['remeasured_mm']:>8.1f}  "
              f"err {s_['error_mm']:>+6.1f} mm ({s_['error_pct']:+.1f}%)  snapped={s_['snapped']}"
              + ("" if s_["within_tolerance"] else "  <-- OUT"))
    if checks:
        print(f"wall-face checks (clear spans on the model, not used for scale): mean bias {bias} mm")
        for c in checks:
            print(f"  {c['label']:<34} stated {c['stated_mm']:>7.0f}  model {c['model_mm']:>8.1f}  "
                  f"err {c['error_mm']:>+6.1f} mm  snapped={c['snapped']}")


if __name__ == "__main__":
    main()
