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

from adt_common import from_geojson, iter_polygons, read_json, thickness, union, write_json


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
        wall_items.append({
            "id": f"W{i + 1:03d}",
            "status": ("DERIVED" if geo_status == "VERIFIED" else geo_status) if from_hatch else geo_status,
            "kind": "concrete (hatched)" if from_hatch else "wall",
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
        "scale": {"mm_per_pt": s, "status": S["status"], "reason": S["reason"],
                  "worst_error_mm": S.get("worst_error_mm"), "samples": S["samples"]},
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
        }],
        "layers": {
            "verified_geometry": "levels[].walls",
            "derived": "levels[].slab, levels[].rooms",
            "furniture": "not modelled (VISUAL ONLY layer – see plan underlay)",
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
    lim.append("Doors and windows are modelled as openings (full-height gaps); sills, heads and leaves are not modelled.")
    if S["status"] != "VERIFIED":
        lim.append(f"Scale is {S['status']}: {S['reason']}.")
    write_json(out / "model.json", model)

    export_dxf(model, out / "plan.dxf")
    export_glb(model, out / "model.glb")
    export_ifc(model, out / "model.ifc")
    render_top(model, out / "top.png")
    n_named = sum(1 for r_ in rooms if r_.get("name"))
    print(f"model: {len(wall_items)} wall bodies, slab {model['levels'][0]['slab']['area_m2']} m², "
          f"{len(rooms)} spaces ({n_named} named), extent {round((bx1-bx0)/1000,2)} x {round((by1-by0)/1000,2)} m")
    print(f"wrote {out}/model.json, plan.dxf, model.glb, model.ifc, top.png")


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
    f.write(str(path))


def render_top(model, path, px_per_m=60):
    lv = model["levels"][0]
    x0, y0, x1, y1 = model["extent_mm"]
    m = 1000
    sc = px_per_m / 1000
    Wd, Ht = int((x1 - x0 + 2 * m) * sc), int((y1 - y0 + 2 * m) * sc)
    im = Image.new("RGB", (Wd, Ht), "white")
    dr = ImageDraw.Draw(im)
    T = lambda x, y: ((x - x0 + m) * sc, (y1 + m - y) * sc)
    for g in lv["slab"]["geometry"]:
        dr.polygon([T(*p) for p in g["exterior"]], fill=(242, 242, 247), outline=(190, 190, 196))
    for r in lv["rooms"]:
        if "geometry" in r:
            dr.polygon([T(*p) for p in r["geometry"]["exterior"]], fill=(232, 241, 255))
    for w in lv["walls"]:
        g = w["geometry"]
        dr.polygon([T(*p) for p in g["exterior"]], fill=(28, 28, 30))
        for h in g["holes"]:
            dr.polygon([T(*p) for p in h], fill=(232, 241, 255))
    # 1 m scale bar
    dr.rectangle([20, Ht - 30, 20 + px_per_m, Ht - 24], fill=(10, 132, 255))
    dr.text((20, Ht - 22), "1 m", fill=(10, 132, 255))
    im.save(path)


if __name__ == "__main__":
    main()
