"""
menagerie_pipeline.py — Download MuJoCo Menagerie robots, convert to USD,
strip physics, and register them in benchmark_gt.json.

Usage
-----
  python menagerie_pipeline.py                   # run all configured robots
  python menagerie_pipeline.py panda ur5e        # run specific robots by key

Each robot entry in ROBOTS defines:
  - mj_description : robot_descriptions loader name
  - xml_name       : the MJCF filename inside the cached repo
  - scene_name     : benchmark scene name (used in GT and renders)
  - n_violations   : how many joints to artificially violate
  - material_hints : prim-path prefix → material type
                     (matched by prefix so "link" covers link0, link1, …)

Output
------
  assets/menagerie/<scene_name>/           ← USD package (geometry, materials)
  assets/menagerie/<scene_name>_gt.json    ← standalone GT
  benchmark_gt.json                        ← updated with new scenes
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

from mujoco_usd_converter import Converter
from pxr import Usd, UsdPhysics
from strip_physics import strip_physics


# ---------------------------------------------------------------------------
# Robot catalogue
# ---------------------------------------------------------------------------

ROBOTS: dict[str, dict] = {
    "panda": {
        "mj_description": "panda_mj_description",
        "xml_name": "panda.xml",
        "menagerie_subdir": "franka_emika_panda",
        "scene_name": "menagerie_franka_panda",
        "n_violations": 0,  # mass-only: industrial joints can naturally exceed ±180°
        # All links are cast aluminium alloy; gripper fingers are hard plastic
        "material_hints_by_name": {
            "link": "aluminum",
            "hand": "aluminum",
            "finger": "hard plastic",
        },
    },
    "ur5e": {
        "mj_description": "ur5e_mj_description",
        "xml_name": "ur5e.xml",
        "menagerie_subdir": "universal_robots_ur5e",
        "scene_name": "menagerie_ur5e",
        "n_violations": 0,  # mass-only
        # UR5e links are aluminium, wrist links are smaller aluminium
        "material_hints_by_name": {
            "base": "aluminum",
            "shoulder": "aluminum",
            "upper_arm": "aluminum",
            "forearm": "aluminum",
            "wrist": "aluminum",
        },
    },
    "anymal_c": {
        "mj_description": "anymal_c_mj_description",
        "xml_name": "anymal_c.xml",
        "menagerie_subdir": "anybotics_anymal_c",
        "scene_name": "menagerie_anymal_c",
        "n_violations": 0,  # mass-only
        # ANYmal C legs: aluminium / carbon fibre composite, body: aluminium
        "material_hints_by_name": {
            "base": "aluminum",
            "hip": "aluminum",
            "thigh": "carbon fiber",
            "shank": "carbon fiber",
            "foot": "rubber",
        },
    },
}

CACHE_DIR = pathlib.Path("~/.cache/robot_descriptions/mujoco_menagerie").expanduser()
ASSET_DIR = pathlib.Path("assets/menagerie")
GT_JSON = pathlib.Path("assets/benchmark_gt.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_material_hints(stage: Usd.Stage, hints_by_name: dict[str, str]) -> dict[str, str]:
    """
    Map prim paths → material type by matching the prim's last name segment
    against the hint keys (substring match, case-insensitive).
    """
    result: dict[str, str] = {}
    for prim in stage.Traverse():
        if not UsdPhysics.RigidBodyAPI(prim):
            continue
        path = str(prim.GetPath())
        last = path.split("/")[-1].lower()
        for key, mat in hints_by_name.items():
            if key.lower() in last:
                result[path] = mat
                break
    return result


def _find_mjcf(subdir: str, xml_name: str) -> pathlib.Path:
    p = CACHE_DIR / subdir / xml_name
    if p.exists():
        return p
    raise FileNotFoundError(
        f"MJCF not found at {p}. "
        "Run `python -c \"from robot_descriptions.loaders.mujoco import "
        f"load_robot_description; load_robot_description('{subdir}')\"` first."
    )


# ---------------------------------------------------------------------------
# Pipeline for a single robot
# ---------------------------------------------------------------------------

def process_robot(key: str, cfg: dict, dry_run: bool = False) -> dict | None:
    scene_name = cfg["scene_name"]
    print(f"\n{'='*60}")
    print(f" Processing: {key}  →  {scene_name}")
    print(f"{'='*60}")

    # 1. Trigger download if needed (load_robot_description caches the repo)
    print(f"[1/4] Loading {cfg['mj_description']} (downloads if needed)...")
    try:
        from robot_descriptions.loaders.mujoco import load_robot_description
        load_robot_description(cfg["mj_description"])
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

    # 2. Locate MJCF
    try:
        mjcf_path = _find_mjcf(cfg["menagerie_subdir"], cfg["xml_name"])
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        return None
    print(f"[2/4] MJCF found: {mjcf_path}")

    # 3. Convert MJCF → USD
    usd_out_dir = ASSET_DIR / scene_name
    usd_out_dir.mkdir(parents=True, exist_ok=True)
    usd_main = usd_out_dir / f"{scene_name}.usda"

    if usd_main.exists():
        print(f"[3/4] USD already exists, skipping conversion: {usd_main}")
    else:
        print(f"[3/4] Converting MJCF → USD ...")
        if not dry_run:
            c = Converter()
            result = c.convert(str(mjcf_path), str(usd_out_dir))
            # Converter names the file after the MJCF stem; rename to scene_name
            converted = usd_out_dir / (pathlib.Path(cfg["xml_name"]).stem + ".usda")
            if converted.exists() and converted != usd_main:
                converted.rename(usd_main)
            print(f"     → {usd_main}")
        else:
            print("     [dry-run, skipping]")
            return None

    # 4. Strip physics
    print(f"[4/4] Stripping physics + injecting {cfg['n_violations']} violation(s)...")
    if not dry_run:
        stage = Usd.Stage.Open(str(usd_main))
        hints = _resolve_material_hints(stage, cfg["material_hints_by_name"])

        entry = strip_physics(
            input_usd=str(usd_main),
            output_dir=str(usd_out_dir),
            material_hints=hints,
            n_violations=cfg["n_violations"],
            seed=42,
            name_override=scene_name,
        )
        return entry
    else:
        print("     [dry-run, skipping]")
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download, convert, and strip Menagerie robots for PhysInt benchmarking."
    )
    parser.add_argument(
        "robots",
        nargs="*",
        help=f"Robot keys to process. Available: {list(ROBOTS)}. Default: all.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without running conversion.")
    parser.add_argument("--gt", default=str(GT_JSON),
                        help=f"benchmark_gt.json to update (default: {GT_JSON})")
    args = parser.parse_args()

    keys = args.robots if args.robots else list(ROBOTS)
    unknown = [k for k in keys if k not in ROBOTS]
    if unknown:
        print(f"Unknown robot key(s): {unknown}. Available: {list(ROBOTS)}")
        sys.exit(1)

    new_entries: list[dict] = []
    for key in keys:
        entry = process_robot(key, ROBOTS[key], dry_run=args.dry_run)
        if entry:
            new_entries.append(entry)

    if not new_entries:
        print("\nNo entries to add.")
        return

    # Update benchmark_gt.json
    gt_path = pathlib.Path(args.gt)
    if gt_path.exists():
        with open(gt_path) as f:
            gt = json.load(f)
    else:
        gt = {"description": "PhysInt benchmark ground truth", "scenes": []}

    existing_names = {s["name"] for s in gt["scenes"]}
    added, updated = 0, 0
    for entry in new_entries:
        if entry["name"] in existing_names:
            gt["scenes"] = [s for s in gt["scenes"] if s["name"] != entry["name"]]
            updated += 1
        else:
            added += 1
        gt["scenes"].append(entry)

    with open(gt_path, "w") as f:
        json.dump(gt, f, indent=2)

    print(f"\nDone. Added {added}, updated {updated} scene(s) in {gt_path}")
    print(f"Total scenes in GT: {len(gt['scenes'])}")


if __name__ == "__main__":
    main()
