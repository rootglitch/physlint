# USD Physics Compliance Report

**Generated:** 2026-02-23T15:51:07.338157Z  
**Input:** `/home/raajg/projects/physint/assets/demo_gripper.usda`  
**Output:** `/home/raajg/projects/physint/assets/demo_gripper_physics.usda`  

## Summary

| | |
|---|---|
| Geometry prims processed | 10 |
| Joint prims processed | 1 |
| Joint limit corrections | 1 |

> **Model notes:** All objects are rigid and have appropriate collision approximations. The elbow joint's upper limit has been corrected for realism.

## Geometry Physics Properties

| Prim | Material | Mass (kg) | Static μ | Dynamic μ | Restitution | Collision |
|------|----------|-----------|----------|-----------|-------------|-----------|
| `/World/PressureVessel/Body` | steel | 353.25 | 0.45 | 0.35 | 0.30 | convexHull |
| `/World/PressureVessel/TopCap` | aluminum | 38.20 | 0.45 | 0.35 | 0.30 | convexHull |
| `/World/PressureVessel/BottomCap` | aluminum | 38.20 | 0.45 | 0.35 | 0.30 | convexHull |
| `/World/RubberGasket` | rubber | 3.30 | 0.70 | 0.60 | 0.05 | convexHull |
| `/World/SupportFrame/Base` | concrete | 3.86 | 0.55 | 0.45 | 0.10 | convexHull |
| `/World/SupportFrame/PillarLeft` | steel | 4.41 | 0.45 | 0.35 | 0.30 | convexHull |
| `/World/SupportFrame/PillarRight` | steel | 4.41 | 0.45 | 0.35 | 0.30 | convexHull |
| `/World/RobotArm/UpperArm` | aluminum | 1.09 | 0.45 | 0.35 | 0.30 | convexHull |
| `/World/RobotArm/LowerArm` | aluminum | 1.09 | 0.45 | 0.35 | 0.30 | convexHull |
| `/World/ValveHandle` | aluminum | 2.70 | 0.45 | 0.35 | 0.30 | convexHull |

## Joint Limit Assessment

| Joint | Lower (°) | Upper (°) | Valid? | Notes |
|-------|-----------|-----------|--------|-------|
| `/World/RobotArm/ElbowJoint` | -10.0 | 145.0 | ⚠️ corrected | Original upper limit of 220.0° is unrealistic for a human-like elbow joint; corrected to 145.0°. |

## Model Reasoning (Chain of Thought)

```
### STEP 1 — REASONING

**Pressure Vessel Body:**  
The cylindrical body has a smooth, metallic gray surface with a slight sheen, suggesting it is made of steel. Its dimensions are 30.0 x 30.0 x 50.0 stage units, which translates to 0.3 x 0.3 x 0.5 meters. The volume is 0.045 m³, and using a density of 7850 kg/m³ for steel, the estimated mass is 353.25 kg. The material properties suggest a static friction of 0.45, dynamic friction of 0.35, and a restitution of 0.30. Given its simple cylindrical shape, a convexHull approximation is appropriate, and it is rigid.

**TopCap and BottomCap:**  
Both spherical caps have a matte gray finish, indicating they are likely made of aluminum. Each cap has a diameter of 30.0 stage units (0.3 meters), giving a volume of 0.014137 m³ per cap. With a density of 2700 kg/m³, the mass is 38.2 kg per cap. The friction and restitution values align with aluminum, and the convexHull approximation is suitable. Both are rigid.

**Rubber Gasket:**  
This cylindrical gasket has a matte black finish, typical of rubber. Its dimensions are 33.0 x 33.0 x 2.5 stage units (0.33 x 0.33 x 0.025 meters), resulting in a volume of 0.0027465 m³. Using a density of 1200 kg/m³ for rubber, the mass is 3.2958 kg. The friction and restitution values match rubber, and the convexHull approximation is valid. It is rigid.

**Support Frame Base:**  
The base is a flat, matte gray rectangle, likely concrete. Its dimensions are 42.0 x 2.0 x 20.0 stage units (0.42 x 0.02 x 0.2 meters), giving a volume of 0.00168 m³. With a density of 2300 kg/m³, the mass is 3.864 kg. The friction and restitution values align with concrete, and the convexHull approximation is suitable. It is rigid.

**Support Frame Pillars:**  
The pillars are vertical, matte gray cubes, likely steel. Each pillar has dimensions of 3.0 x 62.0 x 3.0 stage units (0.03 x 0.62 x 0.03 meters), resulting in a volume of 0.000558 m³. Using a density of 7850 kg/m³, the mass is 4.41 kg per pillar. The friction and restitution values match steel, and the convexHull approximation is appropriate. Both are rigid.

**Robot Arm UpperArm and LowerArm:**  
Both arms are matte gray cubes, likely aluminum. Each arm has dimensions of 4.5 x 20.0 x 4.5 stage units (0.045 x 0.2 x 0.045 meters), giving a volume of 0.000405 m³. With a density of 2700 kg/m³, the mass is 1.0935 kg per arm. The friction and restitution values align with aluminum, and the convexHull approximation is suitable. Both are rigid.

**Valve Handle:**  
The handle is a matte gray cylinder, likely aluminum. Its dimensions are 10.0 x 10.0 x 10.0 stage units (0.1 x 0.1 x 0.1 meters), resulting in a volume of 0.001 m³. Using a density of 2700 kg/m³, the mass is 2.7 kg. The friction and restitution values match aluminum, and the convexHull approximation is valid. It is rigid.

**Robot Arm Elbow Joint:**  
The elbow joint has a lower limit of -10.0° and an upper limit of 220.0°. This upper limit is unrealistic for a human-like elbow, which typically cannot exceed 145°. The corrected limits should be -10.0° to 145.0°.

### STEP 2 — JSON OUTPUT

```json
{
  "geom_prims": [
    {
      "prim_path": "/World/PressureVessel/Body",
      "material_type": "steel",
      "mass_kg": 353.25,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Cylindrical steel body with smooth, metallic gray surface; volume 0.045 m³, density 7850 kg/m³, mass 353.25 kg."
    },
    {
      "prim_path": "/World/PressureVessel/TopCap",
      "material_type": "aluminum",
      "mass_kg": 38.2,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Spherical aluminum cap with matte gray finish; volume 0.014137 m³, density 2700 kg/m³, mass 38.2 kg."
    },
    {
      "prim_path": "/World/PressureVessel/BottomCap",
      "material_type": "aluminum",
      "mass_kg": 38.2,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Spherical aluminum cap with matte gray finish; volume 0.014137 m³, density 2700 kg/m³, mass 38.2 kg."
    },
    {
      "prim_path": "/World/RubberGasket",
      "material_type": "rubber",
      "mass_kg": 3.2958,
      "static_friction": 0.7,
      "dynamic_friction": 0.6,
      "restitution": 0.05,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Cylindrical rubber gasket with matte black finish; volume 0.0027465 m³, density 1200 kg/m³, mass 3.2958 kg."
    },
    {
      "prim_path": "/World/SupportFrame/Base",
      "material_type": "concrete",
      "mass_kg": 3.864,
      "static_friction": 0.55,
      "dynamic_friction": 0.45,
      "restitution": 0.1,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Flat concrete base with matte gray finish; volume 0.00168 m³, density 2300 kg/m³, mass 3.864 kg."
    },
    {
      "prim_path": "/World/SupportFrame/PillarLeft",
      "material_type": "steel",
      "mass_kg": 4.41,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Vertical steel pillar with matte gray finish; volume 0.000558 m³, density 7850 kg/m³, mass 4.41 kg."
    },
    {
      "prim_path": "/World/SupportFrame/PillarRight",
      "material_type": "steel",
      "mass_kg": 4.41,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Vertical steel pillar with matte gray finish; volume 0.000558 m³, density 7850 kg/m³, mass 4.41 kg."
    },
    {
      "prim_path": "/World/RobotArm/UpperArm",
      "material_type": "aluminum",
      "mass_kg": 1.0935,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Cubical aluminum arm with matte gray finish; volume 0.000405 m³, density 2700 kg/m³, mass 1.0935 kg."
    },
    {
      "prim_path": "/World/RobotArm/LowerArm",
      "material_type": "aluminum",
      "mass_kg": 1.0935,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Cubical aluminum arm with matte gray finish; volume 0.000405 m³, density 2700 kg/m³, mass 1.0935 kg."
    },
    {
      "prim_path": "/World/ValveHandle",
      "material_type": "aluminum",
      "mass_kg": 2.7,
      "static_friction": 0.45,
      "dynamic_friction": 0.35,
      "restitution": 0.3,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "reasoning": "Cylindrical aluminum handle with matte gray finish; volume 0.001 m³, density 2700 kg/m³, mass 2.7 kg."
    }
  ],
  "joint_prims": [
    {
      "prim_path": "/World/RobotArm/ElbowJoint",
      "lower_limit_deg": -10.0,
      "upper_limit_deg": 145.0,
      "joint_valid": false,
      "reasoning": "Original upper limit of 220.0° is unrealistic for a human-like elbow joint; corrected to 145.0°."
    }
  ],
  "global_notes": "All objects are rigid and have appropriate collision approximations. The elbow joint's upper limit has been corrected for realism."
}
```
```
