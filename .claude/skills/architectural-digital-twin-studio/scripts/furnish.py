"""Furniture layer – VISUAL ONLY, Modern Minimalist Luxury.

Furniture never changes verified geometry: every item is placed inside the
free space of a space (room polygon, or for open-plan areas the free area
around the label point) shrunk by a wall clearance, and an item that does not
fit is skipped rather than squeezed. Items are lists of rotated boxes
("parts") in model millimetres, so every exporter and the viewer can draw
them the same way.
"""
import math

from shapely import affinity
from shapely.geometry import Point, Polygon, box

# Modern Minimalist Luxury palette (name -> [r, g, b], roughness, metalness)
MATERIALS = {
    "oak":        {"color": [176, 138, 99],  "roughness": 0.55, "metalness": 0.0},
    "walnut":     {"color": [104, 74, 52],   "roughness": 0.5,  "metalness": 0.0},
    "linen":      {"color": [236, 231, 222], "roughness": 0.95, "metalness": 0.0},
    "bouclé":     {"color": [222, 216, 205], "roughness": 1.0,  "metalness": 0.0},
    "charcoal":   {"color": [62, 62, 66],    "roughness": 0.9,  "metalness": 0.0},
    "marble":     {"color": [234, 232, 228], "roughness": 0.18, "metalness": 0.0},
    "travertine": {"color": [214, 200, 178], "roughness": 0.45, "metalness": 0.0},
    "brass":      {"color": [181, 154, 106], "roughness": 0.3,  "metalness": 0.9},
    "black":      {"color": [30, 30, 32],    "roughness": 0.4,  "metalness": 0.6},
    "lacquer":    {"color": [244, 242, 238], "roughness": 0.25, "metalness": 0.0},
    "rug":        {"color": [198, 186, 170], "roughness": 1.0,  "metalness": 0.0},
    "green":      {"color": [96, 122, 88],   "roughness": 0.8,  "metalness": 0.0},
    "glass":      {"color": [188, 212, 222], "roughness": 0.05, "metalness": 0.0, "opacity": 0.32},
    "wall":       {"color": [236, 232, 225], "roughness": 0.85, "metalness": 0.0},
    "shaft":      {"color": [46, 46, 52],    "roughness": 0.6,  "metalness": 0.2, "opacity": 0.75},
}

TYPE_BY_NAME = [
    (("ממ\"ד", "ממ״ד", "mamad", "safe"), "saferoom"),
    (("מדרגות", "stair"), "stair"),
    (("סלון", "living"), "living"),
    (("מטבח", "kitchen"), "kitchen"),
    (("רחצה", "שירותים", "אמבט", "bath", "wc", "toilet"), "bath"),
    (("שינה", "חדר", "bedroom", "room"), "bedroom"),
]


def room_type(r):
    if r.get("type"):
        return r["type"]
    txt = f"{r.get('name', '')} {r.get('name_en', '')}".lower()
    for keys, t in TYPE_BY_NAME:
        if any(k.lower() in txt for k in keys):
            return t
    return None


def _frame(poly):
    """Local frame of a space: centre, long axis angle, length, width."""
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    if l1 >= l2:
        ang, L, W = math.atan2(e1[1], e1[0]), l1, l2
    else:
        ang, L, W = math.atan2(e2[1], e2[0]), l2, l1
    return r.centroid.x, r.centroid.y, ang, L, W


def P(u, v, w, d, z0, h, mat):
    """Part in group-local coordinates: u along the wall, v into the room
    (the group's back edge is v = 0)."""
    return (u, v, w, d, z0, h, mat)


def part_polygon(p):
    b = box(-p["w"] / 2, -p["d"] / 2, p["w"] / 2, p["d"] / 2)
    b = affinity.rotate(b, p["rot"], origin=(0, 0), use_radians=True)
    return affinity.translate(b, p["x"], p["y"])


def _place(group, ax, ay, theta):
    """theta = direction of the wall (u axis); v axis points into the room."""
    out = []
    ct, st = math.cos(theta), math.sin(theta)
    for (u, v, w, d, z0, h, mat) in group:
        x = ax + u * ct - v * st
        y = ay + u * st + v * ct
        out.append({"x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "d": round(d, 1),
                    "rot": round(theta, 5), "z0": round(z0, 1), "h": round(h, 1), "mat": mat})
    return out


def _footprint(parts):
    return [part_polygon(p) for p in parts if p["h"] > 5]


def _search(group, free, target, taken, step=150.0, inset=15.0):
    """Slide the group along every wall of `free`, back to the wall, and keep
    the fitting spot nearest to `target` that does not collide with `taken`."""
    from shapely.geometry.polygon import orient
    width = max(abs(u) + w / 2 for (u, v, w, d, z0, h, m) in group) * 2
    best = None
    rings = [orient(free, 1.0).exterior]
    for ring in rings:
        c = list(ring.coords)
        for i in range(len(c) - 1):
            (x1, y1), (x2, y2) = c[i], c[i + 1]
            L = math.hypot(x2 - x1, y2 - y1)
            if L < width:
                continue
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            nx, ny = -uy, ux  # left normal = inside for a CCW exterior
            theta = math.atan2(uy, ux)
            n = max(1, int((L - width) // step) + 1)
            for k in range(n + 1):
                t = width / 2 + (L - width) * (k / n if n else 0.5)
                ax, ay = x1 + ux * t + nx * inset, y1 + uy * t + ny * inset
                parts = _place(group, ax, ay, theta)
                fps = _footprint(parts)
                if not all(free.contains(f) for f in fps):
                    continue
                if taken is not None and any(f.intersects(taken) for f in fps):
                    continue
                cx = sum(f.centroid.x for f in fps) / len(fps)
                cy = sum(f.centroid.y for f in fps) / len(fps)
                score = math.hypot(cx - target[0], cy - target[1])
                if best is None or score < best[0]:
                    best = (score, parts)
    return best[1] if best else None


# ---------------------------------------------------------------- groups
def _bed(bw):
    g = [P(0, 1050, bw, 2100, 0, 300, "walnut"), P(0, 1080, bw - 40, 2000, 300, 220, "linen"),
         P(0, 40, bw + 120, 80, 0, 1050, "oak"), P(0, 1650, bw - 20, 900, 520, 40, "charcoal")]
    for s in (-1, 1):
        g += [P(s * (bw / 2 + 290), 230, 450, 400, 0, 450, "oak"), P(s * (bw / 2 + 290), 230, 130, 130, 450, 380, "brass")]
    return g


def _rug(w, d, v):
    return [P(0, v, w, d, 0, 8, "rug")]


GROUPS = {
    "bedroom": [
        ("bed", [_bed(1600) + _rug(2800, 1600, 1500), _bed(1600), _bed(1400), _bed(900)], True),
        ("wardrobe", [[P(0, 300, 1800, 600, 0, 2400, "lacquer")], [P(0, 300, 1200, 600, 0, 2400, "lacquer")]], False),
    ],
    "living": [
        ("sofa", [[P(0, 450, L_, 900, 0, 420, "bouclé"), P(0, 80, L_, 160, 0, 780, "bouclé"),
                   P(0, 1450, 1200, 650, 0, 380, "travertine"), P(0, 1300, L_ + 600, 2200, 0, 8, "rug"),
                   P(L_ / 2 + 330, 300, 420, 420, 0, 560, "brass")] for L_ in (2600, 2200, 1800)], True),
        ("tv", [[P(0, 220, 2000, 420, 0, 480, "walnut")], [P(0, 220, 1500, 420, 0, 480, "walnut")]], False),
        ("dining", [[P(0, 1100, 1800, 900, 720, 30, "oak"), P(0, 1100, 1500, 600, 0, 720, "black")] +
                    [P(sx * 500, 1100 + sy * 650, 450, 450, 0, 450, "charcoal") for sx in (-1, 1) for sy in (-1, 1)]], False),
        ("plant", [[P(0, 250, 380, 380, 0, 420, "travertine"), P(0, 250, 520, 520, 420, 650, "green")]], False),
    ],
    "kitchen": [
        ("counter", [[P(0, 300, L_, 600, 0, 870, "lacquer"), P(0, 310, L_, 620, 870, 30, "marble"),
                      P(0, 175, L_, 350, 1500, 700, "lacquer")] for L_ in (3600, 3000, 2400, 1800)], True),
        ("table", [[P(0, 1000, 1400, 800, 720, 30, "oak"), P(0, 1000, 1100, 500, 0, 720, "black")]], False),
    ],
    "saferoom": [
        ("desk", [[P(0, 360, W_, 700, 720, 30, "oak"), P(-W_ / 2 + 60, 360, 60, 650, 0, 720, "black"),
                   P(W_ / 2 - 60, 360, 60, 650, 0, 720, "black"), P(0, 1000, 520, 520, 0, 460, "charcoal"),
                   P(0, 1230, 480, 60, 460, 400, "charcoal")] for W_ in (1500, 1200)], True),
        ("shelf", [[P(0, 180, 1200, 350, 0, 2000, "walnut")], [P(0, 180, 800, 350, 0, 2000, "walnut")]], False),
    ],
}
RECIPES = GROUPS


def furnish_space(rtype, free, label=None, obstacles=None):
    """Return (parts, note). `free` is the usable floor polygon (walls already
    removed and clearance applied). Groups are placed one by one, primary
    first; each must back onto a wall, fit inside `free` and not collide."""
    if rtype not in GROUPS:
        return [], "no furniture for this space type"
    if free.is_empty or free.area < 2.0e6:
        return [], "space too small"
    target = label if label is not None else (free.centroid.x, free.centroid.y)
    placed, taken, missing = [], obstacles, []
    for name, variants, primary in GROUPS[rtype]:
        got = None
        for g in variants:
            got = _search(g, free, target, taken)
            if got:
                break
        if not got:
            if primary:
                return [], f"no room for the {name} without touching walls"
            missing.append(name)
            continue
        placed += got
        fp = [part_polygon(p).buffer(250) for p in got if p["h"] > 5]
        from shapely.ops import unary_union
        taken = unary_union(fp + ([taken] if taken is not None else []))
    return placed, "placed" + (f" (skipped: {', '.join(missing)})" if missing else "")


def free_area(walls, slab, room_geom=None, label=None, clearance=60.0, reach=2600.0):
    """Usable floor: a closed room's polygon, or for an open area the free
    floor within `reach` of the label point. Walls are removed with clearance."""
    if room_geom is not None:
        base = room_geom
    elif label is not None:
        base = slab.intersection(Point(label).buffer(reach, cap_style="square"))
    else:
        return Polygon()
    f = base.difference(walls.buffer(clearance, join_style="mitre"))
    f = f.buffer(-clearance, join_style="mitre").buffer(clearance, join_style="mitre")
    if label is not None and hasattr(f, "geoms"):
        P = Point(label)
        parts = [g for g in f.geoms if g.geom_type == "Polygon"]
        if parts:
            f = min(parts, key=lambda g: g.distance(P))
    return f if f.geom_type == "Polygon" else Polygon()


def eye_view(parts, free, eye=1600.0):
    """Camera pose for an eye-level still of a furnished space: stand in the
    corner of the space's own floor that is farthest from the furniture
    (pulled 450 mm in from the walls) and look at the furniture's centre."""
    fps = [part_polygon(p) for p in parts if p["h"] > 5]
    if not fps or free.is_empty:
        return None
    cx = sum(f.centroid.x for f in fps) / len(fps)
    cy = sum(f.centroid.y for f in fps) / len(fps)
    inner = free.buffer(-450, join_style="mitre")
    if inner.is_empty:
        inner = free
    if hasattr(inner, "geoms"):
        inner = max(inner.geoms, key=lambda g: g.area)
    from shapely.ops import unary_union
    blocked = unary_union([f.buffer(300) for f in fps])
    best = None
    for (x, y) in list(inner.exterior.coords)[:-1]:
        if blocked.contains(Point(x, y)):
            continue
        d = math.hypot(x - cx, y - cy)
        if best is None or d > best[0]:
            best = (d, x, y)
    if best is None:
        return None
    return {"cam": [round(best[1], 1), round(best[2], 1), eye], "target": [round(cx, 1), round(cy, 1), 900.0]}
