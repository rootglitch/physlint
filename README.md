# USD Physics Linter

[![USD Physics Lint](https://github.com/raajg/physint/actions/workflows/physics-lint.yml/badge.svg)](https://github.com/raajg/physint/actions/workflows/physics-lint.yml)

**Audit USD scenes for physics issues before they break your sim** — powered by [NVIDIA Cosmos Reason 2](https://huggingface.co/nvidia/Cosmos-Reason2-8B)

Feed any USD file. Get back a compliance report flagging bad joint limits, missing physics properties, and implausible masses — with visual reasoning from a physical AI model. Optionally write the suggested fixes back to USD.

---

## The problem

USD scenes used in robotics simulation ship with no physics properties, or with properties that were never validated:

- Joint limits set to physically impossible values (e.g. a human elbow at 220°)
- Mass properties missing entirely, or copied from the wrong object
- No collision geometry — the simulator picks arbitrary defaults
- Friction values that cause jitter or tunneling at runtime

These issues are invisible until the sim explodes. There is no `USD physics lint` equivalent to `eslint` or `mypy`.

---

## What this tool does

```
your_scene.usda  →  USD Physics Linter  →  report.md  (violations + suggestions)
                                        →  your_scene_physics.usda  (opt-in)
```

**Default (audit only — safe, non-destructive):**
```bash
python main.py run your_scene.usda --dry-run
```

The input USD is never touched. A compliance report is generated listing every flagged issue with reasoning from Cosmos Reason 2.

**Apply suggested fixes:**
```bash
python main.py run your_scene.usda --output your_scene_physics.usda
```

The tool writes `PhysicsRigidBodyAPI`, `PhysicsCollisionAPI`, `PhysicsMassAPI`, and corrected joint limits back to USD — only when you explicitly ask for it.

---

## How it works

Four steps, fully automated:

1. **Parse** — extracts the scene graph (geometry prims + joint prims) using `pxr.Usd`
2. **Render** — produces 4 camera views (top, front, side, isometric) via Blender Cycles headless
3. **Infer** — sends renders + scene graph JSON to Cosmos Reason 2; the model reasons about materials, masses, and joint validity using chain-of-thought, then emits structured JSON
4. **Report** — saves a Markdown + JSON compliance report with per-prim reasoning; optionally writes physics properties back to USD

---

## Demo

The demo scene (`assets/demo_gripper.usda`) has a stainless-steel pressure vessel, rubber gasket, dark steel support frame, and an orange robot arm with an **intentionally wrong elbow joint limit of 220°** — no physics properties authored anywhere.

### Renders (Blender Cycles, 4 views)

| Top | Front | Side | Isometric |
|-----|-------|------|-----------|
| ![top](renders/demo_test/top.png) | ![front](renders/demo_test/front.png) | ![side](renders/demo_test/side.png) | ![isometric](renders/demo_test/isometric.png) |

### Compliance report output

**Status: 🔴 VIOLATIONS FOUND**

| Joint | Status | Original upper | Suggested upper | Reason |
|-------|--------|---------------|-----------------|--------|
| `/World/RobotArm/ElbowJoint` | 🔴 violation | **220°** | **145°** | Upper limit of 220° is impossible for a human-like elbow joint |

### Inferred physics properties

| Prim | Material | Mass (kg) | Static μ | Dynamic μ | Restitution |
|------|----------|-----------|----------|-----------|-------------|
| `/World/PressureVessel/Body` | steel | 353.25 | 0.45 | 0.35 | 0.30 |
| `/World/PressureVessel/TopCap` | aluminum | 38.20 | 0.45 | 0.35 | 0.30 |
| `/World/PressureVessel/BottomCap` | aluminum | 38.20 | 0.45 | 0.35 | 0.30 |
| `/World/RubberGasket` | **rubber** | 3.30 | **0.70** | **0.60** | **0.05** |
| `/World/SupportFrame/Base` | concrete | 3.86 | 0.55 | 0.45 | 0.10 |
| `/World/SupportFrame/PillarLeft` | steel | 4.41 | 0.45 | 0.35 | 0.30 |
| `/World/SupportFrame/PillarRight` | steel | 4.41 | 0.45 | 0.35 | 0.30 |
| `/World/RobotArm/UpperArm` | aluminum | 1.09 | 0.45 | 0.35 | 0.30 |
| `/World/RobotArm/LowerArm` | aluminum | 1.09 | 0.45 | 0.35 | 0.30 |
| `/World/ValveHandle` | aluminum | 2.70 | 0.45 | 0.35 | 0.30 |

The rubber gasket is correctly identified — zero metallic sheen, near-black matte surface — and gets friction/restitution values appropriate for elastomers rather than metals.

---

## Benchmark

Evaluated on **17 scenes** — 14 programmatic USD scenes spanning diverse robot morphologies and 3 real robot USDs from [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) — using Cosmos Reason 2, 4-bit NF4 quantization.

```
Usage: benchmark.py [OPTIONS]

  Run PhysInt on all benchmark scenes and report accuracy metrics.

Options:
  --gt        PATH     Path to benchmark_gt.json  [default: assets/benchmark_gt.json]
  --model     TEXT     [default: nvidia/Cosmos-Reason2-8B]
  --blender   TEXT     [default: blender]
  --samples   INTEGER  Blender render samples  [default: 32]
  --res       INTEGER  Render resolution  [default: 768]
  --no-cache           Re-render even if renders exist
  --quantize           Load model in 4-bit NF4 (~4 GB VRAM). Required on GPUs with <16 GB.
  --output    PATH     [default: benchmark_results.json]
  --help               Show this message and exit.
```

Run: `conda run -n physint python benchmark.py --quantize`

### Joint violation detection — 80 joints, 100% recall

#### Synthetic scenes (14 scenes, 53 joints)

| Scene | Joints | GT violated | TP | TN | FP | FN |
|-------|--------|-------------|----|----|----|----|
| `bench_revolute_limits` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_mass_materials` | — | — | — | — | — | — |
| `bench_mixed` | 3 | 1 | 1 | 2 | 0 | 0 |
| `bench_prismatic_limits` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_humanoid_arm` | 6 | 2 | 2 | 4 | 0 | 0 |
| `bench_all_valid` | 5 | 0 | 0 | 3 | 2 | 0 |
| `bench_crane` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_symmetric_violation` | 3 | 1 | 1 | 1 | 1 | 0 |
| `bench_scara` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_gripper` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_excavator` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_wrist_3dof` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_linear_gantry` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_all_violated` | 4 | 4 | 4 | 0 | 0 | 0 |
| **Synthetic total** | **53** | **24** | **24** | **26** | **3** | **0** |

**94.3% accuracy, 100% recall on 53 joints across 14 synthetic scenes.** All 24 violated joints caught (zero missed). The 3 false positives are borderline revolute joints where the model over-applies anatomical limits; they vary across runs due to LLM stochasticity.

#### Real robot scenes (3 MuJoCo Menagerie USDs, 27 joints)

| Scene | Type | Joints | GT violated | TP | TN | FP | FN |
|-------|------|--------|-------------|----|----|----|----|
| `menagerie_franka_panda` | real robot | 9 | 0 | 0 | 9 | 0 | 0 |
| `menagerie_ur5e` | real robot | 6 | 0 | 0 | 6 | 0 | 0 |
| `menagerie_anymal_c` | real robot | 12 | 0 | 0 | 12 | 0 | 0 |
| **Menagerie total** | | **27** | **0** | **0** | **27** | **0** | **0** |

**100% accuracy on all 27 real robot joints** — including joints from robot USDs never seen during development.

#### Combined: 80 joints across 17 scenes

| Metric | Score |
|--------|-------|
| **Recall** | **100%** (24/24 violations caught) |
| Precision | 88.9% (24/27 predicted violations) |
| Accuracy | **96.3%** (77/80 correct) |

Revolute joint limits are detected reliably: upper limits beyond anatomical range (220° elbow, 260° wrist roll, 370° continuous roll) are caught; within-range limits (±90° shoulder, ±80° wrist) are correctly passed. Prismatic detection uses deterministic post-processing: after the model identifies joint type and the scene graph provides the body bbox, a rule `travel > body_length → VIOLATED` is applied automatically.

### Mass estimation

**Synthetic scenes** (68 prims across 14 scenes, overall MAPE ~68%):

The clean 4-material calibration scene (`bench_mass_materials`) achieves near-perfect mass estimation:

| Prim | GT material | Pred material | GT mass (kg) | Pred mass (kg) | APE |
|------|-------------|---------------|-------------|----------------|-----|
| SteelCylinder | steel | steel ✓ | 98.65 | 98.60 | **0.1%** |
| RubberSphere | rubber | rubber ✓ | 2.57 | 2.58 | **0.2%** |
| ConcreteCube | concrete | concrete ✓ | 7.76 | 7.76 | **0.0%** |
| AlumCylinder | aluminum | aluminium ✓ | 4.24 | 4.24 | **0.0%** |

**MAPE = 0.1%** on the clean calibration scene. When materials are unambiguous, the pipeline's formula `bbox_volume × fill_factor × density` is accurate to <1%. The fill_factor shape correction (π/4 for cylinders, π/6 for spheres) accounts for geometry precisely; remaining error is from density rounding in the model's chain-of-thought.

Overall synthetic MAPE across all 68 prims is **~68%**, driven by material misclassification in multi-link assemblies where many similar-sized grey components compete. Steel vs. aluminum confusion (density ratio 2.9×) accounts for most of the error. Mass estimation is the harder problem: it requires both correct material identification AND correct geometry parsing, while joint detection only requires structural limit reasoning.

**Real robot USDs** (MuJoCo Menagerie — Franka Panda, UR5e, ANYmal C):

**MAPE = 1265.7%** across 31 links — expected and documented. The formula `bbox_volume × fill_factor × density` assumes solid castings. Real robot links are hollow aluminum castings with internal cable routing, motors, and electronics. The solid-body approximation overestimates mass by 5–20× per link. Joint detection on the same assets is perfect (0 FP, 0 FN), confirming the pipeline correctly separates structural limit reasoning (joints) from geometric mass estimation.

---

## Installation

### Prerequisites

- **Conda** (Miniconda or Anaconda)
- **Blender 5.x** — must be on `PATH` (install via snap: `sudo snap install blender --classic`)
- **GPU with 16 GB VRAM** recommended for Cosmos Reason 2 8B in bfloat16 (tested on RTX 5080 Laptop)
- CUDA 12.x

### 1 — Create the conda environment

```bash
conda env create -f environment.yml
conda activate physint
```

### 2 — Install PyTorch with CUDA

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

> Replace `cu128` with your CUDA version (e.g. `cu121` for CUDA 12.1).

### 3 — Verify Blender is accessible

```bash
blender --version
```

Cosmos Reason 2 model weights (~15 GB) are downloaded automatically from Hugging Face on first run and cached locally.

---

## Usage

### Audit only (recommended first step)

```bash
conda run -n physint python main.py run your_scene.usda --dry-run
```

Generates `your_scene_report/report.md` and `report.json`. The input USD is never modified. Exit code is `1` if violations are found, `0` if clean — suitable for CI.

### Apply suggested fixes

```bash
conda run -n physint python main.py run your_scene.usda \
  --output your_scene_physics.usda
```

### Run on the included demo scene

```bash
conda run -n physint python main.py run assets/demo_gripper.usda --dry-run \
  2>&1 | tee run.log
```

### Regenerate the demo scene from scratch

```bash
conda run -n physint python main.py create-demo
```

### Parse only (no rendering or inference)

```bash
conda run -n physint python main.py run assets/demo_gripper.usda --parse-only
```

Extracts the scene graph without loading the model. Useful for validating USD structure in CI. Prints a pretty summary, then emits JSON to stdout:

```
  Found 10 geometry prims, 1 joint prims
    Geom  /World/PressureVessel/Body       (Cylinder, size=30.00×30.00×50.00)
    Geom  /World/RubberGasket              (Cylinder, size=33.00×33.00×2.50)
    Geom  /World/SupportFrame/Base         (Cube,     size=42.00×2.00×20.00)
    ...
    Joint /World/RobotArm/ElbowJoint       (PhysicsRevoluteJoint, limits=-10.0°..220.0°)
```

```json
{
  "stage_metadata": { "up_axis": "Y", "meters_per_unit": 0.01 },
  "geom_prims": [
    {
      "path": "/World/PressureVessel/Body",
      "type_name": "Cylinder",
      "bbox": { "size": [30.0, 30.0, 50.0] },
      "fill_factor": 0.785,
      "existing_physics": { "has_rigid_body": false, "has_collision": false, "has_mass": false }
    }
  ],
  "joint_prims": [
    { "path": "/World/RobotArm/ElbowJoint", "type_name": "PhysicsRevoluteJoint",
      "lower_limit": -10.0, "upper_limit": 220.0, "axis": "Z" }
  ]
}
```

### All options

```
Arguments:
  input_usd     Input USD file (.usda or .usd)

Options:
  --dry-run           Audit only — report issues, do NOT write physics to USD
  --output, -o        Output USD path  [default: <stem>_physics.usda]
  --report-dir        Directory for report files  [default: <stem>_report/]
  --render-dir        Directory for render images
  --model             HuggingFace model ID  [default: nvidia/Cosmos-Reason2-8B]
  --blender           Blender executable  [default: blender]
  --samples           Blender Cycles render samples  [default: 32]
  --res               Render resolution  [default: 768]
  --quantize          Load model in 4-bit NF4 (~4 GB VRAM). Required on GPUs with <16 GB.
  --parse-only        Only parse USD, skip rendering & inference
```

---

## Project structure

```
physint/
├── main.py                  # CLI — orchestrates all 4 steps
├── render_usd.py            # Blender Python script (runs inside Blender process)
├── environment.yml          # Conda environment
├── src/
│   ├── usd_parser.py        # Extracts scene graph via pxr.Usd (handles rigid-body Xform hierarchies)
│   ├── renderer.py          # Calls Blender headless, extracts material colors via pxr
│   ├── cosmos_client.py     # Cosmos Reason 2 inference + Pydantic output models
│   ├── physics_writer.py    # Writes UsdPhysics APIs back into the USD stage
│   └── report.py            # Generates JSON + Markdown compliance report
├── benchmark.py             # Benchmark runner — evaluates against known GT
├── benchmark_results.json   # Recorded benchmark output
├── strip_physics.py         # Strips physics properties from USD (for Menagerie pipeline)
├── menagerie_pipeline.py    # Downloads + converts MuJoCo Menagerie models to USD
└── assets/
    ├── create_demo.py             # Programmatically creates the demo USD scene
    ├── create_bench_scenes.py     # Creates all 14 benchmark scenes + benchmark_gt.json
    ├── benchmark_gt.json          # Ground truth: 14 synthetic scenes (53 joints, 68 prims)
    ├── demo_gripper.usda          # Demo input (no physics, bad joint limit)
    ├── demo_gripper_physics.usda  # Demo output (physics authored)
    ├── bench_revolute_limits.usda      # 4 revolute joints (2 violated)
    ├── bench_mass_materials.usda       # 4 materials, mass calibration
    ├── bench_mixed.usda                # 3 revolute joints (1 violated) + mass
    ├── bench_prismatic_limits.usda     # 4 prismatic joints (2 violated)
    ├── bench_humanoid_arm.usda         # 6-DOF arm, 6 revolute (2 violated)
    ├── bench_all_valid.usda            # 5 revolute (0 violated) — specificity test
    ├── bench_crane.usda                # Tower crane, 3 revolute + 1 prismatic (2 violated)
    ├── bench_symmetric_violation.usda  # ±200° symmetric impossible range (1 violated)
    ├── bench_scara.usda                # SCARA robot, 3 revolute + 1 prismatic (2 violated)
    ├── bench_gripper.usda              # Parallel jaw gripper, 4 prismatic (2 violated)
    ├── bench_excavator.usda            # Excavator arm, 2 revolute + 2 prismatic (2 violated)
    ├── bench_wrist_3dof.usda           # 3-DOF wrist, 3 revolute + 1 prismatic (2 violated)
    ├── bench_linear_gantry.usda        # Cartesian gantry, 3 prismatic + 1 revolute (2 violated)
    ├── bench_all_violated.usda         # 4 revolute (all violated) — recall stress test
    ├── menagerie/                 # Real robot USDs (physics-stripped for blind evaluation)
    │   ├── franka_panda/          # Franka Panda (7-DOF arm, 9 joints)
    │   ├── universal_robots_ur5e/ # UR5e (6-DOF arm, 6 joints)
    │   └── anybotics_anymal_c/    # ANYmal C (quadruped, 12 joints)
    └── demo_gripper_report/
        ├── report.md              # Human-readable compliance report
        └── report.json            # Machine-readable report (for CI)
```

---

## Design notes

**Why audit-first?**

Physics properties in simulation are engine-dependent, timestep-dependent, and pipeline-specific. A suggested mass or friction value from this tool is a prior, not a ground truth. The `--dry-run` default reflects this — show the reasoning, let the engineer decide whether to apply it.

**Why Cosmos Reason 2?**

The chain-of-thought output is the key feature. The model writes out its visual evidence before assigning numbers:

> *"The cylindrical body has a smooth, metallic gray surface with a slight sheen, suggesting it is made of steel. Its dimensions are 30.0 × 50.0 stage units → 0.3 × 0.5 m. Volume ≈ 0.045 m³, density 7850 kg/m³, estimated mass ≈ 353 kg."*

That reasoning is preserved in the compliance report — it is auditable, correctable, and explains every number.

**Why Blender for rendering?**

USD scene renderers that run fully headless on CPU without a display server are rare. Blender Cycles in `--background` mode works reliably on WSL2, CI runners, and servers without GPUs. The 4-view render set (top / front / side / isometric) gives Cosmos Reason 2 enough visual information to disambiguate material and geometry.

---

## Tested environment

| Component | Version |
|-----------|---------|
| GPU | NVIDIA RTX 5080 Laptop (16 GB) |
| CUDA | 12.8 |
| PyTorch | 2.10.0+cu128 |
| usd-core | 25.11 |
| transformers | 5.2.0 |
| Blender | 5.0.1 |
| Python | 3.11 |
| OS | Ubuntu 22.04 (WSL2) |
