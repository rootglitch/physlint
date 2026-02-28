"""
Blender headless rendering script.
Called via: blender --background --python render_usd.py -- --input <file> --output <dir> --colors <json>
"""
import sys
import os
import json
import argparse

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",   required=True)
    parser.add_argument("--output",  required=True)
    parser.add_argument("--colors",  default=None, help="JSON file: {prim_name: {diffuse, metallic, roughness}}")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--res",     type=int, default=768)
    parser.add_argument("--engine",  default="CYCLES")
    return parser.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in bpy.data.meshes:
        bpy.data.meshes.remove(block)


def import_usd(usd_path: str):
    bpy.ops.wm.usd_import(filepath=usd_path, import_cameras=False, import_lights=False)


def get_scene_bounds() -> tuple[Vector, float]:
    all_verts = []
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for v in obj.bound_box:
                all_verts.append(obj.matrix_world @ Vector(v))
    if not all_verts:
        return Vector((0, 0, 0)), 1.0
    mn = Vector((min(v.x for v in all_verts), min(v.y for v in all_verts), min(v.z for v in all_verts)))
    mx = Vector((max(v.x for v in all_verts), max(v.y for v in all_verts), max(v.z for v in all_verts)))
    center = (mn + mx) / 2
    radius = max((mx - mn).length / 2, 0.01)
    return center, radius


def setup_world_lighting():
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    tree = world.node_tree
    tree.nodes.clear()
    bg  = tree.nodes.new("ShaderNodeBackground")
    out = tree.nodes.new("ShaderNodeOutputWorld")
    bg.inputs["Color"].default_value    = (0.72, 0.75, 0.80, 1.0)
    bg.inputs["Strength"].default_value = 0.9
    tree.links.new(bg.outputs["Background"], out.inputs["Surface"])

    def _sun(name, energy, color, rx, rz):
        d = bpy.data.lights.new(name, type="SUN")
        d.energy = energy
        d.color  = color
        o = bpy.data.objects.new(name, d)
        bpy.context.collection.objects.link(o)
        o.rotation_euler = (rx, 0.0, rz)

    _sun("KeyLight",  3.5, (1.00, 0.95, 0.88),  0.65,  0.60)   # warm key
    _sun("FillLight", 1.5, (0.75, 0.85, 1.00),  1.10, -1.90)   # cool fill
    _sun("RimLight",  0.8, (1.00, 1.00, 1.00), -0.40,  3.14)   # back rim


def _make_material(name: str, diffuse: list, metallic: float, roughness: float) -> bpy.types.Material:
    """Flat PBR fallback — used for generic/unknown material types."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    out  = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (*diffuse, 1.0)
    bsdf.inputs["Metallic"].default_value   = metallic
    bsdf.inputs["Roughness"].default_value  = roughness
    return mat


def _make_steel(name: str) -> bpy.types.Material:
    """
    Isotropic steel: blue-grey, metallic, noise-driven roughness variation + micro-bump.
    Distinguishable from aluminum by: darker tone, isotropic (non-directional) grain.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    lk = tree.links

    out   = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf  = tree.nodes.new("ShaderNodeBsdfPrincipled")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    bump  = tree.nodes.new("ShaderNodeBump")
    rmap  = tree.nodes.new("ShaderNodeMapRange")
    coord = tree.nodes.new("ShaderNodeTexCoord")

    noise.inputs["Scale"].default_value      = 40.0
    noise.inputs["Detail"].default_value     = 8.0
    noise.inputs["Roughness"].default_value  = 0.65
    noise.inputs["Distortion"].default_value = 0.2

    rmap.inputs["From Min"].default_value = 0.0
    rmap.inputs["From Max"].default_value = 1.0
    rmap.inputs["To Min"].default_value   = 0.25
    rmap.inputs["To Max"].default_value   = 0.45

    bump.inputs["Strength"].default_value  = 0.3
    bump.inputs["Distance"].default_value  = 0.005

    bsdf.inputs["Base Color"].default_value = (0.60, 0.62, 0.65, 1.0)
    bsdf.inputs["Metallic"].default_value   = 1.0
    bsdf.inputs["Anisotropic"].default_value = 0.0  # isotropic — key vs. aluminum

    lk.new(coord.outputs["Object"], noise.inputs["Vector"])
    lk.new(noise.outputs["Fac"],    rmap.inputs["Value"])
    lk.new(rmap.outputs["Result"],  bsdf.inputs["Roughness"])
    lk.new(noise.outputs["Fac"],    bump.inputs["Height"])
    lk.new(bump.outputs["Normal"],  bsdf.inputs["Normal"])
    lk.new(bsdf.outputs["BSDF"],    out.inputs["Surface"])
    return mat


def _make_aluminum(name: str) -> bpy.types.Material:
    """
    Brushed aluminum: silver-white, anisotropic directional streaks from Wave texture.
    Distinguishable from steel by: lighter tone, strong directional highlight.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    lk = tree.links

    out     = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf    = tree.nodes.new("ShaderNodeBsdfPrincipled")
    wave    = tree.nodes.new("ShaderNodeTexWave")
    noise   = tree.nodes.new("ShaderNodeTexNoise")
    bump    = tree.nodes.new("ShaderNodeBump")
    coord   = tree.nodes.new("ShaderNodeTexCoord")
    mapping = tree.nodes.new("ShaderNodeMapping")

    mapping.inputs["Scale"].default_value = (8.0, 1.0, 1.0)  # stretch X = brush direction

    wave.wave_type                           = "BANDS"
    wave.bands_direction                     = "X"
    wave.inputs["Scale"].default_value       = 80.0
    wave.inputs["Distortion"].default_value  = 3.0
    wave.inputs["Detail"].default_value      = 4.0
    wave.inputs["Detail Scale"].default_value    = 2.0
    wave.inputs["Detail Roughness"].default_value = 0.6

    noise.inputs["Scale"].default_value      = 200.0
    noise.inputs["Detail"].default_value     = 6.0
    noise.inputs["Roughness"].default_value  = 0.7
    noise.inputs["Distortion"].default_value = 0.1

    bump.inputs["Strength"].default_value = 0.4
    bump.inputs["Distance"].default_value = 0.01

    bsdf.inputs["Base Color"].default_value      = (0.85, 0.87, 0.90, 1.0)
    bsdf.inputs["Metallic"].default_value        = 1.0
    bsdf.inputs["Roughness"].default_value       = 0.15
    bsdf.inputs["Anisotropic"].default_value     = 0.7  # directional streaks

    lk.new(coord.outputs["Object"],   mapping.inputs["Vector"])
    lk.new(mapping.outputs["Vector"], wave.inputs["Vector"])
    lk.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    lk.new(wave.outputs["Color"],     bump.inputs["Height"])
    lk.new(bump.outputs["Normal"],    bsdf.inputs["Normal"])
    lk.new(wave.outputs["Color"],     bsdf.inputs["Anisotropic Rotation"])
    lk.new(bsdf.outputs["BSDF"],      out.inputs["Surface"])
    return mat


def _make_rubber(name: str) -> bpy.types.Material:
    """
    Rubber: near-black, zero metallic, suppressed specularity, fine stochastic micro-bump.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    lk = tree.links

    out   = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf  = tree.nodes.new("ShaderNodeBsdfPrincipled")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    bump  = tree.nodes.new("ShaderNodeBump")
    coord = tree.nodes.new("ShaderNodeTexCoord")

    noise.inputs["Scale"].default_value      = 120.0
    noise.inputs["Detail"].default_value     = 10.0
    noise.inputs["Roughness"].default_value  = 0.8
    noise.inputs["Distortion"].default_value = 0.3

    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.003

    bsdf.inputs["Base Color"].default_value = (0.03, 0.03, 0.03, 1.0)
    bsdf.inputs["Metallic"].default_value   = 0.0
    bsdf.inputs["Roughness"].default_value  = 0.85
    # Suppress specularity (input name changed between Blender 3.x and 4.x)
    for spec_key in ("Specular IOR Level", "Specular"):
        if spec_key in bsdf.inputs:
            bsdf.inputs[spec_key].default_value = 0.05
            break

    lk.new(coord.outputs["Object"], noise.inputs["Vector"])
    lk.new(noise.outputs["Fac"],    bump.inputs["Height"])
    lk.new(bump.outputs["Normal"],  bsdf.inputs["Normal"])
    lk.new(bsdf.outputs["BSDF"],    out.inputs["Surface"])
    return mat


def _make_concrete(name: str) -> bpy.types.Material:
    """
    Concrete: Voronoi aggregate texture (coarse) + Noise micro-cracks (fine) → Bump.
    Two-scale pattern is visually distinctive against metals and rubber.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    lk = tree.links

    out     = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf    = tree.nodes.new("ShaderNodeBsdfPrincipled")
    voronoi = tree.nodes.new("ShaderNodeTexVoronoi")
    noise   = tree.nodes.new("ShaderNodeTexNoise")
    bump    = tree.nodes.new("ShaderNodeBump")
    mix_col = tree.nodes.new("ShaderNodeMixRGB")
    coord   = tree.nodes.new("ShaderNodeTexCoord")

    voronoi.voronoi_dimensions         = "3D"
    voronoi.feature                    = "F1"
    voronoi.inputs["Scale"].default_value = 18.0

    noise.inputs["Scale"].default_value      = 50.0
    noise.inputs["Detail"].default_value     = 8.0
    noise.inputs["Roughness"].default_value  = 0.75
    noise.inputs["Distortion"].default_value = 0.4

    mix_col.blend_type                       = "MULTIPLY"
    mix_col.inputs["Fac"].default_value      = 0.35
    mix_col.inputs["Color1"].default_value   = (0.72, 0.70, 0.68, 1.0)

    bump.inputs["Strength"].default_value = 0.8
    bump.inputs["Distance"].default_value = 0.008

    bsdf.inputs["Metallic"].default_value  = 0.0
    bsdf.inputs["Roughness"].default_value = 0.92

    lk.new(coord.outputs["Object"],      voronoi.inputs["Vector"])
    lk.new(coord.outputs["Object"],      noise.inputs["Vector"])
    lk.new(voronoi.outputs["Distance"],  mix_col.inputs["Color2"])
    lk.new(mix_col.outputs["Color"],     bsdf.inputs["Base Color"])
    lk.new(noise.outputs["Fac"],         bump.inputs["Height"])
    lk.new(bump.outputs["Normal"],       bsdf.inputs["Normal"])
    lk.new(bsdf.outputs["BSDF"],         out.inputs["Surface"])
    return mat


# Flat PBR colours per material type — chosen for maximum VLM discrimination:
#   steel:    dark blue-grey  (0.50) — clearly darker than aluminum
#   aluminum: bright silver   (0.88) — clearly lighter than steel (Δ=0.38 vs original Δ=0.15)
#   rubber:   near-black      (0.02) — very dark, very matte, zero metallic
#   concrete: brownish grey   (0.55) — warm tone contrasts with the cool metal greys
# All metallic=0 so the model reads colour (not reflections) as the primary signal.
_MATERIAL_COLOURS = {
    "steel":    ([0.50, 0.52, 0.56], 0.0, 0.40),
    "aluminum": ([0.88, 0.89, 0.91], 0.0, 0.25),
    "rubber":   ([0.02, 0.02, 0.02], 0.0, 0.97),
    "concrete": ([0.55, 0.53, 0.50], 0.0, 0.92),
}


def apply_colors_from_json(colors_path: str):
    """
    Read prim_colors.json (written by renderer.py using pxr) and apply each
    material directly to matching Blender objects by name.
    Dispatches to type-specific flat PBR colours when material_type is known;
    falls back to the USD diffuse colour for generic/unknown types.
    """
    with open(colors_path) as f:
        prim_colors: dict = json.load(f)

    default_mat = _make_material("_default", [0.6, 0.6, 0.65], 0.0, 0.5)

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        props = prim_colors.get(obj.name)
        if props:
            mat_type = props.get("material_type", "generic")
            if mat_type in _MATERIAL_COLOURS:
                diffuse, metallic, roughness = _MATERIAL_COLOURS[mat_type]
            else:
                diffuse   = props["diffuse"]
                metallic  = props.get("metallic",  0.0)
                roughness = props.get("roughness", 0.5)
            mat = _make_material(f"_physint_{obj.name}", diffuse, metallic, roughness)
        else:
            mat = default_mat

        obj.data.materials.clear()
        obj.data.materials.append(mat)

    applied = sum(1 for obj in bpy.data.objects
                  if obj.type == "MESH" and obj.name in prim_colors)
    print(f"[render_usd.py] Applied typed flat materials to {applied}/{len(prim_colors)} prims")


def add_camera_looking_at(name: str, location: Vector, target: Vector):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = 50
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = location
    direction = target - location
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam_obj


def render_views(args, center: Vector, radius: float):
    os.makedirs(args.output, exist_ok=True)
    dist = radius * 3.0

    views = {
        "top":       center + Vector((0,      0,     dist)),
        "front":     center + Vector((0,     -dist,  center.z - center.z)),
        "side":      center + Vector((dist,   0,     0)),
        "isometric": center + Vector((dist,  -dist,  dist * 0.8)),
    }
    # fix front/side to be at scene centre height
    views["front"] = center + Vector((0, -dist, 0))
    views["side"]  = center + Vector((dist, 0, 0))

    scene = bpy.context.scene
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.render.image_settings.file_format = "PNG"
    scene.render.engine  = "CYCLES"
    scene.cycles.samples = args.samples

    # Enable GPU rendering if available (CUDA → OptiX fallback → CPU)
    _device = "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            prefs.compute_device_type = backend
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type != "CPU"]
            if gpus:
                for d in prefs.devices:
                    d.use = (d.type != "CPU")
                _device = "GPU"
                print(f"[render_usd.py] GPU rendering enabled ({backend}): "
                      f"{', '.join(d.name for d in gpus if d.use)}")
                break
    except Exception as e:
        print(f"[render_usd.py] GPU setup failed ({e}), using CPU")
    scene.cycles.device = _device

    scene.cycles.use_denoising   = (_device == "GPU")  # OptiX denoiser on GPU
    scene.cycles.max_bounces     = 8
    scene.cycles.diffuse_bounces = 4
    scene.cycles.glossy_bounces  = 4
    # Clamp to avoid fireflies from area lights
    scene.cycles.sample_clamp_direct   = 5.0
    scene.cycles.sample_clamp_indirect = 3.0

    for view_name, loc in views.items():
        cam = add_camera_looking_at(f"cam_{view_name}", loc, center)
        scene.camera = cam
        scene.render.filepath = os.path.join(args.output, view_name)
        bpy.ops.render.render(write_still=True)
        print(f"  Rendered: {view_name}")
        bpy.data.objects.remove(cam, do_unlink=True)


def main():
    args = parse_args()
    print(f"[render_usd.py] Importing: {args.input}")
    clear_scene()
    import_usd(args.input)
    setup_world_lighting()
    if args.colors and os.path.exists(args.colors):
        apply_colors_from_json(args.colors)
    else:
        print("[render_usd.py] No colors JSON — rendering with default grey")
    center, radius = get_scene_bounds()
    print(f"[render_usd.py] centre={tuple(round(v,2) for v in center)}, radius={radius:.3f}")
    render_views(args, center, radius)
    print(f"[render_usd.py] Done → {args.output}")


main()
