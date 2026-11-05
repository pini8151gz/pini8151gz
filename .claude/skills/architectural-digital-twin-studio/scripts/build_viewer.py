#!/usr/bin/env python3
"""Step 6 – package the model into the interactive browser viewer.

  build_viewer.py work/floor/model [more model dirs = more floors] --out work/viewer \
      [--title "Project – Floor 1"] [--underlay work/floor/plan-underlay.png]

Writes:
  viewer.html             page body for publishing as a claude.ai Artifact
                          (no <html>/<head>; the Artifact tool adds them)
  viewer-standalone.html  the same as a complete document, to open locally
                          or host anywhere

Everything (model data and the plan underlay) is embedded, so the page works
offline except for three.js, which loads from cdnjs/jsdelivr.
"""
import argparse
import base64
import io
import json
from pathlib import Path

from PIL import Image

from adt_common import read_json

ASSET = Path(__file__).resolve().parent.parent / "assets" / "viewer.html"


def slim_geom(g):
    r = lambda pts: [[round(x), round(y)] for x, y in pts]
    return {"exterior": r(g["exterior"]), "holes": [r(h) for h in g["holes"]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+", help="model folders (one per floor, bottom first)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--underlay", help="plan-underlay.png of the FIRST model (default: next to its walls.json)")
    ap.add_argument("--max-underlay-px", type=int, default=2600)
    a = ap.parse_args()

    models = [read_json(Path(m) / "model.json") for m in a.models]
    M0 = models[0]
    levels = []
    for M in models:
        for lv in M["levels"]:
            levels.append({
                "name": lv["name"], "elevation_mm": lv["elevation_mm"], "elevation_status": lv["elevation_status"],
                "wall_height_mm": lv["wall_height_mm"], "wall_height_status": lv["wall_height_status"],
                "slab_thickness_mm": lv["slab_thickness_mm"],
                "walls": [{"id": w["id"], "status": w["status"], "kind": w.get("kind", "wall"),
                           "geometry": slim_geom(w["geometry"])} for w in lv["walls"]],
                "slab": {"status": lv["slab"]["status"], "geometry": [slim_geom(g) for g in lv["slab"]["geometry"]]},
                "rooms": [{k: (slim_geom(v) if k == "geometry" else v) for k, v in r.items()} for r in lv["rooms"]],
            })

    data = {
        "project": M0["project"],
        "extent_mm": M0["extent_mm"],
        "scale": {k: M0["scale"][k] for k in ("mm_per_pt", "status", "reason", "worst_error_mm", "samples")},
        "limitations": M0.get("limitations", []),
        "levels": levels,
    }

    up = Path(a.underlay) if a.underlay else None
    if up is None and M0["source"].get("underlay"):
        cand = Path(a.models[0]).parent / M0["source"]["underlay"]["file"]
        up = cand if cand.exists() else None
    if up and up.exists():
        im = Image.open(up).convert("RGB")
        if max(im.size) > a.max_underlay_px:
            f = a.max_underlay_px / max(im.size)
            im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        s = M0["scale"]["mm_per_pt"]
        x0, y0, x1, y1 = M0["source"]["underlay"]["bounds_pt"]
        data["underlay"] = {"src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                            "w": (x1 - x0) * s, "h": (y1 - y0) * s}

    title = a.title or f"{M0['project']}"
    page = ASSET.read_text(encoding="utf-8")
    page = page.replace("__ADT_TITLE__", title.replace("<", "&lt;"))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = page.replace("/*__ADT_DATA__*/null", payload)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "viewer.html").write_text(page, encoding="utf-8")
    full = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body style="margin:0">'
            + page + "</body></html>")
    (out / "viewer-standalone.html").write_text(full, encoding="utf-8")
    kb = len(page.encode()) / 1024
    print(f"wrote {out/'viewer.html'} ({kb:.0f} KB, {len(levels)} floor(s)) and viewer-standalone.html")


if __name__ == "__main__":
    main()
