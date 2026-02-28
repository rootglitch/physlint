"""
Write Cosmos Reason 2 physics analysis back into a USD stage using pxr.UsdPhysics.
"""
from __future__ import annotations

import os
from pathlib import Path

from pxr import Usd, UsdGeom, UsdPhysics, Sdf, Gf, Vt

from .cosmos_client import PhysicsAnalysis, GeomPhysics, JointPhysics


def _ensure_physics_scene(stage: Usd.Stage):
    """Add a UsdPhysicsScene prim if none exists (required by Isaac Sim)."""
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Scene):
            return
    stage.DefinePrim("/PhysicsScene", "PhysicsScene")


def _apply_geom_physics(stage: Usd.Stage, gp: GeomPhysics, meters_per_unit: float):
    prim = stage.GetPrimAtPath(gp.prim_path)
    if not prim.IsValid():
        print(f"  [writer] WARN: prim not found: {gp.prim_path}")
        return

    # --- Rigid Body ---
    if gp.is_rigid and not prim.HasAPI(UsdPhysics.RigidBodyAPI):
        UsdPhysics.RigidBodyAPI.Apply(prim)

    # --- Collision ---
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)

    # Set collision approximation via custom attribute (PhysX convention)
    approx_attr = prim.GetAttribute("physics:approximation")
    if not approx_attr.IsValid():
        approx_attr = prim.CreateAttribute("physics:approximation", Sdf.ValueTypeNames.Token)
    approx_attr.Set(gp.collision_approximation)

    # --- Mass ---
    mass_api = UsdPhysics.MassAPI.Apply(prim)
    mass_api.CreateMassAttr().Set(float(gp.mass_kg))

    # --- Physics Material ---
    # Create material prim in a dedicated scope
    mat_scope_path = "/PhysicsMaterials"
    if not stage.GetPrimAtPath(mat_scope_path).IsValid():
        stage.DefinePrim(mat_scope_path, "Scope")

    safe_name = gp.prim_path.replace("/", "_").strip("_")
    mat_path = Sdf.Path(f"{mat_scope_path}/{safe_name}_PhysMat")
    mat_prim = stage.DefinePrim(mat_path, "Material")

    phys_mat = UsdPhysics.MaterialAPI.Apply(mat_prim)
    phys_mat.CreateStaticFrictionAttr().Set(float(gp.static_friction))
    phys_mat.CreateDynamicFrictionAttr().Set(float(gp.dynamic_friction))
    phys_mat.CreateRestitutionAttr().Set(float(gp.restitution))

    # Bind material to geometry prim
    mat_binding_rel = prim.GetRelationship("physics:material:binding")
    if not mat_binding_rel.IsValid():
        mat_binding_rel = prim.CreateRelationship("physics:material:binding", custom=False)
    mat_binding_rel.SetTargets([mat_path])


def _apply_joint_physics(stage: Usd.Stage, jp: JointPhysics):
    prim = stage.GetPrimAtPath(jp.prim_path)
    if not prim.IsValid():
        print(f"  [writer] WARN: joint prim not found: {jp.prim_path}")
        return

    if jp.lower_limit_deg is not None:
        attr = prim.GetAttribute("physics:lowerLimit")
        if not attr.IsValid():
            attr = prim.CreateAttribute("physics:lowerLimit", Sdf.ValueTypeNames.Float)
        attr.Set(float(jp.lower_limit_deg))

    if jp.upper_limit_deg is not None:
        attr = prim.GetAttribute("physics:upperLimit")
        if not attr.IsValid():
            attr = prim.CreateAttribute("physics:upperLimit", Sdf.ValueTypeNames.Float)
        attr.Set(float(jp.upper_limit_deg))


def write_physics(
    input_usd: str,
    analysis: PhysicsAnalysis,
    output_usd: str,
    meters_per_unit: float = 1.0,
):
    """
    Open input_usd, apply all physics properties from analysis, save to output_usd.
    """
    stage = Usd.Stage.Open(input_usd)
    if not stage:
        raise ValueError(f"Cannot open: {input_usd}")

    # Ensure physics scene prim exists
    _ensure_physics_scene(stage)

    print(f"  Applying physics to {len(analysis.geom_prims)} geometry prims...")
    for gp in analysis.geom_prims:
        _apply_geom_physics(stage, gp, meters_per_unit)
        print(f"    ✓ {gp.prim_path}  [{gp.material_type}, {gp.mass_kg:.2f} kg]")

    print(f"  Applying limits to {len(analysis.joint_prims)} joint prims...")
    for jp in analysis.joint_prims:
        _apply_joint_physics(stage, jp)
        status = "✓" if jp.joint_valid else "⚠ corrected"
        print(f"    {status} {jp.prim_path}  [{jp.lower_limit_deg}°..{jp.upper_limit_deg}°]")

    # Export
    os.makedirs(os.path.dirname(os.path.abspath(output_usd)), exist_ok=True)
    stage.GetRootLayer().Export(output_usd)
    print(f"  Saved: {output_usd}")
