#!/usr/bin/env python3
"""Step 5 – accuracy control. Run it before any visualisation work.

  qa_report.py work/floor/model --walls work/floor/walls.json [--pdf plan.pdf]

Checks
  1. Orthographic overlay: the walls are READ BACK from the exported DXF,
     mapped back onto the PDF page and compared pixel by pixel with the source
     wall geometry (IoU and deviation area). This proves the export, not just
     the in-memory model.
  2. Scale: every calibration dimension re-measured on the model.
  3. GLB and IFC round-trip: reopen the files and compare element counts and
     extents with model.json.
  4. Element status counts (VERIFIED / DERIVED / UNRESOLVED) and limitations.

Writes qa_report.json, qa_report.md and overlay.png into the model folder and
exits with code 1 if a blocking check fails.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import Polygon

from adt_common import from_geojson, iter_polygons, read_json, union, write_json


def raster(geom, x0, y0, s, size):
    im = Image.new("1", size, 0)
    dr = ImageDraw.Draw(im)
    for p in iter_polygons(geom):
        dr.polygon([((x - x0) * s, (y - y0) * s) for x, y in p.exterior.coords], fill=1)
        for h in p.interiors:
            dr.polygon([((x - x0) * s, (y - y0) * s) for x, y in h.coords], fill=0)
    return np.array(im, dtype=bool)


def dxf_walls(path):
    import ezdxf
    doc = ezdxf.readfile(path)
    rings = [list(e.get_points("xy")) for e in doc.modelspace().query('LWPOLYLINE[layer=="A-WALL"]')]
    polys = [Polygon(r) for r in rings if len(r) >= 3]
    polys.sort(key=lambda p: -p.area)
    # exterior rings contain their holes: even-odd combine
    g = Polygon()
    for p in polys:
        g = g.symmetric_difference(p.buffer(0))
    return g


def _parts_polys(lv):
    from furnish import part_polygon
    out = []
    for f_ in lv.get("furniture", []):
        for p in f_["parts"]:
            if p["h"] > 5:
                out.append((f_["space"], part_polygon(p)))
    return out


def clash_check(lv):
    """Hard clashes in plan: furniture inside walls, door swings sweeping
    through furniture, furniture of different spaces overlapping."""
    import math
    from shapely.geometry import Polygon as P_
    from shapely.ops import unary_union
    walls = unary_union([P_(w["geometry"]["exterior"], w["geometry"]["holes"]).buffer(0) for w in lv["walls"]])
    parts = _parts_polys(lv)
    out = []
    for sp, pg in parts:
        if pg.intersection(walls).area > 2500:  # > 0.0025 m²
            out.append({"what": f"furniture in {sp} cuts a wall", "kind": "furniture-wall"})
    for d in lv.get("elements", {}).get("doors", []):
        sw = d["swing"]
        hx, hy = sw["hinge"]
        a0 = math.atan2(sw["closed_dir"][1], sw["closed_dir"][0])
        a1 = math.atan2(sw["open_dir"][1], sw["open_dir"][0])
        da = math.atan2(math.sin(a1 - a0), math.cos(a1 - a0))
        sector = P_([(hx, hy)] + [(hx + math.cos(a0 + da * k / 12) * d["width_mm"], hy + math.sin(a0 + da * k / 12) * d["width_mm"]) for k in range(13)])
        for sp, pg in parts:
            if sector.intersection(pg).area > 2500:
                out.append({"what": f"door {d['id']} swings into furniture of {sp}", "kind": "door-furniture"})
                break
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            if parts[i][0] != parts[j][0] and parts[i][1].intersection(parts[j][1]).area > 2500:
                out.append({"what": f"furniture of {parts[i][0]} overlaps {parts[j][0]}", "kind": "furniture-furniture"})
    return out


def continuity(below, above):
    """Register two floors (their sheets are placed differently on the page)
    by the translation that best overlays their walls, then compare the
    building envelopes and the lift/stair cores."""
    import numpy as np
    from PIL import Image, ImageDraw
    from shapely.geometry import Polygon as P_
    from shapely import affinity
    from shapely.ops import unary_union

    def wall_geom(M):
        return unary_union([P_(w["geometry"]["exterior"], w["geometry"]["holes"]).buffer(0) for w in M["levels"][0]["walls"]])

    def env(M):
        return unary_union([P_(g["exterior"]).buffer(0) for g in M["levels"][0]["slab"]["geometry"]])

    A, B = wall_geom(below), wall_geom(above)
    res = 100.0
    x0 = min(A.bounds[0], B.bounds[0]) - 3000
    y0 = min(A.bounds[1], B.bounds[1]) - 3000
    x1 = max(A.bounds[2], B.bounds[2]) + 3000
    y1 = max(A.bounds[3], B.bounds[3]) + 3000
    Wd, Ht = int((x1 - x0) / res), int((y1 - y0) / res)

    def ras(g):
        im = Image.new("L", (Wd, Ht), 0)
        d = ImageDraw.Draw(im)
        for p in getattr(g, "geoms", [g]):
            if p.geom_type != "Polygon":
                continue
            d.polygon([((x - x0) / res, (y - y0) / res) for x, y in p.exterior.coords], fill=1)
            for h in p.interiors:
                d.polygon([((x - x0) / res, (y - y0) / res) for x, y in h.coords], fill=0)
        return np.array(im, dtype=float)
    ra, rb = ras(A), ras(B)
    F = np.fft.ifft2(np.fft.fft2(ra) * np.conj(np.fft.fft2(rb))).real
    iy, ix = np.unravel_index(np.argmax(F), F.shape)
    if iy > Ht // 2:
        iy -= Ht
    if ix > Wd // 2:
        ix -= Wd
    dx, dy = ix * res, iy * res
    Bs = affinity.translate(env(above), dx, dy)
    Ea = env(below)
    iou = Ea.intersection(Bs).area / Ea.union(Bs).area
    lifts_a = [P_(s_["car"]) for s_ in below["levels"][0].get("elements", {}).get("shafts", [])]
    lifts_b = [affinity.translate(P_(s_["car"]), dx, dy) for s_ in above["levels"][0].get("elements", {}).get("shafts", [])]
    matched = sum(1 for la in lifts_a if any(la.intersection(lb).area > 0.5 * la.area for lb in lifts_b))
    # load-bearing concrete (safe rooms, cores) must stack: share of the lower
    # floor's concrete walls that the upper floor's walls cover
    conc = unary_union([P_(w["geometry"]["exterior"], w["geometry"]["holes"]).buffer(0)
                        for w in below["levels"][0]["walls"] if "concrete" in w.get("kind", "")])
    Bw = affinity.translate(B, dx, dy).buffer(150)
    core = conc.intersection(Bw).area / conc.area if not conc.is_empty and conc.area else 0.0
    return {"offset_mm": [dx, dy], "envelope_iou": round(iou, 4), "core_overlap": round(core, 3),
            "lifts_below": len(lifts_a), "lifts_above": len(lifts_b), "lifts_matched": matched}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("--walls", required=True)
    ap.add_argument("--pdf")
    ap.add_argument("--scale", help="scale.json (default: the copy inside model.json)")
    ap.add_argument("--px-per-pt", type=float, default=8.0)
    ap.add_argument("--min-iou", type=float, default=0.97)
    ap.add_argument("--floor-below", help="model folder of the floor below, for the continuity check")
    a = ap.parse_args()

    md = Path(a.model_dir)
    M = read_json(md / "model.json")
    W = read_json(a.walls)
    lv = M["levels"][0]
    s = M["scale"]["mm_per_pt"]
    minx, miny, maxx, maxy = M["source"]["pt_bounds"]
    checks = []

    def check(name, ok, detail, blocking=True):
        checks.append({"check": name, "pass": bool(ok), "blocking": blocking, "detail": detail})

    # 1. overlay – DXF walls back to page points vs source walls
    g_mm = dxf_walls(md / "plan.dxf")
    g_pt = affinity.affine_transform(g_mm, [1 / s, 0, 0, -1 / s, minx, maxy])
    src = from_geojson(W["walls"])
    small = [p for p in iter_polygons(src) if p.area * s * s < 0.03e6]
    src_walls = src.difference(union(small)) if small else src
    hatch = from_geojson(W["walls_from_hatch"]) if W.get("walls_from_hatch") else Polygon()
    k = a.px_per_pt
    m = 10
    size = (int((maxx - minx + 2 * m) * k), int((maxy - miny + 2 * m) * k))
    A = raster(src_walls, minx - m, miny - m, k, size)
    B = raster(g_pt, minx - m, miny - m, k, size)
    inter, uni = np.logical_and(A, B).sum(), np.logical_or(A, B).sum()
    iou = inter / uni if uni else 0
    px_mm2 = (s / k) ** 2
    only_src = np.logical_and(A, ~B).sum() * px_mm2 / 1e6
    only_model = np.logical_and(B, ~A).sum() * px_mm2 / 1e6
    check("Top-view overlay of exported DXF vs source walls", iou >= a.min_iou,
          f"IoU {iou:.4f}; missing in model {only_src:.3f} m², extra in model {only_model:.3f} m²")

    # overlay image: page underneath, source walls blue, model red, overlap dark
    if a.pdf:
        import pymupdf
        page = pymupdf.open(a.pdf)[W["page"] - 1]
        pix = page.get_pixmap(dpi=72 * min(k, 6), clip=pymupdf.Rect(minx - m, miny - m, maxx + m, maxy + m))
        base = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).resize(size)
        base = Image.blend(base, Image.new("RGB", size, "white"), 0.6)
    else:
        base = Image.new("RGB", size, "white")
    arr = np.array(base)
    arr[np.logical_and(A, ~B)] = (10, 132, 255)
    arr[np.logical_and(B, ~A)] = (255, 59, 48)
    arr[np.logical_and(A, B)] = (60, 60, 67)
    ov = Image.fromarray(arr)
    if max(size) > 4000:
        f = 4000 / max(size)
        ov = ov.resize((int(size[0] * f), int(size[1] * f)))
    ov.save(md / "overlay.png")

    # 2. scale
    sc = read_json(Path(a.scale)) if a.scale else M["scale"]
    check("Scale from printed dimensions", sc["status"] == "VERIFIED",
          f"{sc['mm_per_pt']} mm/pt ({sc.get('method', 'walls')}), {sc['status']}: {sc['reason']}")
    dims = [{"label": d["label"], "stated_mm": d["stated_mm"], "model_mm": d["remeasured_mm"],
             "error_mm": d["error_mm"], "ok": d.get("within_tolerance", True)} for d in sc["samples"]]
    faces = sc.get("face_checks") or []
    bias = sc.get("face_bias_mm")
    if faces:
        tol = sc.get("tolerance", {}).get("mm", 40)
        check("Room clear spans between model wall faces", bias is not None and abs(bias) <= tol,
              f"mean deviation {bias:+.1f} mm over {len(faces)} spans (negative = walls drawn thicker than dimensioned)",
              blocking=False)

    # 3. round-trips
    try:
        import trimesh
        sc3 = trimesh.load(md / "model.glb")
        ext = sc3.extents  # metres, Y-up
        exp_w = (M["extent_mm"][2] - M["extent_mm"][0]) / 1000
        exp_d = (M["extent_mm"][3] - M["extent_mm"][1]) / 1000
        ok = abs(ext[0] - exp_w) < 0.05 and abs(ext[2] - exp_d) < 0.05
        check("GLB reopens with the same footprint (m)", ok,
              f"GLB {ext[0]:.2f} x {ext[2]:.2f} x {ext[1]:.2f} m vs model {exp_w:.2f} x {exp_d:.2f} m")
    except Exception as e:  # noqa: BLE001
        check("GLB reopens", False, f"error: {e}")
    try:
        import ifcopenshell
        f = ifcopenshell.open(str(md / "model.ifc"))
        nw, ns, nsp = len(f.by_type("IfcWall")), len(f.by_type("IfcSlab")), len(f.by_type("IfcSpace"))
        exp_sp = sum(1 for r in lv["rooms"] if "geometry" in r)
        n_lint = len({es["name"] for es in lv.get("element_solids", []) if es["cls"] == "IfcWall"})
        check("IFC reopens with every element", nw == len(lv["walls"]) + n_lint and ns == len(lv["slab"]["geometry"]) and nsp == exp_sp,
              f"IfcWall {nw}/{len(lv['walls']) + n_lint} (walls + lintels), IfcSlab {ns}/{len(lv['slab']['geometry'])}, IfcSpace {nsp}/{exp_sp}")
    except Exception as e:  # noqa: BLE001
        check("IFC reopens", False, f"error: {e}")

    # 4. openings, clashes, continuity
    el = lv.get("elements", {})
    if el:
        n_o = len(el.get("doors", [])) + len(el.get("windows", [])) + len(el.get("openings", []))
        check("Openings found in the walls and classified", n_o > 0,
              f"{len(el.get('doors', []))} doors (swing from drawn arc), {len(el.get('windows', []))} windows, "
              f"{len(el.get('openings', []))} passages, {len(el.get('balconies', []))} balconies, "
              f"{len(el.get('stairs', []))} stair flights, {len(el.get('shafts', []))} lift shafts", blocking=False)
    clashes = clash_check(lv)
    check("Clash check (furniture vs walls, door swings vs furniture, overlaps)", not clashes,
          f"{len(clashes)} clash(es)" + (": " + "; ".join(c["what"] for c in clashes[:6]) if clashes else ""), blocking=False)
    cont = None
    if a.floor_below:
        cont = continuity(read_json(Path(a.floor_below) / "model.json"), M)
        check("Continuity with the floor below (lifts, concrete walls, envelope)",
              cont["lifts_matched"] == cont["lifts_below"] and cont["core_overlap"] >= 0.6 and cont["envelope_iou"] >= 0.7,
              f"after aligning the plans ({cont['offset_mm'][0]:+.0f}, {cont['offset_mm'][1]:+.0f} mm): envelope IoU "
              f"{cont['envelope_iou']:.3f} (balconies may differ by design), concrete walls stacked {cont['core_overlap']:.0%}, "
              f"lift shafts {cont['lifts_matched']}/{cont['lifts_below']} matched", blocking=False)

    # 5. status counts
    counts = {}
    for w in lv["walls"]:
        counts[w["status"]] = counts.get(w["status"], 0) + 1
    rooms = {}
    for r in lv["rooms"]:
        rooms[r["status"]] = rooms.get(r["status"], 0) + 1
    hatch_area = round(hatch.area * s * s / 1e6, 2) if not hatch.is_empty else 0
    unresolved = [f"wall height ({lv['wall_height_status']})"] if lv["wall_height_status"] != "VERIFIED" else []
    if lv["elevation_status"] != "VERIFIED":
        unresolved.append(f"level elevation ({lv['elevation_status']})")
    unresolved += [f"room '{r.get('name')}': {r.get('reason')}" for r in lv["rooms"] if r["status"] == "UNRESOLVED"]

    blocking_fail = [c for c in checks if c["blocking"] and not c["pass"]]
    result = {
        "verdict": "PASS" if not blocking_fail else "FAIL",
        "checks": checks,
        "dimensions": dims,
        "clashes": clashes, "continuity": cont,
        "face_checks": faces, "face_bias_mm": bias,
        "wall_status_counts": counts,
        "room_status_counts": rooms,
        "hatched_wall_area_m2": hatch_area,
        "unresolved": unresolved,
        "limitations": M.get("limitations", []),
    }
    write_json(md / "qa_report.json", result)

    L = [f"# Accuracy control – {M['project']} · {lv['name']}", "",
         f"**Verdict: {result['verdict']}**", "", "| Check | Result | Detail |", "|---|---|---|"]
    for c in checks:
        L.append(f"| {c['check']} | {'PASS' if c['pass'] else 'FAIL'} | {c['detail']} |")
    L += ["", "## Dimensions (stated on plan vs measured on model)", "", "| Dimension | Plan (mm) | Model (mm) | Error (mm) |", "|---|---:|---:|---:|"]
    for d in dims:
        L.append(f"| {d['label']} | {d['stated_mm']:.0f} | {d['model_mm']:.1f} | {d['error_mm']:+.1f} |")
    if faces:
        L += ["", "## Room clear spans (model wall faces vs plan, not used for the scale)", "",
              "| Span | Plan (mm) | Model (mm) | Error (mm) |", "|---|---:|---:|---:|"]
        for c in faces:
            L.append(f"| {c['label']} | {c['stated_mm']:.0f} | {c['model_mm']:.1f} | {c['error_mm']:+.1f} |")
        L.append(f"\nMean deviation: {bias:+.1f} mm.")
    L += ["", "## Element status", "",
          f"- Walls: " + ", ".join(f"{k} {v}" for k, v in counts.items()),
          f"- Spaces: " + ", ".join(f"{k} {v}" for k, v in rooms.items()),
          f"- Concrete walls traced from hatch (DERIVED): {hatch_area} m² in plan", "",
          "## Unresolved", ""] + [f"- {u}" for u in unresolved or ["none"]] + ["", "## Limitations", ""] + \
         [f"- {x}" for x in M.get("limitations", [])] + ["", "Overlay: `overlay.png` – grey = match, blue = in plan only, red = in model only."]
    (md / "qa_report.md").write_text("\n".join(L), encoding="utf-8")

    for c in checks:
        print(f"[{'PASS' if c['pass'] else 'FAIL'}] {c['check']}: {c['detail']}")
    print(f"verdict: {result['verdict']}  ->  {md/'qa_report.md'}")
    sys.exit(0 if not blocking_fail else 1)


if __name__ == "__main__":
    main()
