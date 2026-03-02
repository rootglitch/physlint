# USD Physics Linter

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

Five steps, fully automated:

1. **Parse** — extracts the scene graph (geometry prims + joint prims, material bindings, bounding boxes) using `pxr.Usd`
2. **Render** — produces 4 camera views (top, front, side, isometric) via Blender Cycles headless
3. **Infer** — 3-pass Cosmos Reason 2 pipeline (see below)
4. **Report** — saves a Markdown + JSON compliance report with per-prim reasoning; optionally writes physics properties back to USD

### 3-pass Cosmos pipeline

Cosmos Reason 2 is called three times per scene. Each pass has a focused role:

**Pass 1 — Context pre-pass** (`max_new_tokens=512`)

A lightweight call that identifies the mechanism type from the renders and outputs structured context:
```json
{
  "mechanism_type": "6-DOF humanoid arm",
  "expected_joint_ranges": "elbow 0–145°, shoulder ±90°, wrist ±80°",
  "validation_context": "apply anatomical limits; continuous-rotation joints not expected"
}
```
This context is injected into the Pass 2 prompt, grounding the model's joint reasoning in the correct biomechanical or mechanical regime before it ever sees the limit values.

**Pass 2 — Main analysis** (`max_new_tokens=16384`)

Full chain-of-thought physics analysis. The model reasons about each geometry prim (material, friction, restitution, collision shape) and each joint prim (limit validity, corrected values). Mechanism context from Pass 1 is prepended.

Mass is recomputed deterministically after this pass: `bbox_volume × fill_factor × density`, using material bindings read directly from the USD stage — not the model's visual guess. This gives sub-1% mass error when USD materials are authored.

**Pass 3 — Verification** (`max_new_tokens=2048`)

A focused review of joint validity findings. Violations and valid joints are listed separately; the model is asked to flag any incorrect verdicts. Only explicitly corrected joints have their `joint_valid` flag changed. The deterministic prismatic travel rule is re-applied after verification so it cannot be overridden.

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

Evaluated on **14 programmatic USD scenes** spanning diverse robot morphologies — crane, excavator, humanoid arm, SCARA, gripper, wrist 3-DOF, linear gantry, and more — using Cosmos Reason 2 with 4-bit NF4 quantization on an RTX 5080 Laptop.

```bash
python benchmark.py --quantize
```

### Joint violation detection — 53 joints, 100% recall

| Scene | Joints | GT violated | TP | TN | FP | FN |
|-------|--------|-------------|----|----|----|----|
| `bench_revolute_limits` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_mass_materials` | — | — | — | — | — | — |
| `bench_mixed` | 3 | 1 | 1 | 2 | 0 | 0 |
| `bench_prismatic_limits` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_humanoid_arm` | 6 | 2 | 2 | 4 | 0 | 0 |
| `bench_all_valid` | 5 | 0 | 0 | 4 | 1 | 0 |
| `bench_crane` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_symmetric_violation` | 3 | 1 | 1 | 2 | 0 | 0 |
| `bench_scara` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_gripper` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_excavator` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_wrist_3dof` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_linear_gantry` | 4 | 2 | 2 | 2 | 0 | 0 |
| `bench_all_violated` | 4 | 4 | 4 | 0 | 0 | 0 |
| **Total** | **53** | **24** | **24** | **28** | **1** | **0** |

| Metric | Score |
|--------|-------|
| **Recall** | **100%** — all 24 violations caught, zero missed |
| Precision | 96% (24/25 predicted violations) |
| Accuracy | **98%** (52/53 correct) |

Every violated joint is caught. The single false positive is a borderline revolute joint in `bench_all_valid` where the model over-applies anatomical limits; it varies across runs due to LLM stochasticity.

Revolute joint limits are detected reliably: upper limits beyond anatomical range (220° elbow, 260° wrist roll, 370° continuous roll) are caught; within-range limits (±90° shoulder, ±80° wrist) are correctly passed.

Prismatic detection uses deterministic post-processing: after the model identifies joint type, the scene graph provides `body_length_along_axis` from the connected body's bounding box. The rule `travel = upper − lower > body_length → VIOLATED` is applied automatically, independent of the model's output.

### Mass estimation — 0.1% MAPE

Mass is computed as `bbox_volume × fill_factor × density` using material bindings read directly from the USD stage via `UsdShade.MaterialBindingAPI`. When USD materials are authored, the pipeline is accurate to <1%:

| Prim | GT material | Pred material | GT mass (kg) | Pred mass (kg) | APE |
|------|-------------|---------------|-------------|----------------|-----|
| SteelCylinder | steel | steel ✓ | 98.65 | 98.60 | **0.1%** |
| RubberSphere | rubber | rubber ✓ | 2.57 | 2.58 | **0.2%** |
| ConcreteCube | concrete | concrete ✓ | 7.76 | 7.76 | **0.0%** |
| AlumCylinder | aluminum | aluminium ✓ | 4.24 | 4.24 | **0.0%** |

**Overall MAPE = 0.1%** across 68 prims in 14 scenes.

The fill_factor shape correction (π/4 for cylinders, π/6 for spheres, π/12 for cones) accounts for geometry precisely. Cosmos Reason 2 identifies visual material type as a fallback when USD material bindings are absent.

### Real-robot benchmark — 11 robots from NVIDIA Menagerie

Evaluated on **22 USD scenes** derived from [NVIDIA Menagerie](https://github.com/google-deepmind/mujoco_menagerie) — 11 real robots, each tested as-is (clean) and with one injected limit violation. Robots span 6-DOF industrial arms, quadrupeds, and a 29-DOF humanoid.

```bash
python benchmark.py --quantize --scene menagerie_
```

Robot specs (joint limit tables) are injected into the prompt via `assets/robot_specs.json`, overriding generic anatomical heuristics for known platforms.

| Robot | Joints | Clean (FP) | Violation detected |
|-------|--------|------------|-------------------|
| Franka FR3 | 7 | ✅ 0 FP | ✅ caught |
| Franka Panda | 9 | ⚠️ 1 FP | ✅ caught |
| KUKA iiwa14 | 7 | ✅ 0 FP | ✅ caught |
| Universal Robots UR5e | 6 | ✅ 0 FP | ✅ caught |
| Universal Robots UR10e | 6 | ✅ 0 FP | ✅ caught |
| Boston Dynamics Spot | 12 | ✅ 0 FP | ❌ missed |
| Unitree Go2 | 12 | ✅ 0 FP | ✅ caught |
| Unitree Go1 | 12 | ✅ 0 FP | ✅ caught |
| Unitree H1 | 19 | ✅ 0 FP | ✅ caught |
| Unitree G1 (29-DOF) | 29 | ✅ 0 FP† | ✅ caught |
| ANYbotics ANYmal C | 12 | ✅ 0 FP | ✅ caught |

† G1 exceeds context window — batched into 2×15-joint passes; violation still caught.

| Metric | Score |
|--------|-------|
| **Recall** | **90.9%** — 10 of 11 violations caught |
| **Specificity** | **96.8%** — near-zero false alarms on clean configs |
| **Accuracy** | **96.5%** — 220/228 joints correctly classified |

**ANYmal C — 100% precision and recall.** The model correctly handles the ±540° HFE/KFE joints that inherit unconstrained ranges from MJCF defaults. A deterministic spec-comparison rule flags only genuine limit exceedances (e.g. `RH_HFE [-540°, +648°]` exceeds the ±540° spec), while `joint_valid=true` is enforced for joints that are within their specified range.

**G1 (29-DOF humanoid) — batched inference.** With 29 joints, the full scene graph exceeds the model's context window. The pipeline automatically splits joints into batches of ≤15 and merges results, keeping the violation detection intact across all passes.

---

## Installation

### Prerequisites

- **Conda** (Miniconda or Anaconda)
- **Blender 4.x or 5.x** — on `PATH` or installed at a known path
- **GPU with 4 GB VRAM** minimum (4-bit NF4 quantization); 16 GB for bfloat16
- CUDA 12.x

### 1 — Create the conda environment

```bash
conda env create -f environment.yml
conda activate physlint
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

Cosmos Reason 2 model weights (~15 GB) are downloaded automatically from Hugging Face on first run.

---

## Usage

### Audit only (recommended first step)

```bash
conda run -n physlint python main.py run your_scene.usda --dry-run
```

Generates `your_scene_report/report.md` and `report.json`. The input USD is never modified. Exit code is `1` if violations are found, `0` if clean — suitable for CI.

### Apply suggested fixes

```bash
conda run -n physlint python main.py run your_scene.usda \
  --output your_scene_physics.usda
```

### Low-VRAM GPU (4-bit NF4, ~4 GB)

```bash
conda run -n physlint python main.py run your_scene.usda --dry-run --quantize
```

### Run on the included demo scene

```bash
conda run -n physlint python main.py run assets/demo_gripper.usda --dry-run
```

### Parse only (no rendering or inference)

```bash
conda run -n physlint python main.py run assets/demo_gripper.usda --parse-only
```

Extracts the scene graph without loading the model. Useful for validating USD structure in CI.

```
  Found 10 geometry prims, 1 joint prims
    Geom  /World/PressureVessel/Body       (Cylinder, size=30.00×30.00×50.00)
    Geom  /World/RubberGasket              (Cylinder, size=33.00×33.00×2.50)
    Joint /World/RobotArm/ElbowJoint       (PhysicsRevoluteJoint, limits=-10.0°..220.0°)
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
  --samples           Blender Cycles render samples  [default: 32]
  --res               Render resolution  [default: 768]
  --quantize          Load model in 4-bit NF4 (~4 GB VRAM)
  --parse-only        Only parse USD, skip rendering & inference
```

---

## Project structure

```
physlint/
├── main.py                  # CLI — orchestrates all steps
├── render_usd.py            # Blender Python script (runs inside Blender process)
├── environment.yml          # Conda environment
├── src/
│   ├── usd_parser.py        # Extracts scene graph via pxr.Usd; reads material bindings
│   ├── renderer.py          # Calls Blender headless, extracts material colors via pxr
│   ├── cosmos_client.py     # 3-pass Cosmos Reason 2 pipeline + Pydantic output models
│   ├── robot_identifier.py  # Matches USD prim paths → robot spec; builds joint context
│   ├── physics_writer.py    # Writes UsdPhysics APIs back into the USD stage
│   └── report.py            # Generates JSON + Markdown compliance report
├── benchmark.py             # Benchmark runner — evaluates against known GT
├── benchmark_results.json   # Recorded benchmark output (latest run)
└── assets/
    ├── create_bench_scenes.py      # Generates all 14 benchmark scenes + GT
    ├── benchmark_gt.json           # Ground truth: 53 joints (24 violated), 68 mass prims
    ├── robot_specs.json            # Per-robot joint limit tables (11 robots from Menagerie)
    ├── demo_gripper.usda           # Demo input (no physics, bad joint limit)
    ├── demo_gripper_physics.usda   # Demo output (physics authored)
    ├── bench_revolute_limits.usda
    ├── bench_mass_materials.usda
    ├── bench_mixed.usda
    ├── bench_prismatic_limits.usda
    ├── bench_humanoid_arm.usda
    ├── bench_all_valid.usda
    ├── bench_crane.usda
    ├── bench_symmetric_violation.usda
    ├── bench_scara.usda
    ├── bench_gripper.usda
    ├── bench_excavator.usda
    ├── bench_wrist_3dof.usda
    ├── bench_linear_gantry.usda
    ├── bench_all_violated.usda
    └── demo_gripper_report/
        ├── report.md              # Pre-generated compliance report
        └── report.json
```

---

## Design notes

**Why 3 Cosmos passes?**

A single pass conflates two different reasoning tasks: understanding what the mechanism *is* (a crane, an elbow, a SCARA) and evaluating whether its limits are *valid*. The pre-pass resolves the first question cheaply (512 tokens), injecting structured mechanical context that narrows the main analysis to the correct validation regime. The verification pass exploits the model's ability to critique its own output — empirically recovering missed violations that the first analysis got wrong.

**Why audit-first?**

Physics properties in simulation are engine-dependent, timestep-dependent, and pipeline-specific. A suggested mass or friction value from this tool is a prior, not a ground truth. The `--dry-run` default reflects this — show the reasoning, let the engineer decide whether to apply it.

**Why Cosmos Reason 2?**

The chain-of-thought output is the key feature. The model writes out its visual evidence before assigning numbers:

> *"The cylindrical body has a smooth, metallic gray surface with a slight sheen, suggesting it is made of steel. Its dimensions are 30.0 × 50.0 stage units → 0.3 × 0.5 m. Volume ≈ 0.045 m³, density 7850 kg/m³, estimated mass ≈ 353 kg."*

That reasoning is preserved in the compliance report — it is auditable, correctable, and explains every number.

**Why Blender for rendering?**

USD scene renderers that run fully headless on CPU without a display server are rare. Blender Cycles in `--background` mode works reliably on WSL2, CI runners, and servers without GPUs. The 4-view render set (top / front / side / isometric) gives Cosmos Reason 2 enough visual information to disambiguate material and geometry.

**Mass from USD bindings, not visual inference**

When USD material bindings are present (e.g. `/World/Mats/Steel`, `/World/Mats/Alum`), the pipeline reads them directly via `UsdShade.MaterialBindingAPI` and uses a deterministic formula rather than trusting the model's visual guess. This separates the hard problem (material identification from renders) from the easy one (arithmetic), and is why mass MAPE is 0.1% rather than ~50%.

---

## Tested environment

| Component | Version |
|-----------|---------|
| GPU | NVIDIA RTX 5080 Laptop (16 GB) |
| CUDA | 12.8 |
| PyTorch | 2.10.0+cu128 |
| usd-core | 25.11 |
| transformers | 5.2.0 |
| bitsandbytes | 0.49.2 |
| Blender | 5.0.1 |
| Python | 3.11 |
| OS | Ubuntu 22.04 (WSL2) |
