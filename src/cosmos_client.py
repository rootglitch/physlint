"""
Cosmos Reason 2 inference client.

Sends 4 renders + scene graph JSON to the model and returns a structured
PhysicsAnalysis with per-prim physics properties.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import torch
from PIL import Image
from pydantic import BaseModel, Field, field_validator
from transformers import AutoProcessor
from qwen_vl_utils import process_vision_info


# ---------------------------------------------------------------------------
# Pydantic models for structured output
# ---------------------------------------------------------------------------

CollisionApprox = Literal["convexHull", "boundingBox", "meshSimplification", "none"]


Confidence = Literal["high", "medium", "low"]


class GeomPhysics(BaseModel):
    prim_path: str
    material_type: str = Field(description="e.g. 'steel', 'rubber', 'plastic', 'wood', 'glass', 'concrete'")
    mass_kg: float = Field(ge=0.0)
    static_friction: float = Field(ge=0.0, le=2.0)
    dynamic_friction: float = Field(ge=0.0, le=2.0)
    restitution: float = Field(ge=0.0, le=1.0)
    collision_approximation: CollisionApprox
    is_rigid: bool
    confidence: Confidence = Field(
        description=(
            "high = clear visual evidence + unambiguous material; "
            "medium = reasonable inference but some uncertainty; "
            "low = ambiguous visuals, occluded, or atypical material"
        )
    )
    reasoning: str

    @field_validator("dynamic_friction")
    @classmethod
    def dyn_le_static(cls, v, info):
        static = info.data.get("static_friction", v)
        if v > static + 0.05:
            return static  # clamp silently
        return v


class JointPhysics(BaseModel):
    prim_path: str
    lower_limit_deg: Optional[float] = None
    upper_limit_deg: Optional[float] = None
    joint_valid: bool
    confidence: Confidence = Field(
        description=(
            "high = limit clearly impossible or clearly valid; "
            "medium = limit plausible but context-dependent; "
            "low = joint type ambiguous"
        )
    )
    reasoning: str


class PhysicsAnalysis(BaseModel):
    geom_prims: list[GeomPhysics] = Field(default_factory=list)
    joint_prims: list[JointPhysics] = Field(default_factory=list)
    global_notes: str = ""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a physics simulation expert preparing USD scenes for NVIDIA Isaac Sim. "
    "You have deep knowledge of material properties, mechanical engineering, and robotics simulation. "
    "Always reason carefully about visual evidence before assigning numeric values."
)

PREPASS_SYSTEM_PROMPT = (
    "You are a mechanical engineering expert. Identify the type of mechanism or robot "
    "shown in USD scene renders and describe the physics validation context that applies. "
    "Be concise and precise."
)

VERIFICATION_SYSTEM_PROMPT = (
    "You are a physics simulation expert reviewing a USD scene analysis for correctness. "
    "Carefully verify each joint validity assessment against the visual evidence and "
    "mechanical constraints. Be critical — flag false positives and missed violations."
)

MATERIAL_REFERENCE = """
MATERIAL CUES:
- Silvery/grey = metal. Steel=darker grey (frames, vessels, heavy structural). Aluminium=lighter silver (robot arms, lightweight parts).
  Grey objects in ROBOT ARM context → metal (steel or aluminium), NOT concrete.
- Near-black = rubber | Bright saturated = plastic or painted metal
- Flat grey + architectural context (floors, walls, slabs) = concrete
- Translucent = glass

| Material     | kg/m³ | Static μ  | Dynamic μ | Rest |
|--------------|-------|-----------|-----------|------|
| Steel/Iron   | 7850  | 0.40-0.60 | 0.30-0.50 | 0.30 |
| Aluminium    | 2700  | 0.35-0.55 | 0.25-0.45 | 0.30 |
| Hard Plastic | 1050  | 0.35-0.50 | 0.25-0.40 | 0.40 |
| Rubber       | 1200  | 0.70-1.10 | 0.60-0.90 | 0.05 |
| Wood         | 700   | 0.40-0.55 | 0.30-0.45 | 0.30 |
| Glass        | 2500  | 0.40-0.50 | 0.30-0.40 | 0.50 |
| Concrete     | 2300  | 0.55-0.70 | 0.45-0.60 | 0.10 |
| Carbon Fiber | 1600  | 0.25-0.40 | 0.20-0.35 | 0.30 |

MASS CALCULATION — follow exactly:
  Step 1: Convert bbox to metres: xm = bbox_x × mpu, ym = bbox_y × mpu, zm = bbox_z × mpu
          (mpu = meters_per_unit from Stage metadata, e.g. 0.01 means 1 stage unit = 1 cm)
  Step 2: volume_m³ = xm × ym × zm × fill_factor
  Step 3: mass_kg = volume_m³ × density_kg_m3
  WORKED EXAMPLE (mpu=0.01):
    bbox [40,40,10]: xm=40×0.01=0.40, ym=40×0.01=0.40, zm=10×0.01=0.10 m  ← NOT 0.01!
    fill_factor=0.785 (cylinder) → vol = 0.40×0.40×0.10×0.785 = 0.01256 m³
    density=7850 (steel) → mass = 0.01256×7850 = 98.6 kg

JOINT RULES:
  Revolute (degrees):
    Human elbow: lower=-10°, upper=145° (NEVER above 160°). Wrist: lower=-70°, upper=70°.
    Industrial robot: lower=-180°, upper=180°.
    If upper_limit > 180° for a human-like joint → VIOLATED, set joint_valid=false, cap at 145°.
  Prismatic (stage units): RULE: travel = upper_limit − lower_limit.
    Each joint has body_length_along_axis pre-computed in the scene graph.
    If travel > body_length_along_axis → VIOLATED. Set joint_valid=false.
    Example: body_length=30, travel=180 → VIOLATED. body_length=30, travel=30 → valid.
    (lower_limit_deg / upper_limit_deg carry stage-unit values for prismatic joints)
"""


def _build_prompt(scene_graph: dict, context_str: str = "") -> str:
    import copy
    scene_graph = copy.deepcopy(scene_graph)

    # Replace bbox {min, max, size} with just {size} so the model uses the
    # correct side lengths and not the world-space corner coordinates.
    # Strip material_type from geom_prims — it's used internally by
    # _apply_mass_correction (which reads the original scene_graph), but
    # including it in the prompt caused joint-analysis regression in benchmarks.
    for p in scene_graph.get("geom_prims", []):
        if isinstance(p.get("bbox"), dict):
            p["bbox"] = {"size": p["bbox"]["size"]}
        p.pop("material_type", None)

    # Strip body-path and body_length from non-prismatic joints to prevent
    # the model from applying the prismatic travel-check to revolute joints.
    for j in scene_graph.get("joint_prims", []):
        if "Prismatic" not in j.get("type_name", ""):
            for f in ("body0_path", "body1_path", "body_length_along_axis"):
                j.pop(f, None)

    geom_paths = [p["path"] for p in scene_graph.get("geom_prims", [])]
    joint_paths = [p["path"] for p in scene_graph.get("joint_prims", [])]
    meta = scene_graph.get("stage_metadata", {})

    context_block = (
        f"\nMECHANISM CONTEXT (from scene pre-analysis):\n{context_str}\n"
        if context_str else ""
    )

    return f"""
{context_block}{MATERIAL_REFERENCE}

4 renders: top / front / right / isometric.
Stage: up_axis={meta.get('up_axis', 'Y')}, meters_per_unit={meta.get('meters_per_unit', 1.0)}

Scene graph:
{json.dumps(scene_graph, separators=(',', ':'))}

Geometry prims: {geom_paths}
Joint prims:    {joint_paths}

INSTRUCTIONS — follow this ORDER exactly:

STEP 1 — REASONING (write this out FULLY before any JSON):
For each geometry prim write ONE line:
  "Prim <path>: material=<X> because <1-2 word visual cue>. Confidence:<level>."
  (Mass is computed automatically from bbox — you do NOT need to calculate it.)
For each joint prim write 2-3 sentences (full reasoning required for joint validation):
  Revolute: "Joint <name>: lower=<X>°, upper=<Y>°. <reason why valid/invalid>.
   Corrected: lower=<A>°, upper=<B>°. Confidence:<level>."
  Prismatic: "Joint <name>: lower=<X>, upper=<Y>, body_length_along_axis=<B>.
   travel=upper−lower=<T>. <T> vs <B>: <exceeds→VIOLATED, joint_valid=false|fits→valid, joint_valid=true>.
   Corrected if needed: lower=<A>, upper=<C>. Confidence:<level>."

IMPORTANT JSON RULE: If a joint was VIOLATED in step 1, set joint_valid=false in STEP 2 even if you output corrected limits. joint_valid=false means "original limits were wrong".

STEP 2 — JSON OUTPUT (after ALL step 1 reasoning above):

```json
{{
  "geom_prims": [
    {{
      "prim_path": "<exact path>",
      "material_type": "<name>",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "<one sentence>"
    }}
  ],
  "joint_prims": [
    {{
      "prim_path": "<exact path>",
      "lower_limit_deg": null,
      "upper_limit_deg": null,
      "joint_valid": true,
      "confidence": "high",
      "reasoning": "<one sentence>"
    }}
  ],
  "global_notes": "<any overall observations>"
}}
```
""".strip()


def _build_prepass_prompt(scene_graph: dict) -> str:
    """Minimal prompt for Pass 1: identify mechanism type and validation context."""
    meta = scene_graph.get("stage_metadata", {})
    joints = [
        {"path": j["path"], "type": j.get("type_name", "Unknown"),
         "lower": j.get("lower_limit"), "upper": j.get("upper_limit")}
        for j in scene_graph.get("joint_prims", [])
        if "Fixed" not in j.get("type_name", "")
    ]
    return f"""4 renders of a USD physics scene: top / front / side / isometric.
Stage: up_axis={meta.get('up_axis', 'Y')}, meters_per_unit={meta.get('meters_per_unit', 1.0)}
Joints present: {json.dumps(joints, separators=(',', ':'))}

Identify the mechanism and describe the physics validation context that applies.

```json
{{
  "mechanism_type": "<e.g. '6-DOF industrial robot arm', 'linear gantry crane', 'parallel gripper', 'humanoid arm'>",
  "expected_joint_ranges": "<brief description: e.g. 'revolute joints -160° to +160° for industrial arms; elbow limited to 0-145° for human arms'>",
  "validation_context": "<specific constraints guiding joint and mass validation for this mechanism>"
}}
```""".strip()


def _build_verification_prompt(raw: dict, scene_graph: dict) -> str:
    """Prompt for Pass 3: verify correctness of joint validity findings."""
    meta = scene_graph.get("stage_metadata", {})
    joint_by_path = {j["path"]: j for j in scene_graph.get("joint_prims", [])}

    violations = []
    valid_joints = []
    for j in raw.get("joint_prims", []):
        path = j.get("prim_path", "")
        sg = joint_by_path.get(path, {})
        entry = {
            "path": path,
            "type": sg.get("type_name", "Unknown"),
            "original_lower": sg.get("lower_limit"),
            "original_upper": sg.get("upper_limit"),
            "reasoning": j.get("reasoning", ""),
        }
        if not j.get("joint_valid", True):
            violations.append(entry)
        else:
            valid_joints.append(entry)

    return f"""Review this USD physics analysis. 4 renders shown: top/front/side/isometric.
Stage: up_axis={meta.get('up_axis', 'Y')}, meters_per_unit={meta.get('meters_per_unit', 1.0)}

VIOLATIONS FOUND ({len(violations)}):
{json.dumps(violations, indent=2)}

VALID JOINTS ({len(valid_joints)}):
{json.dumps(valid_joints, indent=2)}

For each joint, verify the verdict against visual evidence:
- VIOLATIONS: Is the reasoning sound? Does the visual evidence confirm the limits are physically impossible?
- VALID JOINTS: Are there any that should actually be flagged as violated?

Output ONLY the joints where the verdict should CHANGE. An empty corrections list means the analysis is confirmed correct.

```json
{{
  "corrections": [
    {{
      "prim_path": "<exact path>",
      "joint_valid": true,
      "reasoning": "<why the original verdict was wrong>"
    }}
  ],
  "global_notes": "<brief summary of verification>"
}}
```""".strip()


# ---------------------------------------------------------------------------
# Model loader (singleton to avoid reloading across calls)
# ---------------------------------------------------------------------------

_model_cache: dict = {}


def _load_model(model_id: str, quantize: bool = False):
    cache_key = (model_id, quantize)
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    from transformers import AutoModelForImageTextToText, BitsAndBytesConfig
    quant_label = "4-bit NF4" if quantize else "bfloat16"
    print(f"[cosmos_client] Loading model: {model_id} ({quant_label}) ...")

    kwargs: dict = {"device_map": "auto", "trust_remote_code": True}
    if quantize:
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )
    else:
        kwargs["torch_dtype"] = torch.bfloat16

    model = AutoModelForImageTextToText.from_pretrained(model_id, **kwargs)
    model.eval()
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    _model_cache[cache_key] = (model, processor)
    print(f"[cosmos_client] Model loaded on: {next(model.parameters()).device}")
    return model, processor


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def _run_model(
    model,
    processor,
    system_prompt: str,
    render_paths: list[str],
    user_prompt: str,
    max_new_tokens: int = 512,
    temperature: float = 0.1,
) -> str:
    """Single model.generate() call. Returns decoded response string."""
    content = [
        {"type": "image", "image": Image.open(p).convert("RGB")}
        for p in render_paths
    ]
    content.append({"type": "text", "text": user_prompt})
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": content},
    ]
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.no_grad():
        out_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
        )
    trimmed = out_ids[:, inputs.input_ids.shape[1]:]
    return processor.batch_decode(trimmed, skip_special_tokens=True)[0]


def _apply_verification(raw: dict, verification_response: str, scene_graph: dict) -> dict:
    """Apply corrections from Pass 3 verification to the raw analysis dict.

    Only joints explicitly listed in `corrections` have their joint_valid changed.
    The deterministic prismatic rule is re-applied afterward so it can't be
    overridden by a verification false-positive on prismatic joints.
    """
    try:
        v = _extract_json(verification_response)
    except Exception:
        return raw  # verification parse failed — keep main analysis as-is

    corrections = v.get("corrections", [])
    if not corrections:
        return raw

    raw_by_path = {j["prim_path"]: j for j in raw.get("joint_prims", [])}
    for c in corrections:
        path = c.get("prim_path", "")
        new_valid = c.get("joint_valid")
        if path in raw_by_path and isinstance(new_valid, bool):
            old = raw_by_path[path]["joint_valid"]
            raw_by_path[path]["joint_valid"] = new_valid
            direction = "false→true (cleared)" if (not old and new_valid) else "true→false (new violation)"
            print(f"[cosmos_client] Verification correction: {path} {direction}")
            # Append verification reasoning
            existing = raw_by_path[path].get("reasoning", "")
            raw_by_path[path]["reasoning"] = (
                f"{existing} [Verification: {c.get('reasoning', '')}]"
            )

    return raw


def _extract_json(text: str) -> dict:
    """Pull the first JSON code block out of model output.

    Falls back to json_repair for malformed JSON (missing commas, truncation, etc.).
    """
    import json_repair

    def _try_parse(s: str) -> dict | None:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            try:
                result = json_repair.repair_json(s, return_objects=True)
                if isinstance(result, dict):
                    return result
            except Exception:
                pass
        return None

    # Try ```json ... ```
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        parsed = _try_parse(m.group(1))
        if parsed is not None:
            return parsed

    # Try raw { ... }
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        parsed = _try_parse(m.group(1))
        if parsed is not None:
            return parsed

    raise ValueError("No JSON block found in model output")


def _fix_joint_validity(raw: dict, full_response: str = "") -> dict:
    """Override joint_valid=True when the model's JSON reasoning says VIOLATED.

    The model occasionally writes correct violation reasoning in STEP 1 but then
    outputs corrected limits in STEP 2 JSON and marks them valid.  Only the JSON
    reasoning field is checked (not the full chain-of-thought) to avoid false
    positives from adjacent joints' text bleeding into the window.
    """
    for j in raw.get("joint_prims", []):
        if j.get("joint_valid", True):
            # Only check the per-joint reasoning field in the JSON output
            if "VIOLATED" in j.get("reasoning", "").upper():
                j["joint_valid"] = False
    return raw


# ---------------------------------------------------------------------------
# Deterministic physics post-processing
# ---------------------------------------------------------------------------

# Density table (kg/m³) keyed by lowercase material name fragments.
_DENSITY_BY_MATERIAL: dict[str, float] = {
    "steel": 7850.0,
    "iron": 7850.0,
    "stainless": 7850.0,
    "aluminum": 2700.0,
    "aluminium": 2700.0,
    "alum": 2700.0,
    "plastic": 1050.0,
    "hard plastic": 1050.0,
    "rubber": 1200.0,
    "wood": 700.0,
    "glass": 2500.0,
    "concrete": 2300.0,
    "carbon fiber": 1600.0,
    "carbon": 1600.0,
}


def _lookup_density(material_type: str) -> Optional[float]:
    mat = material_type.lower().strip()
    for key, dens in _DENSITY_BY_MATERIAL.items():
        if key in mat:
            return dens
    return None


def _apply_mass_correction(raw: dict, scene_graph: dict) -> dict:
    """Recompute mass_kg from bbox × fill_factor × density.

    Mass is always recomputed deterministically because the main prompt
    explicitly tells the model NOT to calculate mass (it outputs mass_kg=0.0).
    The model's material classification (confidence, material_type) is preserved;
    only the arithmetic is supplied here.

    HIGH confidence prims: use Cosmos material_type + our arithmetic — the model
    identified the material clearly, so we trust that and compute the correct mass.
    MEDIUM / LOW confidence: same arithmetic, but the material guess may be wrong.
    Skips prims where we can't find bbox or density.
    """
    mpu = scene_graph.get("stage_metadata", {}).get("meters_per_unit", 1.0)
    geom_by_path = {p["path"]: p for p in scene_graph.get("geom_prims", [])}

    for gp in raw.get("geom_prims", []):
        path = gp.get("prim_path", "")
        sg_prim = geom_by_path.get(path)
        if sg_prim is None:
            continue
        bbox = sg_prim.get("bbox")
        if not bbox:
            continue
        size = bbox.get("size") if isinstance(bbox, dict) else None
        if not size or len(size) < 3:
            continue
        fill = sg_prim.get("fill_factor", 1.0) or 1.0
        # Prefer USD material (scene graph) over Cosmos visual guess
        usd_mat = sg_prim.get("material_type", "")
        cosmos_mat = gp.get("material_type", "")
        density = _lookup_density(usd_mat) or _lookup_density(cosmos_mat)
        if density is None:
            continue
        xm, ym, zm = [v * mpu for v in size]
        vol = xm * ym * zm * fill
        gp["mass_kg"] = round(vol * density, 3)

    return raw


def _apply_prismatic_rules(raw: dict, scene_graph: dict) -> dict:
    """Deterministically enforce the prismatic travel rule.

    For each Prismatic joint with a known body_length_along_axis, the rule is
    fully authoritative in both directions:
      travel = upper − lower > body_length_along_axis  →  joint_valid = False
      travel ≤ body_length_along_axis                  →  joint_valid = True

    This overrides the model in both directions — preventing both false
    violations (model says violated but travel fits) and missed violations
    (model says valid but travel exceeds housing length).

    The model's limits (lower/upper) are taken from the ORIGINAL scene graph
    so that corrected-limit outputs don't mask the original violation.
    """
    import math
    joint_by_path = {j["path"]: j for j in scene_graph.get("joint_prims", [])}

    for jp in raw.get("joint_prims", []):
        path = jp.get("prim_path", "")
        sg_joint = joint_by_path.get(path)
        if sg_joint is None:
            continue
        if "Prismatic" not in sg_joint.get("type_name", ""):
            continue
        body_len = sg_joint.get("body_length_along_axis")
        if body_len is None:
            continue
        # Use ORIGINAL scene-graph limits, not model's (possibly corrected) limits
        orig_lower = sg_joint.get("lower_limit")
        orig_upper = sg_joint.get("upper_limit")
        if orig_lower is None or orig_upper is None:
            continue
        # Skip joints whose limits are non-finite (cleared to ±inf) — cannot
        # evaluate travel vs body_length when limits are unconstrained.
        if not math.isfinite(orig_lower) or not math.isfinite(orig_upper):
            continue
        travel = orig_upper - orig_lower
        jp["joint_valid"] = (travel <= body_len)

    return raw


def _fix_cleared_joint_validity(raw: dict, scene_graph: dict) -> dict:
    """Override joint_valid=False → True for joints whose limits were cleared
    (i.e., original limits are ±inf in the stripped USD).

    When a joint's limits are cleared, it is impossible to determine whether
    original limits were violated, so we conservatively assume valid.
    This prevents false positives on Menagerie robots where limits are cleared
    and the model misinterprets ±inf as "unlimited travel = violated".
    """
    import math
    joint_by_path = {j["path"]: j for j in scene_graph.get("joint_prims", [])}
    for jp in raw.get("joint_prims", []):
        if jp.get("joint_valid", True):
            continue   # already valid, nothing to fix
        path = jp.get("prim_path", "")
        sg_joint = joint_by_path.get(path)
        if sg_joint is None:
            continue
        lo = sg_joint.get("lower_limit")
        hi = sg_joint.get("upper_limit")
        # If limits are non-finite (cleared to ±inf), reset to valid
        if (lo is not None and hi is not None and
                (not math.isfinite(lo) or not math.isfinite(hi))):
            jp["joint_valid"] = True
    return raw


def analyze_scene(
    render_paths: list[str],
    scene_graph: dict,
    model_id: str = "nvidia/Cosmos-Reason2-8B",
    max_new_tokens: int = 16384,
    temperature: float = 0.1,
    quantize: bool = False,
) -> tuple[PhysicsAnalysis, str]:
    """
    Run Cosmos Reason 2 on 4 scene renders + scene graph using a 3-pass pipeline.

    Pass 1 (context pre-pass): lightweight call that identifies the mechanism type
    and feeds structured context into the main analysis prompt.

    Pass 2 (main analysis): full physics analysis with mechanism context prepended.
    HIGH-confidence geom prims keep Cosmos mass_kg; medium/low are recomputed
    deterministically.

    Pass 3 (verification): focused review of joint validity findings; can flip
    joint_valid in either direction based on visual re-examination.

    Args:
      quantize: If True, load model in 4-bit NF4 (requires bitsandbytes).
                Reduces VRAM from ~16 GB to ~4 GB; suitable for <=8 GB GPUs.

    Returns:
      (PhysicsAnalysis, chain_of_thought_str)   # cot includes all 3 pass outputs
    """
    assert len(render_paths) == 4, "Expected exactly 4 render paths"
    model, processor = _load_model(model_id, quantize=quantize)

    # Remove FixedJoints — they have no limits and can never be violated.
    sg_filtered = dict(scene_graph)
    sg_filtered["joint_prims"] = [
        j for j in scene_graph.get("joint_prims", [])
        if "Fixed" not in j.get("type_name", "")
    ]

    # ── Pass 1: Scene-context pre-pass ──────────────────────────────────────
    print("[cosmos_client] Pass 1/3 — scene context pre-pass ...")
    prepass_prompt = _build_prepass_prompt(sg_filtered)
    prepass_response = _run_model(
        model, processor, PREPASS_SYSTEM_PROMPT,
        render_paths, prepass_prompt,
        max_new_tokens=512, temperature=temperature,
    )
    print(f"[cosmos_client] Pre-pass output:\n{prepass_response}")

    context_str = ""
    try:
        ctx = _extract_json(prepass_response)
        parts = []
        if ctx.get("mechanism_type"):
            parts.append(f"Mechanism: {ctx['mechanism_type']}")
        if ctx.get("expected_joint_ranges"):
            parts.append(f"Expected ranges: {ctx['expected_joint_ranges']}")
        if ctx.get("validation_context"):
            parts.append(f"Validation notes: {ctx['validation_context']}")
        context_str = "\n".join(parts)
    except Exception:
        pass  # pre-pass parse failure is non-fatal; main pass runs without context

    # ── Pass 2: Main physics analysis ───────────────────────────────────────
    print("[cosmos_client] Pass 2/3 — main physics analysis ...")
    prompt = _build_prompt(sg_filtered, context_str=context_str)
    response = _run_model(
        model, processor, SYSTEM_PROMPT,
        render_paths, prompt,
        max_new_tokens=max_new_tokens, temperature=temperature,
    )

    try:
        raw = _extract_json(response)
    except (ValueError, Exception) as e:
        print(f"[cosmos_client] JSON extraction failed ({e}); returning empty analysis")
        raw = {"geom_prims": [], "joint_prims": [], "global_notes": f"Parse error: {e}"}

    raw = _fix_joint_validity(raw, full_response=response)
    raw = _fix_cleared_joint_validity(raw, sg_filtered)
    raw = _apply_mass_correction(raw, scene_graph)
    raw = _apply_prismatic_rules(raw, scene_graph)

    # ── Pass 3: Verification pass ────────────────────────────────────────────
    print("[cosmos_client] Pass 3/3 — verification pass ...")
    verification_prompt = _build_verification_prompt(raw, sg_filtered)
    verification_response = _run_model(
        model, processor, VERIFICATION_SYSTEM_PROMPT,
        render_paths, verification_prompt,
        max_new_tokens=2048, temperature=temperature,
    )
    print(f"[cosmos_client] Verification output:\n{verification_response}")

    raw = _apply_verification(raw, verification_response, sg_filtered)
    # Re-apply deterministic prismatic rule — verification cannot override physics
    raw = _apply_prismatic_rules(raw, scene_graph)

    analysis = PhysicsAnalysis(**raw)

    cot = (
        f"=== PASS 1: CONTEXT PRE-PASS ===\n{prepass_response}\n\n"
        f"=== PASS 2: MAIN ANALYSIS ===\n{response}\n\n"
        f"=== PASS 3: VERIFICATION ===\n{verification_response}"
    )
    return analysis, cot
