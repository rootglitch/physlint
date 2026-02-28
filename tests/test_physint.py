"""
pytest suite for USD Physics Linter.

All tests run without a GPU — model inference is not exercised here.
Tests cover: USD parsing, fill_factor correctness, JSON extraction,
report generation, and physics write-back.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import pytest

ASSETS = Path(__file__).parent.parent / "assets"
DEMO_USD = ASSETS / "demo_gripper.usda"


# ---------------------------------------------------------------------------
# usd_parser
# ---------------------------------------------------------------------------

class TestParseUsd:
    def test_finds_expected_prim_counts(self):
        from src.usd_parser import parse_usd

        sg = parse_usd(str(DEMO_USD))
        # The demo scene has 10 geometry prims and 1 revolute joint
        assert len(sg.geom_prims) == 10, (
            f"Expected 10 geom prims, got {len(sg.geom_prims)}: "
            f"{[p.path for p in sg.geom_prims]}"
        )
        assert len(sg.joint_prims) == 1, (
            f"Expected 1 joint prim, got {len(sg.joint_prims)}"
        )

    def test_stage_metadata(self):
        from src.usd_parser import parse_usd

        sg = parse_usd(str(DEMO_USD))
        assert sg.up_axis == "Y"
        assert sg.meters_per_unit == pytest.approx(0.01)

    def test_joint_limits_read_correctly(self):
        from src.usd_parser import parse_usd

        sg = parse_usd(str(DEMO_USD))
        joint = sg.joint_prims[0]
        assert joint.upper_limit == pytest.approx(220.0), (
            "Demo scene elbow joint should have upper_limit=220°"
        )

    def test_all_geom_prims_have_fill_factor(self):
        from src.usd_parser import parse_usd

        sg = parse_usd(str(DEMO_USD))
        for p in sg.geom_prims:
            assert 0.0 < p.fill_factor <= 1.0, (
                f"{p.path} has invalid fill_factor={p.fill_factor}"
            )

    def test_fill_factor_values_by_type(self):
        from src.usd_parser import parse_usd, FILL_FACTORS

        sg = parse_usd(str(DEMO_USD))
        for p in sg.geom_prims:
            expected = FILL_FACTORS.get(p.type_name, 0.6)
            assert p.fill_factor == pytest.approx(expected), (
                f"{p.path} type={p.type_name} expected fill_factor={expected}, "
                f"got {p.fill_factor}"
            )

    def test_scene_graph_serialises_fill_factor(self):
        from src.usd_parser import parse_usd

        sg = parse_usd(str(DEMO_USD))
        d = sg.to_dict()
        for gp in d["geom_prims"]:
            assert "fill_factor" in gp, f"{gp['path']} missing fill_factor in to_dict()"
            assert 0.0 < gp["fill_factor"] <= 1.0


# ---------------------------------------------------------------------------
# FILL_FACTORS correctness
# ---------------------------------------------------------------------------

class TestFillFactors:
    """Verify the analytical values are correct to 1%."""

    def test_cylinder(self):
        from src.usd_parser import FILL_FACTORS
        assert FILL_FACTORS["Cylinder"] == pytest.approx(math.pi / 4, rel=0.01)

    def test_sphere(self):
        from src.usd_parser import FILL_FACTORS
        assert FILL_FACTORS["Sphere"] == pytest.approx(math.pi / 6, rel=0.01)

    def test_cone(self):
        from src.usd_parser import FILL_FACTORS
        assert FILL_FACTORS["Cone"] == pytest.approx(math.pi / 12, rel=0.01)

    def test_cube_is_one(self):
        from src.usd_parser import FILL_FACTORS
        assert FILL_FACTORS["Cube"] == pytest.approx(1.0)

    def test_mesh_conservative(self):
        from src.usd_parser import FILL_FACTORS
        # Mesh default should be < 1.0 (conservative, not exact)
        assert 0.4 <= FILL_FACTORS["Mesh"] < 1.0


# ---------------------------------------------------------------------------
# cosmos_client — JSON extraction (no GPU required)
# ---------------------------------------------------------------------------

class TestExtractJson:
    def _sample_response(self, extra_text: str = "") -> str:
        payload = {
            "geom_prims": [
                {
                    "prim_path": "/World/Body",
                    "material_type": "steel",
                    "mass_kg": 12.5,
                    "static_friction": 0.45,
                    "dynamic_friction": 0.35,
                    "restitution": 0.30,
                    "collision_approximation": "convexHull",
                    "is_rigid": True,
                    "confidence": "high",
                    "reasoning": "Silver-grey metallic body with specular highlight.",
                }
            ],
            "joint_prims": [
                {
                    "prim_path": "/World/ElbowJoint",
                    "lower_limit_deg": -10.0,
                    "upper_limit_deg": 145.0,
                    "joint_valid": False,
                    "confidence": "high",
                    "reasoning": "220° is impossible for a human elbow joint.",
                }
            ],
            "global_notes": "Scene is well-lit.",
        }
        return f"{extra_text}\n```json\n{json.dumps(payload)}\n```\n"

    def test_extracts_json_from_code_fence(self):
        from src.cosmos_client import _extract_json

        raw = self._sample_response("Some chain-of-thought reasoning here.")
        result = _extract_json(raw)
        assert result["geom_prims"][0]["material_type"] == "steel"
        assert result["joint_prims"][0]["joint_valid"] is False

    def test_parses_into_physics_analysis(self):
        from src.cosmos_client import _extract_json, PhysicsAnalysis

        raw = self._sample_response()
        result = _extract_json(raw)
        analysis = PhysicsAnalysis(**result)

        assert len(analysis.geom_prims) == 1
        assert len(analysis.joint_prims) == 1
        assert analysis.geom_prims[0].mass_kg == pytest.approx(12.5)
        assert analysis.joint_prims[0].upper_limit_deg == pytest.approx(145.0)

    def test_dynamic_friction_clamped_to_static(self):
        """Pydantic validator must silently clamp dynamic_friction > static_friction."""
        from src.cosmos_client import GeomPhysics

        gp = GeomPhysics(
            prim_path="/World/Test",
            material_type="rubber",
            mass_kg=1.0,
            static_friction=0.7,
            dynamic_friction=0.9,   # intentionally too high
            restitution=0.05,
            collision_approximation="convexHull",
            is_rigid=True,
            confidence="high",
            reasoning="test",
        )
        assert gp.dynamic_friction <= gp.static_friction + 0.05


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

class TestReport:
    def _make_analysis(self):
        from src.cosmos_client import PhysicsAnalysis, GeomPhysics, JointPhysics

        return PhysicsAnalysis(
            geom_prims=[
                GeomPhysics(
                    prim_path="/World/Body",
                    material_type="steel",
                    mass_kg=12.5,
                    static_friction=0.45,
                    dynamic_friction=0.35,
                    restitution=0.30,
                    collision_approximation="convexHull",
                    is_rigid=True,
                    confidence="high",
                    reasoning="Silver-grey metallic.",
                )
            ],
            joint_prims=[
                JointPhysics(
                    prim_path="/World/ElbowJoint",
                    lower_limit_deg=-10.0,
                    upper_limit_deg=145.0,
                    joint_valid=False,
                    confidence="high",
                    reasoning="220° is impossible for a human elbow.",
                )
            ],
            global_notes="",
        )

    def test_report_structure(self):
        from src.usd_parser import parse_usd
        from src.report import generate_report

        sg = parse_usd(str(DEMO_USD))
        analysis = self._make_analysis()
        report = generate_report(
            sg, analysis, "chain of thought",
            ["top.png", "front.png", "side.png", "iso.png"],
            str(DEMO_USD), None,
        )

        assert report["summary"]["joint_limit_corrections"] == 1
        assert report["summary"]["geometry_prims_processed"] == 1
        assert len(report["geometry_findings"]) == 1
        assert len(report["joint_findings"]) == 1

    def test_markdown_flags_violations(self):
        from src.usd_parser import parse_usd
        from src.report import generate_report, save_report

        sg = parse_usd(str(DEMO_USD))
        analysis = self._make_analysis()
        report = generate_report(
            sg, analysis, "cot",
            ["top.png", "front.png", "side.png", "iso.png"],
            str(DEMO_USD), None,
        )

        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "report.json")
            md_path = os.path.join(tmp, "report.md")
            save_report(report, json_path, md_path)

            md = Path(md_path).read_text()
            assert "VIOLATIONS FOUND" in md
            assert "ElbowJoint" in md

    def test_clean_scene_shows_pass(self):
        from src.cosmos_client import PhysicsAnalysis, GeomPhysics, JointPhysics
        from src.usd_parser import parse_usd
        from src.report import generate_report, save_report

        sg = parse_usd(str(DEMO_USD))
        clean_analysis = PhysicsAnalysis(
            geom_prims=[
                GeomPhysics(
                    prim_path="/World/Body",
                    material_type="steel",
                    mass_kg=12.5,
                    static_friction=0.45,
                    dynamic_friction=0.35,
                    restitution=0.30,
                    collision_approximation="convexHull",
                    is_rigid=True,
                    confidence="high",
                    reasoning="Clearly steel.",
                )
            ],
            joint_prims=[
                JointPhysics(
                    prim_path="/World/ElbowJoint",
                    lower_limit_deg=-10.0,
                    upper_limit_deg=145.0,
                    joint_valid=True,   # no violation
                    confidence="high",
                    reasoning="Limits are anatomically valid.",
                )
            ],
        )
        report = generate_report(
            sg, clean_analysis, "cot",
            ["top.png", "front.png", "side.png", "iso.png"],
            str(DEMO_USD), None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, "report.json")
            md_path = os.path.join(tmp, "report.md")
            save_report(report, json_path, md_path)

            md = Path(md_path).read_text()
            assert "PASS" in md
            assert "VIOLATIONS FOUND" not in md


# ---------------------------------------------------------------------------
# physics_writer
# ---------------------------------------------------------------------------

class TestPhysicsWriter:
    def test_write_applies_mass_api(self):
        from src.cosmos_client import PhysicsAnalysis, GeomPhysics, JointPhysics
        from src.physics_writer import write_physics
        from pxr import Usd, UsdPhysics

        analysis = PhysicsAnalysis(
            geom_prims=[
                GeomPhysics(
                    prim_path="/World/PressureVessel/Body",
                    material_type="steel",
                    mass_kg=353.25,
                    static_friction=0.45,
                    dynamic_friction=0.35,
                    restitution=0.30,
                    collision_approximation="convexHull",
                    is_rigid=True,
                    confidence="high",
                    reasoning="Steel cylinder.",
                )
            ],
            joint_prims=[
                JointPhysics(
                    prim_path="/World/RobotArm/ElbowJoint",
                    lower_limit_deg=-10.0,
                    upper_limit_deg=145.0,
                    joint_valid=False,
                    confidence="high",
                    reasoning="Original 220° is impossible.",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_usd = os.path.join(tmp, "out.usda")
            write_physics(str(DEMO_USD), analysis, out_usd, meters_per_unit=0.01)

            stage = Usd.Stage.Open(out_usd)
            body = stage.GetPrimAtPath("/World/PressureVessel/Body")
            assert body.IsValid(), "Body prim should exist in output USD"
            assert body.HasAPI(UsdPhysics.MassAPI), "MassAPI should be applied"

            mass_api = UsdPhysics.MassAPI(body)
            mass_val = mass_api.GetMassAttr().Get()
            assert mass_val == pytest.approx(353.25, rel=0.01)

    def test_write_corrects_joint_limit(self):
        from src.cosmos_client import PhysicsAnalysis, GeomPhysics, JointPhysics
        from src.physics_writer import write_physics
        from pxr import Usd

        analysis = PhysicsAnalysis(
            geom_prims=[],
            joint_prims=[
                JointPhysics(
                    prim_path="/World/RobotArm/ElbowJoint",
                    lower_limit_deg=-10.0,
                    upper_limit_deg=145.0,
                    joint_valid=False,
                    confidence="high",
                    reasoning="220° corrected to 145°.",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_usd = os.path.join(tmp, "out.usda")
            write_physics(str(DEMO_USD), analysis, out_usd, meters_per_unit=0.01)

            stage = Usd.Stage.Open(out_usd)
            joint = stage.GetPrimAtPath("/World/RobotArm/ElbowJoint")
            assert joint.IsValid()
            upper = joint.GetAttribute("physics:upperLimit").Get()
            assert upper == pytest.approx(145.0)
