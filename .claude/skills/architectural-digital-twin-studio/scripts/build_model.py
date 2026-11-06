#!/usr/bin/env python3
"""Step 4 – build the measured 1:1 model and export it.

  build_model.py work/floor/walls.json work/floor/scale.json --out work/floor/model \
      --level-name "Floor 1" --elevation-mm 3500 --wall-height-mm 2700 \
      [--wall-height-status VERIFIED|DERIVED|UNRESOLVED] [--rooms rooms.json] \
      [--room-close-mm 1000] [--slab-close-mm 1500] [--slab-thickness-mm 200]

rooms.json (optional) names spaces you read on the plan; each point is any
spot inside the room, in pt from the walls grid:
  [{"name": "חדר", "name_en": "Bedroom", "unit": "30", "x": 195, "y": 200}, ...]

Model axes (millimetres): X to the right of the page, Y up the page, Z up.
Exports: model.json (single source of truth), plan.dxf, model.glb (metres, as
glTF requires), model.ifc (IFC4), top.png (orthographic top view).
"""
import argparse
import datetime as dt
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import Point, Polygon, mapping

from shapely.geometry import LineString

from adt_common import from_geojson, iter_polygons, read_json, thickness, union, write_json
from elements import apartments, build_elements, element_solids
from furnish import MATERIALS, RECIPES, _frame, eye_view, free_area, furnish_space, part_polygon, room_type


def to_mm(geom, s, minx, maxy):
    # x' = (x - minx) * s ; y' = (maxy - y) * s   (flip so Y points up the page)
    return affinity.affine_transform(geom, [s, 0, 0, -s, -minx * s, maxy * s])


def rings(poly):
    return {
        "exterior": [[round(x, 1), round(y, 1)] for x, y in poly.exterior.coords],
        "holes": [[[round(x, 1), round(y, 1)] for x, y in h.coords] for h in poly.interiors],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("walls")
    ap.add_argument("scale")
    ap.add_argument("--out", required=True)
    ap.add_argument("--level-name", default="Level 0")
    ap.add_argument("--elevation-mm", type=float, default=0.0)
    ap.add_argument("--elevation-status", default="UNRESOLVED")
    ap.add_argument("--wall-height-mm", type=float, default=2700.0)
    ap.add_argument("--wall-height-status", default="UNRESOLVED",
                    help="VERIFIED only if a section or note on the plan states it")
    ap.add_argument("--rooms")
    ap.add_argument("--room-close-mm", type=float, default=1000.0,
                    help="openings narrower than 2x this are bridged when finding rooms")
    ap.add_argument("--slab-close-mm", type=float, default=1500.0)
    ap.add_argument("--slab-thickness-mm", type=float, default=200.0)
    ap.add_argument("--min-body-m2", type=float, default=0.03,
                    help="wall bodies smaller than this are drawing symbols and are dropped")
    ap.add_argument("--elements", help="elements.json from extract_elements.py (doors, windows, stairs, lifts)")
    ap.add_argument("--assume-door-head-mm", type=float, default=2100)
    ap.add_argument("--assume-sill-mm", type=float, default=900)
    ap.add_argument("--assume-window-head-mm", type=float, default=2200)
    ap.add_argument("--assume-full-height-min-width-mm", type=float, default=1500)
    ap.add_argument("--assume-railing-mm", type=float, default=1050)
    ap.add_argument("--assume-rise-mm", type=float, default=175)
    ap.add_argument("--no-furniture", action="store_true", help="skip the VISUAL ONLY furniture layer")
    ap.add_argument("--project", default="Architectural Digital Twin")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    W = read_json(a.walls)
    S = read_json(a.scale)
    s = S["mm_per_pt"]
    walls_pt = from_geojson(W["walls"])
    aux_pt = from_geojson(W["aux"]) if W.get("aux") else Polygon()
    minx, miny, maxx, maxy = walls_pt.bounds
    walls = to_mm(walls_pt, s, minx, maxy)
    aux = to_mm(aux_pt, s, minx, maxy) if not aux_pt.is_empty else aux_pt

    geo_status = "VERIFIED" if S["status"] == "VERIFIED" else "DERIVED" if S["status"] == "DERIVED" else "UNRESOLVED"

    hatch_pt = from_geojson(W["walls_from_hatch"]) if W.get("walls_from_hatch") else Polygon()
    hatch = to_mm(hatch_pt, s, minx, maxy) if not hatch_pt.is_empty else hatch_pt
    solid_pt = from_geojson(W["walls_from_solid"]) if W.get("walls_from_solid") else Polygon()
    solid = to_mm(solid_pt, s, minx, maxy) if not solid_pt.is_empty else solid_pt

    # Walls: one element per connected wall body, straight from the source.
    # Tiny bodies are drawing symbols (section arrows, level marks), not walls.
    wall_items, symbols = [], 0
    bodies = []
    for p in iter_polygons(walls):
        if p.area < a.min_body_m2 * 1e6:
            symbols += 1
        else:
            bodies.append(p)
    walls = union(bodies)
    for i, p in enumerate(sorted(bodies, key=lambda g: -g.area)):
        from_hatch = (not hatch.is_empty) and p.intersection(hatch).area > 0.5 * p.area
        from_solid = (not solid.is_empty) and p.intersection(solid).area > 0.5 * p.area
        wall_items.append({
            "id": f"W{i + 1:03d}",
            "status": ("DERIVED" if geo_status == "VERIFIED" else geo_status) if from_hatch else geo_status,
            "kind": "concrete (hatched)" if from_hatch else "concrete (solid fill)" if from_solid else "wall",
            "source": "envelope of 45° hatch in the PDF" if from_hatch else "PDF vector wall layer",
            "area_m2": round(p.area / 1e6, 3),
            "typical_thickness_mm": round(thickness(p)),
            "geometry": rings(p),
        })

    # Slab outline: walls + slab hints (balcony hatch), gaps closed. DERIVED.
    r = a.slab_close_mm
    slab = union([walls, aux]).buffer(r, join_style="mitre", mitre_limit=4).buffer(-r, join_style="mitre", mitre_limit=4)
    slab = union([Polygon(p.exterior) for p in iter_polygons(slab) if p.area > 1e6])

    # Rooms: close door/window gaps, the enclosed holes are spaces.
    rc = a.room_close_mm
    closed = walls.buffer(rc, join_style="mitre", mitre_limit=4).buffer(-rc, join_style="mitre", mitre_limit=4)
    holes = []
    for p in iter_polygons(closed):
        for h in p.interiors:
            hp = Polygon(h)
            if hp.area > 1.0e6:  # > 1 m²
                holes.append(hp)
    rooms = []
    named = read_json(a.rooms) if a.rooms else []
    used = set()
    for rm in named:
        pt = to_mm(Point(rm["x"], rm["y"]), s, minx, maxy)
        hit = next((k for k, hp in enumerate(holes) if hp.contains(pt)), None)
        entry = {k: v for k, v in rm.items() if k not in ("x", "y")}
        entry["label_point_mm"] = [round(pt.x, 1), round(pt.y, 1)]
        if hit is None:
            entry.update({"status": "UNRESOLVED", "reason": "label point is not inside a closed space"})
        else:
            hp = holes[hit]
            used.add(hit)
            entry.update({
                "status": "DERIVED",
                "reason": f"space bounded by walls, openings < {2 * rc / 1000:g} m bridged",
                "net_area_m2": round(hp.area / 1e6, 2),
                "geometry": rings(hp),
            })
        rooms.append(entry)
    for k, hp in enumerate(holes):
        if k not in used:
            c = hp.representative_point()
            rooms.append({"name": "", "status": "DERIVED", "reason": "unnamed closed space",
                          "label_point_mm": [round(c.x, 1), round(c.y, 1)],
                          "net_area_m2": round(hp.area / 1e6, 2), "geometry": rings(hp)})

    for r_ in rooms:
        t_ = room_type(r_)
        if t_:
            r_["type"] = t_

    # ---- Building elements (doors, windows, balconies, stairs, lifts) -----
    elems = {"doors": [], "windows": [], "openings": [], "lintels": [], "balconies": [], "stairs": [], "shafts": []}
    if a.elements:
        E = read_json(a.elements)
        assume = {"door_head": a.assume_door_head_mm, "sill": a.assume_sill_mm, "window_head": a.assume_window_head_mm,
                  "full_height_min_width": a.assume_full_height_min_width_mm, "railing": a.assume_railing_mm,
                  "rise": a.assume_rise_mm}
        elems = build_elements(E, lambda x, y: ((x - minx) * s, (maxy - y) * s), s, slab, walls, rooms,
                               a.wall_height_mm, geo_status, assume)
    units = apartments(rooms)

    # ---- Dimensions layer -------------------------------------------------
    dims = []
    for smp in S["samples"]:  # dimension lines measured on the plan itself
        p1 = to_mm(Point(*smp["p1"]), s, minx, maxy)
        p2 = to_mm(Point(*smp["p2"]), s, minx, maxy)
        dims.append({"kind": "plan dimension", "status": "VERIFIED", "label": smp["label"],
                     "p1": [round(p1.x, 1), round(p1.y, 1)], "p2": [round(p2.x, 1), round(p2.y, 1)],
                     "stated_mm": smp["stated_mm"], "value_mm": smp.get("remeasured_mm"),
                     "text": f"{smp['stated_mm'] / 10:g}"})
    for r_ in rooms:  # clear spans of every closed space, through its centre
        if "geometry" not in r_:
            continue
        hp = Polygon(r_["geometry"]["exterior"], r_["geometry"]["holes"])
        cx, cy, ang, L, Wd = _frame(hp)
        for a_ in (ang, ang + math.pi / 2):
            ln = LineString([(cx - 1e5 * math.cos(a_), cy - 1e5 * math.sin(a_)),
                             (cx + 1e5 * math.cos(a_), cy + 1e5 * math.sin(a_))]).intersection(hp)
            segs = [g for g in getattr(ln, "geoms", [ln]) if g.geom_type == "LineString" and g.length > 0]
            if not segs:
                continue
            g = min(segs, key=lambda q: q.distance(Point(cx, cy)))
            (x1, y1), (x2, y2) = g.coords[0], g.coords[-1]
            dims.append({"kind": "room clear span", "status": "DERIVED", "label": r_.get("name") or "space",
                         "p1": [round(x1, 1), round(y1, 1)], "p2": [round(x2, 1), round(y2, 1)],
                         "value_mm": round(g.length), "text": f"{round(g.length / 10):g}"})
    if not slab.is_empty:  # overall extents, outside the slab
        sx0, sy0, sx1, sy1 = slab.bounds
        dims.append({"kind": "overall", "status": "DERIVED", "label": "overall width",
                     "p1": [round(sx0, 1), round(sy0 - 1200, 1)], "p2": [round(sx1, 1), round(sy0 - 1200, 1)],
                     "value_mm": round(sx1 - sx0), "text": f"{round((sx1 - sx0) / 10):g}"})
        dims.append({"kind": "overall", "status": "DERIVED", "label": "overall depth",
                     "p1": [round(sx0 - 1200, 1), round(sy0, 1)], "p2": [round(sx0 - 1200, 1), round(sy1, 1)],
                     "value_mm": round(sy1 - sy0), "text": f"{round((sy1 - sy0) / 10):g}"})

    # ---- Furniture layer (VISUAL ONLY) ------------------------------------
    furniture = []
    if not a.no_furniture:
        from shapely.ops import unary_union as _uu
        # door swings and already placed furniture are obstacles for every space;
        # closed rooms are furnished first, open-plan areas after them
        obst = []
        for d in elems.get("doors", []):
            sw = d["swing"]
            hx, hy = sw["hinge"]
            a0 = math.atan2(sw["closed_dir"][1], sw["closed_dir"][0])
            a1 = math.atan2(sw["open_dir"][1], sw["open_dir"][0])
            da = math.atan2(math.sin(a1 - a0), math.cos(a1 - a0))
            obst.append(Polygon([(hx, hy)] + [(hx + math.cos(a0 + da * k / 12) * (d["width_mm"] + 80),
                                                hy + math.sin(a0 + da * k / 12) * (d["width_mm"] + 80)) for k in range(13)]).buffer(0))
        for st in elems.get("stairs", []) + elems.get("shafts", []):
            pass
        order = sorted(rooms, key=lambda r_: 0 if "geometry" in r_ else 1)
        for r_ in order:
            t_ = r_.get("type")
            if t_ not in RECIPES:
                continue
            geom = Polygon(r_["geometry"]["exterior"], r_["geometry"]["holes"]) if "geometry" in r_ else None
            lab = r_.get("label_point_mm")
            free = free_area(walls, slab, geom, None if geom is not None else lab)
            if geom is None:
                # an open area must not spill into closed rooms
                closed = _uu([Polygon(q["geometry"]["exterior"]).buffer(0) for q in rooms if "geometry" in q])
                free = free.difference(closed)
                if hasattr(free, "geoms"):
                    from shapely.geometry import Point as _Pt
                    free = min((g for g in free.geoms if g.geom_type == "Polygon"), key=lambda g: g.distance(_Pt(lab)), default=Polygon())
            parts, note = furnish_space(t_, free, None if geom is not None else lab,
                                        obstacles=_uu(obst) if obst else None)
            for p_ in parts:
                if p_["h"] > 5:
                    obst.append(part_polygon(p_).buffer(150))
            furniture.append({"space": r_.get("name") or t_, "type": t_, "status": "VISUAL ONLY",
                              "note": note, "parts": parts, "view": eye_view(parts, free) if parts else None})

    bx0, by0, bx1, by1 = slab.bounds if not slab.is_empty else walls.bounds
    model = {
        "schema": "adt-model/1",
        "project": a.project,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "units": "mm",
        "axes": "X right on the page, Y up the page, Z up",
        "source": {
            "pdf": W["source_pdf"], "page": W["page"], "layers": W["layers"],
            "params": W["params"], "pt_bounds": [minx, miny, maxx, maxy],
            "underlay": W.get("underlay"),
        },
        "scale": {"mm_per_pt": s, "status": S["status"], "reason": S["reason"], "method": S.get("method"),
                  "worst_error_mm": S.get("worst_error_mm"), "samples": S["samples"],
                  "face_checks": S.get("face_checks", []), "face_bias_mm": S.get("face_bias_mm"),
                  "tolerance": S.get("tolerance")},
        "extent_mm": [round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)],
        "levels": [{
            "name": a.level_name,
            "elevation_mm": a.elevation_mm, "elevation_status": a.elevation_status,
            "wall_height_mm": a.wall_height_mm, "wall_height_status": a.wall_height_status,
            "slab_thickness_mm": a.slab_thickness_mm,
            "walls": wall_items,
            "slab": {"status": "DERIVED",
                     "reason": f"outline of walls and balcony hatch, gaps < {2 * r / 1000:g} m closed",
                     "area_m2": round(slab.area / 1e6, 2),
                     "geometry": [rings(p) for p in iter_polygons(slab)]},
            "rooms": rooms,
            "dimensions": dims,
            "furniture": furniture,
            "elements": elems,
            "element_solids": element_solids(elems, a.wall_height_mm),
            "apartments": units,
        }],
        "materials": MATERIALS,
        "layers": {
            "verified_geometry": "levels[].walls",
            "derived": "levels[].slab, levels[].rooms",
            "dimensions": "levels[].dimensions (plan dimension lines VERIFIED, room spans and extents DERIVED)",
            "furniture": "levels[].furniture (VISUAL ONLY, Modern Minimalist Luxury; never alters walls)",
        },
        "limitations": [],
    }
    lim = model["limitations"]
    if a.wall_height_status != "VERIFIED":
        lim.append(f"Wall height {a.wall_height_mm:g} mm is {a.wall_height_status}: not stated on the plan.")
    if a.elevation_status != "VERIFIED":
        lim.append(f"Level elevation {a.elevation_mm:g} mm is {a.elevation_status}.")
    if symbols:
        lim.append(f"{symbols} tiny bodies (< {a.min_body_m2} m²) on the wall layer were treated as drawing symbols and left out.")
    if a.elements:
        lim.append(f"Door heads ({a.assume_door_head_mm:g} mm), window sills ({a.assume_sill_mm:g} mm) and heads "
                   f"({a.assume_window_head_mm:g} mm), railings ({a.assume_railing_mm:g} mm) and stair rise "
                   f"({a.assume_rise_mm:g} mm) are not printed per element: UNRESOLVED, assumed values.")
        lim.append("Openings are taken from the wall fill; doors inside thin partitions drawn only as lines are not detected.")
    else:
        lim.append("No elements.json: doors and windows are full-height gaps; leaves, sills and heads are not modelled.")
    if not any(r_.get("unit") for r_ in rooms):
        lim.append("Apartments are not grouped: add \"unit\" to rooms.json from the apartment labels on the plan.")
    if S["status"] != "VERIFIED":
        lim.append(f"Scale is {S['status']}: {S['reason']}.")
    write_json(out / "model.json", model)

    export_dxf(model, out / "plan.dxf")
    export_glb(model, out / "model.glb")
    export_ifc(model, out / "model.ifc")
    render_top(model, out / "top.png")
    render_top(model, out / "top-dimensioned.png", dims=True, furniture=True, px_per_m=90)
    n_named = sum(1 for r_ in rooms if r_.get("name"))
    print(f"model: {len(wall_items)} wall bodies, slab {model['levels'][0]['slab']['area_m2']} m², "
          f"{len(rooms)} spaces ({n_named} named), extent {round((bx1-bx0)/1000,2)} x {round((by1-by0)/1000,2)} m")
    nf = sum(len(f_["parts"]) > 0 for f_ in furniture)
    print(f"layers: {len(dims)} dimensions, furniture in {nf}/{len(furniture)} spaces")
    print(f"elements: {len(elems['doors'])} doors, {len(elems['windows'])} windows, {len(elems['openings'])} openings, "
          f"{len(elems['balconies'])} balconies, {len(elems['stairs'])} stair flights, {len(elems['shafts'])} lift shafts, "
          f"{len(units)} apartment groups")
    print(f"wrote {out}/model.json, plan.dxf, model.glb, model.ifc, top.png, top-dimensioned.png")


# ---------------------------------------------------------------- exports
def _poly(g):
    return Polygon(g["exterior"], g["holes"])


def export_dxf(model, path):
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for name, color in (("A-WALL", 7), ("A-SLAB", 8), ("A-ROOM", 3), ("A-ROOM-TEXT", 3)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    lv = model["levels"][0]
    for w in lv["walls"]:
        g = w["geometry"]
        msp.add_lwpolyline(g["exterior"], close=True, dxfattribs={"layer": "A-WALL"})
        for h in g["holes"]:
            msp.add_lwpolyline(h, close=True, dxfattribs={"layer": "A-WALL"})
        hatch = msp.add_hatch(color=8, dxfattribs={"layer": "A-WALL"})
        hatch.paths.add_polyline_path(g["exterior"], is_closed=True, flags=1)
        for h in g["holes"]:
            hatch.paths.add_polyline_path(h, is_closed=True, flags=16)
    for g in lv["slab"]["geometry"]:
        msp.add_lwpolyline(g["exterior"], close=True, dxfattribs={"layer": "A-SLAB"})
    for r in lv["rooms"]:
        if "geometry" in r:
            msp.add_lwpolyline(r["geometry"]["exterior"], close=True, dxfattribs={"layer": "A-ROOM"})
            label = (r.get("name_en") or r.get("name") or "") + f" {r['net_area_m2']} m2"
            x, y = r["label_point_mm"]
            msp.add_text(label.strip(), height=180, dxfattribs={"layer": "A-ROOM-TEXT"}).set_placement((x, y))
    doc.layers.add("A-DIMS", color=4)
    doc.layers.add("A-FURN", color=30)
    for d in lv.get("dimensions", []):
        try:
            dim = msp.add_aligned_dim(p1=d["p1"], p2=d["p2"], distance=450, text=d["text"],
                                      dxfattribs={"layer": "A-DIMS"},
                                      override={"dimtxt": 160, "dimasz": 110, "dimexe": 80, "dimexo": 60})
            dim.render()
        except Exception:  # noqa: BLE001 – a degenerate dimension must not stop the export
            pass
    for f_ in lv.get("furniture", []):
        for pt in f_["parts"]:
            msp.add_lwpolyline(list(part_polygon(pt).exterior.coords), close=True, dxfattribs={"layer": "A-FURN"})
    el = lv.get("elements", {})
    for nm, c in (("A-DOOR", 2), ("A-GLAZ", 5), ("A-RAIL", 6), ("A-STRS", 1), ("A-SHFT", 8), ("A-BALC", 9)):
        doc.layers.add(nm, color=c)
    for d in el.get("doors", []):
        sw = d["swing"]
        hx, hy = sw["hinge"]
        a0 = math.degrees(math.atan2(sw["closed_dir"][1], sw["closed_dir"][0]))
        a1 = math.degrees(math.atan2(sw["open_dir"][1], sw["open_dir"][0]))
        da = (a1 - a0 + 540) % 360 - 180
        start, end = (a0, a1) if da > 0 else (a1, a0)
        msp.add_arc((hx, hy), d["width_mm"], start, end, dxfattribs={"layer": "A-DOOR"})
        msp.add_line((hx, hy), (hx + sw["open_dir"][0] * d["width_mm"], hy + sw["open_dir"][1] * d["width_mm"]), dxfattribs={"layer": "A-DOOR"})
    for es in lv.get("element_solids", []):
        lay = {"IfcWindow": "A-GLAZ", "IfcRailing": "A-RAIL", "IfcStair": "A-STRS", "IfcBuildingElementProxy": "A-SHFT",
               "IfcCovering": "A-BALC"}.get(es["cls"])
        if lay:
            msp.add_lwpolyline(es["polygon"], close=True, dxfattribs={"layer": lay})
    doc.saveas(path)


def export_glb(model, path):
    import trimesh
    lv = model["levels"][0]
    z0 = lv["elevation_mm"] / 1000
    h = lv["wall_height_mm"] / 1000
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    wall_mat = PBRMaterial(name="wall", baseColorFactor=[236, 236, 240, 255], roughnessFactor=0.9, metallicFactor=0.0)
    slab_mat = PBRMaterial(name="slab", baseColorFactor=[200, 200, 205, 255], roughnessFactor=0.9, metallicFactor=0.0)
    scene = trimesh.Scene()
    for w in lv["walls"]:
        p = affinity.scale(_poly(w["geometry"]), 0.001, 0.001, origin=(0, 0))
        m = trimesh.creation.extrude_polygon(p, h)
        m.apply_translation([0, 0, z0])
        m.visual = TextureVisuals(material=wall_mat)
        scene.add_geometry(m, node_name=w["id"], geom_name=w["id"])
    t = lv["slab_thickness_mm"] / 1000
    for k, g in enumerate(lv["slab"]["geometry"]):
        p = affinity.scale(_poly(g), 0.001, 0.001, origin=(0, 0))
        m = trimesh.creation.extrude_polygon(p, t)
        m.apply_translation([0, 0, z0 - t])
        m.visual = TextureVisuals(material=slab_mat)
        scene.add_geometry(m, node_name=f"SLAB{k + 1}", geom_name=f"SLAB{k + 1}")
    # furniture (VISUAL ONLY), one mesh per material
    by_mat = {}
    for f_ in lv.get("furniture", []):
        for pt in f_["parts"]:
            b = trimesh.creation.box(extents=(pt["w"] / 1000, pt["d"] / 1000, max(pt["h"], 5) / 1000))
            b.apply_transform(trimesh.transformations.rotation_matrix(pt["rot"], [0, 0, 1]))
            b.apply_translation([pt["x"] / 1000, pt["y"] / 1000, z0 + (pt["z0"] + max(pt["h"], 5) / 2) / 1000])
            by_mat.setdefault(pt["mat"], []).append(b)
    for es in lv.get("element_solids", []):
        if es["h"] <= 0:
            continue
        pg = affinity.scale(Polygon(es["polygon"]), 0.001, 0.001, origin=(0, 0))
        if not pg.is_valid or pg.area <= 0:
            continue
        m_ = trimesh.creation.extrude_polygon(pg, es["h"] / 1000)
        m_.apply_translation([0, 0, z0 + es["z0"] / 1000])
        by_mat.setdefault(es["mat"], []).append(m_)
    mats = model.get("materials", {})
    for name, meshes in by_mat.items():
        mm = mats.get(name, {"color": [200, 200, 200], "roughness": 0.8, "metalness": 0.0})
        m = trimesh.util.concatenate(meshes)
        alpha = int(255 * mm.get("opacity", 1.0))
        m.visual = TextureVisuals(material=PBRMaterial(name=f"mat-{name}", baseColorFactor=mm["color"] + [alpha],
                                                       roughnessFactor=mm["roughness"], metallicFactor=mm["metalness"],
                                                       alphaMode="BLEND" if alpha < 255 else "OPAQUE"))
        scene.add_geometry(m, node_name=f"FURN-{name}", geom_name=f"FURN-{name}")
    # glTF is Y-up: rotate Z-up model so it stands upright in viewers.
    scene.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0]))
    scene.export(path)


def export_ifc(model, path):
    import ifcopenshell
    import ifcopenshell.api as api
    lv = model["levels"][0]
    f = ifcopenshell.file(schema="IFC4")
    proj = api.run("root.create_entity", f, ifc_class="IfcProject", name=model["project"])
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "MILLIMETERS"})
    ctx = api.run("context.add_context", f, context_type="Model")
    body = api.run("context.add_context", f, context_type="Model", context_identifier="Body",
                   target_view="MODEL_VIEW", parent=ctx)
    site = api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    bldg = api.run("root.create_entity", f, ifc_class="IfcBuilding", name="Building")
    storey = api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=lv["name"])
    api.run("aggregate.assign_object", f, relating_object=proj, products=[site])
    api.run("aggregate.assign_object", f, relating_object=site, products=[bldg])
    api.run("aggregate.assign_object", f, relating_object=bldg, products=[storey])
    storey.Elevation = lv["elevation_mm"]

    def profile(g):
        def curve(pts):
            pts = pts[:-1] if pts[0] == pts[-1] else pts
            cps = [f.createIfcCartesianPoint((float(x), float(y))) for x, y in pts]
            return f.createIfcPolyline(cps + [cps[0]])
        if g["holes"]:
            return f.createIfcArbitraryProfileDefWithVoids("AREA", None, curve(g["exterior"]),
                                                           [curve(h) for h in g["holes"]])
        return f.createIfcArbitraryClosedProfileDef("AREA", None, curve(g["exterior"]))

    def solid(g, depth, z):
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z))), None, None)
        ext = f.createIfcExtrudedAreaSolid(profile(g), pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(depth))
        return f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [ext])

    def place(el, rep, status, extra=None):
        el.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        el.ObjectPlacement = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
        api.run("spatial.assign_container", f, relating_structure=storey, products=[el])
        pset = api.run("pset.add_pset", f, product=el, name="ADT_Accuracy")
        props = {"Status": status}
        props.update(extra or {})
        api.run("pset.edit_pset", f, pset=pset, properties=props)

    z = lv["elevation_mm"]
    for w in lv["walls"]:
        el = api.run("root.create_entity", f, ifc_class="IfcWall", name=w["id"])
        place(el, solid(w["geometry"], lv["wall_height_mm"], z), w["status"],
              {"HeightStatus": lv["wall_height_status"]})
    for k, g in enumerate(lv["slab"]["geometry"]):
        el = api.run("root.create_entity", f, ifc_class="IfcSlab", name=f"SLAB{k + 1}")
        place(el, solid(g, lv["slab_thickness_mm"], z - lv["slab_thickness_mm"]), lv["slab"]["status"])
    for i, r in enumerate(lv["rooms"]):
        if "geometry" not in r:
            continue
        sp = api.run("root.create_entity", f, ifc_class="IfcSpace",
                     name=r.get("name") or f"Space {i + 1}", )
        sp.LongName = r.get("name_en") or None
        sp.Representation = f.createIfcProductDefinitionShape(None, None, [solid(r["geometry"], lv["wall_height_mm"], z)])
        sp.ObjectPlacement = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
        api.run("aggregate.assign_object", f, relating_object=storey, products=[sp])
        pset = api.run("pset.add_pset", f, product=sp, name="ADT_Accuracy")
        api.run("pset.edit_pset", f, pset=pset, properties={"Status": r["status"], "NetAreaM2": r["net_area_m2"]})
    groups = {}
    for es in lv.get("element_solids", []):
        if es["h"] <= 0:
            continue
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z + es["z0"]))), None, None)
        sol = f.createIfcExtrudedAreaSolid(profile({"exterior": es["polygon"], "holes": []}), pos,
                                           f.createIfcDirection((0.0, 0.0, 1.0)), float(es["h"]))
        groups.setdefault((es["cls"], es["name"], es["status"]), []).append(sol)
    for (cls, name, st), sols in groups.items():
        el = api.run("root.create_entity", f, ifc_class=cls, name=name)
        place(el, f.createIfcShapeRepresentation(body, "Body", "SweptSolid", sols), st)
    spaces_by_room = {}
    for sp_ in f.by_type("IfcSpace"):
        spaces_by_room[sp_.Name] = spaces_by_room.get(sp_.Name, []) + [sp_]
    for ap_ in lv.get("apartments", []):
        members = []
        for idx in ap_["rooms"]:
            r = lv["rooms"][idx]
            if "geometry" in r:
                nm = r.get("name") or f"Space {idx + 1}"
                cand = [x for x in f.by_type("IfcSpace") if x.Name == nm and x.id() not in [m.id() for m in members]]
                if cand:
                    members.append(cand[0])
        zone = api.run("root.create_entity", f, ifc_class="IfcZone", name=f"Apartment {ap_['unit']}" if ap_["unit"] != "common" else "Common areas")
        if members:
            f.createIfcRelAssignsToGroup(ifcopenshell.guid.new(), None, None, None, members, None, zone)
    for i, f_ in enumerate(lv.get("furniture", [])):
        if not f_["parts"]:
            continue
        items = []
        for pt in f_["parts"]:
            ring = [list(c) for c in part_polygon(pt).exterior.coords]
            pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z + pt["z0"]))), None, None)
            items.append(f.createIfcExtrudedAreaSolid(profile({"exterior": ring, "holes": []}), pos,
                                                      f.createIfcDirection((0.0, 0.0, 1.0)), float(max(pt["h"], 5))))
        el = api.run("root.create_entity", f, ifc_class="IfcFurniture", name=f"{f_['type']} – {f_['space']}")
        place(el, f.createIfcShapeRepresentation(body, "Body", "SweptSolid", items), "VISUAL ONLY",
              {"Style": "Modern Minimalist Luxury"})
    f.write(str(path))


def _font(size, bold=False):
    from PIL import ImageFont
    for f_ in (f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",):
        if Path(f_).exists():
            return ImageFont.truetype(f_, size)
    return ImageFont.load_default()


def _vis(txt):
    """Text as drawn. Pillow with libraqm lays out Hebrew right-to-left itself;
    without libraqm, Hebrew would come out reversed, so reverse it then."""
    from PIL import features
    import re
    if features.check("raqm") or not re.search("[\u0590-\u05FF]", txt or ""):
        return txt or ""
    return (txt or "")[::-1]


def render_top(model, path, px_per_m=60, dims=False, furniture=False):
    lv = model["levels"][0]
    x0, y0, x1, y1 = model["extent_mm"]
    m = 2200 if dims else 1000
    sc = px_per_m / 1000
    Wd, Ht = int((x1 - x0 + 2 * m) * sc), int((y1 - y0 + 2 * m) * sc)
    im = Image.new("RGB", (Wd, Ht), "white")
    dr = ImageDraw.Draw(im)
    T = lambda x, y: ((x - x0 + m) * sc, (y1 + m - y) * sc)
    for g in lv["slab"]["geometry"]:
        dr.polygon([T(*p) for p in g["exterior"]], fill=(242, 242, 247), outline=(190, 190, 196))
    for w in lv["walls"]:
        g = w["geometry"]
        dr.polygon([T(*p) for p in g["exterior"]], fill=(28, 28, 30))
        for h in g["holes"]:
            dr.polygon([T(*p) for p in h], fill=(242, 242, 247))
    for r in lv["rooms"]:
        if "geometry" in r:
            dr.polygon([T(*p) for p in r["geometry"]["exterior"]], fill=(232, 241, 255))
    if furniture:
        mats = model.get("materials", {})
        for f_ in lv.get("furniture", []):
            for pt in sorted(f_["parts"], key=lambda q: q["z0"] + q["h"]):
                c = mats.get(pt["mat"], {"color": [200, 200, 200]})["color"]
                fill = tuple(int(255 - (255 - v) * 0.55) for v in c)
                dr.polygon([T(*q) for q in part_polygon(pt).exterior.coords], fill=fill, outline=(150, 140, 130))
    if furniture or dims:
        el = lv.get("elements", {})
        for b in el.get("balconies", []):
            dr.polygon([T(*q) for q in b["polygon"]], outline=(170, 160, 150))
        for es in lv.get("element_solids", []):
            if es["cls"] in ("IfcWindow", "IfcRailing"):
                dr.polygon([T(*q) for q in es["polygon"]], fill=(120, 180, 210))
            elif es["cls"] == "IfcStair":
                dr.polygon([T(*q) for q in es["polygon"]], outline=(110, 110, 115))
            elif es["cls"] == "IfcBuildingElementProxy":
                pts = [T(*q) for q in es["polygon"]]
                dr.polygon(pts, outline=(60, 60, 66), width=2)
                dr.line([pts[0], pts[2]], fill=(60, 60, 66), width=2)
                dr.line([pts[1], pts[3]], fill=(60, 60, 66), width=2)
        for d in el.get("doors", []):
            sw = d["swing"]
            hx, hy = sw["hinge"]
            a0 = math.atan2(sw["closed_dir"][1], sw["closed_dir"][0])
            a1 = math.atan2(sw["open_dir"][1], sw["open_dir"][0])
            da = math.atan2(math.sin(a1 - a0), math.cos(a1 - a0))
            arc = [T(hx + math.cos(a0 + da * k / 16) * d["width_mm"], hy + math.sin(a0 + da * k / 16) * d["width_mm"]) for k in range(17)]
            dr.line(arc, fill=(200, 60, 50), width=2)
            dr.line([T(hx, hy), arc[-1]], fill=(200, 60, 50), width=3)
    if dims:
        blue = (10, 100, 220)
        f_small = _font(max(11, int(px_per_m * 0.16)))
        f_room = _font(max(12, int(px_per_m * 0.2)), bold=True)
        for d in lv.get("dimensions", []):
            (ax, ay), (bx, by) = T(*d["p1"]), T(*d["p2"])
            col = blue if d["status"] == "VERIFIED" else (90, 90, 100)
            dr.line([(ax, ay), (bx, by)], fill=col, width=2)
            L = math.hypot(bx - ax, by - ay) or 1
            nx, ny = -(by - ay) / L, (bx - ax) / L
            for (px, py) in ((ax, ay), (bx, by)):
                dr.line([(px - nx * 7 - (bx - ax) / L * 7, py - ny * 7 - (by - ay) / L * 7),
                         (px + nx * 7 + (bx - ax) / L * 7, py + ny * 7 + (by - ay) / L * 7)], fill=col, width=2)
            txt = d["text"]
            tw, th = dr.textbbox((0, 0), txt, font=f_small)[2:]
            lab = Image.new("RGBA", (tw + 6, th + 4), (255, 255, 255, 230))
            ImageDraw.Draw(lab).text((3, 1), txt, fill=col, font=f_small)
            ang = -math.degrees(math.atan2(by - ay, bx - ax))
            if ang > 90 or ang < -90:
                ang += 180
            lab = lab.rotate(ang, expand=True)
            im.paste(lab, (int((ax + bx) / 2 - lab.width / 2 + nx * 12), int((ay + by) / 2 - lab.height / 2 + ny * 12)), lab)
        for r in lv["rooms"]:
            if not r.get("name") and "geometry" not in r:
                continue
            lx, ly = r["label_point_mm"]
            x, y = T(lx + 450, ly + 450)  # keep the name clear of the centre-line dimensions
            lines = [_vis(r.get("name") or "")]
            if r.get("net_area_m2"):
                lines.append(f"{r['net_area_m2']} m²")
            for k, ln in enumerate(l for l in lines if l):
                tw = dr.textbbox((0, 0), ln, font=f_room)[2]
                dr.text((x - tw / 2, y - 14 + k * int(px_per_m * 0.24)), ln, fill=(28, 28, 30), font=f_room)
        f_t = _font(max(14, int(px_per_m * 0.26)), bold=True)
        dr.text((20, 14), f"{model['project']} · {lv['name']}".replace(lv['name'], _vis(lv['name'])).replace(model['project'], _vis(model['project'])),
                fill=(28, 28, 30), font=f_t)
        dr.text((20, 14 + int(px_per_m * 0.34)), "Dimensions in cm · blue = printed on plan (VERIFIED) · grey = derived · furniture VISUAL ONLY",
                fill=(110, 110, 115), font=f_small)
    # 1 m scale bar
    dr.rectangle([20, Ht - 30, 20 + px_per_m, Ht - 24], fill=(10, 132, 255))
    dr.text((20, Ht - 22), "1 m", fill=(10, 132, 255))
    im.save(path)


if __name__ == "__main__":
    main()
