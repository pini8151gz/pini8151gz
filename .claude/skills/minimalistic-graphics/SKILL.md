---
name: minimalistic-graphics
description: "Explain a concept with purposeful animated geometric shapes, dots, lines and restrained typography. Use for abstract process or relationship explanations without characters or data-chart requirements."
metadata:
  author: AI Master
  version: "1.0.0"
---

# גרפיקה מינימליסטית להסברים

## Meaning before decoration
Extract one message from the supplied text. Assign a stable visual meaning to each shape, connector and color. Do not imply a measured quantity through object count or size unless the input supports it. For example, dots can represent requests, boxes can represent steps, and a moving dot can represent transfer; keep that mapping consistent.
Choose 2–4 beats that reveal the relationship: introduce elements, show the change, hold the resulting arrangement. Use the user's words for key labels. Abstract metaphors must not introduce an unsupported product capability or performance claim.

## Build and animate
Use SVG/HTML/CSS or an installed motion engine. Default to a light background, dark text and one accent color. Let spacing and hierarchy carry the explanation. Use large simple geometry and ample whitespace.
Place all objects on a consistent layout grid. Avoid unnecessary tiny detail, shadows and gradients. Use a controlled type scale; headline and labels must remain readable at phone size. Keep text as text with proper Hebrew direction when relevant.
Animate only changes that convey meaning: a connection appears when a relationship is established, a dot follows a line to show transfer, a group separates to show classification. Background drift, perpetual bouncing and unrelated spinning obscure the explanation and should not be defaults.
Use a deterministic timeline with smooth starts and stops. Reveal elements in causal order and hold each state long enough to understand it. A default 10-second piece can spend 2 seconds introducing, 5 seconds demonstrating and 3 seconds holding the result.
When morphing shapes, keep vertex correspondence and topology valid; use a simple crossfade if a morph would create distracting self-intersections. Transitions should preserve object identity and the spatial explanation.

## Category acceptance
The explanation remains understandable without narration. Shape meanings and colors do not change mid-piece. Readable labels, generous margins and the final explanatory state survive both a full-size and phone-size review.

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
/minimalistic-graphics הסבר ב־10 שניות איך רעיון אחד הופך לשלוש משימות. עיגול לרעיון, שלושה מלבנים למשימות, צבע הדגשה כתום ועברית.
```
