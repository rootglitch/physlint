"""
Create 3 benchmark USD scenes with known physics ground truth.

Run once to set up the benchmark dataset:
  conda run -n physint python assets/create_bench_scenes.py

Produces:
  assets/bench_revolute_limits.usda   — robot chain, 5 prims, 4 revolute joints (2 violated, 2 valid)
  assets/bench_mass_materials.usda    — material diversity, 4 prims, 0 joints
  assets/bench_mixed.usda             — combined, 3 prims, 3 revolute joints (1 violated, 2 valid)
  assets/bench_prismatic_limits.usda  — linear actuator, 3 prims, 4 prismatic joints (2 violated, 2 valid)
  assets/benchmark_gt.json            — ground truth manifest (joint flags + analytical masses)

Ground truth masses are computed analytically as:
  mass_kg = true_volume_m3 × density_kg_m3

where true_volume uses exact primitive formulas (not bbox):
  Cylinder: π × r² × h
  Sphere:   (4/3) × π × r³
  Cube:     a³  (fill_factor = 1.0, exact)
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from pxr import Usd, UsdGeom, UsdShade, Gf, Sdf

ASSETS = Path(__file__).parent
MPU = 0.01  # 1 stage unit = 1 cm


# ---------------------------------------------------------------------------
# Shared helpers (identical to create_demo.py)
# ---------------------------------------------------------------------------

def _set_transform(xformable: UsdGeom.Xformable, translate=(0, 0, 0), scale=(1, 1, 1)):
    xformable.AddXformOp(UsdGeom.XformOp.TypeTranslate).Set(Gf.Vec3d(*translate))
    xformable.AddXformOp(UsdGeom.XformOp.TypeScale).Set(Gf.Vec3d(*scale))


def _mat(stage, path, diffuse, metallic=0.0, roughness=0.5):
    mat = UsdShade.Material.Define(stage, path)
    sh = UsdShade.Shader.Define(stage, path + "/Shader")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*diffuse))
    sh.CreateInput("metallic",     Sdf.ValueTypeNames.Float).Set(metallic)
    sh.CreateInput("roughness",    Sdf.ValueTypeNames.Float).Set(roughness)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    return mat


def _bind(prim, mat):
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat)


def _prismatic(stage, path, lower, upper, axis="Y", body0=None, body1=None):
    j = stage.DefinePrim(path, "PhysicsPrismaticJoint")
    j.CreateAttribute("physics:lowerLimit", Sdf.ValueTypeNames.Float).Set(float(lower))
    j.CreateAttribute("physics:upperLimit", Sdf.ValueTypeNames.Float).Set(float(upper))
    j.CreateAttribute("physics:axis",       Sdf.ValueTypeNames.Token).Set(axis)
    if body0:
        j.CreateRelationship("physics:body0").SetTargets([Sdf.Path(body0)])
    if body1:
        j.CreateRelationship("physics:body1").SetTargets([Sdf.Path(body1)])
    return j


def _revolute(stage, path, lower, upper, body0=None, body1=None):
    j = stage.DefinePrim(path, "PhysicsRevoluteJoint")
    j.CreateAttribute("physics:lowerLimit", Sdf.ValueTypeNames.Float).Set(float(lower))
    j.CreateAttribute("physics:upperLimit", Sdf.ValueTypeNames.Float).Set(float(upper))
    j.CreateAttribute("physics:axis",       Sdf.ValueTypeNames.Token).Set("Z")
    if body0:
        j.CreateRelationship("physics:body0").SetTargets([Sdf.Path(body0)])
    if body1:
        j.CreateRelationship("physics:body1").SetTargets([Sdf.Path(body1)])
    return j


def _new_stage(path):
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, MPU)
    root = stage.DefinePrim("/World", "Xform")
    stage.SetDefaultPrim(root)
    return stage


# ---------------------------------------------------------------------------
# Ground-truth mass helpers
# ---------------------------------------------------------------------------

def _mass_cyl(r_cm, h_cm, density):
    r, h = r_cm * MPU, h_cm * MPU
    return math.pi * r ** 2 * h * density


def _mass_sphere(r_cm, density):
    r = r_cm * MPU
    return (4 / 3) * math.pi * r ** 3 * density


def _mass_cube(edge_cm, density):
    e = edge_cm * MPU
    return e ** 3 * density


def _mass_box(a_cm, b_cm, c_cm, density):
    """Mass of a rectangular prism a×b×c cm (Cube with scale=(a,b,c))."""
    return a_cm * MPU * b_cm * MPU * c_cm * MPU * density


# ---------------------------------------------------------------------------
# Scene 1: bench_revolute_limits
# A robot arm chain that tests joint-limit violation detection.
#
# Geometry (no physics authored):
#   Base     — Steel  Cylinder r=20 h=10  (heavy base disk)
#   Link1    — Alum   Cylinder r=5  h=30  (upper arm)
#   Link2    — Alum   Cylinder r=4  h=25  (forearm)
#   Link3    — Alum   Cylinder r=3  h=20  (wrist link)
#   Gripper  — Rubber Sphere   r=5        (end effector)
#
# Joints (4 total):
#   ShoulderYaw  —  -90°..90°   ← VALID   (industrial shoulder rotation)
#   Elbow        —  -10°..220°  ← VIOLATED (human elbow max ~145°)
#   WristPitch   —  -80°..80°   ← VALID   (wrist pitch)
#   WristRoll    —  -10°..260°  ← VIOLATED (wrist roll 260° anatomically impossible)
# ---------------------------------------------------------------------------

def create_bench_revolute_limits(out: Path) -> list[dict]:
    """Returns GT mass records for each geometry prim."""
    stage = _new_stage(out)

    m_steel = _mat(stage, "/World/Mats/Steel",   (0.65, 0.67, 0.70), roughness=0.40)
    m_alum  = _mat(stage, "/World/Mats/Alum",    (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber= _mat(stage, "/World/Mats/Rubber",  (0.03, 0.03, 0.03), roughness=0.98)

    # Geometry — laid out vertically like a stacked arm
    base = UsdGeom.Cylinder.Define(stage, "/World/RobotChain/Base")
    base.GetRadiusAttr().Set(20.0); base.GetHeightAttr().Set(10.0)
    _set_transform(base, translate=(0, 5, 0))
    _bind(base.GetPrim(), m_steel)

    lk1 = UsdGeom.Cylinder.Define(stage, "/World/RobotChain/Link1")
    lk1.GetRadiusAttr().Set(5.0); lk1.GetHeightAttr().Set(30.0)
    _set_transform(lk1, translate=(0, 25, 0))
    _bind(lk1.GetPrim(), m_alum)

    lk2 = UsdGeom.Cylinder.Define(stage, "/World/RobotChain/Link2")
    lk2.GetRadiusAttr().Set(4.0); lk2.GetHeightAttr().Set(25.0)
    _set_transform(lk2, translate=(0, 52, 0))
    _bind(lk2.GetPrim(), m_alum)

    lk3 = UsdGeom.Cylinder.Define(stage, "/World/RobotChain/Link3")
    lk3.GetRadiusAttr().Set(3.0); lk3.GetHeightAttr().Set(20.0)
    _set_transform(lk3, translate=(0, 74, 0))
    _bind(lk3.GetPrim(), m_alum)

    grip = UsdGeom.Sphere.Define(stage, "/World/RobotChain/Gripper")
    grip.GetRadiusAttr().Set(5.0)
    _set_transform(grip, translate=(0, 89, 0))
    _bind(grip.GetPrim(), m_rubber)

    # Joints
    _revolute(stage, "/World/RobotChain/Joints/ShoulderYaw", -90,  90,
              "/World/RobotChain/Base",  "/World/RobotChain/Link1")
    _revolute(stage, "/World/RobotChain/Joints/Elbow",       -10, 220,
              "/World/RobotChain/Link1", "/World/RobotChain/Link2")
    _revolute(stage, "/World/RobotChain/Joints/WristPitch",  -80,  80,
              "/World/RobotChain/Link2", "/World/RobotChain/Link3")
    _revolute(stage, "/World/RobotChain/Joints/WristRoll",   -10, 260,
              "/World/RobotChain/Link3", "/World/RobotChain/Gripper")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (5 prims, 4 joints: 2 violated)")

    return [
        {"path": "/World/RobotChain/Base",    "material": "steel",    "mass_kg": round(_mass_cyl(20, 10, 7850), 2)},
        {"path": "/World/RobotChain/Link1",   "material": "aluminum", "mass_kg": round(_mass_cyl( 5, 30, 2700), 2)},
        {"path": "/World/RobotChain/Link2",   "material": "aluminum", "mass_kg": round(_mass_cyl( 4, 25, 2700), 2)},
        {"path": "/World/RobotChain/Link3",   "material": "aluminum", "mass_kg": round(_mass_cyl( 3, 20, 2700), 2)},
        {"path": "/World/RobotChain/Gripper", "material": "rubber",   "mass_kg": round(_mass_sphere(5, 1200),  3)},
    ]


# ---------------------------------------------------------------------------
# Scene 2: bench_mass_materials
# Designed specifically to test mass estimation accuracy.
# Wide spread of materials and densities; no joints.
#
# Geometry:
#   SteelCylinder  — Steel    Cylinder r=10 h=40   (98.65 kg)
#   RubberSphere   — Rubber   Sphere   r=8          ( 2.57 kg)
#   ConcreteCube   — Concrete Cube     edge=30       (62.10 kg)
#   AlumCylinder   — Aluminum Cylinder r=5  h=20    ( 4.24 kg)
# ---------------------------------------------------------------------------

def create_bench_mass_materials(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel    = _mat(stage, "/World/Mats/Steel",    (0.65, 0.67, 0.70), roughness=0.40)
    m_rubber   = _mat(stage, "/World/Mats/Rubber",   (0.03, 0.03, 0.03), roughness=0.98)
    m_concrete = _mat(stage, "/World/Mats/Concrete", (0.55, 0.53, 0.50), roughness=0.90)
    m_alum     = _mat(stage, "/World/Mats/Alum",     (0.80, 0.83, 0.87), roughness=0.35)

    # Steel cylinder — large, heavy, center of scene
    sc = UsdGeom.Cylinder.Define(stage, "/World/SteelCylinder")
    sc.GetRadiusAttr().Set(10.0); sc.GetHeightAttr().Set(40.0)
    _set_transform(sc, translate=(0, 20, 0))
    _bind(sc.GetPrim(), m_steel)

    # Rubber sphere — small, light, to the left
    rs = UsdGeom.Sphere.Define(stage, "/World/RubberSphere")
    rs.GetRadiusAttr().Set(8.0)
    _set_transform(rs, translate=(-35, 8, 0))
    _bind(rs.GetPrim(), m_rubber)

    # Concrete cube — to the right
    # UsdGeom.Cube size is half-extent; size=15 → edge=30 cm
    cc = UsdGeom.Cube.Define(stage, "/World/ConcreteCube")
    cc.GetSizeAttr().Set(1.0)
    _set_transform(cc, translate=(40, 15, 0), scale=(15.0, 15.0, 15.0))
    _bind(cc.GetPrim(), m_concrete)

    # Aluminum cylinder — behind, smaller
    ac = UsdGeom.Cylinder.Define(stage, "/World/AlumCylinder")
    ac.GetRadiusAttr().Set(5.0); ac.GetHeightAttr().Set(20.0)
    _set_transform(ac, translate=(0, 10, -35))
    _bind(ac.GetPrim(), m_alum)

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (4 prims, 0 joints)")

    # ConcreteCube: UsdGeom.Cube size=1 (full edge=1), scale=(15,15,15) → actual edge=15 stage units.
    # Note: UsdGeom.Cube "size" is the full edge length, NOT the half-extent.
    return [
        {"path": "/World/SteelCylinder", "material": "steel",    "mass_kg": round(_mass_cyl(10, 40, 7850), 2)},
        {"path": "/World/RubberSphere",  "material": "rubber",   "mass_kg": round(_mass_sphere(8, 1200),   2)},
        {"path": "/World/ConcreteCube",  "material": "concrete", "mass_kg": round(_mass_cube(15, 2300),    3)},
        {"path": "/World/AlumCylinder",  "material": "aluminum", "mass_kg": round(_mass_cyl( 5, 20, 2700), 3)},
    ]


# ---------------------------------------------------------------------------
# Scene 3: bench_mixed
# Combined test: mass estimation + joint violation detection.
#
# Geometry:
#   SteelFrame  — Steel    Cube     edge=25  (122.66 kg)
#   AlumArm     — Aluminum Cylinder r=6 h=40 ( 12.22 kg)
#   RubberPad   — Rubber   Cylinder r=5 h=4  (  0.38 kg)
#
# Joints:
#   BaseRevolute   —  -45°..45°   ← VALID   (rotation base)
#   ElbowRevolute  —  -10°..190°  ← VIOLATED (190° exceeds anatomical limit)
#   WristRevolute  —  -70°..70°   ← VALID   (reasonable wrist)
# ---------------------------------------------------------------------------

def create_bench_mixed(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel  = _mat(stage, "/World/Mats/Steel",  (0.65, 0.67, 0.70), roughness=0.40)
    m_alum   = _mat(stage, "/World/Mats/Alum",   (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber = _mat(stage, "/World/Mats/Rubber", (0.03, 0.03, 0.03), roughness=0.98)

    # Steel cube base (centered, sitting on ground)
    frame = UsdGeom.Cube.Define(stage, "/World/Assembly/SteelFrame")
    frame.GetSizeAttr().Set(1.0)
    _set_transform(frame, translate=(0, 12.5, 0), scale=(12.5, 12.5, 12.5))
    _bind(frame.GetPrim(), m_steel)

    # Aluminum arm cylinder on the right
    arm = UsdGeom.Cylinder.Define(stage, "/World/Assembly/AlumArm")
    arm.GetRadiusAttr().Set(6.0); arm.GetHeightAttr().Set(40.0)
    _set_transform(arm, translate=(30, 20, 0))
    _bind(arm.GetPrim(), m_alum)

    # Rubber pad on the floor
    pad = UsdGeom.Cylinder.Define(stage, "/World/Assembly/RubberPad")
    pad.GetRadiusAttr().Set(5.0); pad.GetHeightAttr().Set(4.0)
    _set_transform(pad, translate=(0, 2, 20))
    _bind(pad.GetPrim(), m_rubber)

    # Joints
    _revolute(stage, "/World/Assembly/Joints/BaseRevolute",  -45,  45,
              "/World/Assembly/SteelFrame", "/World/Assembly/AlumArm")
    _revolute(stage, "/World/Assembly/Joints/ElbowRevolute", -10, 190,
              "/World/Assembly/AlumArm",   "/World/Assembly/RubberPad")
    _revolute(stage, "/World/Assembly/Joints/WristRevolute", -70,  70,
              "/World/Assembly/RubberPad", "/World/Assembly/SteelFrame")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (3 prims, 3 joints: 1 violated)")

    # SteelFrame: UsdGeom.Cube size=1 (full edge=1), scale=(12.5,12.5,12.5) → actual edge=12.5 cm.
    return [
        {"path": "/World/Assembly/SteelFrame", "material": "steel",    "mass_kg": round(_mass_cube(12.5, 7850), 2)},
        {"path": "/World/Assembly/AlumArm",    "material": "aluminum", "mass_kg": round(_mass_cyl(6, 40, 2700), 2)},
        {"path": "/World/Assembly/RubberPad",  "material": "rubber",   "mass_kg": round(_mass_cyl(5,  4, 1200), 4)},
    ]


# ---------------------------------------------------------------------------
# Scene 4: bench_prismatic_limits
# A linear actuator assembly — tests prismatic (slider) joint violation detection.
#
# Geometry (no physics authored):
#   SliderBase     — Steel    Cube     30×4×15 cm  (14.13 kg) — the track/rail
#   CarriageBlock  — Aluminum Cube     12×12×12 cm  (4.67 kg) — the moving carriage
#   ActuatorRod    — Steel    Cylinder r=2 h=30 cm   (2.96 kg) — the piston rod
#
# Joints (4 prismatic, limits in stage units = cm):
#   SliderTravel    —  lower=-15, upper=15  ← VALID    (30cm travel fits in 30cm rail)
#   ActuatorStroke  —  lower=0,  upper=180  ← VIOLATED (180cm stroke, rod is 30cm)
#   CarriageRetract —  lower=-10, upper=0   ← VALID    (10cm retract, within rail)
#   RodOverExtend   —  lower=-80, upper=80  ← VIOLATED (160cm total, rod is 30cm)
# ---------------------------------------------------------------------------

def create_bench_prismatic_limits(out: Path) -> list[dict]:
    """Returns GT mass records for each geometry prim."""
    stage = _new_stage(out)

    m_steel = _mat(stage, "/World/Mats/Steel", (0.65, 0.67, 0.70), roughness=0.40)
    m_alum  = _mat(stage, "/World/Mats/Alum",  (0.80, 0.83, 0.87), roughness=0.35)

    # Slider base — flat steel rail, sits on the ground
    base = UsdGeom.Cube.Define(stage, "/World/Actuator/SliderBase")
    base.GetSizeAttr().Set(1.0)
    _set_transform(base, translate=(0, 2, 0), scale=(30.0, 4.0, 15.0))
    _bind(base.GetPrim(), m_steel)

    # Carriage block — aluminum block that slides along the rail
    carriage = UsdGeom.Cube.Define(stage, "/World/Actuator/CarriageBlock")
    carriage.GetSizeAttr().Set(1.0)
    _set_transform(carriage, translate=(0, 10, 0), scale=(12.0, 12.0, 12.0))
    _bind(carriage.GetPrim(), m_alum)

    # Actuator rod — steel cylinder extending upward from carriage
    rod = UsdGeom.Cylinder.Define(stage, "/World/Actuator/ActuatorRod")
    rod.GetRadiusAttr().Set(2.0); rod.GetHeightAttr().Set(30.0)
    _set_transform(rod, translate=(0, 31, 0))
    _bind(rod.GetPrim(), m_steel)

    # Joints — all prismatic (linear slider), axis=Y (vertical)
    _prismatic(stage, "/World/Actuator/Joints/SliderTravel",    -15,  15,  axis="X",
               body0="/World/Actuator/SliderBase",   body1="/World/Actuator/CarriageBlock")
    _prismatic(stage, "/World/Actuator/Joints/ActuatorStroke",    0, 180,  axis="Y",
               body0="/World/Actuator/CarriageBlock", body1="/World/Actuator/ActuatorRod")
    _prismatic(stage, "/World/Actuator/Joints/CarriageRetract",  -10,   0, axis="X",
               body0="/World/Actuator/SliderBase",   body1="/World/Actuator/CarriageBlock")
    _prismatic(stage, "/World/Actuator/Joints/RodOverExtend",    -80,  80,  axis="Y",
               body0="/World/Actuator/CarriageBlock", body1="/World/Actuator/ActuatorRod")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (3 prims, 4 prismatic joints: 2 violated)")

    # SliderBase:    Cube size=1 scale=(30,4,15) → bbox 30×4×15 cm → vol = 0.30×0.04×0.15 = 0.0018 m³
    # CarriageBlock: Cube size=1 scale=(12,12,12) → edge 12 cm   → vol = 0.12³            = 0.001728 m³
    # ActuatorRod:   Cylinder r=2 h=30             → r=0.02 h=0.30 → vol = π×0.02²×0.30   = 0.0003770 m³
    return [
        {"path": "/World/Actuator/SliderBase",    "material": "steel",    "mass_kg": round(0.30 * 0.04 * 0.15 * 7850, 2)},
        {"path": "/World/Actuator/CarriageBlock", "material": "aluminum", "mass_kg": round(0.12 ** 3 * 2700,            2)},
        {"path": "/World/Actuator/ActuatorRod",   "material": "steel",    "mass_kg": round(math.pi * 0.02**2 * 0.30 * 7850, 2)},
    ]


# ---------------------------------------------------------------------------
# Scene 5: bench_humanoid_arm
# 6-DOF humanoid-style arm: shoulder (3-axis), elbow, wrist (2-axis).
#
# Geometry:
#   ShoulderLink — Alum  Cylinder r=7  h=12  (shoulder hub)
#   UpperArm     — Alum  Cylinder r=5  h=30  (upper arm)
#   Forearm      — Alum  Cylinder r=4  h=25  (forearm)
#   WristLink    — Alum  Cylinder r=3  h=8   (wrist)
#   Hand         — Rubber Sphere  r=6        (end effector)
#
# Joints (6 revolute):
#   ShoulderFlexion  — -60°..170°  ← VALID   (normal human range)
#   ShoulderAbduct   — -45°..200°  ← VIOLATED (abduction max ~180°)
#   ShoulderRotation — -90°..90°   ← VALID
#   ElbowFlexion     —   0°..145°  ← VALID
#   WristFlexion     — -70°..70°   ← VALID
#   WristSupination  — -90°..200°  ← VIOLATED (supination max ~90°)
# ---------------------------------------------------------------------------

def create_bench_humanoid_arm(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_alum   = _mat(stage, "/World/Mats/Alum",   (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber = _mat(stage, "/World/Mats/Rubber", (0.03, 0.03, 0.03), roughness=0.98)

    sh = UsdGeom.Cylinder.Define(stage, "/World/Arm/ShoulderLink")
    sh.GetRadiusAttr().Set(7.0); sh.GetHeightAttr().Set(12.0)
    _set_transform(sh, translate=(0, 6, 0))
    _bind(sh.GetPrim(), m_alum)

    ua = UsdGeom.Cylinder.Define(stage, "/World/Arm/UpperArm")
    ua.GetRadiusAttr().Set(5.0); ua.GetHeightAttr().Set(30.0)
    _set_transform(ua, translate=(0, 27, 0))
    _bind(ua.GetPrim(), m_alum)

    fa = UsdGeom.Cylinder.Define(stage, "/World/Arm/Forearm")
    fa.GetRadiusAttr().Set(4.0); fa.GetHeightAttr().Set(25.0)
    _set_transform(fa, translate=(0, 54, 0))
    _bind(fa.GetPrim(), m_alum)

    wl = UsdGeom.Cylinder.Define(stage, "/World/Arm/WristLink")
    wl.GetRadiusAttr().Set(3.0); wl.GetHeightAttr().Set(8.0)
    _set_transform(wl, translate=(0, 73, 0))
    _bind(wl.GetPrim(), m_alum)

    hd = UsdGeom.Sphere.Define(stage, "/World/Arm/Hand")
    hd.GetRadiusAttr().Set(6.0)
    _set_transform(hd, translate=(0, 83, 0))
    _bind(hd.GetPrim(), m_rubber)

    _revolute(stage, "/World/Arm/Joints/ShoulderFlexion",  -60, 170,
              "/World/Arm/ShoulderLink", "/World/Arm/UpperArm")
    _revolute(stage, "/World/Arm/Joints/ShoulderAbduct",   -45, 200,
              "/World/Arm/ShoulderLink", "/World/Arm/UpperArm")
    _revolute(stage, "/World/Arm/Joints/ShoulderRotation", -90,  90,
              "/World/Arm/ShoulderLink", "/World/Arm/UpperArm")
    _revolute(stage, "/World/Arm/Joints/ElbowFlexion",       0, 145,
              "/World/Arm/UpperArm",     "/World/Arm/Forearm")
    _revolute(stage, "/World/Arm/Joints/WristFlexion",     -70,  70,
              "/World/Arm/Forearm",      "/World/Arm/WristLink")
    _revolute(stage, "/World/Arm/Joints/WristSupination",  -90, 200,
              "/World/Arm/WristLink",    "/World/Arm/Hand")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (5 prims, 6 joints: 2 violated)")
    return [
        {"path": "/World/Arm/ShoulderLink", "material": "aluminum", "mass_kg": round(_mass_cyl(7, 12, 2700), 2)},
        {"path": "/World/Arm/UpperArm",     "material": "aluminum", "mass_kg": round(_mass_cyl(5, 30, 2700), 2)},
        {"path": "/World/Arm/Forearm",      "material": "aluminum", "mass_kg": round(_mass_cyl(4, 25, 2700), 2)},
        {"path": "/World/Arm/WristLink",    "material": "aluminum", "mass_kg": round(_mass_cyl(3,  8, 2700), 3)},
        {"path": "/World/Arm/Hand",         "material": "rubber",   "mass_kg": round(_mass_sphere(6, 1200),  3)},
    ]


# ---------------------------------------------------------------------------
# Scene 6: bench_all_valid
# All 5 revolute joints are within normal limits — tests false-positive rate.
#
# Geometry:
#   Base      — Steel  Cube     25×8×25 cm
#   Link1     — Alum   Cylinder r=5 h=35
#   Link2     — Alum   Cylinder r=4 h=30
#   Link3     — Alum   Cylinder r=3 h=20
#   ToolHead  — Alum   Cylinder r=2 h=10
#
# Joints (5 revolute, all valid):
#   BaseTurn     — -90°..90°   ← VALID
#   ShoulderLift — -30°..120°  ← VALID
#   ElbowBend    —   0°..135°  ← VALID
#   WristTilt    — -60°..60°   ← VALID
#   ToolSpin     — -175°..175° ← VALID (full-range spin tool)
# ---------------------------------------------------------------------------

def create_bench_all_valid(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel = _mat(stage, "/World/Mats/Steel", (0.65, 0.67, 0.70), roughness=0.40)
    m_alum  = _mat(stage, "/World/Mats/Alum",  (0.80, 0.83, 0.87), roughness=0.35)

    base = UsdGeom.Cube.Define(stage, "/World/Robot/Base")
    base.GetSizeAttr().Set(1.0)
    _set_transform(base, translate=(0, 4, 0), scale=(25.0, 8.0, 25.0))
    _bind(base.GetPrim(), m_steel)

    lk1 = UsdGeom.Cylinder.Define(stage, "/World/Robot/Link1")
    lk1.GetRadiusAttr().Set(5.0); lk1.GetHeightAttr().Set(35.0)
    _set_transform(lk1, translate=(0, 25.5, 0))
    _bind(lk1.GetPrim(), m_alum)

    lk2 = UsdGeom.Cylinder.Define(stage, "/World/Robot/Link2")
    lk2.GetRadiusAttr().Set(4.0); lk2.GetHeightAttr().Set(30.0)
    _set_transform(lk2, translate=(0, 58, 0))
    _bind(lk2.GetPrim(), m_alum)

    lk3 = UsdGeom.Cylinder.Define(stage, "/World/Robot/Link3")
    lk3.GetRadiusAttr().Set(3.0); lk3.GetHeightAttr().Set(20.0)
    _set_transform(lk3, translate=(0, 83, 0))
    _bind(lk3.GetPrim(), m_alum)

    th = UsdGeom.Cylinder.Define(stage, "/World/Robot/ToolHead")
    th.GetRadiusAttr().Set(2.0); th.GetHeightAttr().Set(10.0)
    _set_transform(th, translate=(0, 98, 0))
    _bind(th.GetPrim(), m_alum)

    _revolute(stage, "/World/Robot/Joints/BaseTurn",     -90, 90,
              "/World/Robot/Base",     "/World/Robot/Link1")
    _revolute(stage, "/World/Robot/Joints/ShoulderLift", -30, 120,
              "/World/Robot/Link1",    "/World/Robot/Link2")
    _revolute(stage, "/World/Robot/Joints/ElbowBend",      0, 135,
              "/World/Robot/Link2",    "/World/Robot/Link3")
    _revolute(stage, "/World/Robot/Joints/WristTilt",    -60,  60,
              "/World/Robot/Link3",    "/World/Robot/ToolHead")
    _revolute(stage, "/World/Robot/Joints/ToolSpin",    -175, 175,
              "/World/Robot/ToolHead", "/World/Robot/Link3")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (5 prims, 5 joints: 0 violated)")
    return [
        {"path": "/World/Robot/Base",     "material": "steel",    "mass_kg": round(_mass_box(25, 8, 25, 7850), 2)},
        {"path": "/World/Robot/Link1",    "material": "aluminum", "mass_kg": round(_mass_cyl(5, 35, 2700), 2)},
        {"path": "/World/Robot/Link2",    "material": "aluminum", "mass_kg": round(_mass_cyl(4, 30, 2700), 2)},
        {"path": "/World/Robot/Link3",    "material": "aluminum", "mass_kg": round(_mass_cyl(3, 20, 2700), 2)},
        {"path": "/World/Robot/ToolHead", "material": "aluminum", "mass_kg": round(_mass_cyl(2, 10, 2700), 3)},
    ]


# ---------------------------------------------------------------------------
# Scene 7: bench_crane
# Tower crane: slew + boom lift (both valid) + jib swing + hook travel (violated).
#
# Geometry:
#   CraneBase     — Steel    Cube     40×6×40 cm  (foundation)
#   CraneMast     — Steel    Cylinder r=5 h=80    (vertical mast)
#   CraneBoom     — Alum     Cube     60×6×6 cm   (horizontal jib boom)
#   CounterWeight — Concrete Cube     15×15×15 cm (counterweight block)
#   HookRod       — Steel    Cylinder r=2 h=80    (hook cable rod)
#
# Joints:
#   SlewRing   — revolute  -180°..180°  ← VALID   (crane can rotate ±180°)
#   BoomLift   — revolute    -5°..55°   ← VALID   (boom elevation)
#   JibSwing   — revolute   -10°..195°  ← VIOLATED (jib swing > 180°)
#   HookTravel — prismatic  body0=CraneMast(h=80), travel=250 > 80  ← VIOLATED
# ---------------------------------------------------------------------------

def create_bench_crane(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel    = _mat(stage, "/World/Mats/Steel",    (0.65, 0.67, 0.70), roughness=0.40)
    m_alum     = _mat(stage, "/World/Mats/Alum",     (0.80, 0.83, 0.87), roughness=0.35)
    m_concrete = _mat(stage, "/World/Mats/Concrete", (0.55, 0.53, 0.50), roughness=0.90)

    cb = UsdGeom.Cube.Define(stage, "/World/Crane/CraneBase")
    cb.GetSizeAttr().Set(1.0)
    _set_transform(cb, translate=(0, 3, 0), scale=(40.0, 6.0, 40.0))
    _bind(cb.GetPrim(), m_steel)

    cm = UsdGeom.Cylinder.Define(stage, "/World/Crane/CraneMast")
    cm.GetRadiusAttr().Set(5.0); cm.GetHeightAttr().Set(80.0)
    _set_transform(cm, translate=(0, 46, 0))
    _bind(cm.GetPrim(), m_steel)

    bm = UsdGeom.Cube.Define(stage, "/World/Crane/CraneBoom")
    bm.GetSizeAttr().Set(1.0)
    _set_transform(bm, translate=(30, 89, 0), scale=(60.0, 6.0, 6.0))
    _bind(bm.GetPrim(), m_alum)

    cw = UsdGeom.Cube.Define(stage, "/World/Crane/CounterWeight")
    cw.GetSizeAttr().Set(1.0)
    _set_transform(cw, translate=(-20, 89, 0), scale=(15.0, 15.0, 15.0))
    _bind(cw.GetPrim(), m_concrete)

    hr = UsdGeom.Cylinder.Define(stage, "/World/Crane/HookRod")
    hr.GetRadiusAttr().Set(2.0); hr.GetHeightAttr().Set(80.0)
    _set_transform(hr, translate=(50, 49, 0))
    _bind(hr.GetPrim(), m_steel)

    _revolute(stage, "/World/Crane/Joints/SlewRing",  -180, 180,
              "/World/Crane/CraneBase", "/World/Crane/CraneMast")
    _revolute(stage, "/World/Crane/Joints/BoomLift",    -5,  55,
              "/World/Crane/CraneMast", "/World/Crane/CraneBoom")
    _revolute(stage, "/World/Crane/Joints/JibSwing",   -10, 195,
              "/World/Crane/CraneBoom", "/World/Crane/CounterWeight")
    # HookTravel: CraneMast h=80, HookRod h=80 → max=80; travel=250 > 80 → VIOLATED
    _prismatic(stage, "/World/Crane/Joints/HookTravel", 0, 250, axis="Y",
               body0="/World/Crane/CraneMast", body1="/World/Crane/HookRod")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (5 prims, 4 joints: 2 violated)")
    return [
        {"path": "/World/Crane/CraneBase",     "material": "steel",    "mass_kg": round(_mass_box(40, 6, 40, 7850),  2)},
        {"path": "/World/Crane/CraneMast",     "material": "steel",    "mass_kg": round(_mass_cyl(5, 80, 7850),      2)},
        {"path": "/World/Crane/CraneBoom",     "material": "aluminum", "mass_kg": round(_mass_box(60, 6, 6, 2700),   2)},
        {"path": "/World/Crane/CounterWeight", "material": "concrete", "mass_kg": round(_mass_box(15, 15, 15, 2300), 3)},
        {"path": "/World/Crane/HookRod",       "material": "steel",    "mass_kg": round(_mass_cyl(2, 80, 7850),      2)},
    ]


# ---------------------------------------------------------------------------
# Scene 8: bench_symmetric_violation
# Tests symmetric impossible joint ranges (total range > 360°).
#
# Geometry:
#   RotorBase    — Steel    Cube     20×5×20 cm
#   ArmPivot     — Alum     Cylinder r=4 h=25
#   SwingFixture — Concrete Cube     15×5×15 cm (independent)
#   SwingArm     — Alum     Cylinder r=3 h=20
#   HalfBase     — Steel    Cube     10×8×10 cm (third fixture)
#   HalfArm      — Alum     Cylinder r=3 h=20
#
# Joints (3 revolute):
#   WideSwing    — -200°..200° ← VIOLATED (400° total range physically impossible)
#   TightPivot   —  -25°..25°  ← VALID
#   HalfRotation —  -90°..90°  ← VALID
# ---------------------------------------------------------------------------

def create_bench_symmetric_violation(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel    = _mat(stage, "/World/Mats/Steel",    (0.65, 0.67, 0.70), roughness=0.40)
    m_alum     = _mat(stage, "/World/Mats/Alum",     (0.80, 0.83, 0.87), roughness=0.35)
    m_concrete = _mat(stage, "/World/Mats/Concrete", (0.55, 0.53, 0.50), roughness=0.90)

    rb = UsdGeom.Cube.Define(stage, "/World/Assembly/RotorBase")
    rb.GetSizeAttr().Set(1.0)
    _set_transform(rb, translate=(0, 2.5, 0), scale=(20.0, 5.0, 20.0))
    _bind(rb.GetPrim(), m_steel)

    ap = UsdGeom.Cylinder.Define(stage, "/World/Assembly/ArmPivot")
    ap.GetRadiusAttr().Set(4.0); ap.GetHeightAttr().Set(25.0)
    _set_transform(ap, translate=(0, 19.5, 0))
    _bind(ap.GetPrim(), m_alum)

    sf = UsdGeom.Cube.Define(stage, "/World/Assembly/SwingFixture")
    sf.GetSizeAttr().Set(1.0)
    _set_transform(sf, translate=(50, 2.5, 0), scale=(15.0, 5.0, 15.0))
    _bind(sf.GetPrim(), m_concrete)

    sa = UsdGeom.Cylinder.Define(stage, "/World/Assembly/SwingArm")
    sa.GetRadiusAttr().Set(3.0); sa.GetHeightAttr().Set(20.0)
    _set_transform(sa, translate=(50, 15, 0))
    _bind(sa.GetPrim(), m_alum)

    hb = UsdGeom.Cube.Define(stage, "/World/Assembly/HalfBase")
    hb.GetSizeAttr().Set(1.0)
    _set_transform(hb, translate=(-50, 4, 0), scale=(10.0, 8.0, 10.0))
    _bind(hb.GetPrim(), m_steel)

    ha = UsdGeom.Cylinder.Define(stage, "/World/Assembly/HalfArm")
    ha.GetRadiusAttr().Set(3.0); ha.GetHeightAttr().Set(20.0)
    _set_transform(ha, translate=(-50, 18, 0))
    _bind(ha.GetPrim(), m_alum)

    _revolute(stage, "/World/Assembly/Joints/WideSwing",    -200, 200,
              "/World/Assembly/RotorBase",    "/World/Assembly/ArmPivot")
    _revolute(stage, "/World/Assembly/Joints/TightPivot",    -25,  25,
              "/World/Assembly/SwingFixture", "/World/Assembly/SwingArm")
    _revolute(stage, "/World/Assembly/Joints/HalfRotation",  -90,  90,
              "/World/Assembly/HalfBase",     "/World/Assembly/HalfArm")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (6 prims, 3 joints: 1 violated)")
    return [
        {"path": "/World/Assembly/RotorBase",    "material": "steel",    "mass_kg": round(_mass_box(20, 5, 20, 7850),  2)},
        {"path": "/World/Assembly/ArmPivot",     "material": "aluminum", "mass_kg": round(_mass_cyl(4, 25, 2700),      2)},
        {"path": "/World/Assembly/SwingFixture", "material": "concrete", "mass_kg": round(_mass_box(15, 5, 15, 2300),  2)},
        {"path": "/World/Assembly/SwingArm",     "material": "aluminum", "mass_kg": round(_mass_cyl(3, 20, 2700),      2)},
        {"path": "/World/Assembly/HalfBase",     "material": "steel",    "mass_kg": round(_mass_box(10, 8, 10, 7850),  2)},
        {"path": "/World/Assembly/HalfArm",      "material": "aluminum", "mass_kg": round(_mass_cyl(3, 20, 2700),      2)},
    ]


# ---------------------------------------------------------------------------
# Scene 9: bench_scara
# SCARA-style robot: 2 horizontal revolute arms + 1 vertical prismatic + tool spin.
#
# Geometry:
#   Base      — Steel  Cube     20×8×20 cm
#   ArmLink1  — Alum   Cube     35×6×6 cm   (horizontal arm in X)
#   ArmLink2  — Alum   Cube     25×6×6 cm   (second arm in X)
#   ZColumn   — Alum   Cylinder r=3 h=60    (vertical spindle)
#   ZCarriage — Alum   Cube     8×15×8 cm   (slides on ZColumn)
#   Tool      — Rubber Sphere   r=4
#
# Joints:
#   Joint1     — revolute  -150°..150°  ← VALID
#   Joint2     — revolute   -10°..210°  ← VIOLATED (elbow > 180°)
#   ZTravel    — prismatic  body0=ZColumn(h=60), travel=200 > 60  ← VIOLATED
#   ToolRotate — revolute  -175°..175°  ← VALID
# ---------------------------------------------------------------------------

def create_bench_scara(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel  = _mat(stage, "/World/Mats/Steel",  (0.65, 0.67, 0.70), roughness=0.40)
    m_alum   = _mat(stage, "/World/Mats/Alum",   (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber = _mat(stage, "/World/Mats/Rubber", (0.03, 0.03, 0.03), roughness=0.98)

    base = UsdGeom.Cube.Define(stage, "/World/Scara/Base")
    base.GetSizeAttr().Set(1.0)
    _set_transform(base, translate=(0, 4, 0), scale=(20.0, 8.0, 20.0))
    _bind(base.GetPrim(), m_steel)

    lk1 = UsdGeom.Cube.Define(stage, "/World/Scara/ArmLink1")
    lk1.GetSizeAttr().Set(1.0)
    _set_transform(lk1, translate=(17.5, 15, 0), scale=(35.0, 6.0, 6.0))
    _bind(lk1.GetPrim(), m_alum)

    lk2 = UsdGeom.Cube.Define(stage, "/World/Scara/ArmLink2")
    lk2.GetSizeAttr().Set(1.0)
    _set_transform(lk2, translate=(47.5, 15, 0), scale=(25.0, 6.0, 6.0))
    _bind(lk2.GetPrim(), m_alum)

    zc = UsdGeom.Cylinder.Define(stage, "/World/Scara/ZColumn")
    zc.GetRadiusAttr().Set(3.0); zc.GetHeightAttr().Set(60.0)
    _set_transform(zc, translate=(65, 45, 0))
    _bind(zc.GetPrim(), m_alum)

    zcar = UsdGeom.Cube.Define(stage, "/World/Scara/ZCarriage")
    zcar.GetSizeAttr().Set(1.0)
    _set_transform(zcar, translate=(65, 22.5, 0), scale=(8.0, 15.0, 8.0))
    _bind(zcar.GetPrim(), m_alum)

    tool = UsdGeom.Sphere.Define(stage, "/World/Scara/Tool")
    tool.GetRadiusAttr().Set(4.0)
    _set_transform(tool, translate=(65, 11, 0))
    _bind(tool.GetPrim(), m_rubber)

    _revolute(stage, "/World/Scara/Joints/Joint1",    -150, 150,
              "/World/Scara/Base",     "/World/Scara/ArmLink1")
    _revolute(stage, "/World/Scara/Joints/Joint2",     -10, 210,
              "/World/Scara/ArmLink1", "/World/Scara/ArmLink2")
    # ZTravel: ZColumn h=60, ZCarriage h=15 → max=60; travel=200 > 60 → VIOLATED
    _prismatic(stage, "/World/Scara/Joints/ZTravel", 0, 200, axis="Y",
               body0="/World/Scara/ZColumn", body1="/World/Scara/ZCarriage")
    _revolute(stage, "/World/Scara/Joints/ToolRotate", -175, 175,
              "/World/Scara/ZCarriage", "/World/Scara/Tool")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (6 prims, 4 joints: 2 violated)")
    return [
        {"path": "/World/Scara/Base",      "material": "steel",    "mass_kg": round(_mass_box(20, 8, 20, 7850),  2)},
        {"path": "/World/Scara/ArmLink1",  "material": "aluminum", "mass_kg": round(_mass_box(35, 6, 6, 2700),   2)},
        {"path": "/World/Scara/ArmLink2",  "material": "aluminum", "mass_kg": round(_mass_box(25, 6, 6, 2700),   2)},
        {"path": "/World/Scara/ZColumn",   "material": "aluminum", "mass_kg": round(_mass_cyl(3, 60, 2700),       2)},
        {"path": "/World/Scara/ZCarriage", "material": "aluminum", "mass_kg": round(_mass_box(8, 15, 8, 2700),   2)},
        {"path": "/World/Scara/Tool",      "material": "rubber",   "mass_kg": round(_mass_sphere(4, 1200),        3)},
    ]


# ---------------------------------------------------------------------------
# Scene 10: bench_gripper
# Parallel jaw gripper — tests prismatic finger joint limits.
#
# Geometry:
#   Palm         — Alum  Cube     30×8×15 cm  (palm body, 30cm wide)
#   MountBracket — Steel Cube     10×15×8 cm  (mounting bracket)
#   FingerL      — Rubber Cube    6×15×4 cm   (left finger)
#   FingerR      — Rubber Cube    6×15×4 cm   (right finger)
#
# Joints (4 prismatic, axis=X):
#   FingerL_Spread — body0=Palm(30cm X), travel=80 > 30  ← VIOLATED
#   FingerL_Close  — body0=Palm(30cm X), travel=8 ≤ 30   ← VALID
#   FingerR_Spread — body0=Palm(30cm X), travel=75 > 30  ← VIOLATED
#   FingerR_Close  — body0=Palm(30cm X), travel=8 ≤ 30   ← VALID
# ---------------------------------------------------------------------------

def create_bench_gripper(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel  = _mat(stage, "/World/Mats/Steel",  (0.65, 0.67, 0.70), roughness=0.40)
    m_alum   = _mat(stage, "/World/Mats/Alum",   (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber = _mat(stage, "/World/Mats/Rubber", (0.03, 0.03, 0.03), roughness=0.98)

    palm = UsdGeom.Cube.Define(stage, "/World/Gripper/Palm")
    palm.GetSizeAttr().Set(1.0)
    _set_transform(palm, translate=(0, 4, 0), scale=(30.0, 8.0, 15.0))
    _bind(palm.GetPrim(), m_alum)

    mb = UsdGeom.Cube.Define(stage, "/World/Gripper/MountBracket")
    mb.GetSizeAttr().Set(1.0)
    _set_transform(mb, translate=(0, 15.5, 0), scale=(10.0, 15.0, 8.0))
    _bind(mb.GetPrim(), m_steel)

    fl = UsdGeom.Cube.Define(stage, "/World/Gripper/FingerL")
    fl.GetSizeAttr().Set(1.0)
    _set_transform(fl, translate=(-18, 4, 0), scale=(6.0, 15.0, 4.0))
    _bind(fl.GetPrim(), m_rubber)

    fr = UsdGeom.Cube.Define(stage, "/World/Gripper/FingerR")
    fr.GetSizeAttr().Set(1.0)
    _set_transform(fr, translate=(18, 4, 0), scale=(6.0, 15.0, 4.0))
    _bind(fr.GetPrim(), m_rubber)

    # Palm 30cm along X; FingerL/R 6cm along X
    # max(30,6)=30; spread travel=80 > 30 VIOLATED; close travel=8 ≤ 30 VALID
    _prismatic(stage, "/World/Gripper/Joints/FingerL_Spread",  0, 80, axis="X",
               body0="/World/Gripper/Palm", body1="/World/Gripper/FingerL")
    _prismatic(stage, "/World/Gripper/Joints/FingerL_Close",  -8,  0, axis="X",
               body0="/World/Gripper/Palm", body1="/World/Gripper/FingerL")
    _prismatic(stage, "/World/Gripper/Joints/FingerR_Spread",  0, 75, axis="X",
               body0="/World/Gripper/Palm", body1="/World/Gripper/FingerR")
    _prismatic(stage, "/World/Gripper/Joints/FingerR_Close",  -8,  0, axis="X",
               body0="/World/Gripper/Palm", body1="/World/Gripper/FingerR")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (4 prims, 4 joints: 2 violated)")
    return [
        {"path": "/World/Gripper/Palm",         "material": "aluminum", "mass_kg": round(_mass_box(30, 8, 15, 2700),  2)},
        {"path": "/World/Gripper/MountBracket", "material": "steel",    "mass_kg": round(_mass_box(10, 15, 8, 7850),  2)},
        {"path": "/World/Gripper/FingerL",      "material": "rubber",   "mass_kg": round(_mass_box(6, 15, 4, 1200),   3)},
        {"path": "/World/Gripper/FingerR",      "material": "rubber",   "mass_kg": round(_mass_box(6, 15, 4, 1200),   3)},
    ]


# ---------------------------------------------------------------------------
# Scene 11: bench_excavator
# Excavator arm: 2 hydraulic cylinder (prismatic) + 2 revolute joints.
#
# Geometry:
#   Chassis    — Steel Cube     60×15×40 cm
#   Cab        — Steel Cube     25×25×30 cm
#   BoomArm    — Alum  Cylinder r=5 h=40   (main boom)
#   StickArm   — Alum  Cylinder r=4 h=35   (stick/dipper)
#   Bucket     — Alum  Cube     25×15×20 cm
#   BoomPiston — Steel Cube     4×10×4 cm  (hydraulic piston body)
#   StickPiston— Steel Cube     4×8×4 cm
#
# Joints:
#   BoomCylinder  — prismatic body0=BoomArm(h=40), travel=150 > 40  ← VIOLATED
#   ArmCylinder   — prismatic body0=StickArm(h=35), travel=120 > 35 ← VIOLATED
#   BucketCurl    — revolute  -45°..135°  ← VALID
#   CabSwing      — revolute  -170°..170° ← VALID
# ---------------------------------------------------------------------------

def create_bench_excavator(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel = _mat(stage, "/World/Mats/Steel", (0.65, 0.67, 0.70), roughness=0.40)
    m_alum  = _mat(stage, "/World/Mats/Alum",  (0.80, 0.83, 0.87), roughness=0.35)

    ch = UsdGeom.Cube.Define(stage, "/World/Excavator/Chassis")
    ch.GetSizeAttr().Set(1.0)
    _set_transform(ch, translate=(0, 7.5, 0), scale=(60.0, 15.0, 40.0))
    _bind(ch.GetPrim(), m_steel)

    cab = UsdGeom.Cube.Define(stage, "/World/Excavator/Cab")
    cab.GetSizeAttr().Set(1.0)
    _set_transform(cab, translate=(10, 32.5, 5), scale=(25.0, 25.0, 30.0))
    _bind(cab.GetPrim(), m_steel)

    ba = UsdGeom.Cylinder.Define(stage, "/World/Excavator/BoomArm")
    ba.GetRadiusAttr().Set(5.0); ba.GetHeightAttr().Set(40.0)
    _set_transform(ba, translate=(25, 55, 0))
    _bind(ba.GetPrim(), m_alum)

    sa = UsdGeom.Cylinder.Define(stage, "/World/Excavator/StickArm")
    sa.GetRadiusAttr().Set(4.0); sa.GetHeightAttr().Set(35.0)
    _set_transform(sa, translate=(25, 92.5, 0))
    _bind(sa.GetPrim(), m_alum)

    bkt = UsdGeom.Cube.Define(stage, "/World/Excavator/Bucket")
    bkt.GetSizeAttr().Set(1.0)
    _set_transform(bkt, translate=(25, 117.5, 0), scale=(25.0, 15.0, 20.0))
    _bind(bkt.GetPrim(), m_alum)

    bp = UsdGeom.Cube.Define(stage, "/World/Excavator/BoomPiston")
    bp.GetSizeAttr().Set(1.0)
    _set_transform(bp, translate=(35, 40, 10), scale=(4.0, 10.0, 4.0))
    _bind(bp.GetPrim(), m_steel)

    sp = UsdGeom.Cube.Define(stage, "/World/Excavator/StickPiston")
    sp.GetSizeAttr().Set(1.0)
    _set_transform(sp, translate=(35, 77, 8), scale=(4.0, 8.0, 4.0))
    _bind(sp.GetPrim(), m_steel)

    # BoomArm h=40, BoomPiston h=10 → max=40; travel=150 > 40 → VIOLATED
    _prismatic(stage, "/World/Excavator/Joints/BoomCylinder", 0, 150, axis="Y",
               body0="/World/Excavator/BoomArm",   body1="/World/Excavator/BoomPiston")
    # StickArm h=35, StickPiston h=8 → max=35; travel=120 > 35 → VIOLATED
    _prismatic(stage, "/World/Excavator/Joints/ArmCylinder",  0, 120, axis="Y",
               body0="/World/Excavator/StickArm",  body1="/World/Excavator/StickPiston")
    _revolute(stage, "/World/Excavator/Joints/BucketCurl",  -45, 135,
              "/World/Excavator/StickArm", "/World/Excavator/Bucket")
    _revolute(stage, "/World/Excavator/Joints/CabSwing",    -170, 170,
              "/World/Excavator/Chassis",  "/World/Excavator/Cab")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (7 prims, 4 joints: 2 violated)")
    return [
        {"path": "/World/Excavator/Chassis",     "material": "steel",    "mass_kg": round(_mass_box(60, 15, 40, 7850), 2)},
        {"path": "/World/Excavator/Cab",         "material": "steel",    "mass_kg": round(_mass_box(25, 25, 30, 7850), 2)},
        {"path": "/World/Excavator/BoomArm",     "material": "aluminum", "mass_kg": round(_mass_cyl(5, 40, 2700),       2)},
        {"path": "/World/Excavator/StickArm",    "material": "aluminum", "mass_kg": round(_mass_cyl(4, 35, 2700),       2)},
        {"path": "/World/Excavator/Bucket",      "material": "aluminum", "mass_kg": round(_mass_box(25, 15, 20, 2700),  2)},
        {"path": "/World/Excavator/BoomPiston",  "material": "steel",    "mass_kg": round(_mass_box(4, 10, 4, 7850),    3)},
        {"path": "/World/Excavator/StickPiston", "material": "steel",    "mass_kg": round(_mass_box(4, 8, 4, 7850),     3)},
    ]


# ---------------------------------------------------------------------------
# Scene 12: bench_wrist_3dof
# 3-DOF wrist (yaw/pitch/roll) + tool gripper travel.
#
# Geometry:
#   YawBase   — Steel Cylinder r=8 h=10
#   YawLink   — Alum  Cylinder r=4 h=15
#   PitchLink — Alum  Cylinder r=3.5 h=12
#   RollLink  — Alum  Cylinder r=3 h=20
#   ToolBody  — Rubber Cube    6×8×6 cm
#
# Joints:
#   Yaw      — revolute  -175°..175°  ← VALID
#   Pitch    — revolute   -90°..90°   ← VALID
#   Roll     — revolute   -10°..370°  ← VIOLATED (370° > 360°)
#   ToolGrip — prismatic  body0=RollLink(h=20), travel=90 > 20  ← VIOLATED
# ---------------------------------------------------------------------------

def create_bench_wrist_3dof(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel  = _mat(stage, "/World/Mats/Steel",  (0.65, 0.67, 0.70), roughness=0.40)
    m_alum   = _mat(stage, "/World/Mats/Alum",   (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber = _mat(stage, "/World/Mats/Rubber", (0.03, 0.03, 0.03), roughness=0.98)

    yb = UsdGeom.Cylinder.Define(stage, "/World/Wrist/YawBase")
    yb.GetRadiusAttr().Set(8.0); yb.GetHeightAttr().Set(10.0)
    _set_transform(yb, translate=(0, 5, 0))
    _bind(yb.GetPrim(), m_steel)

    yl = UsdGeom.Cylinder.Define(stage, "/World/Wrist/YawLink")
    yl.GetRadiusAttr().Set(4.0); yl.GetHeightAttr().Set(15.0)
    _set_transform(yl, translate=(0, 17.5, 0))
    _bind(yl.GetPrim(), m_alum)

    pl = UsdGeom.Cylinder.Define(stage, "/World/Wrist/PitchLink")
    pl.GetRadiusAttr().Set(3.5); pl.GetHeightAttr().Set(12.0)
    _set_transform(pl, translate=(0, 31, 0))
    _bind(pl.GetPrim(), m_alum)

    rl = UsdGeom.Cylinder.Define(stage, "/World/Wrist/RollLink")
    rl.GetRadiusAttr().Set(3.0); rl.GetHeightAttr().Set(20.0)
    _set_transform(rl, translate=(0, 47, 0))
    _bind(rl.GetPrim(), m_alum)

    tb = UsdGeom.Cube.Define(stage, "/World/Wrist/ToolBody")
    tb.GetSizeAttr().Set(1.0)
    _set_transform(tb, translate=(0, 61, 0), scale=(6.0, 8.0, 6.0))
    _bind(tb.GetPrim(), m_rubber)

    _revolute(stage, "/World/Wrist/Joints/Yaw",   -175, 175,
              "/World/Wrist/YawBase",  "/World/Wrist/YawLink")
    _revolute(stage, "/World/Wrist/Joints/Pitch",  -90,  90,
              "/World/Wrist/YawLink",  "/World/Wrist/PitchLink")
    _revolute(stage, "/World/Wrist/Joints/Roll",   -10, 370,
              "/World/Wrist/PitchLink", "/World/Wrist/RollLink")
    # RollLink h=20, ToolBody bbox_y=8 → max=20; travel=90 > 20 → VIOLATED
    _prismatic(stage, "/World/Wrist/Joints/ToolGrip", -10, 80, axis="Y",
               body0="/World/Wrist/RollLink", body1="/World/Wrist/ToolBody")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (5 prims, 4 joints: 2 violated)")
    return [
        {"path": "/World/Wrist/YawBase",   "material": "steel",    "mass_kg": round(_mass_cyl(8, 10, 7850),     2)},
        {"path": "/World/Wrist/YawLink",   "material": "aluminum", "mass_kg": round(_mass_cyl(4, 15, 2700),     2)},
        {"path": "/World/Wrist/PitchLink", "material": "aluminum", "mass_kg": round(_mass_cyl(3.5, 12, 2700),   2)},
        {"path": "/World/Wrist/RollLink",  "material": "aluminum", "mass_kg": round(_mass_cyl(3, 20, 2700),     2)},
        {"path": "/World/Wrist/ToolBody",  "material": "rubber",   "mass_kg": round(_mass_box(6, 8, 6, 1200),   3)},
    ]


# ---------------------------------------------------------------------------
# Scene 13: bench_linear_gantry
# Cartesian/gantry robot with 3 linear axes and a tool spin.
#
# Geometry:
#   GantryBeam — Steel Cube     200×10×10 cm  (main X-axis beam, 200cm long)
#   XBlock     — Alum  Cube     15×15×10 cm   (rides on beam in X)
#   ZRail      — Alum  Cube     10×10×80 cm   (Z-axis rail on XBlock, 80cm deep)
#   ZBlock     — Alum  Cube     10×50×10 cm   (50cm tall, slides vertically on ZRail)
#   ToolSphere — Rubber Sphere  r=5
#
# Joints:
#   X_Axis  — prismatic body0=GantryBeam(200cm X), travel=600 > 200 ← VIOLATED
#   Z_Axis  — prismatic body0=ZRail(80cm Z),        travel=200 > 80  ← VIOLATED
#   Y_Axis  — prismatic body0=ZBlock(50cm Y),        travel=30 ≤ 50  ← VALID
#   ToolSpin— revolute  -175°..175°  ← VALID
# ---------------------------------------------------------------------------

def create_bench_linear_gantry(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel  = _mat(stage, "/World/Mats/Steel",  (0.65, 0.67, 0.70), roughness=0.40)
    m_alum   = _mat(stage, "/World/Mats/Alum",   (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber = _mat(stage, "/World/Mats/Rubber", (0.03, 0.03, 0.03), roughness=0.98)

    gb = UsdGeom.Cube.Define(stage, "/World/Gantry/GantryBeam")
    gb.GetSizeAttr().Set(1.0)
    _set_transform(gb, translate=(0, 5, 0), scale=(200.0, 10.0, 10.0))
    _bind(gb.GetPrim(), m_steel)

    xb = UsdGeom.Cube.Define(stage, "/World/Gantry/XBlock")
    xb.GetSizeAttr().Set(1.0)
    _set_transform(xb, translate=(0, 22.5, 0), scale=(15.0, 15.0, 10.0))
    _bind(xb.GetPrim(), m_alum)

    zr = UsdGeom.Cube.Define(stage, "/World/Gantry/ZRail")
    zr.GetSizeAttr().Set(1.0)
    _set_transform(zr, translate=(0, 22.5, 40), scale=(10.0, 10.0, 80.0))
    _bind(zr.GetPrim(), m_alum)

    zblock = UsdGeom.Cube.Define(stage, "/World/Gantry/ZBlock")
    zblock.GetSizeAttr().Set(1.0)
    _set_transform(zblock, translate=(0, 47.5, 40), scale=(10.0, 50.0, 10.0))
    _bind(zblock.GetPrim(), m_alum)

    ts = UsdGeom.Sphere.Define(stage, "/World/Gantry/ToolSphere")
    ts.GetRadiusAttr().Set(5.0)
    _set_transform(ts, translate=(0, 77, 40))
    _bind(ts.GetPrim(), m_rubber)

    # GantryBeam 200cm X, XBlock 15cm X → max=200; travel=600 > 200 → VIOLATED
    _prismatic(stage, "/World/Gantry/Joints/X_Axis", -300, 300, axis="X",
               body0="/World/Gantry/GantryBeam", body1="/World/Gantry/XBlock")
    # ZRail 80cm Z, ZBlock 10cm Z → max=80; travel=200 > 80 → VIOLATED
    _prismatic(stage, "/World/Gantry/Joints/Z_Axis", -100, 100, axis="Z",
               body0="/World/Gantry/ZRail",       body1="/World/Gantry/ZBlock")
    # ZBlock 50cm Y, ToolSphere 10cm Y (2*r) → max=50; travel=30 ≤ 50 → VALID
    _prismatic(stage, "/World/Gantry/Joints/Y_Axis",  -30,   0, axis="Y",
               body0="/World/Gantry/ZBlock",      body1="/World/Gantry/ToolSphere")
    _revolute(stage, "/World/Gantry/Joints/ToolSpin", -175, 175,
              "/World/Gantry/ZBlock", "/World/Gantry/ToolSphere")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (5 prims, 4 joints: 2 violated)")
    return [
        {"path": "/World/Gantry/GantryBeam", "material": "steel",    "mass_kg": round(_mass_box(200, 10, 10, 7850), 2)},
        {"path": "/World/Gantry/XBlock",     "material": "aluminum", "mass_kg": round(_mass_box(15, 15, 10, 2700),  2)},
        {"path": "/World/Gantry/ZRail",      "material": "aluminum", "mass_kg": round(_mass_box(10, 10, 80, 2700),  2)},
        {"path": "/World/Gantry/ZBlock",     "material": "aluminum", "mass_kg": round(_mass_box(10, 50, 10, 2700),  2)},
        {"path": "/World/Gantry/ToolSphere", "material": "rubber",   "mass_kg": round(_mass_sphere(5, 1200),         3)},
    ]


# ---------------------------------------------------------------------------
# Scene 14: bench_all_violated
# All 4 revolute joints violated — tests recall comprehensively.
#
# Geometry:
#   BaseBlock — Steel  Cube     25×8×25 cm
#   Link1     — Alum   Cylinder r=5 h=30
#   Link2     — Alum   Cylinder r=4 h=25
#   Link3     — Alum   Cylinder r=3 h=20
#   EndSphere — Rubber Sphere   r=5
#
# Joints (4 revolute, all violated):
#   ShoulderSwing — -10°..250°  ← VIOLATED
#   ElbowBend     — -10°..230°  ← VIOLATED
#   WristFlex     — -10°..215°  ← VIOLATED
#   GripperSpin   — -220°..10°  ← VIOLATED (lower -220° impossible)
# ---------------------------------------------------------------------------

def create_bench_all_violated(out: Path) -> list[dict]:
    stage = _new_stage(out)

    m_steel  = _mat(stage, "/World/Mats/Steel",  (0.65, 0.67, 0.70), roughness=0.40)
    m_alum   = _mat(stage, "/World/Mats/Alum",   (0.80, 0.83, 0.87), roughness=0.35)
    m_rubber = _mat(stage, "/World/Mats/Rubber", (0.03, 0.03, 0.03), roughness=0.98)

    bb = UsdGeom.Cube.Define(stage, "/World/ViolatedArm/BaseBlock")
    bb.GetSizeAttr().Set(1.0)
    _set_transform(bb, translate=(0, 4, 0), scale=(25.0, 8.0, 25.0))
    _bind(bb.GetPrim(), m_steel)

    lk1 = UsdGeom.Cylinder.Define(stage, "/World/ViolatedArm/Link1")
    lk1.GetRadiusAttr().Set(5.0); lk1.GetHeightAttr().Set(30.0)
    _set_transform(lk1, translate=(0, 23, 0))
    _bind(lk1.GetPrim(), m_alum)

    lk2 = UsdGeom.Cylinder.Define(stage, "/World/ViolatedArm/Link2")
    lk2.GetRadiusAttr().Set(4.0); lk2.GetHeightAttr().Set(25.0)
    _set_transform(lk2, translate=(0, 50.5, 0))
    _bind(lk2.GetPrim(), m_alum)

    lk3 = UsdGeom.Cylinder.Define(stage, "/World/ViolatedArm/Link3")
    lk3.GetRadiusAttr().Set(3.0); lk3.GetHeightAttr().Set(20.0)
    _set_transform(lk3, translate=(0, 73, 0))
    _bind(lk3.GetPrim(), m_alum)

    es = UsdGeom.Sphere.Define(stage, "/World/ViolatedArm/EndSphere")
    es.GetRadiusAttr().Set(5.0)
    _set_transform(es, translate=(0, 88, 0))
    _bind(es.GetPrim(), m_rubber)

    _revolute(stage, "/World/ViolatedArm/Joints/ShoulderSwing",  -10, 250,
              "/World/ViolatedArm/BaseBlock", "/World/ViolatedArm/Link1")
    _revolute(stage, "/World/ViolatedArm/Joints/ElbowBend",      -10, 230,
              "/World/ViolatedArm/Link1",     "/World/ViolatedArm/Link2")
    _revolute(stage, "/World/ViolatedArm/Joints/WristFlex",      -10, 215,
              "/World/ViolatedArm/Link2",     "/World/ViolatedArm/Link3")
    _revolute(stage, "/World/ViolatedArm/Joints/GripperSpin",   -220,  10,
              "/World/ViolatedArm/Link3",     "/World/ViolatedArm/EndSphere")

    stage.GetRootLayer().Export(str(out))
    print(f"  Created: {out.name}  (5 prims, 4 joints: 4 violated)")
    return [
        {"path": "/World/ViolatedArm/BaseBlock",  "material": "steel",    "mass_kg": round(_mass_box(25, 8, 25, 7850), 2)},
        {"path": "/World/ViolatedArm/Link1",      "material": "aluminum", "mass_kg": round(_mass_cyl(5, 30, 2700),      2)},
        {"path": "/World/ViolatedArm/Link2",      "material": "aluminum", "mass_kg": round(_mass_cyl(4, 25, 2700),      2)},
        {"path": "/World/ViolatedArm/Link3",      "material": "aluminum", "mass_kg": round(_mass_cyl(3, 20, 2700),      2)},
        {"path": "/World/ViolatedArm/EndSphere",  "material": "rubber",   "mass_kg": round(_mass_sphere(5, 1200),        3)},
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Creating benchmark USD scenes...")

    # ---- Original 4 scenes ----
    p1  = ASSETS / "bench_revolute_limits.usda"
    p2  = ASSETS / "bench_mass_materials.usda"
    p3  = ASSETS / "bench_mixed.usda"
    p4  = ASSETS / "bench_prismatic_limits.usda"
    # ---- 10 new scenes ----
    p5  = ASSETS / "bench_humanoid_arm.usda"
    p6  = ASSETS / "bench_all_valid.usda"
    p7  = ASSETS / "bench_crane.usda"
    p8  = ASSETS / "bench_symmetric_violation.usda"
    p9  = ASSETS / "bench_scara.usda"
    p10 = ASSETS / "bench_gripper.usda"
    p11 = ASSETS / "bench_excavator.usda"
    p12 = ASSETS / "bench_wrist_3dof.usda"
    p13 = ASSETS / "bench_linear_gantry.usda"
    p14 = ASSETS / "bench_all_violated.usda"

    masses1  = create_bench_revolute_limits(p1)
    masses2  = create_bench_mass_materials(p2)
    masses3  = create_bench_mixed(p3)
    masses4  = create_bench_prismatic_limits(p4)
    masses5  = create_bench_humanoid_arm(p5)
    masses6  = create_bench_all_valid(p6)
    masses7  = create_bench_crane(p7)
    masses8  = create_bench_symmetric_violation(p8)
    masses9  = create_bench_scara(p9)
    masses10 = create_bench_gripper(p10)
    masses11 = create_bench_excavator(p11)
    masses12 = create_bench_wrist_3dof(p12)
    masses13 = create_bench_linear_gantry(p13)
    masses14 = create_bench_all_violated(p14)

    gt = {
        "description": (
            "Ground truth for PhysInt benchmark. "
            "joint.violated=true means the limit is physically implausible. "
            "mass.mass_kg is computed analytically from exact primitive geometry × material density."
        ),
        "densities_kg_m3": {
            "steel": 7850, "aluminum": 2700,
            "rubber": 1200, "concrete": 2300,
        },
        "scenes": [
            # ---- Scene 1: original revolute limits ----
            {
                "name": "bench_revolute_limits",
                "usd": "assets/bench_revolute_limits.usda",
                "description": "Robot arm chain — tests revolute joint violation detection",
                "joints": [
                    {"path": "/World/RobotChain/Joints/ShoulderYaw", "lower": -90,  "upper":  90, "violated": False},
                    {"path": "/World/RobotChain/Joints/Elbow",       "lower": -10,  "upper": 220, "violated": True},
                    {"path": "/World/RobotChain/Joints/WristPitch",  "lower": -80,  "upper":  80, "violated": False},
                    {"path": "/World/RobotChain/Joints/WristRoll",   "lower": -10,  "upper": 260, "violated": True},
                ],
                "masses": masses1,
            },
            # ---- Scene 2: mass/materials ----
            {
                "name": "bench_mass_materials",
                "usd": "assets/bench_mass_materials.usda",
                "description": "4 materials with known masses — tests mass estimation accuracy",
                "joints": [],
                "masses": masses2,
            },
            # ---- Scene 3: mixed ----
            {
                "name": "bench_mixed",
                "usd": "assets/bench_mixed.usda",
                "description": "Combined — 3 prims + 3 revolute joints (1 violated)",
                "joints": [
                    {"path": "/World/Assembly/Joints/BaseRevolute",  "lower": -45, "upper":  45, "violated": False},
                    {"path": "/World/Assembly/Joints/ElbowRevolute", "lower": -10, "upper": 190, "violated": True},
                    {"path": "/World/Assembly/Joints/WristRevolute", "lower": -70, "upper":  70, "violated": False},
                ],
                "masses": masses3,
            },
            # ---- Scene 4: prismatic limits ----
            {
                "name": "bench_prismatic_limits",
                "usd": "assets/bench_prismatic_limits.usda",
                "description": "Linear actuator — tests prismatic (slider) joint violation detection",
                "joints": [
                    {"path": "/World/Actuator/Joints/SliderTravel",    "lower": -15, "upper":  15, "violated": False},
                    {"path": "/World/Actuator/Joints/ActuatorStroke",  "lower":   0, "upper": 180, "violated": True},
                    {"path": "/World/Actuator/Joints/CarriageRetract", "lower": -10, "upper":   0, "violated": False},
                    {"path": "/World/Actuator/Joints/RodOverExtend",   "lower": -80, "upper":  80, "violated": True},
                ],
                "masses": masses4,
            },
            # ---- Scene 5: humanoid arm (6 revolute, 2 violated) ----
            {
                "name": "bench_humanoid_arm",
                "usd": "assets/bench_humanoid_arm.usda",
                "description": "6-DOF humanoid arm — ShoulderAbduct and WristSupination violated",
                "joints": [
                    {"path": "/World/Arm/Joints/ShoulderFlexion",  "lower": -60, "upper": 170, "violated": False},
                    {"path": "/World/Arm/Joints/ShoulderAbduct",   "lower": -45, "upper": 200, "violated": True},
                    {"path": "/World/Arm/Joints/ShoulderRotation", "lower": -90, "upper":  90, "violated": False},
                    {"path": "/World/Arm/Joints/ElbowFlexion",     "lower":   0, "upper": 145, "violated": False},
                    {"path": "/World/Arm/Joints/WristFlexion",     "lower": -70, "upper":  70, "violated": False},
                    {"path": "/World/Arm/Joints/WristSupination",  "lower": -90, "upper": 200, "violated": True},
                ],
                "masses": masses5,
            },
            # ---- Scene 6: all-valid specificity test (5 revolute, 0 violated) ----
            {
                "name": "bench_all_valid",
                "usd": "assets/bench_all_valid.usda",
                "description": "5 revolute joints all within normal limits — specificity test (expect 0 violations)",
                "joints": [
                    {"path": "/World/Robot/Joints/BaseTurn",     "lower":  -90, "upper":  90, "violated": False},
                    {"path": "/World/Robot/Joints/ShoulderLift", "lower":  -30, "upper": 120, "violated": False},
                    {"path": "/World/Robot/Joints/ElbowBend",    "lower":    0, "upper": 135, "violated": False},
                    {"path": "/World/Robot/Joints/WristTilt",    "lower":  -60, "upper":  60, "violated": False},
                    {"path": "/World/Robot/Joints/ToolSpin",     "lower": -175, "upper": 175, "violated": False},
                ],
                "masses": masses6,
            },
            # ---- Scene 7: tower crane (3 revolute + 1 prismatic, 2 violated) ----
            {
                "name": "bench_crane",
                "usd": "assets/bench_crane.usda",
                "description": "Tower crane — JibSwing revolute and HookTravel prismatic violated",
                "joints": [
                    {"path": "/World/Crane/Joints/SlewRing",   "lower": -180, "upper": 180, "violated": False},
                    {"path": "/World/Crane/Joints/BoomLift",   "lower":   -5, "upper":  55, "violated": False},
                    {"path": "/World/Crane/Joints/JibSwing",   "lower":  -10, "upper": 195, "violated": True},
                    {"path": "/World/Crane/Joints/HookTravel", "lower":    0, "upper": 250, "violated": True},
                ],
                "masses": masses7,
            },
            # ---- Scene 8: symmetric violation (3 revolute, 1 violated) ----
            {
                "name": "bench_symmetric_violation",
                "usd": "assets/bench_symmetric_violation.usda",
                "description": "WideSwing ±200° (400° total range) — symmetric impossible limit",
                "joints": [
                    {"path": "/World/Assembly/Joints/WideSwing",    "lower": -200, "upper": 200, "violated": True},
                    {"path": "/World/Assembly/Joints/TightPivot",   "lower":  -25, "upper":  25, "violated": False},
                    {"path": "/World/Assembly/Joints/HalfRotation", "lower":  -90, "upper":  90, "violated": False},
                ],
                "masses": masses8,
            },
            # ---- Scene 9: SCARA robot (3 revolute + 1 prismatic, 2 violated) ----
            {
                "name": "bench_scara",
                "usd": "assets/bench_scara.usda",
                "description": "SCARA robot — Joint2 elbow revolute and ZTravel prismatic violated",
                "joints": [
                    {"path": "/World/Scara/Joints/Joint1",     "lower": -150, "upper": 150, "violated": False},
                    {"path": "/World/Scara/Joints/Joint2",     "lower":  -10, "upper": 210, "violated": True},
                    {"path": "/World/Scara/Joints/ZTravel",    "lower":    0, "upper": 200, "violated": True},
                    {"path": "/World/Scara/Joints/ToolRotate", "lower": -175, "upper": 175, "violated": False},
                ],
                "masses": masses9,
            },
            # ---- Scene 10: gripper (4 prismatic, 2 violated) ----
            {
                "name": "bench_gripper",
                "usd": "assets/bench_gripper.usda",
                "description": "Parallel jaw gripper — Spread joints exceed palm width; Close joints valid",
                "joints": [
                    {"path": "/World/Gripper/Joints/FingerL_Spread", "lower":  0, "upper":  80, "violated": True},
                    {"path": "/World/Gripper/Joints/FingerL_Close",  "lower": -8, "upper":   0, "violated": False},
                    {"path": "/World/Gripper/Joints/FingerR_Spread", "lower":  0, "upper":  75, "violated": True},
                    {"path": "/World/Gripper/Joints/FingerR_Close",  "lower": -8, "upper":   0, "violated": False},
                ],
                "masses": masses10,
            },
            # ---- Scene 11: excavator (2 revolute + 2 prismatic, 2 violated) ----
            {
                "name": "bench_excavator",
                "usd": "assets/bench_excavator.usda",
                "description": "Excavator arm — hydraulic cylinders over-stroke (prismatic violated)",
                "joints": [
                    {"path": "/World/Excavator/Joints/BoomCylinder", "lower":   0, "upper": 150, "violated": True},
                    {"path": "/World/Excavator/Joints/ArmCylinder",  "lower":   0, "upper": 120, "violated": True},
                    {"path": "/World/Excavator/Joints/BucketCurl",   "lower": -45, "upper": 135, "violated": False},
                    {"path": "/World/Excavator/Joints/CabSwing",     "lower":-170, "upper": 170, "violated": False},
                ],
                "masses": masses11,
            },
            # ---- Scene 12: 3-DOF wrist (3 revolute + 1 prismatic, 2 violated) ----
            {
                "name": "bench_wrist_3dof",
                "usd": "assets/bench_wrist_3dof.usda",
                "description": "3-DOF wrist — Roll exceeds 360°; ToolGrip prismatic over-travels",
                "joints": [
                    {"path": "/World/Wrist/Joints/Yaw",      "lower": -175, "upper": 175, "violated": False},
                    {"path": "/World/Wrist/Joints/Pitch",    "lower":  -90, "upper":  90, "violated": False},
                    {"path": "/World/Wrist/Joints/Roll",     "lower":  -10, "upper": 370, "violated": True},
                    {"path": "/World/Wrist/Joints/ToolGrip", "lower":  -10, "upper":  80, "violated": True},
                ],
                "masses": masses12,
            },
            # ---- Scene 13: linear gantry (3 prismatic + 1 revolute, 2 violated) ----
            {
                "name": "bench_linear_gantry",
                "usd": "assets/bench_linear_gantry.usda",
                "description": "Cartesian gantry — X_Axis and Z_Axis prismatic exceed beam dimensions",
                "joints": [
                    {"path": "/World/Gantry/Joints/X_Axis",  "lower": -300, "upper": 300, "violated": True},
                    {"path": "/World/Gantry/Joints/Z_Axis",  "lower": -100, "upper": 100, "violated": True},
                    {"path": "/World/Gantry/Joints/Y_Axis",  "lower":  -30, "upper":   0, "violated": False},
                    {"path": "/World/Gantry/Joints/ToolSpin","lower": -175, "upper": 175, "violated": False},
                ],
                "masses": masses13,
            },
            # ---- Scene 14: all-violated recall test (4 revolute, all violated) ----
            {
                "name": "bench_all_violated",
                "usd": "assets/bench_all_violated.usda",
                "description": "All 4 revolute joints violated — maximum recall stress test",
                "joints": [
                    {"path": "/World/ViolatedArm/Joints/ShoulderSwing", "lower":  -10, "upper": 250, "violated": True},
                    {"path": "/World/ViolatedArm/Joints/ElbowBend",     "lower":  -10, "upper": 230, "violated": True},
                    {"path": "/World/ViolatedArm/Joints/WristFlex",     "lower":  -10, "upper": 215, "violated": True},
                    {"path": "/World/ViolatedArm/Joints/GripperSpin",   "lower": -220, "upper":  10, "violated": True},
                ],
                "masses": masses14,
            },
        ],
    }

    gt_path = ASSETS / "benchmark_gt.json"
    gt_path.write_text(json.dumps(gt, indent=2))
    print(f"  Created: {gt_path.name}")

    # Print summary
    total_scenes    = len(gt["scenes"])
    total_joints    = sum(len(s["joints"]) for s in gt["scenes"])
    total_violated  = sum(sum(1 for j in s["joints"] if j["violated"]) for s in gt["scenes"])
    total_masses    = sum(len(s["masses"]) for s in gt["scenes"])
    print(f"\nBenchmark summary:")
    print(f"  Scenes : {total_scenes}")
    print(f"  Joints : {total_joints} total  ({total_violated} violated, {total_joints-total_violated} valid)")
    print(f"  Masses : {total_masses} prims with known ground-truth mass")


if __name__ == "__main__":
    main()
