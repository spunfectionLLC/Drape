"""Draped garment + avatar as a glTF binary (.glb), and a Blender script that
turns it into a photoreal studio render (Cycles: soft lights, fabric sheen,
a floor that catches the shadow).

    write_glb(path, meshes)              # [{name, pos, idx, uv?, color, roughness, sheen?}]
    blender_bundle(zip_path, glb_bytes, fabric)   # garment.glb + render_in_blender.py + README
"""
from __future__ import annotations

import json
import struct
import zipfile

import numpy as np


def _normals(P, F):
    N = np.zeros_like(P)
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-12)


def write_glb(path, meshes):
    """meshes: list of dicts {name, pos (n,3), idx (m,3), uv (n,2)?, color (r,g,b), roughness, double_sided}."""
    bin_ = bytearray()
    views, accessors, gmeshes, nodes, materials = [], [], [], [], []

    def add(arr, target, comp, typ, minmax=False):
        a = np.ascontiguousarray(arr)
        off = len(bin_)
        bin_.extend(a.tobytes())
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": a.nbytes, **({"target": target} if target else {})})
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(len(a)), "type": typ}
        if minmax:
            acc["min"] = a.min(0).tolist(); acc["max"] = a.max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    for m in meshes:
        P = np.asarray(m["pos"], np.float32)
        F = np.asarray(m["idx"], np.uint32)
        N = _normals(P.astype(float), F).astype(np.float32)
        attrs = {"POSITION": add(P, 34962, 5126, "VEC3", True), "NORMAL": add(N, 34962, 5126, "VEC3")}
        if m.get("uv") is not None:
            attrs["TEXCOORD_0"] = add(np.asarray(m["uv"], np.float32), 34962, 5126, "VEC2")
        ind = add(F.reshape(-1), 34963, 5125, "SCALAR")
        r, g, b = [float(c) ** 2.2 for c in m.get("color", (0.8, 0.8, 0.8))]     # glTF colours are linear
        mat = {"name": m["name"], "doubleSided": bool(m.get("double_sided", True)),
               "pbrMetallicRoughness": {"baseColorFactor": [r, g, b, 1.0], "metallicFactor": 0.0,
                                        "roughnessFactor": float(m.get("roughness", 0.85))}}
        if m.get("sheen"):
            mat["extensions"] = {"KHR_materials_sheen": {"sheenColorFactor": [r, g, b], "sheenRoughnessFactor": 0.5}}
        materials.append(mat)
        gmeshes.append({"name": m["name"], "primitives": [{"attributes": attrs, "indices": ind,
                                                             "material": len(materials) - 1}]})
        nodes.append({"name": m["name"], "mesh": len(gmeshes) - 1})
    from . import brand
    doc = {"asset": {"version": "2.0", "generator": brand.generator(), "copyright": brand.COPYRIGHT},
           "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": gmeshes,
           "materials": materials, "accessors": accessors, "bufferViews": views,
           "buffers": [{"byteLength": len(bin_)}]}
    if any(m.get("sheen") for m in meshes):
        doc["extensionsUsed"] = ["KHR_materials_sheen"]
    js = json.dumps(doc, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    with open(path, "wb") as f:
        f.write(out)
    return len(out)


PALETTE = [(0.20, 0.36, 0.62), (0.80, 0.42, 0.18), (0.18, 0.55, 0.45), (0.55, 0.30, 0.55),
           (0.75, 0.62, 0.20), (0.35, 0.35, 0.40), (0.62, 0.22, 0.26), (0.25, 0.50, 0.65)]

FABRIC_LOOK = {   # roughness, sheen (fuzzy fibres), weave scale (cm)
    "jersey": (0.85, 0.6, 0.12), "poplin": (0.75, 0.2, 0.08), "denim": (0.9, 0.3, 0.2), "canvas": (0.9, 0.2, 0.25),
    "fleece": (1.0, 1.0, 0.3), "silk": (0.35, 0.1, 0.05), "chiffon": (0.5, 0.2, 0.05), "rib": (0.85, 0.5, 0.3),
    "lining": (0.4, 0.1, 0.05), "flannel": (0.95, 0.9, 0.2)}


def _disc(c, n, r, thick, seg=20):
    """A button: a short cylinder at c facing n."""
    n = np.asarray(n, float); n /= np.linalg.norm(n) + 1e-12
    t1 = np.cross(n, [0, 1, 0] if abs(n[1]) < 0.9 else [1, 0, 0]); t1 /= np.linalg.norm(t1)
    t2 = np.cross(n, t1)
    a = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    ring = np.cos(a)[:, None] * t1 + np.sin(a)[:, None] * t2
    top = c + n * thick + r * ring; bot = c + r * ring
    P = np.vstack([top, bot, [c + n * thick * 1.15], [c]])
    F = []
    ct, cb = 2 * seg, 2 * seg + 1
    for k in range(seg):
        j = (k + 1) % seg
        F += [[ct, k, j], [cb, seg + j, seg + k], [k, seg + k, j], [j, seg + k, seg + j]]
    return P, np.array(F)


def trim_meshes(trims, X):
    """Buttons and snaps from the studio's trims, at the draped positions X (welded mesh)."""
    from .render import vertex_normals
    out = []
    if not trims:
        return out
    Ps, Fs, off = [], [], 0
    cent = X.mean(0)
    for t in trims:
        if t.get("type") not in ("button", "snap"):
            continue
        v = int(t["v"]); c = X[v]
        n = c - np.array([cent[0], c[1], cent[2]]); n /= np.linalg.norm(n) + 1e-12
        P, F = _disc(c + n * 0.001, n, float(t.get("r", 0.0075)), 0.0025)
        Ps.append(P); Fs.append(F + off); off += len(P)
    if Ps:
        out.append({"name": "buttons", "pos": np.vstack(Ps), "idx": np.vstack(Fs), "color": (0.92, 0.89, 0.80),
                    "roughness": 0.25, "double_sided": False})
    return out


def garment_meshes(z, body=None, color=None, fabric="poplin", one_color=True, trims=None):
    """Meshes for a drape result (the studio's result.npz): one per pattern piece
    (with the pattern's own UVs, in metres, so a texture tiles at true scale), and the avatar."""
    X, T, U = z["x0"], z["tris0"], z["uv0"]
    pid = z["panel_id0"] if "panel_id0" in z.files else None
    names = [str(n) for n in z["panel_names"]] if "panel_names" in z.files else None
    rough, sheen, _ = FABRIC_LOOK.get(fabric, (0.8, 0.3, 0.1))
    out = []
    if pid is None:
        out.append({"name": "garment", "pos": X, "idx": T, "uv": U, "color": color or PALETTE[0],
                    "roughness": rough, "sheen": sheen > 0.4})
    else:
        tp = pid[T[:, 0]]
        for k in range(int(pid.max()) + 1):
            F = T[tp == k]
            if not len(F):
                continue
            used = np.unique(F)
            remap = -np.ones(len(X), int); remap[used] = np.arange(len(used))
            out.append({"name": names[k] if names else f"piece_{k}", "pos": X[used], "idx": remap[F], "uv": U[used],
                        "color": color or (PALETTE[0] if one_color else PALETTE[k % len(PALETTE)]),
                        "roughness": rough, "sheen": sheen > 0.4})
    if trims:
        out += trim_meshes(trims, z["stand"] if "stand" in z.files else z["x"])
    if body is not None:
        out.append({"name": "avatar", "pos": body.V, "idx": body.F, "color": (0.55, 0.52, 0.50), "roughness": 0.6,
                    "double_sided": False})
    return out


BLENDER_SCRIPT = r'''"""Photoreal render of a drape garment in Blender (3.6+ / 4.x).

    blender --background --python render_in_blender.py        (writes render.png next to this file)
or open Blender > Scripting > open this file > Run Script.
"""
import math, os, bpy

HERE = os.path.dirname(os.path.abspath(__file__))
FABRIC = "%(fabric)s"
ROUGH, SHEEN, WEAVE_CM = %(look)s

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(HERE, "garment.glb"))
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = int(os.environ.get("DRAPE_SAMPLES", 128))
scene.render.resolution_x, scene.render.resolution_y = 1200, 1600
scene.view_settings.look = "AgX - Medium High Contrast" if "AgX" in [i.name for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items] else "None"

def fabric_material(mat):
    """Principled BSDF + a fine procedural weave bump + fibre sheen."""
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = ROUGH
    for key in ("Sheen Weight", "Sheen"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = SHEEN
    tex = nt.nodes.new("ShaderNodeTexWave"); tex.wave_type = "BANDS"
    tex.inputs["Scale"].default_value = 100.0 / max(WEAVE_CM, 0.02)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(coord.outputs["UV"], tex.inputs["Vector"])
    tex2 = nt.nodes.new("ShaderNodeTexWave"); tex2.wave_type = "BANDS"; tex2.bands_direction = "Y"
    tex2.inputs["Scale"].default_value = 100.0 / max(WEAVE_CM, 0.02)
    nt.links.new(coord.outputs["UV"], tex2.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMath"); mix.operation = "MULTIPLY"
    nt.links.new(tex.outputs["Fac"], mix.inputs[0]); nt.links.new(tex2.outputs["Fac"], mix.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.15
    bump.inputs["Distance"].default_value = 0.0005
    nt.links.new(mix.outputs["Value"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

lo, hi = [1e9] * 3, [-1e9] * 3
for ob in scene.objects:
    if ob.type != "MESH":
        continue
    for v in ob.bound_box:
        w = ob.matrix_world @ __import__("mathutils").Vector(v)
        lo = [min(a, b) for a, b in zip(lo, w)]; hi = [max(a, b) for a, b in zip(hi, w)]
    if ob.name not in ("avatar", "buttons"):
        for slot in ob.material_slots:
            fabric_material(slot.material)
        mod = ob.modifiers.new("smooth", "SUBSURF"); mod.levels = 1; mod.render_levels = 2
        ob.data.shade_smooth() if hasattr(ob.data, "shade_smooth") else None
        sol = ob.modifiers.new("thickness", "SOLIDIFY"); sol.thickness = 0.0015; sol.offset = -1
# glTF is Y-up; Blender imports it Z-up, so heights are z
cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
h = hi[2] - lo[2]
bpy.ops.mesh.primitive_plane_add(size=20, location=(cx, cy, lo[2]))
floor = bpy.context.object
fm = bpy.data.materials.new("floor"); fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.92, 0.9, 0.87, 1)
fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
floor.data.materials.append(fm)
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.92, 0.91, 0.89, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35
def area(name, loc, energy, size):
    bpy.ops.object.light_add(type="AREA", location=loc); L = bpy.context.object
    L.data.energy = energy; L.data.size = size
    d = __import__("mathutils").Vector((cx, cy, lo[2] + h * 0.6)) - L.location
    L.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
area("key", (cx + 2.0, cy - 2.5, lo[2] + h * 1.3), 300, 2.5)
area("fill", (cx - 2.5, cy - 1.5, lo[2] + h * 0.9), 120, 3.0)
area("rim", (cx, cy + 2.5, lo[2] + h * 1.4), 220, 2.0)
bpy.ops.object.camera_add(location=(cx, cy - h * 2.4, lo[2] + h * 0.55))
cam = bpy.context.object; cam.data.lens = 70
d = __import__("mathutils").Vector((cx, cy, lo[2] + h * 0.52)) - cam.location
cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
scene.render.filepath = os.path.join(HERE, "render.png")
if bpy.app.background:
    bpy.ops.render.render(write_still=True)
    print("wrote", scene.render.filepath)
'''


def blender_bundle(zip_path, glb_path, fabric="poplin"):
    look = FABRIC_LOOK.get(fabric, (0.8, 0.3, 0.1))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(glb_path, "garment.glb")
        zf.writestr("render_in_blender.py", BLENDER_SCRIPT % {"fabric": fabric, "look": repr(tuple(look))})
        zf.writestr("README.txt", (
            "Photoreal render of your garment (Spunfection Studio · spunfection.studio)\n\n"
            "1. Install Blender (free, blender.org).\n"
            "2. Unzip this folder.\n"
            "3. Either double-click nothing and run:  blender --background --python render_in_blender.py\n"
            "   or open Blender, go to the Scripting tab, open render_in_blender.py and press Run Script,\n"
            "   then F12 to render.\n\n"
            "garment.glb also opens in any 3D viewer (Windows 3D Viewer, online glTF viewers) and imports\n"
            "into Blender, Unity, Unreal, three.js and most other 3D tools.\n"
            "The pieces' UVs are their pattern coordinates in metres: a texture tiles at true size.\n"))
    return zip_path
