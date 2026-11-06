#!/usr/bin/env python3
"""Step 7c – photorealistic stills and film with Blender Cycles (path tracing).

Builds the scene directly from model.json (the single verified source), so
the geometry in every image is the measured model; only materials, light
and furniture are VISUAL ONLY. Runs on the CPU when there is no GPU.

Setup (once):  python3.11 -m venv bvenv && bvenv/bin/pip install bpy   (Blender as a Python module)
Run:
  bvenv/bin/python render_photoreal.py work/floor-1/model/model.json --out work/photoreal \
      [--size 1600x900] [--samples 128] [--max-rooms 6] [--video] [--video-size 1280x720]
      [--video-samples 24] [--render-fps 8] [--fps 24]

Outputs: interiors/NN-<type>.png (eye level, 2-point perspective),
axonometric-furnished.png, aerial.png, film/walkthrough.mp4 (+ clips/),
photoreal.json (timings and settings).

Time on 4 CPU cores (sample plan): ~2–4 min per 1600×900 still at 128
samples; the film renders key frames at --render-fps and interpolates to
--fps with motion compensation (ffmpeg minterpolate), ~1–2 h for 30 s.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import time

import bpy
import bmesh
from mathutils import Vector, geometry

A = None


# ----------------------------------------------------------------- materials
def _node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        if k in n.inputs:
            n.inputs[k].default_value = v
    return n


def _principled(name, color, rough=0.5, metal=0.0, transmission=0.0, coat=0.0, sheen=0.0, ior=1.45, alpha=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for key in ("Transmission Weight", "Transmission"):
        if key in b.inputs:
            b.inputs[key].default_value = transmission
    for key in ("Coat Weight", "Clearcoat"):
        if key in b.inputs:
            b.inputs[key].default_value = coat
    for key in ("Sheen Weight", "Sheen"):
        if key in b.inputs:
            b.inputs[key].default_value = sheen
    b.inputs["IOR"].default_value = ior
    b.inputs["Alpha"].default_value = alpha
    return m, nt, b


def srgb(rgb):
    def c(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return tuple(c(v) for v in rgb)


def mat_wood(name, light, dark, plank=True, scale=1.0, rough=0.38):
    m, nt, b = _principled(name, light, rough)
    tc = _node(nt, "ShaderNodeTexCoord", (-1200, 0))
    mp = _node(nt, "ShaderNodeMapping", (-1000, 0))
    nt.links.new(tc.outputs["Object" if not plank else "Generated"], mp.inputs["Vector"])
    if plank:
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        mp.inputs["Scale"].default_value = (1.0 * scale, 1.0 * scale, 1.0)
        br = _node(nt, "ShaderNodeTexBrick", (-800, 200))
        br.inputs["Scale"].default_value = 1.0
        br.inputs["Mortar Size"].default_value = 0.004
        br.inputs["Brick Width"].default_value = 1.2
        br.inputs["Row Height"].default_value = 0.18
        br.offset = 0.37
        nt.links.new(mp.outputs["Vector"], br.inputs["Vector"])
        br.inputs["Color1"].default_value = (*light, 1)
        br.inputs["Color2"].default_value = (*[(a + b_) / 2 for a, b_ in zip(light, dark)], 1)
        br.inputs["Mortar"].default_value = (*dark, 1)
    wave = _node(nt, "ShaderNodeTexWave", (-800, -150))
    wave.inputs["Scale"].default_value = 3.0 * scale
    wave.inputs["Distortion"].default_value = 6.0
    wave.inputs["Detail"].default_value = 3.0
    nt.links.new(mp.outputs["Vector"], wave.inputs["Vector"])
    ramp = _node(nt, "ShaderNodeValToRGB", (-550, -150))
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    mix = _node(nt, "ShaderNodeMix", (-300, 0))
    mix.data_type = "RGBA"
    mix.inputs["Factor"].default_value = 0.45
    if plank:
        nt.links.new(br.outputs["Color"], mix.inputs[6])
    else:
        mix.inputs[6].default_value = (*light, 1)
    nt.links.new(ramp.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    bump = _node(nt, "ShaderNodeBump", (-300, -300))
    bump.inputs["Strength"].default_value = 0.08
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_noise(name, color, rough, bump_strength=0.15, scale=180.0, sheen=0.0, metal=0.0):
    m, nt, b = _principled(name, color, rough, metal=metal, sheen=sheen)
    n = _node(nt, "ShaderNodeTexNoise", (-500, -200))
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = 8.0
    bump = _node(nt, "ShaderNodeBump", (-250, -200))
    bump.inputs["Strength"].default_value = bump_strength
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_marble(name, base=(0.92, 0.91, 0.89), vein=(0.55, 0.53, 0.5)):
    m, nt, b = _principled(name, base, 0.12, coat=0.3)
    n = _node(nt, "ShaderNodeTexNoise", (-800, 0))
    n.inputs["Scale"].default_value = 2.5
    n.inputs["Detail"].default_value = 12.0
    n.inputs["Distortion"].default_value = 3.0
    w = _node(nt, "ShaderNodeTexWave", (-600, 0))
    w.inputs["Scale"].default_value = 1.5
    w.inputs["Distortion"].default_value = 12.0
    nt.links.new(n.outputs["Color"], w.inputs["Vector"])
    r = _node(nt, "ShaderNodeValToRGB", (-350, 0))
    r.color_ramp.elements[0].position = 0.0
    r.color_ramp.elements[0].color = (*vein, 1)
    r.color_ramp.elements[1].position = 0.12
    r.color_ramp.elements[1].color = (*base, 1)
    nt.links.new(w.outputs["Fac"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], b.inputs["Base Color"])
    return m


def build_materials():
    M = {}
    M["floor"] = mat_wood("oak-parquet", srgb((196, 160, 118)), srgb((150, 112, 76)), plank=True)
    M["oak"] = mat_wood("oak", srgb((184, 146, 104)), srgb((140, 104, 70)), plank=False, scale=2.0)
    M["walnut"] = mat_wood("walnut", srgb((110, 78, 54)), srgb((70, 48, 32)), plank=False, scale=2.0, rough=0.42)
    M["wall"] = mat_noise("plaster", srgb((236, 233, 227)), 0.9, 0.05, 40.0)
    M["ceiling"] = mat_noise("ceiling", srgb((242, 241, 238)), 0.95, 0.02, 30.0)
    M["linen"] = mat_noise("linen", srgb((232, 227, 218)), 0.95, 0.25, 400.0, sheen=0.4)
    M["bouclé"] = mat_noise("boucle", srgb((222, 216, 205)), 1.0, 0.6, 260.0, sheen=0.6)
    M["charcoal"] = mat_noise("charcoal-wool", srgb((66, 66, 70)), 0.95, 0.3, 300.0, sheen=0.3)
    M["rug"] = mat_noise("wool-rug", srgb((150, 138, 122)), 1.0, 0.9, 120.0, sheen=0.5)
    M["marble"] = mat_marble("marble")
    M["travertine"] = mat_noise("travertine", srgb((214, 200, 178)), 0.45, 0.25, 25.0)
    M["brass"] = mat_noise("brass", srgb((200, 168, 110)), 0.28, 0.02, 60.0, metal=1.0)
    M["black"] = mat_noise("black-metal", srgb((28, 28, 30)), 0.35, 0.01, 60.0, metal=0.8)
    M["lacquer"] = _principled("white-lacquer", srgb((244, 242, 238)), 0.18, coat=0.6)[0]
    M["green"] = mat_noise("leaves", srgb((70, 104, 62)), 0.6, 0.6, 30.0, sheen=0.2)
    M["glass"] = _principled("glass", (0.95, 0.97, 0.98), 0.0, transmission=1.0, ior=1.5)[0]
    M["frame"] = _principled("aluminium-black", srgb((38, 38, 40)), 0.3, metal=0.9)[0]
    M["shaft"] = _principled("lift-steel", srgb((150, 150, 155)), 0.25, metal=1.0)[0]
    M["slab"] = mat_noise("concrete", srgb((180, 178, 172)), 0.85, 0.2, 20.0)
    M["steel"] = _principled("brushed-steel", srgb((170, 170, 172)), 0.3, metal=1.0)[0]
    M["screen"] = _principled("tv-glass", srgb((8, 8, 10)), 0.05, coat=1.0)[0]
    M["shade"] = _principled("lamp-shade", srgb((240, 232, 214)), 0.9, transmission=0.4)[0]
    art, nt, b = _principled("canvas", srgb((200, 190, 175)), 0.9)
    n = _node(nt, "ShaderNodeTexNoise", (-600, 0)); n.inputs["Scale"].default_value = 1.6; n.inputs["Detail"].default_value = 2.0
    r = _node(nt, "ShaderNodeValToRGB", (-350, 0))
    r.color_ramp.elements[0].color = (*srgb((196, 120, 84)), 1); r.color_ramp.elements[1].color = (*srgb((232, 222, 204)), 1)
    r.color_ramp.elements.new(0.55).color = (*srgb((60, 74, 90)), 1)
    nt.links.new(n.outputs["Fac"], r.inputs["Fac"]); nt.links.new(r.outputs["Color"], b.inputs["Base Color"])
    M["art"] = art
    M["books"] = [mat_noise(f"book{i}", srgb(c), 0.7, 0.05, 50.0) for i, c in enumerate(
        [(150, 62, 48), (52, 72, 96), (210, 196, 170), (90, 104, 78), (40, 40, 44), (186, 150, 96)])]
    return M


# ----------------------------------------------------------------- geometry
def prism(name, outer, holes, z0, h, mat, bevel=0.0, coll=None):
    """Extrude a polygon (metres) with holes from z0 by h."""
    outer = [Vector((x, y, 0)) for x, y in outer]
    holes = [[Vector((x, y, 0)) for x, y in hh] for hh in holes]
    if len(outer) > 1 and (outer[0] - outer[-1]).length < 1e-6:
        outer = outer[:-1]
    holes = [hh[:-1] if len(hh) > 1 and (hh[0] - hh[-1]).length < 1e-6 else hh for hh in holes]
    loops = [outer] + holes
    try:
        tris = geometry.tessellate_polygon([[tuple(v) for v in lp] for lp in loops])
    except Exception:  # noqa: BLE001
        return None
    pts = [v for lp in loops for v in lp]
    if not tris:
        return None
    bm = bmesh.new()
    bot = [bm.verts.new((p.x, p.y, z0)) for p in pts]
    top = [bm.verts.new((p.x, p.y, z0 + h)) for p in pts]
    for a, b, c in tris:
        try:
            bm.faces.new((top[a], top[b], top[c]))
            bm.faces.new((bot[c], bot[b], bot[a]))
        except ValueError:
            pass
    off = 0
    for lp in loops:
        n = len(lp)
        for i in range(n):
            j = (i + 1) % n
            try:
                bm.faces.new((bot[off + i], bot[off + j], top[off + j], top[off + i]))
            except ValueError:
                pass
        off += n
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    ob.data.materials.append(mat)
    if bevel > 0:
        md = ob.modifiers.new("bevel", "BEVEL")
        md.width = bevel
        md.segments = 3
        md.limit_method = "ANGLE"
    for f in ob.data.polygons:
        f.use_smooth = False
    return ob


def box(name, x, y, w, d, rot, z0, h, mat, bevel=0.012, coll=None):
    ob = prism(name, [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)], [], 0, h, mat,
               bevel=min(bevel, w / 4, d / 4, h / 4), coll=coll)
    if ob:
        ob.location = (x, y, z0)
        ob.rotation_euler = (0, 0, rot)
    return ob


def cyl(name, x, y, r, z0, h, mat, coll, verts=32):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=(x, y, z0 + h / 2))
    o = bpy.context.active_object
    o.data.materials.append(mat)
    for poly in o.data.polygons:
        poly.use_smooth = True
    for c in o.users_collection:
        c.objects.unlink(o)
    coll.objects.link(o)
    return o


def detailed(p, MAT, coll, tops, H):
    """Detailed model of a furniture part on its exact footprint (VISUAL ONLY).
    Local frame: u along the part width (wall direction), v toward the room."""
    role = p.get("role", "")
    cx, cy = p["x"] / 1000, p["y"] / 1000
    W_, D_, Z0, Hh = p["w"] / 1000, p["d"] / 1000, p["z0"] / 1000, max(p["h"], 5) / 1000
    a = p["rot"]
    ca, sa = math.cos(a), math.sin(a)

    def at(u, v):
        return cx + u * ca - v * sa, cy + u * sa + v * ca

    def B(u, v, w, d, z0, h, mat, bev=0.006, tilt=0.0):
        x, y = at(u, v)
        o = box(role, x, y, w, d, a, z0, h, mat, bev, coll)
        if o and tilt:
            o.rotation_euler = (tilt * ca, tilt * sa, a)
        return o

    def legs(w, d, z0, h, r=0.022, inset=0.05, mat=None):
        for su in (-1, 1):
            for sv in (-1, 1):
                x, y = at(su * (w / 2 - inset), sv * (d / 2 - inset))
                cyl("leg", x, y, r, z0, h, mat or MAT["black"], coll, 16)

    if role == "sofa-seat":
        B(0, 0, W_, D_ - 0.02, 0.08, 0.16, MAT["bouclé"], 0.03)
        n = 3 if W_ > 2.0 else 2
        cw = (W_ - 0.36) / n
        for i in range(n):
            B(-W_ / 2 + 0.18 + cw * (i + .5), 0.06, cw - 0.012, D_ - 0.24, 0.24, 0.18, MAT["bouclé"], 0.06)
        for su in (-1, 1):
            B(su * (W_ / 2 - 0.09), 0, 0.18, D_ - 0.02, 0.08, 0.5, MAT["bouclé"], 0.06)
        legs(W_ - 0.1, D_ - 0.1, 0, 0.08, 0.018, 0.04, MAT["walnut"])
        return True
    if role == "sofa-back":
        B(0, 0, W_, D_, 0.08, 0.7, MAT["bouclé"], 0.05)
        n = 3 if W_ > 2.0 else 2
        cw = (W_ - 0.36) / n
        for i in range(n):
            B(-W_ / 2 + 0.18 + cw * (i + .5), D_ / 2 + 0.1, cw - 0.02, 0.2, 0.42, 0.42, MAT["linen"], 0.07, tilt=math.radians(-8))
        # framed artwork on the wall above the sofa
        B(0, -D_ / 2 + 0.02, min(1.4, W_ * 0.6), 0.03, 1.25, 0.9, MAT["black"], 0.004)
        B(0, -D_ / 2 + 0.04, min(1.4, W_ * 0.6) - 0.06, 0.02, 1.28, 0.84, MAT["art"], 0.0)
        return True
    if role == "bed-frame":
        B(0, 0, W_, D_, 0.1, Hh - 0.1, MAT["walnut"], 0.02)
        legs(W_ - 0.1, D_ - 0.1, 0, 0.1, 0.025, 0.06, MAT["walnut"])
        return True
    if role == "mattress":
        B(0, 0, W_, D_, Z0, 0.2, MAT["linen"], 0.06)
        B(0, D_ * 0.18, W_ + 0.04, D_ * 0.66, Z0 + 0.16, 0.08, MAT["linen"], 0.04)  # duvet
        n = 2 if W_ > 1.2 else 1
        for i in range(n):
            u = 0 if n == 1 else (-1 if i == 0 else 1) * W_ / 4
            B(u, -D_ / 2 + 0.25, W_ / n - 0.1, 0.38, Z0 + 0.2, 0.14, MAT["linen"], 0.06)
        return True
    if role == "headboard":
        B(0, 0, W_, D_, 0, Hh, MAT["bouclé"], 0.03)
        B(0, -D_ / 2 + 0.02, min(1.2, W_ * 0.7), 0.03, 1.45, 0.7, MAT["black"], 0.004)
        B(0, -D_ / 2 + 0.04, min(1.2, W_ * 0.7) - 0.06, 0.02, 1.48, 0.64, MAT["art"], 0.0)
        return True
    if role == "nightstand":
        B(0, 0, W_, D_, 0.12, Hh - 0.12, MAT["oak"], 0.01)
        B(0, D_ / 2, W_ - 0.04, 0.004, 0.32, 0.004, MAT["black"], 0.0)
        legs(W_ - 0.04, D_ - 0.04, 0, 0.12, 0.012, 0.03, MAT["black"])
        return True
    if role in ("table-lamp", "side-lamp"):
        x, y = at(0, 0)
        if role == "table-lamp":
            cyl("lamp", x, y, 0.07, Z0, 0.22, MAT["brass"], coll)
            cyl("shade", x, y, 0.15, Z0 + 0.22, 0.2, MAT["shade"], coll)
        else:
            cyl("base", x, y, 0.16, 0, 0.02, MAT["black"], coll)
            cyl("pole", x, y, 0.012, 0.02, 1.4, MAT["brass"], coll, 12)
            cyl("shade", x, y, 0.2, 1.38, 0.26, MAT["shade"], coll)
        L_ = bpy.data.lights.new("lamp", "POINT")
        L_.energy = 30
        L_.color = (1.0, 0.76, 0.52)
        L_.shadow_soft_size = 0.1
        lo = bpy.data.objects.new("lamp", L_)
        lo.location = (x, y, (Z0 + 0.32) if role == "table-lamp" else 1.5)
        coll.objects.link(lo)
        return True
    if role == "coffee-table":
        B(0, 0, W_, D_, Hh - 0.04, 0.04, MAT["travertine"], 0.01)
        B(0, 0, W_ * 0.55, D_ * 0.55, 0, Hh - 0.04, MAT["travertine"], 0.01)
        return True
    if role == "rug":
        B(0, 0, W_, D_, 0.012, 0.012, MAT["rug"], 0.004)
        return True
    if role == "tv-unit":
        B(0, 0, W_, D_, 0.1, Hh - 0.1, MAT["walnut"], 0.006)
        for i in range(1, 4):
            B(-W_ / 2 + W_ * i / 4, D_ / 2, 0.004, 0.004, 0.12, Hh - 0.14, MAT["black"], 0.0)
        B(0, -D_ / 2 + 0.03, min(1.45, W_ * 0.75), 0.04, 1.05, min(1.45, W_ * 0.75) * 0.5625, MAT["screen"], 0.004)
        legs(W_ - 0.1, D_ - 0.1, 0, 0.1, 0.015, 0.04, MAT["black"])
        return True
    if role == "dining-top":
        B(0, 0, W_, D_, Z0, Hh, MAT["oak"], 0.008)
        return True
    if role == "dining-base":
        legs(W_ + 0.2, D_ + 0.1, 0, 0.72, 0.025, 0.06, MAT["black"])
        return True
    if role in ("chair", "chair-seat"):
        tgt = tops[0] if tops else None
        back_v = -1.0
        if tgt is not None:
            tx, ty = tgt["x"] / 1000 - cx, tgt["y"] / 1000 - cy
            back_v = -1.0 if (-tx * sa + ty * ca) > 0 else 1.0
        B(0, 0, W_ - 0.02, D_ - 0.02, 0.43, 0.05, MAT["charcoal"], 0.02)
        B(0, back_v * (D_ / 2 - 0.03), W_ - 0.04, 0.04, 0.48, 0.42, MAT["charcoal"], 0.015)
        legs(W_ - 0.06, D_ - 0.06, 0, 0.43, 0.014, 0.03, MAT["walnut"] if role == "chair" else MAT["black"])
        return True
    if role == "chair-back":
        return True  # drawn with the seat
    if role == "planter":
        x, y = at(0, 0)
        cyl("pot", x, y, W_ / 2, 0, Hh, MAT["travertine"], coll)
        return True
    if role == "base-cabinets":
        B(0, 0.02, W_, D_ - 0.04, 0.1, Hh - 0.1, MAT["lacquer"], 0.003)
        B(0, -0.04, W_, D_ - 0.1, 0, 0.1, MAT["black"], 0.0)
        n = max(1, int(round(W_ / 0.6)))
        for i in range(1, n):
            B(-W_ / 2 + W_ * i / n, D_ / 2, 0.003, 0.004, 0.12, Hh - 0.14, MAT["black"], 0.0)
        for i in range(n):
            B(-W_ / 2 + W_ * (i + .5) / n, D_ / 2 + 0.012, 0.3, 0.012, Hh - 0.07, 0.012, MAT["brass"], 0.002)
        # sink and cooktop
        B(-W_ / 4, 0, 0.6, 0.42, Hh + 0.005, 0.03, MAT["steel"], 0.01)
        x, y = at(-W_ / 4, -D_ / 2 + 0.08)
        cyl("tap", x, y, 0.015, Hh + 0.03, 0.32, MAT["brass"], coll, 16)
        if W_ > 2.0:
            B(W_ / 4, 0.02, 0.6, 0.5, Hh + 0.03, 0.006, MAT["screen"], 0.004)
        return True
    if role == "worktop":
        B(0, 0, W_, D_, Z0, Hh, MAT["marble"], 0.004)
        return True
    if role == "wall-cabinets":
        B(0, 0, W_, D_, Z0, Hh, MAT["lacquer"], 0.003)
        n = max(1, int(round(W_ / 0.6)))
        for i in range(1, n):
            B(-W_ / 2 + W_ * i / n, D_ / 2, 0.003, 0.004, Z0 + 0.02, Hh - 0.04, MAT["black"], 0.0)
        return True
    if role == "wardrobe":
        B(0, 0, W_, D_, 0.05, Hh - 0.05, MAT["lacquer"], 0.003)
        n = max(2, int(round(W_ / 0.6)))
        for i in range(1, n):
            B(-W_ / 2 + W_ * i / n, D_ / 2, 0.003, 0.004, 0.08, Hh - 0.12, MAT["black"], 0.0)
        for i in range(n):
            B(-W_ / 2 + W_ * (i + .5) / n + 0.22, D_ / 2 + 0.012, 0.012, 0.012, 0.9, 0.5, MAT["brass"], 0.002)
        return True
    if role == "bookshelf":
        for su in (-1, 1):
            B(su * (W_ / 2 - 0.012), 0, 0.025, D_, 0, Hh, MAT["walnut"], 0.002)
        for k in range(6):
            z = 0.05 + k * (Hh - 0.08) / 5
            B(0, 0, W_ - 0.05, D_, z, 0.022, MAT["walnut"], 0.002)
            if k < 5:
                u = -W_ / 2 + 0.05
                while u < W_ / 2 - 0.12:
                    bw = random.uniform(0.02, 0.05)
                    bh = random.uniform(0.18, 0.28)
                    B(u + bw / 2, 0.02, bw, D_ - 0.08, z + 0.022, bh, random.choice(MAT["books"]), 0.002)
                    u += bw + random.uniform(0.002, 0.01)
        return True
    if role in ("desk-top", "desk-leg", "throw"):
        return False
    return False


def mm(p):
    return (p[0] / 1000.0, p[1] / 1000.0)


def build_scene(M, MAT, cut=None, ceiling=True):
    lv = M["levels"][0]
    H = lv["wall_height_mm"] / 1000.0
    hw = cut if cut is not None else H
    coll = bpy.data.collections.new("model")
    bpy.context.scene.collection.children.link(coll)
    for g in lv["slab"]["geometry"]:
        prism("slab", [mm(p) for p in g["exterior"]], [[mm(p) for p in h] for h in g["holes"]], -0.2, 0.2, MAT["slab"], coll=coll)
        prism("floor", [mm(p) for p in g["exterior"]], [[mm(p) for p in h] for h in g["holes"]], 0.0, 0.012, MAT["floor"], coll=coll)
        if ceiling:
            prism("ceiling", [mm(p) for p in g["exterior"]], [[mm(p) for p in h] for h in g["holes"]], H, 0.2, MAT["ceiling"], coll=coll)
    for w in lv["walls"]:
        g = w["geometry"]
        prism(w["id"], [mm(p) for p in g["exterior"]], [[mm(p) for p in h] for h in g["holes"]], 0.012, hw - 0.012, MAT["wall"], coll=coll)
    for es in lv.get("element_solids", []):
        z0, h = es["z0"] / 1000.0, es["h"] / 1000.0
        if cut is not None:
            if z0 >= cut:
                continue
            h = min(h, cut - z0)
        if h <= 0:
            continue
        mat = MAT.get(es["mat"], MAT["wall"])
        ob = prism(es["name"], [mm(p) for p in es["polygon"]], [], z0, h, mat,
                   bevel=0.004 if es["mat"] in ("oak", "black") else 0.0, coll=coll)
        if es["cls"] == "IfcWindow" and ob is not None:
            # black aluminium frame around the pane
            xs = [p[0] for p in es["polygon"]]
            ys = [p[1] for p in es["polygon"]]
            cx, cy = sum(xs[:-1]) / (len(xs) - 1) / 1000, sum(ys[:-1]) / (len(ys) - 1) / 1000
            pg = [mm(p) for p in es["polygon"][:-1]]
            e1 = Vector((pg[1][0] - pg[0][0], pg[1][1] - pg[0][1], 0))
            e2 = Vector((pg[2][0] - pg[1][0], pg[2][1] - pg[1][1], 0))
            L, D = (e1, e2) if e1.length >= e2.length else (e2, e1)
            ang = math.atan2(L.y, L.x)
            for zz in (z0, z0 + h - 0.05):
                box("frame", cx, cy, L.length + 0.06, 0.07, ang, zz, 0.05, MAT["frame"], 0.004, coll)
            for s_ in (-1, 1):
                box("frame", cx + math.cos(ang) * s_ * L.length / 2, cy + math.sin(ang) * s_ * L.length / 2,
                    0.05, 0.07, ang, z0, h, MAT["frame"], 0.004, coll)
            if L.length > 1.6:
                box("mullion", cx, cy, 0.05, 0.07, ang, z0, h, MAT["frame"], 0.004, coll)
    for f in lv.get("furniture", []):
        tops = [q for q in f["parts"] if q.get("role") == "dining-top"]
        for p in f["parts"]:
            if p.get("role") and detailed(p, MAT, coll, tops, H):
                continue
            x, y = mm((p["x"], p["y"]))
            h = max(p["h"], 5) / 1000.0
            if p["mat"] == "green":  # foliage: a soft cluster instead of a block
                for k in range(7):
                    r = min(p["w"], p["d"]) / 1000 * random.uniform(0.25, 0.4)
                    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=r,
                                                          location=(x + random.uniform(-.12, .12), y + random.uniform(-.12, .12),
                                                                    p["z0"] / 1000 + random.uniform(.15, h)))
                    o = bpy.context.active_object
                    o.data.materials.append(MAT["green"])
                    for poly in o.data.polygons:
                        poly.use_smooth = True
                continue
            bev = 0.03 if p["mat"] in ("bouclé", "linen", "charcoal") else 0.006 if p["h"] > 20 else 0.0
            box("furn", x, y, p["w"] / 1000, p["d"] / 1000, p["rot"], p["z0"] / 1000, h, MAT.get(p["mat"], MAT["oak"]), bev, coll)
            if p["mat"] == "brass" and p["h"] >= 300:  # bedside / floor lamp glow
                L_ = bpy.data.lights.new("lamp", "POINT")
                L_.energy = 25
                L_.color = (1.0, 0.78, 0.55)
                L_.shadow_soft_size = 0.08
                lo = bpy.data.objects.new("lamp", L_)
                lo.location = (x, y, (p["z0"] + p["h"]) / 1000 + 0.05)
                coll.objects.link(lo)
    return coll


def lights(M, interior=True):
    lv = M["levels"][0]
    H = lv["wall_height_mm"] / 1000.0
    sc = bpy.context.scene
    w = bpy.data.worlds.new("sky")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    try:
        sky = nt.nodes.new("ShaderNodeTexSky")
        for t in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
            try:
                sky.sky_type = t
                break
            except TypeError:
                continue
        if hasattr(sky, "sun_elevation"):
            sky.sun_elevation = math.radians(38)
            sky.sun_rotation = math.radians(215)
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.35
    except Exception:  # noqa: BLE001
        bg.inputs["Color"].default_value = (0.75, 0.82, 0.95, 1)
        bg.inputs["Strength"].default_value = 1.2
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 4.0
    sun.angle = math.radians(0.6)
    sun.color = (1.0, 0.95, 0.88)
    so = bpy.data.objects.new("sun", sun)
    so.rotation_euler = (math.radians(52), 0, math.radians(215))
    sc.collection.objects.link(so)
    if interior:
        # warm ceiling lights, one per furnished space + one per closed room
        pts = []
        for f in lv.get("furniture", []):
            if f["parts"]:
                xs = [p["x"] for p in f["parts"]]
                ys = [p["y"] for p in f["parts"]]
                pts.append((sum(xs) / len(xs) / 1000, sum(ys) / len(ys) / 1000))
        for x, y in pts:
            L_ = bpy.data.lights.new("ceiling", "AREA")
            L_.shape = "DISK"
            L_.size = 0.6
            L_.energy = 55
            L_.color = (1.0, 0.86, 0.7)
            lo = bpy.data.objects.new("ceiling", L_)
            lo.location = (x, y, H - 0.02)
            sc.collection.objects.link(lo)


def setup_render(width, height, samples, path):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 8
    sc.cycles.diffuse_bounces = 4
    sc.cycles.glossy_bounces = 4
    sc.cycles.transmission_bounces = 8
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = 100
    sc.render.use_persistent_data = True
    sc.render.filepath = path
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        try:
            sc.view_settings.view_transform = "Filmic"
            sc.view_settings.look = "Medium High Contrast"
        except TypeError:
            pass
    sc.view_settings.exposure = -0.6


def camera(name, loc, target, lens=20.0, two_point=True, ortho=None):
    sc = bpy.context.scene
    cd = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cd)
    sc.collection.objects.link(cam)
    cam.location = loc
    d = Vector(target) - Vector(loc)
    if two_point and ortho is None:
        # architectural 2-point perspective: level camera, frame with lens shift
        yaw = math.atan2(d.y, d.x) - math.pi / 2
        cam.rotation_euler = (math.radians(90), 0, yaw)
        horiz = math.hypot(d.x, d.y)
        cd.shift_y = max(-0.3, min(0.3, (d.z / max(horiz, 0.1)) * (lens / 36.0) * 0.9))
    else:
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if ortho is not None:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho
    else:
        cd.lens = lens
        cd.sensor_width = 36
    cd.clip_start = 0.05
    cd.clip_end = 500
    sc.camera = cam
    return cam


def render(path):
    bpy.context.scene.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    return round(time.time() - t, 1)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


# ----------------------------------------------------------------- main
def views(M, maxr):
    lv = M["levels"][0]
    v = [f for f in lv.get("furniture", []) if f.get("view")]
    byT = {}
    for f in v:
        byT.setdefault(f["type"], []).append(f)
    order = [k for k in ("living", "bedroom", "kitchen", "saferoom") if k in byT]
    out, i = [], 0
    while len(out) < len(v):
        for k in order:
            if i < len(byT[k]):
                out.append(byT[k][i])
        i += 1
    return out[:maxr]


def main():
    global A
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1600x900")
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--max-rooms", type=int, default=6)
    ap.add_argument("--only", help="comma list: interiors,axo,aerial")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--video-size", default="1280x720")
    ap.add_argument("--video-samples", type=int, default=24)
    ap.add_argument("--render-fps", type=int, default=8)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--seconds-per-space", type=float, default=4.0)
    A = ap.parse_args(argv)
    random.seed(7)
    M = json.load(open(A.model, encoding="utf-8"))
    out = os.path.abspath(A.out)
    os.makedirs(os.path.join(out, "interiors"), exist_ok=True)
    W, Hh = map(int, A.size.split("x"))
    lv = M["levels"][0]
    log = {"settings": vars(A), "stills": []}
    only = set((A.only or "interiors,axo,aerial").split(","))
    poses = views(M, A.max_rooms)

    # interiors
    if "interiors" in only and poses:
        reset()
        MAT = build_materials()
        build_scene(M, MAT, ceiling=True)
        lights(M, interior=True)
        setup_render(W, Hh, A.samples, "")
        for i, f in enumerate(poses):
            c, t = f["view"]["cam"], f["view"]["target"]
            cam = camera(f"cam{i}", (c[0] / 1000, c[1] / 1000, c[2] / 1000), (t[0] / 1000, t[1] / 1000, 1.1), lens=18)
            p = os.path.join(out, "interiors", f"{i + 1:02d}-{f['type']}.png")
            s = render(p)
            log["stills"].append({"file": os.path.relpath(p, out), "seconds": s})
            print(f"interior {i + 1}/{len(poses)} {f['type']}: {s}s", flush=True)

    # furnished axonometric (walls cut at 1.4 m, no ceiling) and aerial
    if "axo" in only or "aerial" in only:
        reset()
        MAT = build_materials()
        build_scene(M, MAT, cut=1.4, ceiling=False)
        lights(M, interior=False)
        setup_render(W, Hh, max(64, A.samples // 2), "")
        x0, y0, x1, y1 = [v / 1000 for v in M["extent_mm"]]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        R = max(x1 - x0, y1 - y0)
        if "axo" in only:
            # zoom on the densest furnished area
            pts = [(p["x"] / 1000, p["y"] / 1000) for f in lv.get("furniture", []) for p in f["parts"]]
            if pts:
                best = max(pts, key=lambda q: sum(1 for r in pts if abs(r[0] - q[0]) < 6 and abs(r[1] - q[1]) < 6))
                tx, ty = best
            else:
                tx, ty = cx, cy
            camera("axo", (tx + 30, ty - 30, 30), (tx, ty, 0), two_point=False, ortho=16)
            log["stills"].append({"file": "axonometric-furnished.png", "seconds": render(os.path.join(out, "axonometric-furnished.png"))})
            camera("axo-all", (cx + 60, cy - 60, 55), (cx, cy, 0), two_point=False, ortho=R * 0.82)
            log["stills"].append({"file": "axonometric-floor.png", "seconds": render(os.path.join(out, "axonometric-floor.png"))})
        if "aerial" in only:
            camera("aerial", (cx + R * 0.55, cy - R * 0.55, R * 0.42), (cx, cy, 0), lens=35, two_point=False)
            log["stills"].append({"file": "aerial.png", "seconds": render(os.path.join(out, "aerial.png"))})
        print("axonometric/aerial done", flush=True)

    # film
    if A.video and poses:
        vw, vh = map(int, A.video_size.split("x"))
        fdir = os.path.join(out, "film")
        os.makedirs(os.path.join(fdir, "clips"), exist_ok=True)
        clips = []

        def enc(frames_dir, name):
            raw = os.path.join(frames_dir, "%05d.png")
            dst = os.path.join(fdir, "clips", name)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(A.render_fps), "-i", raw,
                            "-vf", f"minterpolate=fps={A.fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", dst], check=True)
            return dst

        def ease(t):
            return 4 * t ** 3 if t < .5 else 1 - (-2 * t + 2) ** 3 / 2

        # aerial descent (no ceiling, full walls)
        reset()
        MAT = build_materials()
        build_scene(M, MAT, ceiling=False)
        lights(M, interior=False)
        setup_render(vw, vh, A.video_samples, "")
        x0, y0, x1, y1 = [v / 1000 for v in M["extent_mm"]]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        R = max(x1 - x0, y1 - y0)
        n = int(5 * A.render_fps)
        tmp = os.path.join(fdir, "frames")
        os.makedirs(tmp, exist_ok=True)
        for k in range(n):
            t = ease(k / (n - 1))
            a = math.radians(215 + 50 * t)
            dist = R * (1.0 - 0.4 * t)
            camera("fly", (cx + math.cos(a) * dist, cy + math.sin(a) * dist, R * (0.75 - 0.4 * t)), (cx, cy, 0), lens=35, two_point=False)
            render(os.path.join(tmp, f"{k:05d}.png"))
        clips.append(enc(tmp, "00-aerial.mp4"))
        for fn in os.listdir(tmp):
            os.remove(os.path.join(tmp, fn))
        print("film: aerial done", flush=True)
        # interiors: slow push-in with a gentle pan
        reset()
        MAT = build_materials()
        build_scene(M, MAT, ceiling=True)
        lights(M, interior=True)
        setup_render(vw, vh, A.video_samples, "")
        for i, f in enumerate(poses):
            c, tg = f["view"]["cam"], f["view"]["target"]
            c0 = Vector((c[0] / 1000, c[1] / 1000, c[2] / 1000))
            t0 = Vector((tg[0] / 1000, tg[1] / 1000, 1.1))
            c1 = c0.lerp(Vector((t0.x, t0.y, c0.z)), 0.25)
            n = int(A.seconds_per_space * A.render_fps)
            side = Vector((-(t0 - c0).y, (t0 - c0).x, 0)).normalized()
            for k in range(n):
                t = ease(k / (n - 1))
                camera("push", tuple(c0.lerp(c1, t)), tuple(t0 + side * (math.sin(t * math.pi) * 0.35)), lens=18)
                render(os.path.join(tmp, f"{k:05d}.png"))
            clips.append(enc(tmp, f"{i + 1:02d}-{f['type']}.mp4"))
            for fn in os.listdir(tmp):
                os.remove(os.path.join(tmp, fn))
            print(f"film: space {i + 1}/{len(poses)} done", flush=True)
        os.rmdir(tmp)
        # join with cross-fades
        durs = [float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", c])) for c in clips]
        XF, off, last, filt = 0.8, 0.0, "[0:v]", ""
        for i in range(1, len(clips)):
            off += durs[i - 1] - XF
            lab = "[v]" if i == len(clips) - 1 else f"[x{i}]"
            filt += f"{last}[{i}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}{lab};"
            last = lab
        inputs = [a for c in clips for a in ("-i", c)]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", filt.rstrip(";"), "-map", "[v]",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
                        os.path.join(fdir, "walkthrough.mp4")], check=True)
        log["film"] = {"file": "film/walkthrough.mp4", "clips": [os.path.relpath(c, out) for c in clips]}
        print("film done", flush=True)

    log["note"] = ("Path-traced (Blender Cycles) renders of the verified model. Geometry = model.json; "
                   "materials, light and furniture are VISUAL ONLY.")
    json.dump(log, open(os.path.join(out, "photoreal.json"), "w"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
