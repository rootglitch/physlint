#!/usr/bin/env python3
"""
benchmark.py — evaluate PhysInt on 3 scenes with known ground truth.

Metrics:
  Joint violation detection  — precision, recall, accuracy (binary classification)
  Mass estimation            — MAPE vs analytical ground truth per prim

Usage:
  conda run -n physint python benchmark.py
  conda run -n physint python benchmark.py --no-cache        # re-render even if renders exist
  conda run -n physint python benchmark.py --samples 16      # faster renders for testing
  conda run -n physint python benchmark.py --model nvidia/Cosmos-Reason2-8B

Output:
  benchmark_results.json    — full per-prim results + summary statistics
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
app = typer.Typer(add_completion=False)

REPO_ROOT = Path(__file__).parent
GT_PATH   = REPO_ROOT / "assets" / "benchmark_gt.json"


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

def _eval_joints(
    gt_joints: list[dict],
    pred_joints: list[dict],
) -> dict:
    """
    Compare model joint predictions against ground truth.
    gt_joints:   [{"path": ..., "violated": bool}, ...]
    pred_joints: PhysicsAnalysis.joint_prims serialised as dicts

    Returns counts and metrics.
    """
    # Index predictions by prim_path
    pred_by_path = {j["prim_path"]: j for j in pred_joints}

    tp = tn = fp = fn = missed = 0
    per_joint = []

    for gt in gt_joints:
        path = gt["path"]
        gt_violated = gt["violated"]

        if path not in pred_by_path:
            missed += 1
            fn += int(gt_violated)
            per_joint.append({
                "path": path, "gt_violated": gt_violated,
                "pred_violated": None, "outcome": "MISSED",
            })
            continue

        pred = pred_by_path[path]
        # joint_valid=True means model thinks it's OK → not violated
        pred_violated = not pred["joint_valid"]

        if gt_violated and pred_violated:
            outcome = "TP"
            tp += 1
        elif not gt_violated and not pred_violated:
            outcome = "TN"
            tn += 1
        elif not gt_violated and pred_violated:
            outcome = "FP"
            fp += 1
        else:  # gt_violated and not pred_violated
            outcome = "FN"
            fn += 1

        per_joint.append({
            "path": path,
            "gt_lower": gt["lower"], "gt_upper": gt["upper"],
            "gt_violated": gt_violated,
            "pred_violated": pred_violated,
            "pred_lower": pred.get("lower_limit_deg"),
            "pred_upper": pred.get("upper_limit_deg"),
            "confidence": pred.get("confidence"),
            "reasoning": pred.get("reasoning", "")[:120],
            "outcome": outcome,
        })

    total = tp + tn + fp + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall    = tp / (tp + fn) if (tp + fn) > 0 else None
    accuracy  = (tp + tn) / total if total > 0 else None

    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn, "missed": missed,
        "total": total,
        "precision": round(precision, 3) if precision is not None else None,
        "recall":    round(recall,    3) if recall    is not None else None,
        "accuracy":  round(accuracy,  3) if accuracy  is not None else None,
        "per_joint": per_joint,
    }


def _eval_masses(
    gt_masses: list[dict],
    pred_geoms: list[dict],
) -> dict:
    """
    Compare model mass predictions against analytical ground truth.
    Returns per-prim APE and overall MAPE.
    """
    pred_by_path = {g["prim_path"]: g for g in pred_geoms}

    per_prim = []
    ape_values = []

    for gt in gt_masses:
        path = gt["path"]
        gt_mass = gt["mass_kg"]

        if path not in pred_by_path:
            per_prim.append({
                "path": path, "gt_mass_kg": gt_mass,
                "pred_mass_kg": None, "ape_pct": None,
                "gt_material": gt["material"],
                "pred_material": None,
                "outcome": "MISSED",
            })
            continue

        pred = pred_by_path[path]
        pred_mass = pred["mass_kg"]
        ape = abs(pred_mass - gt_mass) / gt_mass * 100.0

        per_prim.append({
            "path": path,
            "gt_mass_kg":   round(gt_mass,  3),
            "pred_mass_kg": round(pred_mass, 3),
            "ape_pct":      round(ape, 1),
            "gt_material":   gt["material"],
            "pred_material": pred.get("material_type"),
            "confidence":    pred.get("confidence"),
            "reasoning":     pred.get("reasoning", "")[:100],
        })
        ape_values.append(ape)

    mape = sum(ape_values) / len(ape_values) if ape_values else None

    sorted_by_ape = sorted([p for p in per_prim if p["ape_pct"] is not None],
                           key=lambda x: x["ape_pct"])
    best  = sorted_by_ape[0]  if sorted_by_ape else None
    worst = sorted_by_ape[-1] if sorted_by_ape else None

    return {
        "mape_pct":    round(mape, 1) if mape is not None else None,
        "n_prims":     len(ape_values),
        "n_missed":    sum(1 for p in per_prim if p["ape_pct"] is None),
        "best_prim":   best["path"].split("/")[-1]  if best  else None,
        "best_ape":    best["ape_pct"]              if best  else None,
        "worst_prim":  worst["path"].split("/")[-1] if worst else None,
        "worst_ape":   worst["ape_pct"]             if worst else None,
        "per_prim":    per_prim,
    }


# ---------------------------------------------------------------------------
# Rich display helpers
# ---------------------------------------------------------------------------

def _print_joint_table(scene_name: str, joint_metrics: dict):
    t = Table(title=f"Joints — {scene_name}", show_header=True, header_style="bold")
    t.add_column("Joint",         style="cyan",  no_wrap=True)
    t.add_column("GT limits",     justify="right")
    t.add_column("GT violated",   justify="center")
    t.add_column("Pred violated", justify="center")
    t.add_column("Outcome",       justify="center")
    t.add_column("Confidence",    justify="center")

    _outcome_style = {"TP": "green", "TN": "green", "FP": "red", "FN": "red", "MISSED": "yellow"}

    for j in joint_metrics["per_joint"]:
        name    = j["path"].split("/")[-1]
        limits  = f"{j['gt_lower']}°..{j['gt_upper']}°" if "gt_lower" in j else "?"
        gt_v    = "🔴 YES" if j["gt_violated"] else "✅ NO"
        pred_v  = ("🔴 YES" if j["pred_violated"] else "✅ NO") if j["pred_violated"] is not None else "[dim]—[/dim]"
        out     = j["outcome"]
        conf    = j.get("confidence", "—") or "—"
        style   = _outcome_style.get(out, "white")
        t.add_row(name, limits, gt_v, pred_v,
                  f"[{style}]{out}[/{style}]", conf)
    console.print(t)


def _print_mass_table(scene_name: str, mass_metrics: dict):
    t = Table(title=f"Masses — {scene_name}", show_header=True, header_style="bold")
    t.add_column("Prim",        style="cyan", no_wrap=True)
    t.add_column("GT material", justify="left")
    t.add_column("Pred material")
    t.add_column("GT mass kg",   justify="right")
    t.add_column("Pred mass kg", justify="right")
    t.add_column("APE %",        justify="right")

    for p in mass_metrics["per_prim"]:
        name = p["path"].split("/")[-1]
        ape  = p["ape_pct"]
        ape_s = (
            f"[green]{ape:.1f}[/green]"  if ape is not None and ape < 20 else
            f"[yellow]{ape:.1f}[/yellow]" if ape is not None and ape < 50 else
            f"[red]{ape:.1f}[/red]"      if ape is not None else "[dim]—[/dim]"
        )
        mat_match = (
            "" if p["pred_material"] is None else
            " ✓" if p["pred_material"].lower() in (p["gt_material"] or "").lower()
                 or (p["gt_material"] or "").lower() in (p["pred_material"] or "").lower()
            else " ✗"
        )
        t.add_row(
            name,
            p["gt_material"] or "—",
            (p["pred_material"] or "—") + mat_match,
            f"{p['gt_mass_kg']:.3f}"  if p["gt_mass_kg"]   is not None else "—",
            f"{p['pred_mass_kg']:.3f}" if p["pred_mass_kg"] is not None else "—",
            ape_s,
        )
    console.print(t)


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

@app.command()
def run(
    gt_path:    Path = typer.Option(GT_PATH, "--gt",      help="Path to benchmark_gt.json"),
    model_id:   str  = typer.Option("nvidia/Cosmos-Reason2-8B", "--model"),
    blender:    str  = typer.Option("blender", "--blender"),
    samples:    int  = typer.Option(32,  "--samples", help="Blender render samples"),
    res:        int  = typer.Option(768, "--res",     help="Render resolution"),
    no_cache:   bool = typer.Option(False, "--no-cache",   help="Re-render even if renders exist"),
    quantize:   bool = typer.Option(False, "--quantize",   help="Load model in 4-bit NF4 (~4 GB VRAM). Required on GPUs with <16 GB."),
    output:     Path = typer.Option(REPO_ROOT / "benchmark_results.json", "--output"),
    scene:      str  = typer.Option(None,  "--scene",      help="Run only this scene (by name). Omit to run all."),
):
    """
    Run PhysInt on all benchmark scenes and report accuracy metrics.
    """
    if not gt_path.exists():
        console.print(f"[red]GT manifest not found: {gt_path}[/red]")
        console.print("Run first:  conda run -n physint python assets/create_bench_scenes.py")
        raise typer.Exit(1)

    gt = json.loads(gt_path.read_text())

    if scene:
        gt["scenes"] = [s for s in gt["scenes"] if s["name"] == scene]
        if not gt["scenes"]:
            console.print(f"[red]Scene '{scene}' not found in GT manifest.[/red]")
            raise typer.Exit(1)

    # Lazy imports — keep startup fast
    from src.usd_parser   import parse_usd
    from src.renderer     import render_usd_views
    from src.cosmos_client import analyze_scene

    quant_label = "4-bit NF4" if quantize else "bfloat16"
    console.print(Panel.fit(
        f"[bold cyan]PhysInt Benchmark[/bold cyan]\n"
        f"Model  : {model_id} ({quant_label})\n"
        f"Scenes : {len(gt['scenes'])}\n"
        f"Joints : {sum(len(s['joints']) for s in gt['scenes'])} "
        f"({sum(sum(1 for j in s['joints'] if j['violated']) for s in gt['scenes'])} violated)\n"
        f"Masses : {sum(len(s['masses']) for s in gt['scenes'])} prims",
        border_style="cyan",
    ))

    scene_results = []

    all_joint_tp = all_joint_tn = all_joint_fp = all_joint_fn = 0
    all_ape: list[float] = []

    for idx, scene in enumerate(gt["scenes"]):
        console.rule(f"[bold]Scene {idx+1}/{len(gt['scenes'])} — {scene['name']}[/bold]")

        usd_path    = REPO_ROOT / scene["usd"]
        render_dir  = REPO_ROOT / "benchmark_renders" / scene["name"]
        render_dir.mkdir(parents=True, exist_ok=True)

        # ── Render ──────────────────────────────────────────────────────
        render_paths = [str(render_dir / f"{v}.png") for v in ("top", "front", "side", "isometric")]
        renders_exist = all(Path(p).exists() for p in render_paths)

        if renders_exist and not no_cache:
            console.print(f"  [dim]Using cached renders in {render_dir}[/dim]")
        else:
            console.print(f"  Rendering with Blender ({samples} samples, {res}px)...")
            t0 = time.time()
            render_paths = render_usd_views(
                str(usd_path), str(render_dir),
                blender_exe=blender, samples=samples, res=res,
            )
            console.print(f"  Rendered in [bold]{time.time()-t0:.0f}s[/bold]")

        # ── Parse + Infer ────────────────────────────────────────────────
        sg = parse_usd(str(usd_path))
        console.print(f"  Parsed: {len(sg.geom_prims)} geom prims, {len(sg.joint_prims)} joint prims")

        console.print(f"  Running Cosmos inference...")
        t0 = time.time()
        analysis, cot = analyze_scene(render_paths, sg.to_dict(), model_id=model_id,
                                      quantize=quantize)
        elapsed = time.time() - t0
        console.print(f"  Inference done in [bold]{elapsed:.0f}s[/bold]")

        # ── Evaluate ─────────────────────────────────────────────────────
        pred_joints = [j.model_dump() for j in analysis.joint_prims]
        pred_geoms  = [g.model_dump() for g in analysis.geom_prims]

        joint_metrics = _eval_joints(scene["joints"], pred_joints)
        mass_metrics  = _eval_masses(scene["masses"],  pred_geoms)

        if scene["joints"]:
            _print_joint_table(scene["name"], joint_metrics)
        _print_mass_table(scene["name"], mass_metrics)

        # Accumulate totals
        all_joint_tp += joint_metrics["tp"]
        all_joint_tn += joint_metrics["tn"]
        all_joint_fp += joint_metrics["fp"]
        all_joint_fn += joint_metrics["fn"]
        all_ape.extend(
            p["ape_pct"] for p in mass_metrics["per_prim"]
            if p["ape_pct"] is not None
        )

        scene_results.append({
            "name": scene["name"],
            "joint_metrics": joint_metrics,
            "mass_metrics":  mass_metrics,
            "chain_of_thought": cot,
        })

    # ── Aggregate summary ────────────────────────────────────────────────────
    total_j    = all_joint_tp + all_joint_tn + all_joint_fp + all_joint_fn
    precision  = all_joint_tp / (all_joint_tp + all_joint_fp) if (all_joint_tp + all_joint_fp) > 0 else None
    recall     = all_joint_tp / (all_joint_tp + all_joint_fn) if (all_joint_tp + all_joint_fn) > 0 else None
    accuracy   = (all_joint_tp + all_joint_tn) / total_j if total_j > 0 else None
    overall_mape = sum(all_ape) / len(all_ape) if all_ape else None

    summary = {
        "model": model_id,
        "joint_detection": {
            "tp": all_joint_tp, "tn": all_joint_tn,
            "fp": all_joint_fp, "fn": all_joint_fn,
            "precision": round(precision, 3) if precision is not None else None,
            "recall":    round(recall,    3) if recall    is not None else None,
            "accuracy":  round(accuracy,  3) if accuracy  is not None else None,
        },
        "mass_estimation": {
            "mape_pct":  round(overall_mape, 1) if overall_mape is not None else None,
            "n_prims":   len(all_ape),
        },
    }

    # Print summary panel
    _pct = lambda v: f"{v*100:.0f}%" if v is not None else "N/A"
    jd = summary["joint_detection"]
    me = summary["mass_estimation"]

    console.print(Panel.fit(
        f"[bold green]=== BENCHMARK RESULTS ===[/bold green]\n\n"
        f"[bold]Joint violation detection[/bold]  ({total_j} joints total)\n"
        f"  Precision : {_pct(jd['precision'])}   ({jd['tp']} TP / {jd['tp']+jd['fp']} predicted violated)\n"
        f"  Recall    : {_pct(jd['recall'])}   ({jd['tp']} TP / {jd['tp']+jd['fn']} actual violations)\n"
        f"  Accuracy  : {_pct(jd['accuracy'])}   ({jd['tp']+jd['tn']}/{total_j} correct)\n"
        f"  False +ve : {jd['fp']}   False -ve : {jd['fn']}\n\n"
        f"[bold]Mass estimation MAPE[/bold]  ({me['n_prims']} prims)\n"
        f"  Overall MAPE : {me['mape_pct']}%\n",
        border_style="green",
    ))

    # Save results
    results = {
        "summary": summary,
        "scenes":  scene_results,
    }
    output.write_text(json.dumps(results, indent=2))
    console.print(f"Results saved to [bold]{output}[/bold]")

    # Always exit 0 — FP/FN are reported in results, not used as pass/fail gate
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
