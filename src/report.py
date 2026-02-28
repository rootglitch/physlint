"""
Generate a human-readable physics compliance report (JSON + Markdown).
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from .cosmos_client import PhysicsAnalysis
from .usd_parser import SceneGraph


def generate_report(
    scene_graph: SceneGraph,
    analysis: PhysicsAnalysis,
    chain_of_thought: str,
    render_paths: list[str],
    input_usd: str,
    output_usd: str | None,
) -> dict:
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Flag joint issues
    joint_issues = [j for j in analysis.joint_prims if not j.joint_valid]

    report = {
        "timestamp": timestamp,
        "input_usd": input_usd,
        "output_usd": output_usd,
        "scene_graph_joints": [
            {"path": jp.path, "lower_limit": jp.lower_limit, "upper_limit": jp.upper_limit}
            for jp in scene_graph.joint_prims
        ],
        "summary": {
            "geometry_prims_processed": len(analysis.geom_prims),
            "joint_prims_processed": len(analysis.joint_prims),
            "joint_limit_corrections": len(joint_issues),
            "global_notes": analysis.global_notes,
        },
        "geometry_findings": [
            {
                "prim_path": g.prim_path,
                "material_type": g.material_type,
                "confidence": g.confidence,
                "mass_kg": g.mass_kg,
                "static_friction": g.static_friction,
                "dynamic_friction": g.dynamic_friction,
                "restitution": g.restitution,
                "collision_approximation": g.collision_approximation,
                "is_rigid": g.is_rigid,
                "reasoning": g.reasoning,
            }
            for g in analysis.geom_prims
        ],
        "joint_findings": [
            {
                "prim_path": j.prim_path,
                "lower_limit_deg": j.lower_limit_deg,
                "upper_limit_deg": j.upper_limit_deg,
                "joint_valid": j.joint_valid,
                "confidence": j.confidence,
                "reasoning": j.reasoning,
            }
            for j in analysis.joint_prims
        ],
        "render_paths": render_paths,
        "chain_of_thought": chain_of_thought,
    }
    return report


def save_report(report: dict, json_path: str, md_path: str | None = None):
    os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    if md_path:
        _write_markdown(report, md_path)


def _write_markdown(report: dict, path: str):
    s = report["summary"]
    n_violations = s["joint_limit_corrections"]
    output_line = (f"**Output:** `{report['output_usd']}`  " if report["output_usd"]
                   else "**Mode:** Dry run — input USD not modified  ")
    status_badge = "🔴 VIOLATIONS FOUND" if n_violations else "✅ PASS"

    lines = [
        "# USD Physics Compliance Report",
        f"",
        f"**Status:** {status_badge}  ",
        f"**Generated:** {report['timestamp']}  ",
        f"**Input:** `{report['input_usd']}`  ",
        output_line,
        f"",
        "## Summary",
        f"",
        f"| | |",
        f"|---|---|",
        f"| Geometry prims processed | {s['geometry_prims_processed']} |",
        f"| Joint prims processed | {s['joint_prims_processed']} |",
        f"| Joint violations detected | {'🔴 ' if n_violations else '✅ '}{n_violations} |",
        f"",
    ]
    if s["global_notes"]:
        lines += [f"> **Model notes:** {s['global_notes']}", ""]

    _conf_badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}

    if report["geometry_findings"]:
        lines += [
            "## Geometry Physics Properties",
            "",
            "| Prim | Material | Confidence | Mass (kg) | Static μ | Dynamic μ | Restitution | Collision |",
            "|------|----------|------------|-----------|----------|-----------|-------------|-----------|",
        ]
        for g in report["geometry_findings"]:
            badge = _conf_badge.get(g.get("confidence", "medium"), "🟡")
            lines.append(
                f"| `{g['prim_path']}` | {g['material_type']} | {badge} {g.get('confidence','medium')} "
                f"| {g['mass_kg']:.2f} "
                f"| {g['static_friction']:.2f} | {g['dynamic_friction']:.2f} "
                f"| {g['restitution']:.2f} | {g['collision_approximation']} |"
            )
        lines.append("")

    if report["joint_findings"]:
        lines += [
            "## Joint Limit Assessment",
            "",
            "| Joint | Status | Original lower | Original upper | Suggested lower | Suggested upper | Reason |",
            "|-------|--------|---------------|----------------|-----------------|-----------------|--------|",
        ]
        for j in report["joint_findings"]:
            if j["joint_valid"]:
                status = "✅ valid"
                orig_lo = orig_hi = sug_lo = sug_hi = str(j["lower_limit_deg"])
                orig_hi = str(j["upper_limit_deg"])
                sug_lo = sug_hi = "—"
            else:
                status = "🔴 violation"
                orig = next(
                    (sg for sg in report.get("scene_graph_joints", [])
                     if sg["path"] == j["prim_path"]), None
                )
                orig_lo = str(orig["lower_limit"]) if orig else "?"
                orig_hi = str(orig["upper_limit"]) if orig else "?"
                sug_lo = str(j["lower_limit_deg"])
                sug_hi = str(j["upper_limit_deg"])
            lines.append(
                f"| `{j['prim_path']}` | {status} | {orig_lo} | {orig_hi} "
                f"| {sug_lo} | {sug_hi} | {j['reasoning']} |"
            )
        lines.append("")

    lines += [
        "## Model Reasoning (Chain of Thought)",
        "",
        "```",
        report["chain_of_thought"][:8000],
        "```",
        "",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
