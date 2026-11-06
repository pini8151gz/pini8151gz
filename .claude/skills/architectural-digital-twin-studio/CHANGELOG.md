# Changelog

## 2026-11-05 – v2
- Working pipeline: `probe_pdf.py`, `extract_walls.py`, `calibrate.py`, `build_model.py`, `qa_report.py`, `build_viewer.py`, `package_deliverables.py`.
- Walls taken from the PDF's vector wall layer; openings respect paint order; concrete walls traced from 45° hatch (DERIVED).
- Scale calibrated from printed dimensions with face snapping and per-dimension error; title-block scale never used.
- Exports: model.json (single source), DXF, GLB, IFC4 with accuracy property sets.
- QA gate that re-reads the exported files and overlays them on the source.
- Interactive viewer: dollhouse, top, walk (minimap, collisions, joystick), 360°, section, 2D/3D compare, snapping measure, spaces list, accuracy panel, Hebrew/English, light/dark.
- Tested end to end on a real 10-page sales plan (פסגות הגליל, בני ברק).
- Frontmatter reduced to `name` + `description`; description broadened so the skill triggers on everyday phrasing.

## 2026-11-05 – v1
- Initial professional skill creation
- CAD-accurate modeling + Real-time Architectural Visualization
- Full UX and deliverables specification
