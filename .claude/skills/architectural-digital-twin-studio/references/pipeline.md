# Pipeline reference

All scripts live in `scripts/` and import `adt_common.py`; run them with that folder as the working directory or on `PYTHONPATH`.

| Step | Script | Reads | Writes |
|---|---|---|---|
| 1 | `probe_pdf.py plan.pdf --out work/probe [--pages 3-6]` | PDF | `probe.json`, `page-N.png`, `page-N-layer-K.png`, `contact.png` |
| 2 | `extract_walls.py plan.pdf --page N --layer ... --out work/F` | PDF | `walls.json`, `walls-grid.png`, `tiles/`, `plan-underlay.png` |
| 3 | `calibrate.py work/F/walls.json --pair ... --out work/F/scale.json` | walls.json | `scale.json` |
| 4 | `build_model.py work/F/walls.json work/F/scale.json --out work/F/model` | both | `model.json`, `plan.dxf`, `model.glb`, `model.ifc`, `top.png` |
| 5 | `qa_report.py work/F/model --walls work/F/walls.json --pdf plan.pdf` | model, walls | `qa_report.md/json`, `overlay.png` (exit 1 on FAIL) |
| 6 | `build_viewer.py work/F/model [...] --out work/viewer` | model(s) | `viewer.html`, `viewer-standalone.html` |
| 7 | `package_deliverables.py work/F [...] --viewer work/viewer --out x.zip` | all | ZIP |

## Reading the probe

`layers` lists paint groups by total area. Typical patterns in Israeli sales plans (`תוכנית מכר`) exported from CAD:

- **Wall poche** – a mid-grey fill (`fill #989898` in the sample) with median thickness ~0.3 pt (that's the hatch of balconies mixed in; the walls themselves are thicker pieces).
- **Everything else** – black fill: outlines, text converted to curves, furniture, dimension lines, 45° concrete hatch.
- **Openings** – white fill painted after the walls.
- **Highlights** – red/blue/green fills (sales markings such as safe-room frames). Not walls.

Render the candidate layer (`page-N-layer-K.png`) before choosing; never choose by colour name alone.

## extract_walls.py options

| Option | Default | When to change |
|---|---|---|
| `--min-thickness` | 0.35 pt | pieces thinner than this go to `aux` (hatch, slab hints). Raise if balcony tile hatch leaks into walls; lower if thin partitions disappear. |
| `--min-area` | 0.5 pt² | drop specks. |
| `--erase-layer` | none | layer painted over walls to open doors/windows (paint-order aware). |
| `--grow` | 0 | outline stroke width when the poche is painted inside a separate outline. |
| `--hatch-layer` | none | layer holding 45° concrete hatch; walls traced from it are DERIVED. |
| `--min-wall` | 0.5 pt | morphological opening that removes slivers (glass lines) – keep below the thinnest real wall. |
| `--bbox` | page | restrict to one drawing on a sheet with several. |

Coordinates are PDF points, origin top-left, y down. The grid in `walls-grid.png` and `tiles/` is labelled in the same units.

## Calibration tips

- Dimension strings are usually centimetres. A chain like `25 | 90 | 370` gives you both small and large spans – prefer the larger, wall-to-wall ones.
- `--faces clear` (default) snaps each end to the face that has wall behind it and room in front – the clear span. Use `--faces nearest` for an overall dimension measured to outer faces.
- A dimension that refuses to snap ends on something that is not a wall (railing, axis line, slab edge) – choose another one.
- Calibration snaps only to faces drawn in the PDF; hatch-derived walls are ignored.
- If horizontal and vertical dimensions disagree consistently (>1%), the PDF may have been scaled non-uniformly: report it as UNRESOLVED rather than averaging.

## Sample result (the plan used to build this skill)

`פסגות הגליל, בני ברק`, sales plan, 10 A4 pages, text outlined. Page 5 (`קומה א'`):
`--layer "fill #989898" --erase-layer "fill #ffffff" --hatch-layer "fill #000000" --grow 0.28` →
5 dimensions, scale 72.06 mm/pt (1:204 on the PDF, the title block said 1:100), worst error 20 mm,
54 wall bodies (42 VERIFIED, 12 DERIVED concrete), floor 18.17 × 50.17 m, QA PASS (IoU 0.9987).

## Troubleshooting

- `ModuleNotFoundError: scipy` from trimesh – something set `face_colors`; use PBR materials (build_model does).
- `ifcopenshell.api.root.create_file` missing – newer ifcopenshell; use `ifcopenshell.file(schema="IFC4")`.
- Viewer blank in a sandbox – CDN blocked; route `three.min.js` and `OrbitControls.js` to a local copy in Playwright.
- `hidden` panels visible in standalone HTML – keep `[hidden]{display:none!important}` in the viewer CSS.
