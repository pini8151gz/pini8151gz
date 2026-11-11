---
name: map-route
description: "Animate a route between supplied geographic locations on a map with accurate endpoint placement. Use for travel or geographic storytelling, distinguishing an illustrative connection from a verified road route."
metadata:
  author: AI Master
  version: "1.0.0"
---

# מסלול מונפש על מפה

## Resolve geographic meaning
Read origin, destination and any stops. Resolve ambiguous place names before drawing. Use supplied coordinates or a reliable geocoding/map source actually available to you; record the source and coordinate order. Do not invent coordinates, travel durations, road paths or distances. Missing geographic data is a reason to ask, not a reason to draw a fictitious map.
Clarify route type if needed. Default to a clearly labeled illustrative connection, not a driving itinerary. Use actual routing data for a claimed road route. If no map dataset is available, offer a labeled schematic connection rather than presenting an invented outline as a geographic map.

## Geometry and timing
Use an available map dataset, licensed tiles or vector basemap and preserve required attribution. Keep labels separate from the map mesh. A tilted flat map is a perspective map, not real terrain; call it that. Real terrain needs elevation data.
Use the map's coordinate projection consistently for outline, endpoints, route and labels. For long-distance illustrative travel, use a geodesic path or an explicitly schematic arc; handle the antimeridian with longitude unwrapping or split geometry so the line does not cross the whole viewport incorrectly.
Fit the camera to the entire route with padding for markers and labels. If the chosen projection clamps polar latitudes, disclose the limit and choose an appropriate view.
Parameterize drawing progress by cumulative path length so speed stays consistent despite unevenly spaced points. Start with the origin, reveal the route, then highlight the destination. Default 8 seconds: 1-second origin hold, 5-second route reveal, 2-second final hold. Keep camera movement gentle and endpoint labels readable.
For a 3D globe, use a sphere and correctly mapped geographic coordinates; lift the connection above the surface and avoid passing through the globe. A hidden endpoint may require a camera move rather than a misleading repositioning.

## Category acceptance
Cross-check endpoint placement and names against the source. Inspect route continuity, antimeridian behavior when relevant, marker visibility and attribution. The screen explicitly identifies illustrative routes; travel metrics appear only when supplied or verified.

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
/map-route הצג חיבור המחשה בין תל אביב לירושלים על מפה אמיתית. אמת את המיקומים, בלי זמן נסיעה ובלי להציג את הקו כנתיב כביש.
```
