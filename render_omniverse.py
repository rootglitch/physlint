"""
Isaac Sim headless rendering script — Omniverse replacement for render_usd.py.

Called via powershell.exe from WSL2:
  python render_omniverse.py --input C:\\path\\to\\scene.usda --output C:\\path\\to\\output [--res 768] [--samples 64]

Outputs: top.png, front.png, side.png, isometric.png in the output directory.

Key advantage over Blender: UsdPreviewSurface materials are read natively —
no prim_colors.json workaround needed. Rendered with RTX (GPU-accelerated).
"""
from __future__ import annotations

import argparse
import os
import sys


def parse_args():
    # Must parse before SimulationApp consumes sys.argv
    parser = argparse.ArgumentParser(description="Isaac Sim headless USD renderer")
    parser.add_argument("--input",   required=True, help="USD file path (Windows)")
    parser.add_argument("--output",  required=True, help="Output directory (Windows)")
    parser.add_argument("--res",     type=int, default=768, help="Square render resolution")
    parser.add_argument("--samples", type=int, default=64,  help="RTX subframes per view")
    # Accept (and ignore) legacy --colors arg for API compat with renderer.py
    parser.add_argument("--colors",  default=None, help="(ignored — Omniverse reads materials natively)")
    return parser.parse_args()


args = parse_args()

# ── Boot Isaac Sim (must happen before any omni.* imports) ───────────────────
from isaacsim import SimulationApp

kit = SimulationApp({
    "headless":   True,
    "renderer":   "RaytracedLighting",   # RTX Interactive — GPU accelerated on RTX 5080
})

# ── Omniverse imports (after kit init) ───────────────────────────────────────
import numpy as np
from PIL import Image

import omni.usd
import omni.replicator.core as rep
import carb
from pxr import Usd, UsdGeom, Gf


# ─────────────────────────────────────────────────────────────────────────────

def get_scene_bounds(stage: Usd.Stage) -> tuple[tuple[float, float, float], float]:
    """Return (center_xyz, radius) using USD bounding box."""
    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), ["default", "render"], useExtentsHint=True
    )
    root_bbox = bbox_cache.ComputeWorldBound(stage.GetPseudoRoot())
    rng = root_bbox.GetRange()
    if rng.IsEmpty():
        return (0.0, 0.0, 0.0), 1.0
    mn, mx = rng.GetMin(), rng.GetMax()
    cx = (mn[0] + mx[0]) / 2
    cy = (mn[1] + mx[1]) / 2
    cz = (mn[2] + mx[2]) / 2
    radius = max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) / 2
    return (cx, cy, cz), max(float(radius), 0.01)


def render_view(
    view_name: str,
    cam_pos: tuple[float, float, float],
    center: tuple[float, float, float],
    output_dir: str,
    res: int,
    samples: int,
) -> str:
    """
    Place a camera, render one frame, save to {view_name}.png.
    Returns the saved file path.
    """
    print(f"[render_omniverse.py] Rendering: {view_name}  cam={tuple(round(v,1) for v in cam_pos)}")

    # Create camera pointing at scene centre
    camera = rep.create.camera(
        position=cam_pos,
        look_at=center,
        focal_length=24.0,       # wider FOV — good for mechanical scenes
    )

    # Render product: this is the "viewport" tied to a camera
    rp = rep.create.render_product(camera, (res, res))

    # RGB annotator — direct numpy access, avoids BasicWriter filename quirks
    rgb_ann = rep.annotators.get("rgb")
    rgb_ann.attach([rp])

    # Warm-up: let Kit settle the stage
    for _ in range(8):
        kit.update()

    # Trigger the RTX render with rt_subframes accumulation
    rep.orchestrator.step(rt_subframes=samples)

    # Drain the update loop so the annotator buffer is populated
    for _ in range(8):
        kit.update()

    # Collect rendered pixels
    data = rgb_ann.get_data()

    out_path = os.path.join(output_dir, f"{view_name}.png")
    if data is not None and data.size > 0:
        # Annotator returns (H, W, 4) RGBA uint8 — drop alpha channel
        img = Image.fromarray(data[..., :3])
        img.save(out_path)
        print(f"[render_omniverse.py]   Saved: {out_path}")
    else:
        print(f"[render_omniverse.py]   WARNING: annotator returned no data for {view_name}")

    # Clean up so the next view starts fresh
    rgb_ann.detach([rp])
    rp.destroy()

    return out_path


def main():
    os.makedirs(args.output, exist_ok=True)
    usd_path = os.path.abspath(args.input)

    print(f"[render_omniverse.py] Loading stage: {usd_path}")
    omni.usd.get_context().open_stage(usd_path)

    # Let Kit finish loading the stage
    for _ in range(15):
        kit.update()

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError(f"Failed to open USD stage: {usd_path}")

    center, radius = get_scene_bounds(stage)
    print(f"[render_omniverse.py] centre={tuple(round(v,2) for v in center)}, radius={radius:.3f}")

    dist = radius * 3.0
    cx, cy, cz = center

    views = {
        "top":       (cx,        cy,        cz + dist),
        "front":     (cx,        cy - dist, cz),
        "side":      (cx + dist, cy,        cz),
        "isometric": (cx + dist, cy - dist, cz + dist * 0.8),
    }

    for view_name, cam_pos in views.items():
        render_view(view_name, cam_pos, center, args.output, args.res, args.samples)

    print(f"[render_omniverse.py] Done → {args.output}")


main()
kit.close()
