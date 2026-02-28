"""
Orchestrate Blender headless GPU rendering of a USD file into 4 view images.

Renders run on Windows Blender (CYCLES + GPU via CUDA/OptiX), called from
WSL2 via powershell.exe. Path translation uses wslpath: /mnt/c/... → C:\\...

UsdPreviewSurface colors are extracted via pxr (same as before) because
Blender's USD importer does not reliably read them directly.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


# Windows Blender executable
_BLENDER_EXE = Path("C:/Program Files/Blender Foundation/Blender 4.5/blender.exe")

# render_usd.py lives alongside renderer.py's parent (project root)
_RENDER_SCRIPT = Path(__file__).parent.parent / "render_usd.py"


def _to_windows_path(wsl_path: str) -> str:
    """
    Convert a WSL2 path to a Windows path using wslpath.
      /mnt/c/Crypt/... → C:\\Crypt\\...
      /home/raajg/...  → \\\\wsl.localhost\\Ubuntu\\home\\raajg\\...
    """
    result = subprocess.run(
        ["wslpath", "-w", wsl_path],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _extract_prim_colors(usd_path: str) -> dict[str, dict]:
    """
    Use pxr to read material colors for every prim that has a material binding.
    Returns {prim_name: {diffuse, metallic, roughness, material_type}}.
    """
    from pxr import Usd, UsdShade

    stage = Usd.Stage.Open(usd_path)

    def _read_mat_props(mat_prim) -> dict:
        for child in mat_prim.GetChildren():
            shader = UsdShade.Shader(child)
            if shader and shader.GetIdAttr().Get() == "UsdPreviewSurface":
                di = shader.GetInput("diffuseColor")
                me = shader.GetInput("metallic")
                ro = shader.GetInput("roughness")
                return {
                    "diffuse":   list(di.Get())    if (di  and di.Get()  is not None) else [0.6, 0.6, 0.6],
                    "metallic":  float(me.Get())   if (me  and me.Get()  is not None) else 0.0,
                    "roughness": float(ro.Get())   if (ro  and ro.Get()  is not None) else 0.5,
                }
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

    mat_props: dict[str, dict] = {}
    for prim in stage.Traverse():
        if UsdShade.Material(prim):
            props = _read_mat_props(prim)
            if props:
                path = str(prim.GetPath())
                props["material_type"] = _infer_material_type(path)
                mat_props[path] = props

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
    samples: int = 64,
    res: int = 768,
    # Legacy params kept for call-site compatibility
    blender_exe: str = "blender",
    engine: str = "CYCLES",
) -> list[str]:
    """
    Render 4 views of a USD scene using Windows Blender (CYCLES GPU).
    Returns [top.png, front.png, side.png, isometric.png] absolute paths.

    Called from WSL2; paths are translated via wslpath for the Windows subprocess.
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

    # Translate WSL2 paths → Windows paths
    win_usd     = _to_windows_path(usd_path)
    win_output  = _to_windows_path(output_dir)
    win_colors  = _to_windows_path(colors_json)
    win_script  = _to_windows_path(str(_RENDER_SCRIPT))
    win_blender = str(_BLENDER_EXE).replace("/", "\\")

    print(f"[renderer] Launching Windows Blender GPU render ({res}px × {samples} samples)")

    # Build PowerShell command — single-quoted strings handle spaces in paths
    ps_cmd = (
        f"& '{win_blender}' --background"
        f" --python '{win_script}'"
        f" --"
        f" --input '{win_usd}'"
        f" --output '{win_output}'"
        f" --colors '{win_colors}'"
        f" --samples {samples}"
        f" --res {res}"
        f" --engine CYCLES"
    )

    result = subprocess.run(
        ["powershell.exe", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.stdout:
        print(result.stdout[-3000:])
    if result.returncode != 0:
        print("[renderer] stderr:", result.stderr[-3000:])
        raise RuntimeError(f"Blender render failed (exit {result.returncode})")

    view_names = ["top", "front", "side", "isometric"]
    paths = [os.path.join(output_dir, f"{v}.png") for v in view_names]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise RuntimeError(f"Expected render outputs not found: {missing}")

    return paths
