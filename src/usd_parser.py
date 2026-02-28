"""
Parse a USD stage and extract physics-relevant scene graph information.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import json

from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf


# Prim types that are candidates for physics authoring
GEOMETRY_TYPES = {
    "Mesh", "Cube", "Sphere", "Cylinder", "Cone", "Capsule",
    "BasisCurves", "Points",
}

# Ratio of actual solid volume to bounding-box volume for each primitive type.
# mass = bbox_volume * fill_factor * density
# Cylinder: π/4 ≈ 0.785  (πr²h vs (2r)²h)
# Sphere:   π/6 ≈ 0.524  ((4/3)πr³ vs (2r)³)
# Cone:     π/12 ≈ 0.262 ((1/3)πr²h vs (2r)²h)
# Capsule:  roughly cylinder + two hemispheres ≈ 0.785 (capsule ≈ cylinder for tall shapes)
# Cube / BasisCurves / Points: bbox IS the volume → 1.0
# Mesh: arbitrary shape, conservative default 0.6
FILL_FACTORS: dict[str, float] = {
    "Cylinder":   0.785,
    "Sphere":     0.524,
    "Cone":       0.262,
    "Capsule":    0.785,
    "Cube":       1.000,
    "Mesh":       0.600,
    "BasisCurves": 1.000,
    "Points":     1.000,
}

JOINT_TYPES = {
    "PhysicsRevoluteJoint", "PhysicsPrismaticJoint", "PhysicsSphericalJoint",
    "PhysicsFixedJoint", "PhysicsJoint",
    # USD 25+ names
    "RevoluteJoint", "PrismaticJoint", "SphericalJoint", "FixedJoint",
}


@dataclass
class BBox:
    min: list[float]
    max: list[float]
    size: list[float]


@dataclass
class ExistingPhysics:
    has_rigid_body: bool = False
    has_collision: bool = False
    has_mass: bool = False
    has_material: bool = False
    mass_kg: Optional[float] = None
    static_friction: Optional[float] = None
    dynamic_friction: Optional[float] = None


@dataclass
class GeomPrimInfo:
    kind: str = "geom"
    path: str = ""
    type_name: str = ""
    display_name: str = ""
    bbox: Optional[BBox] = None
    fill_factor: float = 1.0
    existing_physics: ExistingPhysics = field(default_factory=ExistingPhysics)


@dataclass
class JointPrimInfo:
    kind: str = "joint"
    path: str = ""
    type_name: str = ""
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None
    axis: Optional[str] = None
    body0_path: Optional[str] = None
    body1_path: Optional[str] = None
    # Prismatic only: bbox size of the connected body along the joint axis (stage units).
    # travel = upper - lower; if travel > body_length_along_axis → physically impossible.
    body_length_along_axis: Optional[float] = None


@dataclass
class SceneGraph:
    up_axis: str
    meters_per_unit: float
    geom_prims: list[GeomPrimInfo]
    joint_prims: list[JointPrimInfo]

    def to_dict(self) -> dict:
        return {
            "stage_metadata": {
                "up_axis": self.up_axis,
                "meters_per_unit": self.meters_per_unit,
            },
            "geom_prims": [asdict(p) for p in self.geom_prims],
            "joint_prims": [asdict(p) for p in self.joint_prims],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @property
    def all_prim_paths(self) -> list[str]:
        return [p.path for p in self.geom_prims] + [p.path for p in self.joint_prims]


def _bbox_from_range(mn: list, mx: list) -> Optional[BBox]:
    sz = [mx[i] - mn[i] for i in range(3)]
    if all(abs(s) < 1e-9 for s in sz):
        return None
    return BBox(
        min=[round(v, 6) for v in mn],
        max=[round(v, 6) for v in mx],
        size=[round(v, 6) for v in sz],
    )


def _compute_bbox(prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache) -> Optional[BBox]:
    try:
        bound = bbox_cache.ComputeWorldBound(prim)
        r = bound.ComputeAlignedRange()
        return _bbox_from_range(list(r.GetMin()), list(r.GetMax()))
    except Exception:
        return None


def _compute_link_bbox(prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache) -> Optional[BBox]:
    """Compute world-space bbox from direct Mesh/geometry children only.

    Skips child Xform prims (those are child links, not this link's geometry).
    Used for rigid-body Xform prims so the bbox reflects only the link's own
    visual geometry, not the entire sub-tree of its descendants.
    """
    mn = [float("inf")] * 3
    mx = [float("-inf")] * 3
    found = False
    for child in prim.GetChildren():
        if child.GetTypeName() not in GEOMETRY_TYPES:
            continue
        try:
            bound = bbox_cache.ComputeWorldBound(child)
            r = bound.ComputeAlignedRange()
            lo, hi = list(r.GetMin()), list(r.GetMax())
            for i in range(3):
                if abs(hi[i] - lo[i]) < 1e-9:
                    continue
                mn[i] = min(mn[i], lo[i])
                mx[i] = max(mx[i], hi[i])
                found = True
        except Exception:
            continue
    if not found or any(mn[i] == float("inf") for i in range(3)):
        return None
    return _bbox_from_range(mn, mx)


def _read_existing_physics(prim: Usd.Prim) -> ExistingPhysics:
    ep = ExistingPhysics(
        has_rigid_body=UsdPhysics.RigidBodyAPI.CanApply(prim) and prim.HasAPI(UsdPhysics.RigidBodyAPI),
        has_collision=prim.HasAPI(UsdPhysics.CollisionAPI),
        has_mass=prim.HasAPI(UsdPhysics.MassAPI),
    )
    if ep.has_mass:
        mass_api = UsdPhysics.MassAPI(prim)
        mass_attr = mass_api.GetMassAttr()
        if mass_attr.IsAuthored():
            ep.mass_kg = mass_attr.Get()
    return ep


def _read_joint(prim: Usd.Prim) -> JointPrimInfo:
    info = JointPrimInfo(
        path=str(prim.GetPath()),
        type_name=prim.GetTypeName(),
    )
    type_name = prim.GetTypeName()

    # Read body relationships (present on all joint types)
    for rel_name, attr in [("physics:body0", "body0_path"), ("physics:body1", "body1_path")]:
        rel = prim.GetRelationship(rel_name)
        if rel.IsValid():
            targets = rel.GetTargets()
            if targets:
                setattr(info, attr, str(targets[0]))

    if "Revolute" in type_name:
        lower = prim.GetAttribute("physics:lowerLimit")
        upper = prim.GetAttribute("physics:upperLimit")
        axis_attr = prim.GetAttribute("physics:axis")
        info.lower_limit = lower.Get() if lower.IsValid() and lower.Get() is not None else None
        info.upper_limit = upper.Get() if upper.IsValid() and upper.Get() is not None else None
        info.axis = axis_attr.Get() if axis_attr.IsValid() and axis_attr.Get() is not None else "X"
    elif "Prismatic" in type_name:
        lower = prim.GetAttribute("physics:lowerLimit")
        upper = prim.GetAttribute("physics:upperLimit")
        axis_attr = prim.GetAttribute("physics:axis")
        info.lower_limit = lower.Get() if lower.IsValid() and lower.Get() is not None else None
        info.upper_limit = upper.Get() if upper.IsValid() and upper.Get() is not None else None
        info.axis = axis_attr.Get() if axis_attr.IsValid() and axis_attr.Get() is not None else "Y"
    return info


_AXIS_IDX = {"X": 0, "Y": 1, "Z": 2}


def _annotate_prismatic_body_lengths(
    joint_prims: list[JointPrimInfo],
    geom_prims: list[GeomPrimInfo],
) -> None:
    """Fill body_length_along_axis for prismatic joints from connected body bboxes.

    Uses the LARGER of the two connected bodies along the joint axis — this represents
    the housing/rail that constrains travel. Travel > housing_length is physically
    impossible regardless of which body is the mover.
    """
    geom_by_path = {p.path: p for p in geom_prims}
    for j in joint_prims:
        if "Prismatic" not in j.type_name:
            continue
        axis_idx = _AXIS_IDX.get((j.axis or "Y").upper(), 1)
        sizes = []
        for path in [j.body0_path, j.body1_path]:
            if path and path in geom_by_path:
                geom = geom_by_path[path]
                if geom.bbox:
                    sizes.append(geom.bbox.size[axis_idx])
        if sizes:
            j.body_length_along_axis = round(max(sizes), 3)


def parse_usd(usd_path: str) -> SceneGraph:
    """
    Open a USD file and extract a physics-relevant scene graph.

    Returns a SceneGraph with all geometry and joint prims found.

    Handles two USD styles:
    - Synthetic (bench) scenes: rigid bodies are leaf geometry prims (Cube, Sphere…)
    - Real robot scenes (Menagerie): rigid bodies are Xform prims whose direct
      children are Mesh sub-parts. In this case we emit the Xform at the link
      level and skip its mesh children so prim paths match the GT.
    """
    stage = Usd.Stage.Open(usd_path)
    if not stage:
        raise ValueError(f"Could not open USD stage: {usd_path}")

    up_axis = UsdGeom.GetStageUpAxis(stage) or "Y"
    meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage) or 1.0

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        includedPurposes=["default", "render"],
    )

    # --- Pass 1: find all Xform prims with RigidBodyAPI (robot links) --------
    # These are NOT in GEOMETRY_TYPES so the normal traversal would miss them.
    rigid_body_xform_paths: set[str] = set()
    rb_xform_prims: list[Usd.Prim] = []
    for prim in stage.Traverse():
        tn = prim.GetTypeName()
        if tn not in GEOMETRY_TYPES and UsdPhysics.RigidBodyAPI(prim):
            path = str(prim.GetPath())
            rigid_body_xform_paths.add(path)
            rb_xform_prims.append(prim)

    geom_prims: list[GeomPrimInfo] = []
    joint_prims: list[JointPrimInfo] = []

    # --- Pass 2: rigid body Xform prims → link-level geom entries -----------
    for prim in rb_xform_prims:
        bbox = _compute_link_bbox(prim, bbox_cache)
        if bbox is None:
            # Fallback: whole-prim world bbox
            bbox = _compute_bbox(prim, bbox_cache)
        ep = _read_existing_physics(prim)
        geom_prims.append(GeomPrimInfo(
            path=str(prim.GetPath()),
            type_name="Mesh",          # treat as complex mesh for fill_factor
            display_name=prim.GetName(),
            bbox=bbox,
            fill_factor=0.6,
            existing_physics=ep,
        ))

    # --- Pass 3: leaf geometry prims (synthetic bench scenes) ----------------
    # Skip geometry prims whose DIRECT parent is a rigid-body Xform
    # (those are visual sub-meshes of a robot link, already captured above).
    for prim in stage.Traverse():
        type_name = prim.GetTypeName()
        if type_name not in GEOMETRY_TYPES:
            continue
        parent_path = str(prim.GetParent().GetPath())
        if parent_path in rigid_body_xform_paths:
            continue   # sub-mesh of a robot link — skip
        bbox = _compute_bbox(prim, bbox_cache)
        ep = _read_existing_physics(prim)
        geom_prims.append(GeomPrimInfo(
            path=str(prim.GetPath()),
            type_name=type_name,
            display_name=prim.GetName(),
            bbox=bbox,
            fill_factor=FILL_FACTORS.get(type_name, 0.6),
            existing_physics=ep,
        ))

    # --- Pass 4: joints -------------------------------------------------------
    for prim in stage.Traverse():
        if prim.GetTypeName() in JOINT_TYPES:
            joint_prims.append(_read_joint(prim))

    _annotate_prismatic_body_lengths(joint_prims, geom_prims)

    return SceneGraph(
        up_axis=up_axis,
        meters_per_unit=meters_per_unit,
        geom_prims=geom_prims,
        joint_prims=joint_prims,
    )
