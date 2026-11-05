#!/usr/bin/env python3
"""Step 1 – look at a plan PDF before trusting anything in it.

For every page it reports whether the page is vector or scanned, whether a
text layer exists, and how the drawing is split into paint "layers" (same
fill/stroke colour and width). It renders each page, and for drawing pages it
also renders the biggest layers on their own so you can SEE which layer holds
the walls.

Usage:
  probe_pdf.py plan.pdf --out work/probe [--dpi 110] [--pages 3-6] [--layer-renders 8]

Outputs (in --out):
  probe.json            per-page facts + layer table
  page-<n>.png          the page as printed
  page-<n>-layer-<k>.png  one layer alone (black on white), k = rank in table
  contact.png           all pages side by side
"""
import argparse
import statistics
from collections import defaultdict
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from adt_common import drawing_polygons, layer_key, thickness, write_json


def parse_pages(spec, n):
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    return [p for p in out if 0 <= p < n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--pages", help="1-based, e.g. 3-6 or 2,5")
    ap.add_argument("--layer-renders", type=int, default=8)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(a.pdf)
    pages = parse_pages(a.pages, len(doc))
    report = {"pdf": str(a.pdf), "page_count": len(doc), "pages": []}
    thumbs = []

    for pi in pages:
        page = doc[pi]
        pw, ph = page.rect.width, page.rect.height
        text = page.get_text("text").strip()
        images = page.get_images(full=True)
        img_cover = 0.0
        for im in images:
            for r in page.get_image_rects(im[0]):
                img_cover = max(img_cover, (r.width * r.height) / (pw * ph))
        drawings = page.get_drawings()

        layers = defaultdict(lambda: {"count": 0, "area": 0.0, "thick": []})
        polys_by_layer = defaultdict(list)
        for d in drawings:
            k = layer_key(d)
            polys = drawing_polygons(d)
            L = layers[k]
            L["count"] += 1
            for p in polys:
                L["area"] += p.area
                L["thick"].append(thickness(p))
            polys_by_layer[k].extend(polys)
        table = []
        for k, L in layers.items():
            table.append({
                "layer": k,
                "count": L["count"],
                "area_pt2": round(L["area"], 1),
                "median_thickness_pt": round(statistics.median(L["thick"]), 3) if L["thick"] else 0,
            })
        table.sort(key=lambda r: -r["area_pt2"])
        for i, r in enumerate(table):
            r["rank"] = i + 1

        kind = "empty"
        if img_cover > 0.6 and len(drawings) < 200:
            kind = "scanned"
        elif len(drawings) >= 200:
            kind = "vector-drawing"
        elif text:
            kind = "text"
        elif images:
            kind = "image"

        pix = page.get_pixmap(dpi=a.dpi)
        png = out / f"page-{pi + 1}.png"
        pix.save(png)
        thumbs.append(Image.open(png).convert("RGB"))

        renders = []
        if kind == "vector-drawing":
            s = a.dpi / 72
            for r in table[: a.layer_renders]:
                im = Image.new("L", (int(pw * s), int(ph * s)), 255)
                dr = ImageDraw.Draw(im)
                for p in polys_by_layer[r["layer"]]:
                    for g in getattr(p, "geoms", [p]):
                        if hasattr(g, "exterior"):
                            dr.polygon([(x * s, y * s) for x, y in g.exterior.coords], fill=0)
                f = out / f"page-{pi + 1}-layer-{r['rank']}.png"
                im.save(f)
                renders.append(f.name)

        report["pages"].append({
            "page": pi + 1,
            "size_pt": [round(pw, 2), round(ph, 2)],
            "rotation": page.rotation,
            "kind": kind,
            "has_text_layer": bool(text),
            "text_chars": len(text),
            "image_count": len(images),
            "largest_image_cover": round(img_cover, 3),
            "drawing_count": len(drawings),
            "layers": table[:25],
            "render": png.name,
            "layer_renders": renders,
        })

    if thumbs:
        h = 360
        ths = [t.resize((int(t.width * h / t.height), h)) for t in thumbs]
        sheet = Image.new("RGB", (sum(t.width for t in ths), h), "white")
        x = 0
        for t in ths:
            sheet.paste(t, (x, 0))
            x += t.width
        sheet.save(out / "contact.png")

    write_json(out / "probe.json", report)
    for p in report["pages"]:
        print(f"page {p['page']:>3}  {p['kind']:<15} text={'yes' if p['has_text_layer'] else 'no ':<3} "
              f"drawings={p['drawing_count']:<6} images={p['image_count']}")
        if p["kind"] == "vector-drawing":
            for r in p["layers"][:6]:
                print(f"         #{r['rank']:<2} {r['layer']:<28} n={r['count']:<6} area={r['area_pt2']:<9} "
                      f"t~{r['median_thickness_pt']}")
    print(f"\nwrote {out/'probe.json'}")


if __name__ == "__main__":
    main()
