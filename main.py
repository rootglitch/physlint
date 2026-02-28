#!/usr/bin/env python3
"""
USD Physics Linter — powered by Cosmos Reason 2

Audits a USD scene for physics issues (bad joint limits, missing properties,
implausible masses) and optionally writes corrected properties back.

Usage:
  # Audit only — no files modified
  conda run -n physint python main.py run assets/demo_gripper.usda --dry-run

  # Audit + write corrected USD
  conda run -n physint python main.py run assets/demo_gripper.usda --output corrected.usda
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

app = typer.Typer(name="physint", help="USD Physics Linter — audit USD scenes with Cosmos Reason 2")
console = Console()


@app.command()
def run(
    input_usd: Path = typer.Argument(..., help="Input USD file (.usda or .usd)"),
    output_usd: Optional[Path] = typer.Option(None, "--output", "-o", help="Output USD path (omit to use <stem>_physics.usda)"),
    report_dir: Optional[Path] = typer.Option(None, "--report-dir", help="Directory for report files"),
    render_dir: Optional[Path] = typer.Option(None, "--render-dir", help="Directory for render images"),
    model_id: str = typer.Option("nvidia/Cosmos-Reason2-8B", "--model", help="HuggingFace model ID"),
    blender: str = typer.Option("blender", "--blender", help="Blender executable path"),
    samples: int = typer.Option(32, "--samples", help="Blender Cycles render samples"),
    res: int = typer.Option(768, "--res", help="Render resolution"),
    engine: str = typer.Option("CYCLES", "--engine", help="Blender render engine (CYCLES works headlessly on WSL2)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Audit only — report issues but do NOT write physics to USD"),
    parse_only: bool = typer.Option(False, "--parse-only", help="Only parse USD, skip rendering & inference"),
    quantize: bool = typer.Option(False, "--quantize", help="Load model in 4-bit NF4 (requires bitsandbytes). Reduces VRAM from ~16 GB to ~4 GB."),
):
    """Audit a USD scene for physics issues and optionally write corrected properties back.

    By default (no --dry-run) the corrected USD is written alongside the report.
    Use --dry-run to inspect results before committing any changes.
    """
    input_usd = Path(input_usd).resolve()
    if not input_usd.exists():
        console.print(f"[red]Error: Input file not found: {input_usd}[/red]")
        raise typer.Exit(1)

    stem = input_usd.stem
    parent = input_usd.parent

    output_usd = Path(output_usd) if output_usd else parent / f"{stem}_physics.usda"
    render_dir = Path(render_dir) if render_dir else parent / f"{stem}_renders"
    report_dir = Path(report_dir) if report_dir else parent / f"{stem}_report"
    report_dir.mkdir(parents=True, exist_ok=True)

    mode_label = "[yellow]DRY RUN — audit only, no USD written[/yellow]" if dry_run else f"Output: {output_usd}"
    console.print(Panel.fit(
        f"[bold cyan]USD Physics Linter[/bold cyan]\n"
        f"Input:  {input_usd}\n"
        f"{mode_label}\n"
        f"Model:  {model_id}",
        border_style="cyan",
    ))

    # Step 1: Parse USD
    console.rule("[bold]Step 1 / 4 — Parse USD Scene Graph[/bold]")
    from src.usd_parser import parse_usd
    scene_graph = parse_usd(str(input_usd))
    console.print(f"  Found [bold]{len(scene_graph.geom_prims)}[/bold] geometry prims, "
                  f"[bold]{len(scene_graph.joint_prims)}[/bold] joint prims")

    for gp in scene_graph.geom_prims:
        sz = gp.bbox.size if gp.bbox else [0, 0, 0]
        console.print(f"    [dim]Geom[/dim]  {gp.path}  [dim]({gp.type_name}, "
                      f"size={sz[0]:.2f}×{sz[1]:.2f}×{sz[2]:.2f})[/dim]")
    for jp in scene_graph.joint_prims:
        console.print(f"    [dim]Joint[/dim] {jp.path}  [dim]({jp.type_name}, "
                      f"limits={jp.lower_limit}°..{jp.upper_limit}°)[/dim]")

    if parse_only:
        console.print("\n[yellow]--parse-only: stopping here.[/yellow]")
        console.print(scene_graph.to_json())
        raise typer.Exit(0)

    # Step 2: Render
    console.rule("[bold]Step 2 / 4 — Render 4 Views via Blender[/bold]")
    from src.renderer import render_usd_views
    render_paths = render_usd_views(
        str(input_usd), str(render_dir),
        blender_exe=blender, samples=samples, res=res, engine=engine,
    )
    console.print(f"  Renders saved to [bold]{render_dir}[/bold]")

    # Step 3: Cosmos Reason 2 inference
    console.rule("[bold]Step 3 / 4 — Cosmos Reason 2 Physics Analysis[/bold]")
    from src.cosmos_client import analyze_scene
    scene_dict = scene_graph.to_dict()
    analysis, chain_of_thought = analyze_scene(
        render_paths, scene_dict, model_id=model_id, quantize=quantize
    )
    console.print(f"  Analyzed [bold]{len(analysis.geom_prims)}[/bold] geometry prims, "
                  f"[bold]{len(analysis.joint_prims)}[/bold] joint prims")

    _conf_style = {"high": "green", "medium": "yellow", "low": "red"}

    # Print summary table
    table = Table(title="Physics Properties", show_header=True)
    table.add_column("Prim", style="cyan", no_wrap=True)
    table.add_column("Material")
    table.add_column("Confidence")
    table.add_column("Mass (kg)", justify="right")
    table.add_column("μ static", justify="right")
    table.add_column("μ dynamic", justify="right")
    table.add_column("e", justify="right")
    table.add_column("Collision")
    for g in analysis.geom_prims:
        short = g.prim_path.split("/")[-1]
        conf = g.confidence
        table.add_row(
            short, g.material_type,
            f"[{_conf_style[conf]}]{conf}[/{_conf_style[conf]}]",
            f"{g.mass_kg:.2f}", f"{g.static_friction:.2f}",
            f"{g.dynamic_friction:.2f}", f"{g.restitution:.2f}",
            g.collision_approximation,
        )
    console.print(table)

    n_violations = sum(1 for j in analysis.joint_prims if not j.joint_valid)
    if analysis.joint_prims:
        jtable = Table(title="Joint Assessment", show_header=True)
        jtable.add_column("Joint", style="cyan")
        jtable.add_column("Original lower °", justify="right")
        jtable.add_column("Original upper °", justify="right")
        jtable.add_column("Suggested lower °", justify="right")
        jtable.add_column("Suggested upper °", justify="right")
        jtable.add_column("Status")
        jtable.add_column("Confidence")
        jtable.add_column("Reason", no_wrap=False)
        for j in analysis.joint_prims:
            if j.joint_valid:
                status = "[green]✓ valid[/green]"
                orig_lo = str(j.lower_limit_deg)
                orig_hi = str(j.upper_limit_deg)
                sug_lo = "-"
                sug_hi = "-"
            else:
                status = "[red]✗ violation[/red]"
                # Pull original limits from scene graph for display
                orig = next((jp for jp in scene_graph.joint_prims
                             if jp.path == j.prim_path), None)
                orig_lo = str(orig.lower_limit) if orig else "?"
                orig_hi = str(orig.upper_limit) if orig else "?"
                sug_lo = str(j.lower_limit_deg)
                sug_hi = str(j.upper_limit_deg)
            conf = j.confidence
            jtable.add_row(
                j.prim_path.split("/")[-1],
                orig_lo, orig_hi, sug_lo, sug_hi,
                status,
                f"[{_conf_style[conf]}]{conf}[/{_conf_style[conf]}]",
                j.reasoning[:70],
            )
        console.print(jtable)

    if n_violations:
        console.print(f"  [red bold]{n_violations} joint violation(s) detected.[/red bold]")
    else:
        console.print("  [green]All joints within valid limits.[/green]")

    # Step 4: Report (always) + write-back (only if not --dry-run)
    console.rule("[bold]Step 4 / 4 — Compliance Report[/bold]")
    from src.report import generate_report, save_report
    report = generate_report(
        scene_graph, analysis, chain_of_thought,
        render_paths, str(input_usd), str(output_usd) if not dry_run else None,
    )
    json_path = str(report_dir / "report.json")
    md_path = str(report_dir / "report.md")
    save_report(report, json_path, md_path)
    console.print(f"  JSON report    : [bold]{json_path}[/bold]")
    console.print(f"  Markdown report: [bold]{md_path}[/bold]")

    if dry_run:
        console.print(Panel.fit(
            f"[bold yellow]Dry run complete — no USD modified.[/bold yellow]\n\n"
            f"[bold]{n_violations}[/bold] joint violation(s) flagged.\n"
            f"Re-run without [bold]--dry-run[/bold] to apply suggested fixes.\n\n"
            f"JSON report    : [bold]{json_path}[/bold]\n"
            f"Markdown report: [bold]{md_path}[/bold]\n"
            f"Renders        : [bold]{render_dir}/[/bold]",
            border_style="yellow",
        ))
        raise typer.Exit(1 if n_violations else 0)

    from src.physics_writer import write_physics
    write_physics(
        str(input_usd), analysis, str(output_usd),
        meters_per_unit=scene_graph.meters_per_unit,
    )

    console.print(Panel.fit(
        f"[bold green]✓ Done![/bold green]\n\n"
        f"Corrected USD  : [bold]{output_usd}[/bold]\n"
        f"JSON report    : [bold]{json_path}[/bold]\n"
        f"Markdown report: [bold]{md_path}[/bold]\n"
        f"Renders        : [bold]{render_dir}/[/bold]",
        border_style="green",
    ))


@app.command()
def create_demo(
    output: Path = typer.Argument(Path("assets/demo_gripper.usda"), help="Where to write the demo USD"),
):
    """Create the demo USD scene (robot gripper + pressure vessel + rubber pad)."""
    from assets.create_demo import create_demo_usd
    create_demo_usd(str(output))
    console.print(f"[green]Demo USD created:[/green] {output}")


if __name__ == "__main__":
    app()
