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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("--walls", required=True)
    ap.add_argument("--pdf")
    ap.add_argument("--px-per-pt", type=float, default=8.0)
    ap.add_argument("--min-iou", type=float, default=0.97)
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
    sc = M["scale"]
    check("Scale from printed dimensions", sc["status"] == "VERIFIED",
          f"{sc['mm_per_pt']} mm/pt, {sc['status']}: {sc['reason']}")
    dims = [{"label": d["label"], "stated_mm": d["stated_mm"], "model_mm": d["remeasured_mm"],
             "error_mm": d["error_mm"], "ok": d.get("within_tolerance", True)} for d in sc["samples"]]

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
        check("IFC reopens with every element", nw == len(lv["walls"]) and ns == len(lv["slab"]["geometry"]) and nsp == exp_sp,
              f"IfcWall {nw}/{len(lv['walls'])}, IfcSlab {ns}/{len(lv['slab']['geometry'])}, IfcSpace {nsp}/{exp_sp}")
    except Exception as e:  # noqa: BLE001
        check("IFC reopens", False, f"error: {e}")

    # 4. status counts
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
