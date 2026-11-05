#!/usr/bin/env python3
"""Step 2 – take the wall geometry straight from the PDF's vector layer.

Pick the layer that holds the walls from probe_pdf.py's layer renders, then:

  extract_walls.py plan.pdf --page 5 --layer "fill #989898" --out work/floor-1 \
      [--min-thickness 0.35] [--min-area 0.5] [--bbox x0,y0,x1,y1] [--grid 20]

Pieces thinner than --min-thickness (pt) are treated as hatch / outline noise
and kept separately as `aux` (they often mark balcony or slab areas). Nothing
is moved, straightened or snapped: the walls are the source polygons, merged.

Outputs:
  walls.json        walls + aux as GeoJSON in PDF points (y down), with stats
  walls-grid.png    the page faded, walls in black, a labelled point grid –
                    read approximate coordinates here for calibrate.py
  tiles/tile-r<i>-c<j>.png  zoomed crops of the same, to read dimensions
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from adt_common import (drawing_polygons, iter_polygons, layer_key, load_page,
                        thickness, to_geojson, union, write_json)
from shapely.geometry import box


def draw_geom(dr, geom, s, ox, oy, fill):
    for p in iter_polygons(geom):
        dr.polygon([((x - ox) * s, (y - oy) * s) for x, y in p.exterior.coords], fill=fill)
        for h in p.interiors:
            dr.polygon([((x - ox) * s, (y - oy) * s) for x, y in h.coords], fill=(255, 255, 255))


def hatched_walls(drawings, a, clip, erasers):
    """Walls drawn as an outline filled with 45° hatch (concrete) instead of a
    poche colour. Short strokes at 45°/135° that have several parallel
    neighbours are hatch; their merged, slightly shrunk envelope is the wall.
    The result is DERIVED (an envelope of the hatch, not a drawn polygon)."""
    import math
    from shapely.strtree import STRtree
    if not a.hatch_layer:
        return union([]), 0
    segs, angs, seqs = [], [], []
    for seq, d in enumerate(drawings):
        if layer_key(d) not in a.hatch_layer:
            continue
        for p in drawing_polygons(d):
            if p.area <= 0 or (clip is not None and not p.intersects(clip)):
                continue
            r = p.minimum_rotated_rectangle
            if r.geom_type != "Polygon":
                continue
            c = list(r.exterior.coords)[:4]
            l01, l12 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
            (pa, pb, L, w) = (c[0], c[1], l01, l12) if l01 >= l12 else (c[1], c[2], l12, l01)
            if not (0.8 <= L <= 8) or w > 0.45:
                continue
            ang = math.degrees(math.atan2(pb[1] - pa[1], pb[0] - pa[0])) % 180
            if min(abs(ang - 45), abs(ang - 135)) > 8:
                continue
            segs.append(p)
            angs.append(ang)
            seqs.append(seq)
    if not segs:
        return union([]), 0
    tree = STRtree(segs)
    keep = []
    for i, p in enumerate(segs):
        n = sum(1 for j in tree.query(p.buffer(2.5)) if j != i and abs(angs[j] - angs[i]) <= 3)
        if n >= 3:
            keep.append(i)
    g = union([segs[i].buffer(0.9) for i in keep]).buffer(-0.5)
    g = union([q for q in iter_polygons(g) if q.area > 4])
    if erasers and not g.is_empty:
        first = min(seqs[i] for i in keep) if keep else 0
        cut = [e for s_, e in erasers if s_ > first and e.area > 0 and e.intersects(g)]
        if cut:
            g = g.difference(union(cut))
    return g, len(keep)


def font(size):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, required=True, help="1-based page number")
    ap.add_argument("--layer", required=True, action="append",
                    help='layer key from probe.json, e.g. "fill #989898" (repeatable)')
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-thickness", type=float, default=0.35)
    ap.add_argument("--min-area", type=float, default=0.5)
    ap.add_argument("--erase-layer", action="append",
                    help='layer painted over walls to cut openings, e.g. "fill #ffffff" (repeatable)')
    ap.add_argument("--hatch-layer", action="append",
                    help='layer whose 45° hatch strokes mark concrete walls (e.g. safe rooms, cores), '
                         'e.g. "fill #000000" (repeatable)')
    ap.add_argument("--grow", type=float, default=0.0,
                    help="pt – grow (+) or thin (−) the walls uniformly; 0 = walls exactly as filled. A non-zero value is a DERIVED correction")
    ap.add_argument("--min-wall", type=float, default=0.5,
                    help="pt – thinnest real wall; anything thinner is removed (0 = keep all)")
    ap.add_argument("--bbox", help="x0,y0,x1,y1 in pt – keep only this part of the page")
    ap.add_argument("--grid", type=float, default=20, help="grid spacing in pt for the preview")
    ap.add_argument("--dpi", type=int, default=220)
    ap.add_argument("--tiles", default="3x2", help="rows x cols of zoomed preview tiles")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    doc, page, drawings = load_page(a.pdf, a.page - 1)
    clip = box(*map(float, a.bbox.split(","))) if a.bbox else None

    keep, thin, erasers = [], [], []
    for seq, d in enumerate(drawings):
        key = layer_key(d)
        if key in a.layer:
            for p in drawing_polygons(d):
                if clip is not None and not p.intersects(clip):
                    continue
                if thickness(p) >= a.min_thickness and p.area >= a.min_area:
                    keep.append([seq, p])
                else:
                    thin.append(p)
        elif key in (a.erase_layer or []):
            erasers.extend((seq, p) for p in drawing_polygons(d))

    # Paint order matters: openings are often painted in white OVER the wall
    # fill. Anything from an --erase-layer cuts only the wall pieces painted
    # before it (a white room background painted earlier must not erase walls).
    erased = 0
    if erasers:
        from shapely.strtree import STRtree
        tree = STRtree([p for _, p in keep])
        for seq, e in erasers:
            if e.area <= 0:
                continue
            for i in tree.query(e):
                ws, wp = keep[i]
                if ws < seq and wp.intersects(e):
                    keep[i][1] = wp.difference(e)
                    erased += 1

    walls = union([p for _, p in keep])
    aux = union(thin)
    hatch_walls, n_hatch = hatched_walls(drawings, a, clip, erasers)

    # Many plans paint the wall poche (fill) INSIDE a stroked outline of
    # another colour. The poche alone is thinner than the drawn wall by one
    # outline stroke on each side, so grow it by --grow (the outline stroke
    # width, see probe.json: median thickness of the outline layer). Growing
    # by a fraction of a point cannot bridge a door or window gap.
    if a.grow != 0 and not walls.is_empty:
        walls = walls.buffer(a.grow, join_style="mitre", mitre_limit=3)

    # Drop slivers thinner than --min-wall so openings stay open.
    if a.min_wall > 0 and not walls.is_empty:
        r = a.min_wall / 2
        walls = walls.buffer(-r, join_style="mitre", mitre_limit=3).buffer(r, join_style="mitre", mitre_limit=3)
        walls = union([p for p in iter_polygons(walls) if p.area >= a.min_area])
    if not hatch_walls.is_empty:
        hatch_walls = hatch_walls.difference(walls)
        hatch_walls = union([p for p in iter_polygons(hatch_walls) if p.area >= 1.0])
        walls = union([walls, hatch_walls])
    if clip is not None:
        walls, aux = walls.intersection(clip), aux.intersection(clip)
    if walls.is_empty:
        raise SystemExit("No wall geometry found – check --layer, --min-thickness and --bbox.")

    pieces = list(iter_polygons(walls))
    minx, miny, maxx, maxy = walls.bounds
    data = {
        "source_pdf": str(Path(a.pdf).resolve()),
        "page": a.page,
        "page_size_pt": [page.rect.width, page.rect.height],
        "layers": a.layer,
        "params": {"min_thickness_pt": a.min_thickness, "min_area_pt2": a.min_area, "bbox": a.bbox,
                   "min_wall_pt": a.min_wall, "grow_pt": a.grow,
                   "erase_layers": a.erase_layer or [], "hatch_layers": a.hatch_layer or []},
        "units": "pt (PDF points, origin top-left, y down)",
        "stats": {
            "source_pieces_kept": len(keep),
            "source_pieces_thin": len(thin),
            "wall_pieces_cut_by_erasers": erased,
            "hatch_strokes_used": n_hatch,
            "hatched_wall_area_pt2": round(hatch_walls.area, 2),
            "wall_polygons": len(pieces),
            "wall_area_pt2": round(walls.area, 2),
            "bounds_pt": [round(v, 3) for v in (minx, miny, maxx, maxy)],
        },
        "walls": to_geojson(walls),
        "walls_from_hatch": to_geojson(hatch_walls),
        "aux": to_geojson(aux),
    }
    write_json(out / "walls.json", data)

    # Preview: faded page + walls + grid, cropped to the walls with a margin.
    s = a.dpi / 72
    m = 30
    cx0, cy0 = max(0, minx - m), max(0, miny - m)
    cx1, cy1 = min(page.rect.width, maxx + m), min(page.rect.height, maxy + m)
    import pymupdf
    pix = page.get_pixmap(dpi=a.dpi, clip=pymupdf.Rect(cx0, cy0, cx1, cy1))
    base = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    base = Image.blend(base, Image.new("RGB", base.size, "white"), 0.55)
    dr = ImageDraw.Draw(base)
    draw_geom(dr, walls, s, cx0, cy0, (20, 20, 20))
    f = font(max(10, int(s * 3.2)))
    g = a.grid
    x = (int(cx0 // g) + 1) * g
    while x < cx1:
        X = (x - cx0) * s
        dr.line([(X, 0), (X, base.height)], fill=(10, 132, 255), width=1)
        dr.text((X + 2, 2), f"{x:g}", fill=(10, 100, 220), font=f)
        x += g
    y = (int(cy0 // g) + 1) * g
    while y < cy1:
        Y = (y - cy0) * s
        dr.line([(0, Y), (base.width, Y)], fill=(10, 132, 255), width=1)
        dr.text((2, Y + 2), f"{y:g}", fill=(10, 100, 220), font=f)
        y += g
    base.save(out / "walls-grid.png")

    rows, cols = map(int, a.tiles.lower().split("x"))
    tdir = out / "tiles"
    tdir.mkdir(exist_ok=True)
    tw, th = base.width / cols, base.height / rows
    for i in range(rows):
        for j in range(cols):
            crop = base.crop((int(j * tw), int(i * th), int((j + 1) * tw), int((i + 1) * th)))
            crop.save(tdir / f"tile-r{i + 1}-c{j + 1}.png")

    # Full-resolution plan crop for the viewer's 2D/3D comparison underlay.
    pix2 = page.get_pixmap(dpi=a.dpi, clip=pymupdf.Rect(minx, miny, maxx, maxy))
    pix2.save(out / "plan-underlay.png")
    data["underlay"] = {"file": "plan-underlay.png", "bounds_pt": [minx, miny, maxx, maxy]}
    write_json(out / "walls.json", data)

    print(f"walls: {len(pieces)} polygons from {len(keep)} source pieces "
          f"({len(thin)} thin pieces kept as aux)")
    print(f"bounds (pt): {[round(v, 1) for v in (minx, miny, maxx, maxy)]}")
    print(f"wrote {out/'walls.json'}, walls-grid.png, tiles/, plan-underlay.png")


if __name__ == "__main__":
    main()
