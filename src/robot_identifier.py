"""
Identify a robot from USD prim paths and return its spec entry from robot_specs.json.

Used by cosmos_client.py to inject per-robot joint limit context into Pass 2.
"""
from __future__ import annotations

import json
from pathlib import Path

_SPECS_PATH = Path(__file__).parent.parent / "assets" / "robot_specs.json"
_specs: dict | None = None


def _load_specs() -> dict:
    global _specs
    if _specs is None:
        with open(_SPECS_PATH) as f:
            _specs = json.load(f)
    return _specs


def identify_robot(prim_names: list[str]) -> tuple[str | None, dict | None]:
    """
    Match prim names against identifier_keys in robot_specs.json.

    Returns (robot_key, spec_dict) or (None, None) if unrecognised.

    The search is case-insensitive substring match: any prim name containing
    one of the robot's identifier_keys → match.
    """
    specs = _load_specs()
    search_text = " ".join(prim_names).lower()

    best_key: str | None = None
    best_len = 0   # prefer longer (more specific) match

    for robot_key, spec in specs.items():
        for kw in spec["identifier_keys"]:
            if kw.lower() in search_text and len(kw) > best_len:
                best_key = robot_key
                best_len = len(kw)

    if best_key:
        return best_key, specs[best_key]
    return None, None


def build_joint_context(spec: dict) -> str:
    """
    Format a robot's joint limits as a compact string for prompt injection.

    Example:
        Robot: Franka FR3
        Joint limits (degrees):
          fr3_joint1: [-157.2, 157.2]  fr3_joint2: [-102.2, 102.2]  ...
          fr3_joint6: [31.2, 258.8]  (NOTE: asymmetric — this is correct by design)
    """
    lines = [f"Robot: {spec['display_name']}", "Joint limits (degrees):"]
    joint_pairs: list[str] = []
    has_unconstrained = False
    for j in spec["joints"]:
        if j["type"] == "prismatic":
            # prismatic: show in metres, not degrees
            lo, hi = j["lower_rad"], j["upper_rad"]
            joint_pairs.append(f"  {j['name']}: [{lo:.4f}, {hi:.4f}] m (prismatic)")
        else:
            lo, hi = j["lower_deg"], j["upper_deg"]
            range_deg = hi - lo
            if range_deg > 360:
                # Effectively unconstrained — spec defines no real upper limit
                note = " [UNCONSTRAINED — always mark valid]"
                has_unconstrained = True
            elif lo > 0 or hi < 0:
                note = " [asymmetric by design]"
            elif abs(hi) > 180 or abs(lo) > 180:
                note = " [wide-range by design]"
            else:
                note = ""
            joint_pairs.append(f"  {j['name']}: [{lo:.1f}, {hi:.1f}]°{note}")
    lines.extend(joint_pairs)
    if has_unconstrained:
        lines.append(
            "NOTE: Joints marked [UNCONSTRAINED] have no effective limit — "
            "always set joint_valid=true for these joints regardless of USD limits."
        )
    return "\n".join(lines)
