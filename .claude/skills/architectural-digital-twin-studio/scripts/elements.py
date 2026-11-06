"""Building elements derived from the plan: doors (with swing), windows,
openings, lintels, balconies with railings, stair flights, lift shafts and
apartment grouping. Used by build_model.py.

Status rules
- Plan positions/widths of openings come from the PDF geometry → VERIFIED
  when the scale is VERIFIED.
- Door swing (hinge side, opening side) from the drawn arc → DERIVED.
- Heights not printed for each element (door head, sill, railing, stair rise)
  → UNRESOLVED, with the assumed value stated.
"""
import math

from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import unary_union

DOOR_MAX_MM = 1300.0


def _rect(cx, cy, ux, uy, w, d):
    nx, ny = -uy, ux
    return Polygon([(cx + ux * w / 2 + nx * d / 2, cy + uy * w / 2 + ny * d / 2),
                    (cx - ux * w / 2 + nx * d / 2, cy - uy * w / 2 + ny * d / 2),
                    (cx - ux * w / 2 - nx * d / 2, cy - uy * w / 2 - ny * d / 2),
                    (cx + ux * w / 2 - nx * d / 2, cy + uy * w / 2 - ny * d / 2)])


def build_elements(E, to_mm_pt, s, slab, walls, rooms, H, status_geo, assume):
    """E: elements.json; to_mm_pt(x, y) -> (X, Y) in model mm; s: mm per pt."""
    interior = unary_union([Polygon(p.exterior) for p in getattr(
        walls.buffer(1500, join_style="mitre").buffer(-1500, join_style="mitre"), "geoms",
        [walls.buffer(1500, join_style="mitre").buffer(-1500, join_style="mitre")])])
    balconies_g = slab.difference(interior.buffer(50))
    balconies = []
    for k, g in enumerate(getattr(balconies_g, "geoms", [balconies_g])):
        if g.geom_type != "Polygon" or g.area < 1.5e6:
            continue
        g = g.buffer(-30).buffer(30)
        if g.is_empty or g.geom_type != "Polygon":
            continue
        rail = g.exterior.difference(interior.buffer(120))
        rail_lines = [list(l.coords) for l in getattr(rail, "geoms", [rail]) if l.geom_type == "LineString" and l.length > 300]
        balconies.append({"id": f"B{k + 1:02d}", "status": "DERIVED",
                          "reason": "slab outside the wall envelope (balcony tile hatch area)",
                          "area_m2": round(g.area / 1e6, 2),
                          "polygon": [[round(x, 1), round(y, 1)] for x, y in g.exterior.coords],
                          "railing": {"lines": [[[round(x, 1), round(y, 1)] for x, y in ln] for ln in rail_lines],
                                      "height_mm": assume["railing"], "height_status": "UNRESOLVED"}})

    # ---- openings → doors / windows / passages
    doors, windows, passages, lintels = [], [], [], []
    for i, o in enumerate(E.get("openings", [])):
        cx, cy = to_mm_pt(*o["center"])
        ux, uy = o["axis"][0], -o["axis"][1]          # page y is flipped
        w, dpt = o["width_pt"] * s, o["depth_pt"] * s
        nx, ny = -uy, ux
        side_pts = [Point(cx + nx * (dpt / 2 + 450), cy + ny * (dpt / 2 + 450)),
                    Point(cx - nx * (dpt / 2 + 450), cy - ny * (dpt / 2 + 450))]
        outside = [not interior.contains(p) for p in side_pts]
        exterior = any(outside)
        base = {"id": f"O{i + 1:03d}", "center": [round(cx, 1), round(cy, 1)], "axis": [round(ux, 5), round(uy, 5)],
                "width_mm": round(w), "depth_mm": round(dpt), "status": status_geo, "exterior": exterior}
        D = o.get("door")
        if D and w <= DOOR_MAX_MM:
            hu = D["hinge_u"]
            on = -D["opens_n"]                          # flip with the page y axis
            hx = cx + ux * hu * w / 2 + nx * on * dpt / 2
            hy = cy + uy * hu * w / 2 + ny * on * dpt / 2
            base.update({"kind": "door", "head_mm": assume["door_head"], "head_status": "UNRESOLVED",
                         "swing": {"hinge": [round(hx, 1), round(hy, 1)], "closed_dir": [round(-hu * ux, 5), round(-hu * uy, 5)],
                                   "open_dir": [round(on * nx, 5), round(on * ny, 5)], "status": "DERIVED",
                                   "arc_coverage": D["arc_coverage"]}})
            doors.append(base)
            head = assume["door_head"]
            sill = 0
        elif exterior:
            full = w >= assume["full_height_min_width"]
            sill = 0 if full else assume["sill"]
            head = assume["window_head"]
            base.update({"kind": "window", "sill_mm": sill, "head_mm": head, "height_status": "UNRESOLVED",
                         "type": "full-height glazing" if full else "window"})
            windows.append(base)
        else:
            head = assume["door_head"]
            sill = 0
            base.update({"kind": "opening", "head_mm": head, "head_status": "UNRESOLVED"})
            passages.append(base)
        rect = _rect(cx, cy, ux, uy, w, dpt)
        if head < H:
            lintels.append({"of": base["id"], "z0": head, "z1": H, "status": "DERIVED",
                            "polygon": [[round(x, 1), round(y, 1)] for x, y in rect.exterior.coords]})
        if sill > 0:
            lintels.append({"of": base["id"], "z0": 0, "z1": sill, "status": "DERIVED",
                            "polygon": [[round(x, 1), round(y, 1)] for x, y in rect.exterior.coords]})

    # ---- stair flights and lift shafts from line work
    lines = []
    for x1, y1, x2, y2 in E.get("lines", []):
        a = to_mm_pt(x1, y1)
        b = to_mm_pt(x2, y2)
        lines.append((a, b))
    stairs, shafts = [], []
    for r in rooms:
        if r.get("type") != "stair" or "geometry" not in r:
            continue
        poly = Polygon(r["geometry"]["exterior"], r["geometry"]["holes"])
        inside = [(a, b) for a, b in lines if poly.buffer(-50).contains(LineString([a, b]).centroid)
                  and 700 <= math.dist(a, b) <= 2200]
        groups = {}
        for a, b in inside:
            ang = round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180 / 3) * 3
            groups.setdefault(ang, []).append((a, b))
        for ang, segs in groups.items():
            if len(segs) < 4:
                continue
            th = math.radians(ang)
            ux, uy = math.cos(th), math.sin(th)
            nx, ny = -uy, ux
            offs = sorted(((a[0] + b[0]) / 2 * nx + (a[1] + b[1]) / 2 * ny, (a, b)) for a, b in segs)
            run = [offs[0]]
            best = []
            for o in offs[1:]:
                gap = o[0] - run[-1][0]
                if 220 <= gap <= 340:
                    run.append(o)
                elif gap < 60:
                    continue
                else:
                    if len(run) > len(best):
                        best = run
                    run = [o]
            if len(run) > len(best):
                best = run
            if len(best) < 4:
                continue
            gaps = [best[k + 1][0] - best[k][0] for k in range(len(best) - 1)]
            going = sorted(gaps)[len(gaps) // 2]
            treads = []
            for _, (a, b) in best:
                treads.append([[round(a[0], 1), round(a[1], 1)], [round(b[0], 1), round(b[1], 1)]])
            width = sorted(math.dist(a, b) for _, (a, b) in best)[len(best) // 2]
            stairs.append({"space": r.get("name"), "status": "DERIVED", "treads": treads,
                           "going_mm": round(going), "going_status": status_geo, "width_mm": round(width),
                           "rise_mm": assume["rise"], "rise_status": "UNRESOLVED",
                           "direction_status": "UNRESOLVED", "normal": [round(nx, 5), round(ny, 5)]})
    # lift symbol: two lines crossing at their middles. The diagonals are
    # often broken around a label, so first merge collinear pieces.
    long_lines = [(a, b) for a, b in _merge_collinear([(a, b) for a, b in lines if math.dist(a, b) >= 300])
                  if 1000 <= math.dist(a, b) <= 3200]
    used = set()
    for i, (a1, b1) in enumerate(long_lines):
        for j in range(i + 1, len(long_lines)):
            if i in used or j in used:
                continue
            a2, b2 = long_lines[j]
            m1 = ((a1[0] + b1[0]) / 2, (a1[1] + b1[1]) / 2)
            m2 = ((a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2)
            if math.dist(m1, m2) > 150 or abs(math.dist(a1, b1) - math.dist(a2, b2)) > 300:
                continue
            v1 = (b1[0] - a1[0], b1[1] - a1[1])
            v2 = (b2[0] - a2[0], b2[1] - a2[1])
            cosang = abs(v1[0] * v2[0] + v1[1] * v2[1]) / (math.hypot(*v1) * math.hypot(*v2))
            if cosang > 0.6:
                continue
            car = MultiPoint([a1, b1, a2, b2]).minimum_rotated_rectangle
            hole = next((Polygon(rr["geometry"]["exterior"]) for rr in rooms if "geometry" in rr
                         and Polygon(rr["geometry"]["exterior"]).contains(Point(m1))
                         and Polygon(rr["geometry"]["exterior"]).area < 9e6), None)
            cc = list(car.exterior.coords)
            sides = sorted([math.dist(cc[0], cc[1]), math.dist(cc[1], cc[2])])
            if not (850 <= sides[0] and sides[1] <= 2600):
                continue  # a lift car is roughly 1–2.5 m a side
            in_stair = any(rr.get("type") == "stair" and "geometry" in rr and
                           Polygon(rr["geometry"]["exterior"]).contains(Point(m1)) for rr in rooms)
            if in_stair:
                continue
            shaft = hole if hole is not None and hole.area < 6e6 else car.buffer(120, join_style="mitre")
            shafts.append({"kind": "lift", "status": "DERIVED", "reason": "lift car symbol (X) on the plan",
                           "car": [[round(x, 1), round(y, 1)] for x, y in car.exterior.coords],
                           "polygon": [[round(x, 1), round(y, 1)] for x, y in shaft.exterior.coords]})
            used.update((i, j))

    return {"doors": doors, "windows": windows, "openings": passages, "lintels": lintels,
            "balconies": balconies, "stairs": stairs, "shafts": shafts}


def _merge_collinear(segs, ang_tol=3.0, off_tol=90.0, gap_tol=700.0):
    """Join segments that lie on the same line (distance of the new piece's
    ends to the merged line ≤ off_tol mm) with gaps up to gap_tol mm."""
    merged = []  # [a, b] endpoints

    def ang(a, b):
        return math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi

    for a, b in sorted(segs, key=lambda q: -math.dist(*q)):
        placed = False
        for m in merged:
            da = abs(ang(a, b) - ang(*m))
            da = min(da, math.pi - da)
            if math.degrees(da) > ang_tol:
                continue
            (mx1, my1), (mx2, my2) = m
            L = math.dist(m[0], m[1])
            ux, uy = (mx2 - mx1) / L, (my2 - my1) / L
            d1 = abs((a[0] - mx1) * uy - (a[1] - my1) * ux)
            d2 = abs((b[0] - mx1) * uy - (b[1] - my1) * ux)
            if max(d1, d2) > off_tol:
                continue
            ta = (a[0] - mx1) * ux + (a[1] - my1) * uy
            tb = (b[0] - mx1) * ux + (b[1] - my1) * uy
            lo, hi = min(ta, tb), max(ta, tb)
            if lo > L + gap_tol or hi < -gap_tol:
                continue
            t0, t1 = min(0, lo), max(L, hi)
            m[0] = (mx1 + ux * t0, my1 + uy * t0)
            m[1] = (mx1 + ux * t1, my1 + uy * t1)
            placed = True
            break
        if not placed:
            merged.append([tuple(a), tuple(b)])
    return [tuple(m) for m in merged]


def apartments(rooms):
    units = {}
    for idx, r in enumerate(rooms):
        u = r.get("unit")
        if r.get("type") == "stair" and not u:
            u = "common"
        if not u:
            continue
        a = units.setdefault(u, {"unit": u, "rooms": [], "closed_area_m2": 0.0,
                                 "status": "DERIVED", "reason": "rooms grouped by the apartment label read on the plan"})
        a["rooms"].append(idx)
        a["closed_area_m2"] = round(a["closed_area_m2"] + (r.get("net_area_m2") or 0), 2)
    return list(units.values())


def _ring(poly):
    return [[round(x, 1), round(y, 1)] for x, y in poly.exterior.coords]


def element_solids(el, H):
    """Flatten elements into extrudable solids shared by GLB, IFC and the viewer:
    {cls, name, status, polygon (mm), z0, h, mat}."""
    out = []
    for L in el.get("lintels", []):
        out.append({"cls": "IfcWall", "name": f"Lintel {L['of']}", "status": L["status"], "polygon": L["polygon"],
                    "z0": L["z0"], "h": L["z1"] - L["z0"], "mat": "wall"})
    for d in el.get("doors", []):
        sw = d["swing"]
        hx, hy = sw["hinge"]
        cdx, cdy = sw["closed_dir"]
        odx, ody = sw["open_dir"]
        a0 = math.atan2(cdy, cdx)
        a1 = math.atan2(ody, odx)
        da = math.atan2(math.sin(a1 - a0), math.cos(a1 - a0))
        ang = a0 + da * (28 / 90)          # leaf drawn ~28° open so the swing reads in 3D
        L = d["width_mm"] - 30
        ux, uy = math.cos(ang), math.sin(ang)
        leaf = _rect(hx + ux * L / 2, hy + uy * L / 2, ux, uy, L, 40)
        out.append({"cls": "IfcDoor", "name": f"Door {d['id']}", "status": sw["status"], "polygon": _ring(leaf),
                    "z0": 0, "h": d["head_mm"] - 10, "mat": "oak"})
    for w in el.get("windows", []):
        cx, cy = w["center"]
        ux, uy = w["axis"]
        g = _rect(cx, cy, ux, uy, max(w["width_mm"] - 60, 100), 24)
        out.append({"cls": "IfcWindow", "name": f"{w['type'].capitalize()} {w['id']}", "status": w["status"],
                    "polygon": _ring(g), "z0": w["sill_mm"], "h": w["head_mm"] - w["sill_mm"], "mat": "glass"})
    for b in el.get("balconies", []):
        out.append({"cls": "IfcCovering", "name": f"Balcony {b['id']} floor", "status": b["status"],
                    "polygon": b["polygon"], "z0": 0, "h": 15, "mat": "travertine"})
        for ln in b["railing"]["lines"]:
            ls = LineString(ln)
            out.append({"cls": "IfcRailing", "name": f"Railing {b['id']}", "status": "UNRESOLVED",
                        "polygon": _ring(ls.buffer(12, cap_style="flat", join_style="mitre")),
                        "z0": 0, "h": b["railing"]["height_mm"], "mat": "glass"})
            out.append({"cls": "IfcRailing", "name": f"Handrail {b['id']}", "status": "UNRESOLVED",
                        "polygon": _ring(ls.buffer(25, cap_style="flat", join_style="mitre")),
                        "z0": b["railing"]["height_mm"], "h": 40, "mat": "black"})
    for k, st in enumerate(el.get("stairs", [])):
        nx, ny = st["normal"]
        for i, (a, b) in enumerate(st["treads"]):
            g = Polygon([a, b, (b[0] + nx * st["going_mm"], b[1] + ny * st["going_mm"]),
                         (a[0] + nx * st["going_mm"], a[1] + ny * st["going_mm"])])
            if not g.is_valid or g.area <= 0:
                continue
            out.append({"cls": "IfcStair", "name": f"Stair flight {k + 1}", "status": "DERIVED",
                        "polygon": _ring(g.buffer(0)), "z0": 0, "h": (i + 1) * st["rise_mm"], "mat": "travertine"})
    for k, sh in enumerate(el.get("shafts", [])):
        out.append({"cls": "IfcBuildingElementProxy", "name": f"Lift shaft {k + 1}", "status": sh["status"],
                    "polygon": sh["car"], "z0": 0, "h": H, "mat": "shaft"})
    return out
