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
    "fr3": {
        "mj_description": "fr3_mj_description",
        "xml_name": "fr3.xml",
        "menagerie_subdir": "franka_fr3",
        "scene_name": "menagerie_fr3",
        "n_violations": 0,
        # Franka Research 3: cast aluminium links, hard plastic finger pads
        "material_hints_by_name": {
            "link": "aluminum",
            "hand": "aluminum",
            "finger": "hard plastic",
        },
    },
    "iiwa14": {
        "mj_description": "iiwa14_mj_description",
        "xml_name": "iiwa14.xml",
        "menagerie_subdir": "kuka_iiwa_14",
        "scene_name": "menagerie_iiwa14",
        "n_violations": 0,
        # KUKA iiwa14: precision-cast aluminium links throughout
        "material_hints_by_name": {
            "link": "aluminum",
            "flange": "aluminum",
        },
    },
    "spot": {
        "mj_description": "spot_mj_description",
        "xml_name": "spot.xml",
        "menagerie_subdir": "boston_dynamics_spot",
        "scene_name": "menagerie_spot",
        "n_violations": 0,
        # Spot: aluminium structural frame, hard plastic covers, rubber foot pads
        "material_hints_by_name": {
            "base": "aluminum",
            "hip": "aluminum",
            "upper": "aluminum",
            "lower": "aluminum",
            "foot": "rubber",
            "body": "hard plastic",
        },
    },
    "go2": {
        "mj_description": "go2_mj_description",
        "xml_name": "go2.xml",
        "menagerie_subdir": "unitree_go2",
        "scene_name": "menagerie_go2",
        "n_violations": 0,
        # Unitree Go2: aluminium links, rubber feet
        "material_hints_by_name": {
            "trunk": "aluminum",
            "hip": "aluminum",
            "thigh": "aluminum",
            "calf": "aluminum",
            "foot": "rubber",
        },
    },
    "h1": {
        "mj_description": "h1_mj_description",
        "xml_name": "h1.xml",
        "menagerie_subdir": "unitree_h1",
        "scene_name": "menagerie_h1",
        "n_violations": 0,
        # Unitree H1: aluminium structural frame, hard plastic covers
        "material_hints_by_name": {
            "pelvis": "aluminum",
            "torso": "aluminum",
            "hip": "aluminum",
            "thigh": "aluminum",
            "calf": "aluminum",
            "ankle": "aluminum",
            "shoulder": "aluminum",
            "elbow": "aluminum",
            "wrist": "aluminum",
        },
    },
    "go1": {
        "mj_description": "go1_mj_description",
        "xml_name": "go1.xml",
        "menagerie_subdir": "unitree_go1",
        "scene_name": "menagerie_go1",
        "n_violations": 0,
        "material_hints_by_name": {
            "trunk": "aluminum",
            "hip": "aluminum",
            "thigh": "aluminum",
            "calf": "aluminum",
            "foot": "rubber",
        },
    },
    "g1": {
        "mj_description": "g1_mj_description",
        "xml_name": "g1.xml",
        "menagerie_subdir": "unitree_g1",
        "scene_name": "menagerie_g1",
        "n_violations": 0,
        # Unitree G1: aluminium links throughout, rubber soles
        "material_hints_by_name": {
            "pelvis": "aluminum",
            "torso": "aluminum",
            "head": "hard plastic",
            "hip": "aluminum",
            "knee": "aluminum",
            "ankle": "aluminum",
            "foot": "rubber",
            "shoulder": "aluminum",
            "elbow": "aluminum",
            "wrist": "aluminum",
            "hand": "hard plastic",
        },
    },
    "ur10e": {
        "mj_description": "ur10e_mj_description",
        "xml_name": "ur10e.xml",
        "menagerie_subdir": "universal_robots_ur10e",
        "scene_name": "menagerie_ur10e",
        "n_violations": 0,
        "material_hints_by_name": {
            "base": "aluminum",
            "shoulder": "aluminum",
            "upper_arm": "aluminum",
            "forearm": "aluminum",
            "wrist": "aluminum",
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

def process_robot(
    key: str,
    cfg: dict,
    dry_run: bool = False,
    also_violated: bool = False,
) -> list[dict]:
    """Returns a list of scene entry dicts (clean, and optionally violated)."""
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
        return []

    # 2. Locate MJCF
    try:
        mjcf_path = _find_mjcf(cfg["menagerie_subdir"], cfg["xml_name"])
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        return []
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
            c.convert(str(mjcf_path), str(usd_out_dir))
            # Converter may name the file after the model (not the MJCF stem).
            # Find any top-level .usda in the output dir that isn't the target name.
            candidates = [
                p for p in usd_out_dir.glob("*.usda")
                if p.name != usd_main.name
            ]
            if candidates and not usd_main.exists():
                candidates[0].rename(usd_main)
            if not usd_main.exists():
                raise FileNotFoundError(
                    f"Converter did not produce a USDA file in {usd_out_dir}"
                )
            print(f"     → {usd_main}")
        else:
            print("     [dry-run, skipping]")
            return []

    # 4. Strip physics (clean variant)
    print(f"[4/4] Stripping physics (clean) ...")
    entries: list[dict] = []
    if not dry_run:
        stage = Usd.Stage.Open(str(usd_main))
        hints = _resolve_material_hints(stage, cfg["material_hints_by_name"])

        clean_entry = strip_physics(
            input_usd=str(usd_main),
            output_dir=str(usd_out_dir),
            material_hints=hints,
            n_violations=0,
            seed=42,
            name_override=scene_name,
            clear_limits=False,
        )
        entries.append(clean_entry)

        # Optional violated variant
        if also_violated:
            print(f"     Generating violated variant ({scene_name}_violated) ...")
            viol_dir = ASSET_DIR / (scene_name + "_violated")
            viol_dir.mkdir(parents=True, exist_ok=True)
            viol_entry = strip_physics(
                input_usd=str(usd_main),
                output_dir=str(viol_dir),
                material_hints=hints,
                n_violations=1,
                seed=42,
                name_override=scene_name + "_violated",
                clear_limits=False,
            )
            entries.append(viol_entry)
    else:
        print("     [dry-run, skipping]")
        return []

    return entries


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
    parser.add_argument("--violated", action="store_true",
                        help="Also generate a violated variant for each robot (n_violations=1).")
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
        entries = process_robot(key, ROBOTS[key], dry_run=args.dry_run,
                                also_violated=args.violated)
        new_entries.extend(entries)

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
