"""
Extract joint and mass specs from cached Menagerie MJCF files.
Outputs assets/robot_specs.json for V2 context injection.

Handles MJCF default-class inheritance for joint ranges.

Usage:
    python scripts/extract_specs.py
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

MENAGERIE = Path.home() / ".cache/robot_descriptions/mujoco_menagerie"
OUT = Path(__file__).parent.parent / "assets" / "robot_specs.json"

# Robots to extract: (dir_name, display_name, identifier_keys)
ROBOTS = [
    ("franka_fr3",           "Franka FR3",           ["fr3", "franka_fr3"]),
    ("franka_fr3_v2",        "Franka FR3 v2",        ["fr3_v2"]),
    ("franka_emika_panda",   "Franka Panda",          ["panda", "franka_panda", "franka_emika"]),
    ("kuka_iiwa_14",         "KUKA iiwa 14",          ["iiwa", "iiwa14", "kuka"]),
    ("boston_dynamics_spot", "Boston Dynamics Spot",  ["spot"]),
    ("unitree_go2",          "Unitree Go2",           ["go2", "unitree_go2"]),
    ("unitree_go1",          "Unitree Go1",           ["go1", "unitree_go1"]),
    ("unitree_h1",           "Unitree H1",            ["h1", "unitree_h1"]),
    ("unitree_g1",           "Unitree G1",            ["g1", "unitree_g1"]),
    ("anybotics_anymal_c",   "ANYbotics ANYmal C",    ["anymal_c", "anybotics"]),
    ("anybotics_anymal_b",   "ANYbotics ANYmal B",    ["anymal_b"]),
    ("universal_robots_ur5e","Universal Robots UR5e", ["ur5e"]),
    ("universal_robots_ur10e","Universal Robots UR10e",["ur10e"]),
]

# Prefer the main model XML: avoid these suffixes/prefixes
_SKIP_STEMS = {"scene", "scene_arm", "mjx_scene", "mjx_single_cube"}
_SKIP_SUFFIXES = ("_arm", "_hand", "_nohand", "_mjx", "_v2")  # v2 handled as separate entry


def _find_main_xml(robot_dir: Path, dir_name: str) -> Path | None:
    """Pick the best MJCF file for the given robot directory."""
    candidates = sorted(robot_dir.glob("*.xml"))
    # Build a priority list: prefer stem that exactly matches the "model" word
    # e.g. boston_dynamics_spot → "spot", franka_emika_panda → "panda"
    model_word = dir_name.rsplit("_", 1)[-1]  # last segment: "spot", "panda", "fr3", etc.

    def score(p: Path) -> int:
        s = p.stem
        if s in _SKIP_STEMS:
            return 100
        if any(s.endswith(sfx) for sfx in _SKIP_SUFFIXES):
            return 50
        if s == model_word:
            return 0   # best
        if model_word in s:
            return 1
        return 10

    candidates = [c for c in candidates if c.stem not in _SKIP_STEMS]
    if not candidates:
        return None
    return min(candidates, key=score)


# ---------------------------------------------------------------------------
# MJCF default-class resolution
# ---------------------------------------------------------------------------

def _build_defaults(root: ET.Element) -> dict[str, dict[str, str]]:
    """
    Walk <default> elements recursively and build a flat map:
        class_name → {attr: value, ...}  (joint attributes only)

    Child defaults inherit parent defaults (child overrides parent).
    """
    flat: dict[str, dict[str, str]] = {}

    def _walk(node: ET.Element, inherited: dict[str, str]) -> None:
        cls = node.get("class", "__root__")
        # Merge: parent inherited ← this node's <joint> attrs
        merged = dict(inherited)
        jel = node.find("joint")
        if jel is not None:
            merged.update(jel.attrib)
        flat[cls] = merged
        for child in node:
            if child.tag == "default":
                _walk(child, merged)

    defaults_root = root.find("default")
    if defaults_root is not None:
        _walk(defaults_root, {})
    return flat


def _resolve_joint_range(jel: ET.Element, defaults: dict[str, dict]) -> str | None:
    """Return the effective 'range' string for a joint element, resolving defaults."""
    # Inline attribute takes priority
    r = jel.get("range")
    if r:
        return r
    # Look up class chain
    cls = jel.get("class")
    if cls and cls in defaults:
        return defaults[cls].get("range")
    # Try root default
    if "__root__" in defaults:
        return defaults["__root__"].get("range")
    return None


def _resolve_joint_type(jel: ET.Element, defaults: dict[str, dict]) -> str:
    t = jel.get("type")
    if t:
        return t
    cls = jel.get("class")
    if cls and cls in defaults:
        t = defaults[cls].get("type")
        if t:
            return t
    if "__root__" in defaults:
        t = defaults["__root__"].get("type")
        if t:
            return t
    return "hinge"


# ---------------------------------------------------------------------------

def _rad_to_deg(v: float) -> float:
    return round(math.degrees(v), 2)


def _parse_mjcf(xml_path: Path) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    defaults = _build_defaults(root)

    joints: list[dict] = []
    links:  list[dict] = []

    def _walk_body(node: ET.Element, childclass: str | None) -> None:
        """Recursively walk worldbody, passing down the effective childclass."""
        for child in node:
            if child.tag == "body":
                bname = child.get("name")
                # childclass overrides when body declares its own
                new_cc = child.get("childclass", childclass)
                if bname:
                    inertial = child.find("inertial")
                    mass = None
                    if inertial is not None:
                        mass = inertial.get("mass")
                    if mass is None:
                        mass = child.get("mass")
                    if mass is not None:
                        links.append({"name": bname, "mass_kg": round(float(mass), 4)})
                _walk_body(child, new_cc)

            elif child.tag == "joint":
                jname = child.get("name")
                if not jname:
                    continue
                # Effective class: explicit class attr > inherited childclass
                eff_class = child.get("class") or childclass
                # Resolve type
                jtype = child.get("type")
                if not jtype and eff_class and eff_class in defaults:
                    jtype = defaults[eff_class].get("type", "hinge")
                jtype = jtype or "hinge"
                if jtype == "free":
                    continue
                is_prismatic = jtype == "slide"
                # Resolve range: inline > effective class > __root__
                range_str = child.get("range")
                if not range_str and eff_class and eff_class in defaults:
                    range_str = defaults[eff_class].get("range")
                if not range_str and "__root__" in defaults:
                    range_str = defaults["__root__"].get("range")
                if not range_str:
                    continue
                lo_r, hi_r = map(float, range_str.split())
                joints.append({
                    "name":      jname,
                    "type":      "prismatic" if is_prismatic else "revolute",
                    "lower_deg": _rad_to_deg(lo_r) if not is_prismatic else round(lo_r, 4),
                    "upper_deg": _rad_to_deg(hi_r) if not is_prismatic else round(hi_r, 4),
                    "lower_rad": round(lo_r, 6),
                    "upper_rad": round(hi_r, 6),
                })

    # worldbody may be a direct child of root, or under <mujoco>
    wb = root.find(".//worldbody")
    if wb is not None:
        top_cc = wb.get("childclass")
        _walk_body(wb, top_cc)

    return {"joints": joints, "links": links}


def main() -> None:
    specs: dict[str, dict] = {}

    for dir_name, display_name, id_keys in ROBOTS:
        robot_dir = MENAGERIE / dir_name
        if not robot_dir.exists():
            print(f"  [skip] {dir_name} — not cached")
            continue

        xml_path = _find_main_xml(robot_dir, dir_name)
        if xml_path is None:
            print(f"  [skip] {dir_name} — no XML found")
            continue

        data = _parse_mjcf(xml_path)
        specs[dir_name] = {
            "display_name":    display_name,
            "identifier_keys": id_keys,
            "source_xml":      str(xml_path.relative_to(MENAGERIE.parent)),
            "joints":          data["joints"],
            "links":           data["links"],
        }
        n_j = len(data["joints"])
        n_l = len(data["links"])
        print(f"  [ok]   {display_name:40s} {n_j:3d} joints, {n_l:3d} links  ({xml_path.name})")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(specs, f, indent=2)

    print(f"\nWrote {len(specs)} robots → {OUT}")


if __name__ == "__main__":
    main()
