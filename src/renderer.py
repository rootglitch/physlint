"""
Orchestrate Blender headless rendering of a USD file into 4 view images.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


RENDER_SCRIPT = Path(__file__).parent.parent / "render_usd.py"


def _extract_prim_colors(usd_path: str) -> dict[str, list[float]]:
    """
    Use pxr to read material colors for every prim that has a material binding.
    Returns {prim_name: {diffuse, metallic, roughness}}.

    Handles two USD material styles:
    - Standard: Material prim → UsdPreviewSurface Shader child
    - MuJoCo-USD-Converter: Material prim with direct inputs:diffuseColor attribute
    """
    from pxr import Usd, UsdShade

    stage = Usd.Stage.Open(usd_path)

    def _read_mat_props(mat_prim: Usd.Prim) -> dict:
        """Try all known material property locations."""
        # Style 1: UsdPreviewSurface Shader child
        for child in mat_prim.GetChildren():
            shader = UsdShade.Shader(child)
            if shader and shader.GetIdAttr().Get() == "UsdPreviewSurface":
                di  = shader.GetInput("diffuseColor")
                me  = shader.GetInput("metallic")
                ro  = shader.GetInput("roughness")
                return {
                    "diffuse":   list(di.Get())    if (di  and di.Get()  is not None) else [0.6, 0.6, 0.6],
                    "metallic":  float(me.Get())   if (me  and me.Get()  is not None) else 0.0,
                    "roughness": float(ro.Get())   if (ro  and ro.Get()  is not None) else 0.5,
                }
        # Style 2: inputs:diffuseColor directly on the Material prim
        dc_attr = mat_prim.GetAttribute("inputs:diffuseColor")
        if dc_attr and dc_attr.Get() is not None:
            me_attr = mat_prim.GetAttribute("inputs:metallic")
            ro_attr = mat_prim.GetAttribute("inputs:roughness")
            return {
                "diffuse":   list(dc_attr.Get()),
                "metallic":  float(me_attr.Get()) if (me_attr and me_attr.Get() is not None) else 0.0,
                "roughness": float(ro_attr.Get()) if (ro_attr and ro_attr.Get() is not None) else 0.5,
            }
        return {}

    def _infer_material_type(mat_path: str) -> str:
        p = mat_path.lower()
        if "steel"    in p: return "steel"
        if "alum"     in p: return "aluminum"
        if "rubber"   in p: return "rubber"
        if "concrete" in p: return "concrete"
        return "generic"

    # 1. Build material_prim_path → color props
    mat_props: dict[str, dict] = {}
    for prim in stage.Traverse():
        if UsdShade.Material(prim):
            props = _read_mat_props(prim)
            if props:
                path = str(prim.GetPath())
                props["material_type"] = _infer_material_type(path)
                mat_props[path] = props

    # 2. Map each geometry prim to its material props via MaterialBindingAPI
    prim_colors: dict[str, dict] = {}
    for prim in stage.Traverse():
        binding = UsdShade.MaterialBindingAPI(prim)
        bound_mat, _ = binding.ComputeBoundMaterial()
        if not bound_mat:
            continue
        mat_path = str(bound_mat.GetPath())
        if mat_path in mat_props:
            prim_colors[prim.GetName()] = mat_props[mat_path]

    return prim_colors


def render_usd_views(
    usd_path: str,
    output_dir: str,
    blender_exe: str = "blender",
    samples: int = 32,
    res: int = 768,
    engine: str = "CYCLES",
) -> list[str]:
    """
    Render 4 views of a USD scene using Blender headlessly.
    Returns [top.png, front.png, side.png, isometric.png] absolute paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    usd_path   = os.path.abspath(usd_path)
    output_dir = os.path.abspath(output_dir)

    # Extract colors via pxr and write sidecar JSON for the render script
    prim_colors = _extract_prim_colors(usd_path)
    colors_json = os.path.join(output_dir, "prim_colors.json")
    with open(colors_json, "w") as f:
        json.dump(prim_colors, f)
    print(f"[renderer] Extracted {len(prim_colors)} material colours from USD")

    cmd = [
        blender_exe,
        "--background",
        "--python", str(RENDER_SCRIPT),
        "--",
        "--input",  usd_path,
        "--output", output_dir,
        "--colors", colors_json,
        "--samples", str(samples),
        "--res",     str(res),
        "--engine",  engine,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("[renderer] Blender stdout:", result.stdout[-3000:])
        print("[renderer] Blender stderr:", result.stderr[-3000:])
        raise RuntimeError(f"Blender render failed (exit {result.returncode})")

    view_names = ["top", "front", "side", "isometric"]
    paths = [os.path.join(output_dir, f"{v}.png") for v in view_names]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise RuntimeError(f"Expected render outputs not found: {missing}")

    return paths
