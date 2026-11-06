#!/usr/bin/env python3
"""Step 7 – collect every deliverable into one ZIP.

  package_deliverables.py --out work/deliverables.zip work/floor-1 [work/floor-2 ...] --viewer work/viewer

Each floor folder is the --out of extract_walls.py (it holds walls.json,
scale.json, rooms.json if any, and the model/ folder from build_model.py).
"""
import argparse
import zipfile
from pathlib import Path

KEEP = {"walls.json", "scale.json", "rooms.json", "dims.txt", "face-checks.txt", "elements.json", "walls-grid.png", "plan-underlay.png"}
MODEL = {"model.json", "plan.dxf", "model.glb", "model.ifc", "top.png", "top-dimensioned.png", "overlay.png",
         "qa_report.md", "qa_report.json"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("floors", nargs="+")
    ap.add_argument("--viewer")
    ap.add_argument("--renders", help="output folder of render_views.js")
    ap.add_argument("--extra", action="append", default=[], help="more files to include at the ZIP root (e.g. perf.json)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    n = 0
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
        for fl in a.floors:
            fl = Path(fl)
            for f in fl.iterdir():
                if f.name in KEEP:
                    z.write(f, f"{fl.name}/source/{f.name}")
                    n += 1
            for f in (fl / "model").glob("*"):
                if f.name in MODEL:
                    z.write(f, f"{fl.name}/{f.name}")
                    n += 1
        if a.renders:
            r = Path(a.renders)
            for f in sorted(r.rglob("*")):
                if f.is_file() and f.suffix.lower() in (".png", ".mp4", ".json"):
                    z.write(f, f"renders/{f.relative_to(r)}")
                    n += 1
        for x in a.extra:
            z.write(x, Path(x).name)
            n += 1
        if a.viewer:
            for f in Path(a.viewer).glob("*.html"):
                z.write(f, f"viewer/{f.name}")
                n += 1
    print(f"wrote {a.out} ({n} files)")


if __name__ == "__main__":
    main()
