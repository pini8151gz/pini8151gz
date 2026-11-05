#!/usr/bin/env python3
"""Step 7 – collect every deliverable into one ZIP.

  package_deliverables.py --out work/deliverables.zip work/floor-1 [work/floor-2 ...] --viewer work/viewer

Each floor folder is the --out of extract_walls.py (it holds walls.json,
scale.json, rooms.json if any, and the model/ folder from build_model.py).
"""
import argparse
import zipfile
from pathlib import Path

KEEP = {"walls.json", "scale.json", "rooms.json", "calibration-pairs.txt", "walls-grid.png", "plan-underlay.png"}
MODEL = {"model.json", "plan.dxf", "model.glb", "model.ifc", "top.png", "overlay.png", "qa_report.md", "qa_report.json"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("floors", nargs="+")
    ap.add_argument("--viewer")
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
        if a.viewer:
            for f in Path(a.viewer).glob("*.html"):
                z.write(f, f"viewer/{f.name}")
                n += 1
    print(f"wrote {a.out} ({n} files)")


if __name__ == "__main__":
    main()
