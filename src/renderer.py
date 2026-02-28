"""
Orchestrate Isaac Sim headless rendering of a USD file into 4 view images.

Renders run on Windows (native GPU via Vulkan/RTX), called from WSL2 via
powershell.exe. Path translation uses wslpath: /mnt/c/... → C:\\...

UsdPreviewSurface materials are read natively by Omniverse — no
prim_colors.json sidecar needed (unlike the previous Blender backend).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


# Windows-side paths (constants — adjust if installation moves)
_OMNI_PYTHON = Path("C:/Users/raajg/miniconda3/envs/isaacsim/python.exe")
_RENDER_SCRIPT = Path("C:/Crypt/Projects/physlint/render_omniverse.py")


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


def render_usd_views(
    usd_path: str,
    output_dir: str,
    samples: int = 64,
    res: int = 768,
    # Legacy params kept for call-site compatibility — not used by Omniverse backend
    blender_exe: str = "blender",
    engine: str = "CYCLES",
) -> list[str]:
    """
    Render 4 views of a USD scene using Isaac Sim (RTX) on Windows.
    Returns [top.png, front.png, side.png, isometric.png] absolute paths.

    Called from WSL2; the USD file and output dir can be on /mnt/c/ or
    WSL2-native paths (both are accessible from Windows via wslpath).
    """
    os.makedirs(output_dir, exist_ok=True)
    usd_path   = os.path.abspath(usd_path)
    output_dir = os.path.abspath(output_dir)

    # Translate WSL2 paths → Windows paths for the subprocess
    win_usd    = _to_windows_path(usd_path)
    win_output = _to_windows_path(output_dir)
    win_script = str(_RENDER_SCRIPT).replace("/", "\\")
    win_python = str(_OMNI_PYTHON).replace("/", "\\")

    print(f"[renderer] Launching Isaac Sim render (RTX {res}px × {samples} subframes)")
    print(f"[renderer]   USD:    {win_usd}")
    print(f"[renderer]   output: {win_output}")

    # Build the PowerShell command — single-quoted strings handle spaces in paths
    ps_cmd = (
        f"& '{win_python}' '{win_script}'"
        f" --input '{win_usd}'"
        f" --output '{win_output}'"
        f" --res {res}"
        f" --samples {samples}"
    )

    result = subprocess.run(
        ["powershell.exe", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        timeout=600,   # Isaac Sim first-run extension download can be slow
    )

    # Always print stdout so Isaac Sim startup/download messages are visible
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print("[renderer] stderr:", result.stderr[-4000:])
        raise RuntimeError(f"Isaac Sim render failed (exit {result.returncode})")

    view_names = ["top", "front", "side", "isometric"]
    paths = [os.path.join(output_dir, f"{v}.png") for v in view_names]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise RuntimeError(f"Expected render outputs not found: {missing}")

    return paths
