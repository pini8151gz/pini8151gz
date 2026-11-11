---
name: breakdown
description: "Create an exploded-view product animation that separates and reassembles identified components. Use for product structure and assembly explanations, not generic scene breakdowns."
metadata:
  author: AI Master
  version: "1.0.0"
---

# פירוק מוצר לחלקים

## Inputs and component truth
Read the supplied product image, model, parts list or diagram. Build a component table containing part name, supporting source, parent assembly, rest transform and explosion direction. A single exterior photo does not establish hidden components. Ask for missing internal details or explicitly offer an exterior-only or schematic illustration; never invent a purportedly accurate interior.

## Scene and motion
For a 3D product use an available 3D renderer and source model, or construct a clearly labeled schematic from primitives. For a flat labeled diagram, SVG can be sufficient; identify that output as a 2D schematic.
Preserve the assembled silhouette and materials. Give each component a stable identifier and one rest transform. Explode outward along distinct axes with a small stagger so the user can follow each part. Compute transforms from the rest pose and time, never by accumulating per-frame translations.
Default duration 10 seconds: assembled hold 0–2; separate parts 2–5; exploded hold with labels 5–7; reverse the same paths 7–9; assembled hold 9–10. Adjust for the number of parts.
Use easing with zero velocity at the holds. Labels stay readable and do not rotate with the objects. Draw restrained leader lines; avoid crossing the product with unnecessary text. Include only components actually visible and supported by the input.
Prevent clipping and unintended intersections across the complete explosion and return paths. Fit the camera to the entire exploded bounding box, not only the initial assembled model. Distinguish a marketing exploded view from a real assembly procedure.

## Category acceptance
Every part returns to its exact rest transform. The final silhouette matches the opening. Labels match the parts table, all components remain visible during the hold, and the output does not imply unverified product specifications.

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
/breakdown צור המחשה סכמטית של עט מארבעה חלקים: מכסה, גוף, מילוי וחוד. הפרד וחבר מחדש ב־10 שניות.
```
