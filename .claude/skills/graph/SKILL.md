---
name: graph
description: "Create an animated data chart from user-supplied numbers while preserving labels, units, missing values and scale. Use for bar, line or other statistical charts, not dependency graphs."
metadata:
  author: AI Master
  version: "1.0.0"
---

# גרף מונפש מנתונים

## Data contract
Parse the supplied table or file into labels, values, units, series and ordering. Keep the original source alongside normalized data. Missing is not zero; preserve negative values. Ask about ambiguous units or decimal separators rather than guessing. Use synthetic numbers only if requested and label them as demonstration data.
Select bars for category comparisons and lines for ordered temporal trends. Do not connect unordered categories with a trend line or use a pie chart for negative values or parts that do not form a whole. Preserve chronological order where meaningful.

## Scale and geometry
Compute the scale once from the complete dataset and keep it fixed throughout the animation. Include zero for quantitative bar charts; use an explicit zero baseline for mixed signs. Choose a readable nonzero domain for all-zero or single-value datasets. Do not silently truncate axes. A logarithmic scale must be requested or justified and visibly labeled; it cannot represent zero or negative values.
Use deterministic SVG, Canvas or a charting library already installed. Render data labels as actual text, not generated image text. Use direction-aware layout for Hebrew and isolate numeric runs so punctuation and currency remain correct.
Animate bars from the zero baseline to the exact final values. Reveal a line along its final geometry; do not morph fabricated interim samples into real data. Stagger entries only if it preserves the intended comparison. Keep axis ticks and the legend stable.
Use restrained colors and redundant labels for series. Keep number formatting consistent with source precision. Distinguish display rounding from underlying values. For busy datasets use fewer on-screen labels or a wider format instead of microscopic text.
Default duration 8 seconds with a final hold of at least 2 seconds. The last frame must be the complete chart, not a fade to black. Display a source/date only when supplied or verified.

## Category acceptance
Compare each final mark and value label to the normalized dataset. Check zero, negative and missing values when present. Verify units, category order, final hold and Hebrew readability. Report any excluded rows and the reason; never quietly drop data.

## Execution and delivery
This is an original AI Master instruction skill, not the source creator's package and not a bundled video engine. It runs in a coding agent with filesystem and execution access. The user's request after the slash command is the brief; follow explicit user choices over the defaults below.

1. Inspect the current project, supplied assets and available render tools. Reuse the existing setup. For a complete brief, proceed to a working scene without unnecessary questions. Default to a vertical 1080×1920 composition at 30 fps, Hebrew only when the brief calls for it, with no invented brand or CTA.
2. Choose an engine that can represent the requested visual: SVG/Canvas for 2D, an available 3D engine for genuine 3D, and an existing local video pipeline for export. Do not assume another AI Master skill, a paid API, a model or a plugin is installed. If a required dependency is missing, explain exactly what is missing and request only the installation or cost authorization actually needed.
3. Implement the animation as a function of elapsed time or frame number. Keep asset paths local to the project. For browser scenes, wait for fonts and images before capture. Avoid wall-clock-only loops, random frame-to-frame behavior and untracked network assets. Keep the source editable.
4. Produce and inspect a short preview first, then complete the requested duration. Reuse a functioning renderer such as an installed HyperFrames, Remotion, Blender or frame-capture pipeline; consult that installed version's documented commands rather than guessing. A browser preview alone is not an MP4. Do not submit paid generations without authorization.
5. Render to a new output filename. Never overwrite user source material. Inspect first, middle and last frames plus scene boundaries. Check phone-size readability and text direction. Use a valid font available on the machine; do not invent a font path.
6. If MP4 was requested, verify that the file exists, decodes and has the intended dimensions, frame rate and duration, using ffprobe/ffmpeg or equivalent available tools. Prefer H.264 with yuv420p and faststart for compatibility. Include audio only when supplied or authorized; never claim that a silent clip has narration.
7. Deliver the source project and the actual rendered file with a brief account of checks and any limitation. If rendering is blocked, return the working preview/source and the concrete missing prerequisite, explicitly stating that MP4 delivery is incomplete. Do not post or send the result externally unless asked.

## Example invocation

```text
/graph צור גרף עמודות מונפש לנתוני הדגמה: א׳ 12, ב׳ 18, ג׳ 9. יחידה: פניות. כתוב בבירור ״נתוני הדגמה״. 8 שניות.
```
