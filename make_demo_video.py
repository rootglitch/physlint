#!/usr/bin/env python3
"""
make_demo_video.py — USD Physics Linter demo video for Luma submission.

Output : demo_video.mp4  (1920×1080, 30 fps, ~65 s)
Run    : conda run -n physlint python make_demo_video.py
"""
from __future__ import annotations
import json, math, os, shutil, subprocess, sys, tempfile, textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ── Layout ────────────────────────────────────────────────────────────────────
W, H  = 1920, 1080
FPS   = 30
REPO  = Path(__file__).parent

# ── Palette (GitHub dark + NVIDIA green) ──────────────────────────────────────
BG      = ( 13,  17,  23)   # #0d1117  background
BG2     = ( 22,  27,  34)   # #161b22  card
BG3     = ( 33,  38,  45)   # #21262d  table alt row
ACCENT  = (118, 185,   0)   # #76b900  NVIDIA green
BLUE    = ( 88, 166, 255)   # #58a6ff
RED     = (248,  81,  73)   # #f85149
GREEN   = ( 63, 185,  80)   # #3fb950
YELLOW  = (210, 153,  34)   # #d29922
TEXT    = (230, 237, 243)   # primary text
TEXT2   = (139, 148, 158)   # secondary text

SANS      = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO      = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

def fnt(size, bold=False):  return ImageFont.truetype(SANS_BOLD if bold else SANS, size)
def mfnt(size):             return ImageFont.truetype(MONO, size)


# ── Drawing helpers ───────────────────────────────────────────────────────────

def new_frame(bg=BG):
    img = Image.new("RGB", (W, H), bg)
    return img, ImageDraw.Draw(img)


def center_text(draw, y, text, font, color=TEXT, wrap=None):
    if wrap:
        lines = textwrap.wrap(text, wrap)
    else:
        lines = [text]
    line_h = font.getbbox("Ag")[3] + 6
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y + i * line_h), line, font=font, fill=color)
    return y + len(lines) * line_h


def left_text(draw, x, y, text, font, color=TEXT):
    draw.text((x, y), text, font=font, fill=color)
    bbox = draw.textbbox((0, 0), text, font=font)
    return y + (bbox[3] - bbox[1]) + 8


def accent_bar(draw, y=0, thickness=4):
    draw.rectangle([0, y, W, y + thickness], fill=ACCENT)


def section_header(draw, title, y=80):
    f = fnt(52, bold=True)
    draw.text((100, y), title, font=f, fill=ACCENT)
    draw.rectangle([100, y + 66, W - 100, y + 69], fill=BG3)
    return y + 90


def progress_bar(draw, x, y, w, h, pct, color=ACCENT, bg=BG3):
    draw.rectangle([x, y, x + w, y + h], fill=bg)
    draw.rectangle([x, y, x + int(w * pct), y + h], fill=color)


def rounded_box(draw, x1, y1, x2, y2, color=BG2, border=None, r=8):
    draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=color,
                           outline=border, width=2 if border else 0)


def fade(img, alpha):
    """Multiply image brightness by alpha (0=black, 1=full)."""
    if alpha >= 1.0:
        return img
    arr = np.array(img, dtype=float)
    arr = np.clip(arr * alpha, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def crossfade(a: Image.Image, b: Image.Image, t: float) -> Image.Image:
    arr_a = np.array(a, dtype=float)
    arr_b = np.array(b, dtype=float)
    return Image.fromarray(np.clip(arr_a * (1 - t) + arr_b * t, 0, 255).astype(np.uint8))


def ease(t):
    """Smooth step."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# ── Scene functions ───────────────────────────────────────────────────────────

def scene_title(t):
    img, draw = new_frame()
    alpha = ease(min(t * 3, 1.0))

    accent_bar(draw, y=0)
    accent_bar(draw, y=H - 4)

    y = 300
    y = center_text(draw, y, "USD Physics Linter", fnt(96, bold=True), TEXT)
    y += 30
    y = center_text(draw, y, "Audit USD scenes for physics issues before they break your sim",
                    fnt(36), TEXT2, wrap=60)
    y += 50
    center_text(draw, y, "Powered by NVIDIA Cosmos Reason 2", fnt(30), ACCENT)

    center_text(draw, H - 80, "github.com/rootglitch/physlint", fnt(26), TEXT2)

    return fade(img, alpha)


def scene_problem(t):
    img, draw = new_frame()
    accent_bar(draw)

    y = section_header(draw, "The Problem")
    y += 20

    bullets = [
        (RED,   "Joint limits set to impossible values"),
        (RED,   "e.g. a human elbow at 220° — anatomically impossible"),
        (RED,   "Mass properties missing or copied from the wrong object"),
        (RED,   "No collision geometry — simulator picks arbitrary defaults"),
        (RED,   "Friction values causing jitter or tunneling at runtime"),
    ]
    indents = [0, 40, 0, 0, 0]

    f_main = fnt(36)
    f_sub  = fnt(30)
    for i, ((color, text), indent) in enumerate(zip(bullets, indents)):
        show = ease(min((t - i * 0.15) * 5, 1.0))
        if show <= 0:
            continue
        f = f_sub if indent else f_main
        c = TEXT2 if indent else TEXT
        bullet = "  " if indent else "●  "
        a = int(255 * show)
        rgba = c + (a,)
        draw.text((100 + indent, y), bullet + text, font=f, fill=c)
        y += (50 if not indent else 42)

    # Bottom quote
    if t > 0.8:
        alpha2 = ease((t - 0.8) * 5)
        draw.text((100, H - 130),
                  '"Invisible until the sim explodes. No physics lint equivalent exists."',
                  font=fnt(32, bold=True), fill=YELLOW)

    return img


def scene_pipeline(t):
    img, draw = new_frame()
    accent_bar(draw)
    section_header(draw, "How It Works")

    steps = [
        ("Parse",   "pxr.Usd",        "Extract scene graph\ngeometry + joints"),
        ("Render",  "Blender Cycles",  "4 camera views\nheadless, no display"),
        ("Infer",   "Cosmos Reason 2", "Visual reasoning\nchain-of-thought"),
        ("Report",  "Markdown + JSON", "Violations flagged\noptional USD write-back"),
    ]

    box_w, box_h = 340, 200
    total_w = len(steps) * box_w + (len(steps) - 1) * 60
    x0 = (W - total_w) // 2
    y0 = 320

    for i, (title, sub, desc) in enumerate(steps):
        show = ease(min((t - i * 0.18) * 4, 1.0))
        if show <= 0:
            continue
        x = x0 + i * (box_w + 60)
        bx1, by1, bx2, by2 = x, y0, x + box_w, y0 + box_h
        col = tuple(int(c * show + BG[j] * (1 - show)) for j, c in enumerate(BG2))
        rounded_box(draw, bx1, by1, bx2, by2, color=col, border=ACCENT if show > 0.5 else BG3)

        cx = x + box_w // 2
        draw.text((cx - draw.textlength(title, fnt(40, bold=True)) // 2, y0 + 20),
                  title, font=fnt(40, bold=True), fill=ACCENT)
        draw.text((cx - draw.textlength(sub, fnt(24)) // 2, y0 + 72),
                  sub, font=fnt(24), fill=TEXT2)
        for j, line in enumerate(desc.split("\n")):
            lw = draw.textlength(line, fnt(26))
            draw.text((cx - lw // 2, y0 + 120 + j * 36), line, font=fnt(26), fill=TEXT)

        # Arrow
        if i < len(steps) - 1 and show > 0.7:
            ax = bx2 + 10
            ay = y0 + box_h // 2
            draw.line([(ax, ay), (ax + 50, ay)], fill=ACCENT, width=3)
            draw.polygon([(ax + 50, ay - 10), (ax + 60, ay), (ax + 50, ay + 10)], fill=ACCENT)

    # Step numbers
    center_text(draw, 580, "Four steps — fully automated, no configuration required", fnt(30), TEXT2)
    return img


def scene_renders(t, renders):
    img, draw = new_frame()
    accent_bar(draw)

    labels = ["Top", "Front", "Side", "Isometric"]

    if t < 0.65:
        # Sequential: each view visible for ~2s
        idx = min(int(t / 0.65 * 4), 3)
        show_t = (t / 0.65 * 4) - idx

        label = f"demo_fr3.usda   →   Step 2/4: Render — {labels[idx]} view"
        center_text(draw, 40, label, fnt(30), TEXT2)

        r = renders[idx]
        rw, rh = r.size
        scale = min((W - 200) / rw, (H - 180) / rh)
        nw, nh = int(rw * scale), int(rh * scale)
        rx, ry = (W - nw) // 2, (H - nh) // 2 + 30

        alpha = ease(show_t * 3)
        thumb = r.resize((nw, nh), Image.LANCZOS)
        thumb = fade(thumb, alpha)
        img.paste(thumb, (rx, ry))

        draw.text((rx, ry + nh + 10), labels[idx], font=fnt(28, bold=True), fill=ACCENT)
    else:
        # 2×2 grid
        grid_t = ease((t - 0.65) / 0.35)
        center_text(draw, 20, "demo_fr3.usda   →   4 camera views", fnt(30), TEXT2)

        pad = 30
        cell_w = (W - 3 * pad) // 2
        cell_h = (H - 130 - 3 * pad) // 2
        positions = [(pad, 100), (pad * 2 + cell_w, 100),
                     (pad, 100 + pad + cell_h), (pad * 2 + cell_w, 100 + pad + cell_h)]

        for i, ((px, py), label) in enumerate(zip(positions, labels)):
            r = renders[i]
            thumb = r.resize((cell_w, cell_h), Image.LANCZOS)
            thumb = fade(thumb, grid_t)
            img.paste(thumb, (px, py))
            draw.text((px + 8, py + 8), label, font=fnt(26, bold=True), fill=ACCENT)

    return img


def scene_reasoning(t):
    img, draw = new_frame()
    accent_bar(draw)
    y = section_header(draw, "Cosmos Reason 2 — Chain of Thought")

    excerpt = [
        'Prim /fr3/fr3_link0:',
        '  "Smooth silver-grey cylindrical base with machined finish — cast aluminium.',
        '   bbox [0.10, 0.10, 0.08] m, fill_factor=0.785 (cylinder).',
        '   volume = 0.10 × 0.10 × 0.08 × 0.785 = 6.28e-4 m³,',
        '   density 2700 kg/m³, estimated mass ≈ 1.70 kg. Confidence: high."',
        '',
        'Prim /fr3/fr3_link3:',
        '  "Elbow link — compact aluminium casting, anodised grey. bbox [0.08, 0.08, 0.12] m.',
        '   volume = 0.08 × 0.08 × 0.12 × 0.785 = 6.03e-4 m³, mass ≈ 1.63 kg."',
        '',
        'Joint /fr3/.../fr3_joint2:',
        '  "lower=-102.2°, upper=220.0°.',
        '   Upper limit of 220° exceeds 180° industrial joint constraint.',
        '   VIOLATED — cannot physically reach without self-collision.',
        '   → VIOLATION detected. Corrected: upper=180.0°"',
    ]

    # Terminal box
    bx1, by1, bx2, by2 = 80, y, W - 80, H - 60
    rounded_box(draw, bx1, by1, bx2, by2, color=BG2, border=BG3)

    # Traffic lights
    for i, col in enumerate([(RED), (YELLOW), (GREEN)]):
        draw.ellipse([bx1 + 16 + i * 24, by1 + 12, bx1 + 32 + i * 24, by1 + 28], fill=col)
    draw.text((bx1 + 92, by1 + 10), "cosmos_reason2_inference.log", font=mfnt(20), fill=TEXT2)

    # Sequential per-line typing: line i types out during t in [i/n, (i+1)/n]
    line_h = 32
    visible_lines = (by2 - by1 - 50) // line_h
    n_lines = len(excerpt)

    # Which line is currently being typed
    active = min(int(t * n_lines), n_lines - 1)
    line_t = (t * n_lines) - int(t * n_lines)  # progress within the active line [0,1]
    if t >= 1.0:
        active, line_t = n_lines - 1, 1.0

    # Scroll window: keep active line visible near the bottom
    start = max(0, active - visible_lines + 3)

    for i in range(n_lines):
        disp_i = i - start
        if disp_i < 0 or disp_i >= visible_lines:
            continue
        line = excerpt[i]
        ly = by1 + 44 + disp_i * line_h

        if i < active:
            shown = line                              # fully typed
        elif i == active:
            chars = int(ease(line_t) * max(len(line), 1))
            shown = line[:chars]                      # currently typing
        else:
            continue                                  # not yet visible

        color = ACCENT if line.startswith("Joint") or line.startswith("Prim") else (
            RED if "VIOLATED" in line or "VIOLATION" in line or "220°" in line
            else TEXT2 if line.startswith("  ") or line.startswith("   ")
            else TEXT)
        draw.text((bx1 + 20, ly), shown, font=mfnt(22), fill=color)

    return img


def scene_report(t, report_data):
    img, draw = new_frame()
    accent_bar(draw)
    y = section_header(draw, "Compliance Report")

    # Status badge — measure text width, then anchor flush to right margin
    badge_font = fnt(28, bold=True)
    badge_text = "VIOLATION DETECTED"
    badge_w = int(draw.textlength(badge_text, badge_font))
    bx1_b = W - badge_w - 80
    rounded_box(draw, bx1_b, 70, W - 40, 115, color=(80, 20, 20), border=RED)
    draw.text((bx1_b + 20, 78), badge_text, font=badge_font, fill=RED)

    y += 10
    draw.text((100, y), "Joint Limit Assessment", font=fnt(36, bold=True), fill=TEXT)
    y += 48

    # Joint table
    cols = [("Joint", 500), ("Status", 180), ("Original °", 160), ("Suggested °", 160), ("Reason", 580)]
    hx = 100
    rounded_box(draw, hx, y, W - 100, y + 44, color=BG3)
    for col, cw in cols:
        draw.text((hx + 10, y + 8), col, font=fnt(24, bold=True), fill=TEXT2)
        hx += cw

    y += 44
    # Single violated joint row — pick the first violation
    violated_joints = [j for j in report_data["joint_findings"] if not j["joint_valid"]]
    joint = next(
        (j for j in violated_joints if "joint2" in j["prim_path"]),
        violated_joints[0] if violated_joints else report_data["joint_findings"][0],
    )
    orig_label = "220°"   # the injected violation we set in demo_fr3.usda
    sug_label  = f"{int(round(joint.get('upper_limit_deg', 180)))}°"
    row_alpha = ease(t * 2)
    rounded_box(draw, 100, y, W - 100, y + 50, color=(60, 15, 15))
    rx = 100
    row_vals = [
        (joint["prim_path"].split("/")[-1], TEXT),
        ("⚠ corrected", RED),
        (orig_label, RED),
        (sug_label, GREEN),
        (f"Upper {orig_label} violates industrial limit; corrected to {sug_label}", TEXT2),
    ]
    for (val, col), (_, cw) in zip(row_vals, cols):
        draw.text((rx + 10, y + 12), str(val), font=fnt(24), fill=col)
        rx += cw
    y += 70

    # Mass table header
    show_mass = ease((t - 0.35) / 0.4)
    if show_mass <= 0:
        return fade(img, 1.0)

    draw.text((100, y), "Inferred Physics Properties", font=fnt(36, bold=True), fill=TEXT)
    y += 48

    mass_cols = [("Prim", 380), ("Material", 180), ("Mass (kg)", 150), ("Static μ", 130), ("Restitution", 150)]
    hx = 100
    rounded_box(draw, hx, y, W - 100, y + 44, color=BG3)
    for col, cw in mass_cols:
        draw.text((hx + 10, y + 8), col, font=fnt(24, bold=True), fill=TEXT2)
        hx += cw
    y += 44

    highlight_rows = {"rubber": (40, 60, 20), "concrete": (20, 40, 60)}
    for i, finding in enumerate(report_data["geometry_findings"][:6]):
        alpha_row = ease((show_mass - i * 0.12) * 4)
        if alpha_row <= 0:
            continue
        mat = finding["material_type"]
        bg_col = highlight_rows.get(mat, BG2)
        rounded_box(draw, 100, y, W - 100, y + 44, color=bg_col)
        rx = 100
        row_vals2 = [
            (finding["prim_path"].split("/")[-1], TEXT),
            (mat, ACCENT if mat == "rubber" else TEXT),
            (f"{finding['mass_kg']:.2f}", TEXT),
            (f"{finding['static_friction']:.2f}", TEXT2),
            (f"{finding['restitution']:.2f}", TEXT2),
        ]
        for (val, col), (_, cw) in zip(row_vals2, mass_cols):
            draw.text((rx + 10, y + 10), str(val), font=fnt(24), fill=col)
            rx += cw
        y += 46

    draw.text((100, y + 8), "★  All FR3 links identified as aluminium — smooth silver-grey machined finish, "
              "characteristic anodised surface → density 2700 kg/m³", font=fnt(24), fill=ACCENT)

    return fade(img, show_mass ** 0.3)


def scene_benchmark(t):
    img, draw = new_frame()
    accent_bar(draw)
    y = section_header(draw, "Benchmark — 14 Scenes, Known Ground Truth")

    # Joint detection section
    y += 10
    draw.text((100, y), "Joint Violation Detection  —  53 joints evaluated", font=fnt(36, bold=True), fill=TEXT)
    y += 50

    joint_rows = [
        ("bench_revolute_limits",   "revolute",  4,  2,  2, 0, 0, GREEN),
        ("bench_mixed",             "revolute",  3,  1,  1, 0, 0, GREEN),
        ("bench_all_violated",      "revolute",  6,  6,  6, 0, 0, GREEN),
        ("bench_all_valid",         "revolute",  6,  0,  0, 1, 0, YELLOW),
        ("bench_crane / excavator", "revolute",  8,  4,  4, 0, 0, GREEN),
        ("… + 9 more scenes",       "mixed",    26, 11, 11, 0, 0, GREEN),
    ]
    jcols = [("Scene", 420), ("Type", 130), ("Joints", 90), ("Violated", 120), ("Caught", 110), ("FP", 80), ("FN", 80)]
    hx = 100
    rounded_box(draw, hx, y, W - 100, y + 40, color=BG3)
    for col, cw in jcols:
        draw.text((hx + 8, y + 8), col, font=fnt(22, bold=True), fill=TEXT2)
        hx += cw
    y += 40

    for i, (scene, jtype, joints, violated, caught, fp, fn, hcol) in enumerate(joint_rows):
        alpha_row = ease((t - i * 0.08) * 5)
        if alpha_row <= 0:
            continue
        rounded_box(draw, 100, y, W - 100, y + 38, color=BG2 if i % 2 == 0 else BG3)
        rx = 100
        for val, (_, cw) in zip([scene, jtype, joints, violated, caught, fp, fn], jcols):
            col = hcol if val == caught and isinstance(val, int) else TEXT
            if val == fp and fp > 0:
                col = YELLOW
            draw.text((rx + 8, y + 8), str(val), font=fnt(20), fill=col)
            rx += cw
        y += 38

    # Summary callout
    y += 12
    summary_alpha = ease((t - 0.5) / 0.3)
    if summary_alpha > 0:
        rounded_box(draw, 100, y, W - 100, y + 52, color=(20, 50, 20), border=GREEN)
        draw.text((120, y + 12),
                  "98% accuracy  |  100% recall  |  24/24 violations caught  |  1 FP",
                  font=fnt(28, bold=True), fill=GREEN)
        y += 68

    # Mass section
    mass_alpha = ease((t - 0.65) / 0.25)
    if mass_alpha <= 0:
        return img

    draw.text((100, y), "Mass Estimation  —  68 prims, 14 scenes", font=fnt(34, bold=True), fill=TEXT)
    y += 48

    prims = [
        ("SteelCylinder", "steel",    "steel ✓",    98.65, 98.60, 0.1),
        ("RubberSphere",  "rubber",   "rubber ✓",    2.57,  2.57,  0.0),
        ("ConcreteCube",  "concrete", "concrete ✓",  7.76,  7.76,  0.0),
        ("AlumCylinder",  "aluminum", "aluminium ✓", 4.24,  4.24,  0.0),
        ("SteelFrame",    "steel",    "steel ✓",    15.33, 15.33,  0.0),
    ]
    mcols = [("Prim", 260), ("GT mat", 150), ("Pred mat", 160), ("GT kg", 100), ("Pred kg", 100), ("APE %", 90)]
    hx = 100
    rounded_box(draw, hx, y, 980, y + 36, color=BG3)
    for col, cw in mcols:
        draw.text((hx + 6, y + 7), col, font=fnt(20, bold=True), fill=TEXT2)
        hx += cw
    y += 36

    for i, (name, mat, pred_mat, gt_kg, pred_kg, ape) in enumerate(prims):
        alpha_row = ease((mass_alpha - i * 0.12) * 5)
        if alpha_row <= 0:
            continue
        rounded_box(draw, 100, y, 980, y + 34, color=BG2 if i % 2 == 0 else BG3)
        rx = 100
        ape_col = GREEN if ape < 1 else YELLOW if ape < 5 else RED
        for val, (_, cw) in zip([name, mat, pred_mat, f"{gt_kg:.2f}", f"{pred_kg:.2f}", f"{ape:.1f}%"], mcols):
            col = ape_col if val == f"{ape:.1f}%" else TEXT
            draw.text((rx + 6, y + 7), str(val), font=fnt(20), fill=col)
            rx += cw
        y += 34

    # MAPE callout
    mape_alpha = ease((mass_alpha - 0.6) / 0.3)
    if mape_alpha > 0:
        rounded_box(draw, 1000, 660, W - 100, 840, color=(20, 50, 20), border=GREEN)
        draw.text((1030, 685), "MAPE = 0.1%", font=fnt(56, bold=True), fill=GREEN)
        draw.text((1030, 758), "Mass from USD material bindings", font=fnt(26), fill=TEXT2)
        draw.text((1030, 792), "— deterministic, not visual guessing", font=fnt(26), fill=TEXT2)

    return img


def scene_close(t):
    img, draw = new_frame()
    accent_bar(draw, y=0)
    accent_bar(draw, y=H - 4)

    alpha = ease(t * 2)

    y = 220
    y = center_text(draw, y, "USD Physics Linter", fnt(80, bold=True), TEXT)
    y += 40

    # Install block
    rounded_box(draw, 260, y, W - 260, y + 190, color=BG2, border=BG3)
    cmds = [
        "conda env create -f environment.yml && conda activate physlint",
        "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128",
        "python main.py run your_scene.usda --dry-run",
    ]
    for i, cmd in enumerate(cmds):
        draw.text((290, y + 20 + i * 54), "$ " + cmd, font=mfnt(26), fill=ACCENT)

    y += 210
    center_text(draw, y, "Exit code 1 if violations found — drop-in CI integration", fnt(30), TEXT2)
    y += 60
    center_text(draw, y, "github.com/rootglitch/physlint", fnt(36, bold=True), BLUE)

    return fade(img, alpha)


# ── Assemble ──────────────────────────────────────────────────────────────────

def load_renders():
    rd = REPO / "renders" / "demo_fr3"
    views = []
    for name in ["top", "front", "side", "isometric"]:
        p = rd / f"{name}.png"
        if p.exists():
            views.append(Image.open(p).convert("RGB"))
        else:
            # Placeholder
            ph = Image.new("RGB", (768, 768), BG3)
            d = ImageDraw.Draw(ph)
            d.text((300, 360), name, font=fnt(40), fill=TEXT2)
            views.append(ph)
    return views


def load_report():
    p = REPO / "assets" / "demo_fr3_report" / "report.json"
    return json.loads(p.read_text())


def generate_frames(tmpdir: Path):
    renders     = load_renders()
    report_data = load_report()

    FADE = 12   # cross-fade frames

    # (scene_fn, duration_seconds)
    scenes = [
        (lambda t: scene_title(t),                        7.0),
        (lambda t: scene_problem(t),                     10.0),
        (lambda t: scene_pipeline(t),                     8.0),
        (lambda t: scene_renders(t, renders),            15.0),
        (lambda t: scene_reasoning(t),                   18.0),
        (lambda t: scene_report(t, report_data),         14.0),
        (lambda t: scene_benchmark(t),                   16.0),
        (lambda t: scene_close(t),                        7.0),
    ]

    frame_idx = 0
    prev_last = None

    for scene_idx, (scene_fn, duration) in enumerate(scenes):
        n = int(duration * FPS)
        frames_this_scene = []

        print(f"  Scene {scene_idx + 1}/{len(scenes)} — generating {n} frames...", flush=True)
        for i in range(n):
            t = i / max(n - 1, 1)
            img = scene_fn(t)
            frames_this_scene.append(img)

        # Cross-fade from previous scene
        if prev_last is not None:
            for fi in range(FADE):
                t_fade = fi / FADE
                blended = crossfade(prev_last, frames_this_scene[fi], t_fade)
                blended.save(tmpdir / f"frame_{frame_idx:05d}.png")
                frame_idx += 1
            # Write remaining frames
            for img in frames_this_scene[FADE:]:
                img.save(tmpdir / f"frame_{frame_idx:05d}.png")
                frame_idx += 1
        else:
            for img in frames_this_scene:
                img.save(tmpdir / f"frame_{frame_idx:05d}.png")
                frame_idx += 1

        prev_last = frames_this_scene[-1]

    print(f"  Total frames: {frame_idx}  ({frame_idx / FPS:.1f}s)", flush=True)
    return frame_idx


def encode(tmpdir: Path, output: Path):
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i",  str(tmpdir / "frame_%05d.png"),
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(output),
    ]
    print(f"  Encoding: {' '.join(cmd[:6])} ...", flush=True)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    output = REPO / "demo_video.mp4"
    tmpdir = Path(tempfile.mkdtemp(prefix="physlint_video_"))
    print(f"USD Physics Linter — Demo Video\n  frames → {tmpdir}\n  output → {output}")
    try:
        generate_frames(tmpdir)
        encode(tmpdir, output)
        mb = output.stat().st_size / 1e6
        print(f"\n✓ demo_video.mp4  ({mb:.1f} MB)  {output}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
