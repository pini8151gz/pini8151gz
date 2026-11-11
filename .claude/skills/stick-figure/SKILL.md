---
name: stick-figure
description: "Turn an idea or short script into a clear animated stick-figure explainer with consistent characters and gestures. Use when the visual language is simple line-drawn human figures."
metadata:
  author: AI Master
  version: "1.0.0"
---

# סרטון דמויות מקל

## Story and characters
Extract the message and make 2–4 visual beats: a situation, an action or obstacle, and a resolution. Keep supplied wording and meaning. If the brief is complete, choose sensible scene lengths and proceed. Identify each character with a stable name, body proportions and accent color.

## Rig and staging
Use SVG or Canvas for clean lines; use an installed animation/video engine when available. Build each figure from a head, torso, hips, and articulated limbs. Define joint pivots once. Hands attach to forearms, feet to legs, and the head to the torso. Keep limb segment lengths constant; move joints rather than stretching arbitrary lines.
Use a consistent ground line, stroke width and character scale. Default to dark lines on a light background with one accent color. Use readable poses before adding motion.
For a walk, coordinate opposite arm and leg swings, contact and passing poses. Keep the planted foot still during its contact interval and make any body translation consistent with the step. For a gesture, anticipate, execute, then hold the final pose. Do not animate every limb continuously.
Anchor held props to the correct hand. Change facial expression sparingly using simple eyes and mouth. Stage characters so their limbs do not overlap into an unreadable knot. A cut or a short slide between scenes is preferable to excessive transitions.
Use a deterministic timeline. For a default 12-second short, allow roughly 3–4 seconds per beat and at least 1 second to read the result. Adapt to the script and do not invent a business outcome.

## Category acceptance
Inspect contact poses, prop attachment and transitions. Character identity, limb lengths and stroke weight remain consistent. Each scene communicates one action even with audio muted.

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
/stick-figure צור סרטון של 12 שניות: אדם מול ערימת משימות, מחלק אותן לשלוש קבוצות, ואז מטפל בקבוצה אחת בכל פעם. בלי הבטחות לחיסכון בזמן.
```
