"""
strip_physics.py — Extract physics ground truth from a USD and produce a
stripped copy suitable for PhysInt evaluation.

Usage
-----
  python strip_physics.py <input.usda> [options]

What it does
------------
1. Walks all prims in the input USD.
2. For every rigid body with PhysicsMassAPI → records the authorised mass,
   then clears `physics:mass` so PhysInt must infer it visually.
3. For every Revolute / Prismatic joint → records the lower/upper limits.
   Optionally injects deliberate violations into a subset of joints so the
   violation-detection benchmark has positive examples.
4. Writes:
   - <output_dir>/<stem>_stripped.usda   (no physics attrs)
   - <output_dir>/<stem>_gt.json         (benchmark_gt.json–compatible entry)

Material hints
--------------
Because USD visual materials carry names like "off_white" not "aluminum",
you can supply hints via --material flags:

  --material /panda/Geometry/link0:aluminum
  --material /panda/Geometry/link0/link1:aluminum

Or point to a JSON file:
  --material-file hints.json    # {"path": "material_type", ...}

If no hint is given for a prim the material field is left as "unknown".
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import pathlib
import random
import sys
from typing import Optional

from pxr import Sdf, Usd, UsdGeom, UsdPhysics, UsdShade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_mass(prim: Usd.Prim) -> Optional[float]:
    """Return the authored physics:mass (kg) or None."""
    mass_api = UsdPhysics.MassAPI(prim)
    attr = mass_api.GetMassAttr()
    val = attr.Get()
    return float(val) if val is not None and val > 0 else None


def _clear_mass(prim: Usd.Prim) -> None:
    """Remove the authored physics:mass value."""
    mass_api = UsdPhysics.MassAPI(prim)
    mass_api.GetMassAttr().Clear()
    # Also clear density so nothing can be inferred from it
    mass_api.GetDensityAttr().Clear()


def _get_joint_limits(prim: Usd.Prim) -> tuple[Optional[float], Optional[float]]:
    lo_attr = prim.GetAttribute("physics:lowerLimit")
    hi_attr = prim.GetAttribute("physics:upperLimit")
    lo = lo_attr.Get() if lo_attr else None
    hi = hi_attr.Get() if hi_attr else None
    return (float(lo) if lo is not None else None,
            float(hi) if hi is not None else None)


def _set_joint_limits(prim: Usd.Prim, lo: float, hi: float) -> None:
    prim.GetAttribute("physics:lowerLimit").Set(lo)
    prim.GetAttribute("physics:upperLimit").Set(hi)


def _clear_joint_limits(prim: Usd.Prim) -> None:
    prim.GetAttribute("physics:lowerLimit").Clear()
    prim.GetAttribute("physics:upperLimit").Clear()


def _is_rigid_body(prim: Usd.Prim) -> bool:
    return bool(UsdPhysics.RigidBodyAPI(prim))


def _joint_type(prim: Usd.Prim) -> Optional[str]:
    if prim.IsA(UsdPhysics.RevoluteJoint):
        return "revolute"
    if prim.IsA(UsdPhysics.PrismaticJoint):
        return "prismatic"
    return None


# ---------------------------------------------------------------------------
# Violation injection
# ---------------------------------------------------------------------------

def _inject_revolute_violation(lo: float, hi: float) -> tuple[float, float]:
    """Return a violated (lo, hi) pair for a revolute joint (degrees)."""
    # Push upper well past 180° — clearly unphysical for human-like joints
    new_hi = max(hi, 0) + random.uniform(100, 180)
    new_hi = round(new_hi, 1)
    return lo, new_hi


def _inject_prismatic_violation(lo: float, hi: float,
                                body_len: Optional[float]) -> tuple[float, float]:
    """Return a violated (lo, hi) pair for a prismatic joint (stage units)."""
    ref = body_len if body_len else max(abs(hi - lo) * 2, 50)
    new_hi = lo + ref * random.uniform(2.5, 5.0)
    new_hi = round(new_hi, 2)
    return lo, new_hi


# ---------------------------------------------------------------------------
# Main strip logic
# ---------------------------------------------------------------------------

def strip_physics(
    input_usd: str,
    output_dir: str,
    material_hints: dict[str, str],
    n_violations: int = 0,
    seed: int = 42,
    name_override: Optional[str] = None,
    clear_limits: bool = True,
) -> dict:
    """
    Strip physics from `input_usd`, optionally inject violations.

    Args:
      clear_limits: If True, clear joint limits in the stripped USD (model must
                    predict them from visuals). If False, preserve original limits
                    so the model can validate them. Use False for real robot USDs
                    where limits are known-valid and we want to test specificity.

    Returns a benchmark_gt.json–compatible scene entry dict.
    """
    random.seed(seed)

    input_path = pathlib.Path(input_usd).resolve()
    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = name_override or input_path.stem
    stripped_path = out_dir / f"{stem}_stripped.usda"

    # Open the original stage (sublayers resolve relative to its directory).
    # Flatten all composition arcs (sublayers, references, payloads) into a
    # single in-memory layer so we can freely edit and relocate it.
    stage_in = Usd.Stage.Open(str(input_path))
    flat_layer = stage_in.Flatten()
    flat_layer.Export(str(stripped_path))

    # Re-open the flat copy for editing
    stage = Usd.Stage.Open(str(stripped_path))

    gt_masses: list[dict] = []
    gt_joints: list[dict] = []

    # --- Collect rigid bodies (mass GT) ---
    body_prims = [
        p for p in stage.Traverse()
        if _is_rigid_body(p) and UsdPhysics.MassAPI(p)
    ]

    for prim in body_prims:
        mass = _get_mass(prim)
        if mass is None:
            continue
        path = str(prim.GetPath())
        material = material_hints.get(path, "unknown")
        gt_masses.append({
            "path": path,
            "material": material,
            "mass_kg": round(mass, 4),
        })
        _clear_mass(prim)

    # --- Collect joints and choose which to violate ---
    joint_prims = [
        p for p in stage.Traverse()
        if _joint_type(p) is not None
    ]

    # Randomly pick joints to violate (prefer revolute for interpretability)
    revolute_joints = [p for p in joint_prims if _joint_type(p) == "revolute"]
    prismatic_joints = [p for p in joint_prims if _joint_type(p) == "prismatic"]
    violation_candidates = revolute_joints or prismatic_joints
    n_to_violate = min(n_violations, len(violation_candidates))
    to_violate = set(
        str(p.GetPath())
        for p in random.sample(violation_candidates, n_to_violate)
    )

    for prim in joint_prims:
        path = str(prim.GetPath())
        jtype = _joint_type(prim)
        lo, hi = _get_joint_limits(prim)
        if lo is None or hi is None:
            continue

        violated = path in to_violate
        if violated:
            if jtype == "revolute":
                lo, hi = _inject_revolute_violation(lo, hi)
            else:
                lo, hi = _inject_prismatic_violation(lo, hi, None)
            _set_joint_limits(prim, lo, hi)

        gt_joints.append({
            "path": path,
            "type": jtype,
            "lower": round(lo, 2),
            "upper": round(hi, 2),
            "violated": violated,
        })

        if clear_limits:
            _clear_joint_limits(prim)

    stage.GetRootLayer().Save()

    scene_entry = {
        "name": stem,
        "usd": str(stripped_path),
        "description": f"Stripped from {input_path.name} — {len(gt_masses)} bodies, "
                       f"{len(gt_joints)} joints ({n_to_violate} violated)",
        "joints": gt_joints,
        "masses": gt_masses,
    }

    # Write standalone GT JSON
    gt_path = out_dir / f"{stem}_gt.json"
    with open(gt_path, "w") as f:
        json.dump(scene_entry, f, indent=2)

    print(f"[strip_physics] Stripped → {stripped_path}")
    print(f"[strip_physics] GT       → {gt_path}")
    print(f"  {len(gt_masses)} bodies stripped, "
          f"{len(gt_joints)} joints ({n_to_violate} violated)")

    return scene_entry


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Strip physics from a USD and write benchmark GT."
    )
    parser.add_argument("input", help="Input .usda / .usd path")
    parser.add_argument("--output-dir", default="assets/menagerie",
                        help="Output directory (default: assets/menagerie)")
    parser.add_argument("--name", default=None,
                        help="Override scene name (default: input stem)")
    parser.add_argument("--material", action="append", default=[],
                        metavar="PATH:MATERIAL",
                        help="Material hint, e.g. /panda/link0:aluminum. Repeatable.")
    parser.add_argument("--material-file", default=None,
                        help="JSON file mapping prim path → material type")
    parser.add_argument("--inject-violations", type=int, default=0,
                        metavar="N",
                        help="Number of joints to artificially violate (default: 0)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--update-gt", default=None,
                        metavar="GT_JSON",
                        help="Append the new scene entry to this benchmark_gt.json")
    args = parser.parse_args()

    # Build material hints dict
    hints: dict[str, str] = {}
    if args.material_file:
        with open(args.material_file) as f:
            hints.update(json.load(f))
    for item in args.material:
        if ":" not in item:
            print(f"Warning: ignoring malformed --material '{item}' (expected PATH:MAT)")
            continue
        path, mat = item.split(":", 1)
        hints[path] = mat

    entry = strip_physics(
        input_usd=args.input,
        output_dir=args.output_dir,
        material_hints=hints,
        n_violations=args.inject_violations,
        seed=args.seed,
        name_override=args.name,
    )

    if args.update_gt:
        gt_path = pathlib.Path(args.update_gt)
        if gt_path.exists():
            with open(gt_path) as f:
                gt = json.load(f)
        else:
            gt = {"description": "PhysInt benchmark ground truth", "scenes": []}
        # Remove any existing entry with same name
        gt["scenes"] = [s for s in gt["scenes"] if s["name"] != entry["name"]]
        gt["scenes"].append(entry)
        with open(gt_path, "w") as f:
            json.dump(gt, f, indent=2)
        print(f"[strip_physics] Updated {gt_path}")


if __name__ == "__main__":
    main()
