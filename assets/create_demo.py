"""
Programmatically create a demo USD scene for the USD Physical Intelligence Layer.

Scene contains:
  - A stainless steel pressure vessel (cylinder body + dome caps)
  - A rubber gasket ring (flat cylinder, near-black)
  - A dark steel support frame
  - A robot arm elbow with an intentionally bad joint limit (220°)
  - A red plastic valve handle

No physics properties are authored — the tool fills them in from scratch.
Uses UsdPreviewSurface so Blender imports the correct material colors.
"""
from __future__ import annotations

import os

from pxr import Usd, UsdGeom, UsdShade, Gf, Sdf, Vt


def _set_transform(xformable: UsdGeom.Xformable, translate=(0, 0, 0), scale=(1, 1, 1)):
    xformable.AddXformOp(UsdGeom.XformOp.TypeTranslate).Set(Gf.Vec3d(*translate))
    xformable.AddXformOp(UsdGeom.XformOp.TypeScale).Set(Gf.Vec3d(*scale))


def _make_preview_surface(
    stage: Usd.Stage,
    mat_path: str,
    diffuse: tuple,
    metallic: float = 0.0,
    roughness: float = 0.5,
    opacity: float = 1.0,
) -> UsdShade.Material:
    """Create a UsdPreviewSurface material that Blender imports with correct color."""
    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, mat_path + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor",  Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*diffuse))
    shader.CreateInput("metallic",      Sdf.ValueTypeNames.Float).Set(metallic)
    shader.CreateInput("roughness",     Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("opacity",       Sdf.ValueTypeNames.Float).Set(opacity)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def _bind(prim: Usd.Prim, mat: UsdShade.Material):
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat)


def create_demo_usd(output_path: str = "assets/demo_gripper.usda"):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    stage = Usd.Stage.CreateNew(output_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)   # 1 unit = 1 cm

    root = stage.DefinePrim("/World", "Xform")
    stage.SetDefaultPrim(root)

    # ── Material library ───────────────────────────────────────────────
    mats = stage.DefinePrim("/World/Materials", "Scope")

    # metallic=0 everywhere: diffuse colour shows directly under any lighting.
    # Material identity communicated through colour + roughness, not reflectance.
    m_steel  = _make_preview_surface(stage, "/World/Materials/Steel",
                                     diffuse=(0.65, 0.67, 0.70), metallic=0.0, roughness=0.40)
    m_dsteel = _make_preview_surface(stage, "/World/Materials/DarkSteel",
                                     diffuse=(0.20, 0.21, 0.23), metallic=0.0, roughness=0.55)
    m_rubber = _make_preview_surface(stage, "/World/Materials/Rubber",
                                     diffuse=(0.03, 0.03, 0.03), metallic=0.0, roughness=0.98)
    m_red    = _make_preview_surface(stage, "/World/Materials/RedPlastic",
                                     diffuse=(0.85, 0.06, 0.04), metallic=0.0, roughness=0.55)
    m_orange = _make_preview_surface(stage, "/World/Materials/OrangeRobot",
                                     diffuse=(0.92, 0.35, 0.04), metallic=0.0, roughness=0.50)

    # ── 1. Pressure vessel (stainless steel) — centre of scene ─────────
    vessel = UsdGeom.Cylinder.Define(stage, "/World/PressureVessel/Body")
    vessel.GetRadiusAttr().Set(15.0)
    vessel.GetHeightAttr().Set(50.0)
    _set_transform(vessel, translate=(0, 25, 0))
    _bind(vessel.GetPrim(), m_steel)

    top_cap = UsdGeom.Sphere.Define(stage, "/World/PressureVessel/TopCap")
    top_cap.GetRadiusAttr().Set(15.0)
    _set_transform(top_cap, translate=(0, 50, 0), scale=(1.0, 0.4, 1.0))
    _bind(top_cap.GetPrim(), m_steel)

    bot_cap = UsdGeom.Sphere.Define(stage, "/World/PressureVessel/BottomCap")
    bot_cap.GetRadiusAttr().Set(15.0)
    _set_transform(bot_cap, translate=(0, 0, 0), scale=(1.0, 0.4, 1.0))
    _bind(bot_cap.GetPrim(), m_steel)

    # ── 2. Rubber gasket (near-black, flat ring) ───────────────────────
    gasket = UsdGeom.Cylinder.Define(stage, "/World/RubberGasket")
    gasket.GetRadiusAttr().Set(16.5)
    gasket.GetHeightAttr().Set(2.5)
    _set_transform(gasket, translate=(0, 5, 0))
    _bind(gasket.GetPrim(), m_rubber)

    # ── 3. Dark steel support frame ────────────────────────────────────
    base = UsdGeom.Cube.Define(stage, "/World/SupportFrame/Base")
    base.GetSizeAttr().Set(1.0)
    _set_transform(base, translate=(0, -1, 0), scale=(42.0, 2.0, 20.0))
    _bind(base.GetPrim(), m_dsteel)

    pillar_l = UsdGeom.Cube.Define(stage, "/World/SupportFrame/PillarLeft")
    pillar_l.GetSizeAttr().Set(1.0)
    _set_transform(pillar_l, translate=(-19, 30, 0), scale=(3.0, 62.0, 3.0))
    _bind(pillar_l.GetPrim(), m_dsteel)

    pillar_r = UsdGeom.Cube.Define(stage, "/World/SupportFrame/PillarRight")
    pillar_r.GetSizeAttr().Set(1.0)
    _set_transform(pillar_r, translate=(19, 30, 0), scale=(3.0, 62.0, 3.0))
    _bind(pillar_r.GetPrim(), m_dsteel)

    # ── 4. Robot arm — placed adjacent to vessel, not far away ────────
    # Upper arm: x=30 (just right of the vessel at x=0, r=15)
    upper_arm = UsdGeom.Cube.Define(stage, "/World/RobotArm/UpperArm")
    upper_arm.GetSizeAttr().Set(1.0)
    _set_transform(upper_arm, translate=(30, 40, 0), scale=(4.5, 20.0, 4.5))
    _bind(upper_arm.GetPrim(), m_orange)

    lower_arm = UsdGeom.Cube.Define(stage, "/World/RobotArm/LowerArm")
    lower_arm.GetSizeAttr().Set(1.0)
    _set_transform(lower_arm, translate=(30, 17, 0), scale=(4.5, 20.0, 4.5))
    _bind(lower_arm.GetPrim(), m_orange)

    # Elbow joint — intentionally invalid upper limit: 220° (human elbow max is ~145°)
    elbow = stage.DefinePrim("/World/RobotArm/ElbowJoint", "PhysicsRevoluteJoint")
    elbow.CreateAttribute("physics:lowerLimit", Sdf.ValueTypeNames.Float).Set(-10.0)
    elbow.CreateAttribute("physics:upperLimit", Sdf.ValueTypeNames.Float).Set(220.0)
    elbow.CreateAttribute("physics:axis",       Sdf.ValueTypeNames.Token).Set("Z")
    elbow.CreateRelationship("physics:body0").SetTargets([Sdf.Path("/World/RobotArm/UpperArm")])
    elbow.CreateRelationship("physics:body1").SetTargets([Sdf.Path("/World/RobotArm/LowerArm")])

    # ── 5. Red plastic valve handle on top of vessel ──────────────────
    valve = UsdGeom.Cylinder.Define(stage, "/World/ValveHandle")
    valve.GetRadiusAttr().Set(5.0)   # bigger so it's visible in renders
    valve.GetHeightAttr().Set(10.0)
    _set_transform(valve, translate=(0, 60, 0))
    _bind(valve.GetPrim(), m_red)

    stage.GetRootLayer().Export(output_path)
    print(f"Demo USD saved: {output_path}")
    print(f"  Materials      : Steel, DarkSteel, Rubber (black), RedPlastic, OrangeRobot")
    print(f"  Geometry prims : 10 (vessel×3, gasket, frame×3, arm×2, valve)")
    print(f"  Joint prims    : ElbowJoint — limits -10°..220° (deliberately wrong)")
    print(f"  Physics        : NONE — tool fills everything in from scratch")


if __name__ == "__main__":
    create_demo_usd()
