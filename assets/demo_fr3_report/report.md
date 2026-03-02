# USD Physics Compliance Report

**Status:** 🔴 VIOLATIONS FOUND  
**Generated:** 2026-03-01T22:29:04.323813Z  
**Input:** `/mnt/c/Crypt/Projects/physlint/assets/demo_fr3.usda`  
**Mode:** Dry run — input USD not modified  

## Summary

| | |
|---|---|
| Geometry prims processed | 9 |
| Joint prims processed | 7 |
| Joint violations detected | 🔴 2 |

> **Model notes:** Two joints violated industrial robot constraints: fr3_joint6 and fr3_joint2. Both were corrected to upper limit 180°.

## Geometry Physics Properties

| Prim | Material | Confidence | Mass (kg) | Static μ | Dynamic μ | Restitution | Collision |
|------|----------|------------|-----------|----------|-----------|-------------|-----------|
| `/fr3/Geometry/base` | steel | 🟢 high | 440.33 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0` | aluminium | 🟢 high | 9.68 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0/fr3_link1` | steel | 🟢 high | 23.60 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2` | aluminium | 🟢 high | 8.12 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3` | steel | 🟢 high | 26.77 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4` | aluminium | 🟢 high | 9.21 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5` | steel | 🟢 high | 29.92 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6` | aluminium | 🟢 high | 3.92 | 0.00 | 0.00 | 0.00 | convexHull |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_link7` | steel | 🟢 high | 4.05 | 0.00 | 0.00 | 0.00 | convexHull |

## Joint Limit Assessment

| Joint | Status | Original lower | Original upper | Suggested lower | Suggested upper | Reason |
|-------|--------|---------------|----------------|-----------------|-----------------|--------|
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_link7/fr3_joint7` | ✅ valid | -172.79833984375 | 172.79833984375 | — | — | Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_link7/fr3_joint7: lower=-172.79833984375°, upper=172.79833984375°. Within industrial robot range (-180° to 180°). Valid. |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_joint6` | 🔴 violation | 31.197551727294922 | 258.79931640625 | 31.197551727294922 | 180.0 | Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_joint6: lower=31.197551727294922°, upper=258.79931640625°. Upper limit exceeds 180°, violating industrial robot joint constraints. VIOLATED. Corrected: lower=31.197551727294922°, upper=180°. |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_joint5` | ✅ valid | -160.80059814453125 | 160.80059814453125 | — | — | Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_joint5: lower=-160.80059814453125°, upper=160.80059814453125°. Within industrial robot range (-180° to 180°). Valid. |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_joint4` | ✅ valid | -174.2994842529297 | -8.69749927520752 | — | — | Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_joint4: lower=-174.2994842529297°, upper=-8.69749927520752°. Within industrial robot range (-180° to 180°). Valid. |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_joint3` | ✅ valid | -166.19786071777344 | 166.19786071777344 | — | — | Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_joint3: lower=-166.19786071777344°, upper=166.19786071777344°. Within industrial robot range (-180° to 180°). Valid. |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_joint2` | 🔴 violation | -102.19847869873047 | 220.0 | -102.19847869873047 | 180.0 | Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_joint2: lower=-102.19847869873047°, upper=220.0°. Upper limit exceeds 180°, violating industrial robot joint constraints. VIOLATED. Corrected: lower=-102.19847869873047°, upper=180°. |
| `/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_joint1` | ✅ valid | -157.20242309570312 | 157.20242309570312 | — | — | Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_joint1: lower=-157.20242309570312°, upper=157.20242309570312°. Within industrial robot range (-180° to 180°). Valid. |

## Model Reasoning (Chain of Thought)

```
=== PASS 1: CONTEXT PRE-PASS ===
```json
{
  "mechanism_type": "6-DOF industrial robot arm",
  "expected_joint_ranges": "revolute joints with varying ranges: -174.3° to -8.7°, -166.2° to +166.2°, -160.8° to +160.8°, -157.2° to +157.2°, 31.2° to 258.8°, and -172.8° to +172.8°",
  "validation_context": "Validate that all joints operate within their specified angular limits to ensure safe and precise movement of the robot arm."
}
```

=== PASS 2: MAIN ANALYSIS ===
 STEP 1 — REASONING

For each geometry prim write ONE line:
  "Prim <path>: material=<X> because <1-2 word visual cue>. Confidence:<level>."
  (Mass is computed automatically from bbox — you do NOT need to calculate it.)
For each joint prim write 2-3 sentences (full reasoning required for joint validation):
  Revolute: "Joint <name>: lower=<X>°, upper=<Y>°. <reason why valid/invalid>.
   Corrected: lower=<A>°, upper=<B>°. Confidence:<level>."
  Prismatic: "Joint <name>: lower=<X>, upper=<Y>, body_length_along_axis=<B>.
   travel=upper−lower=<T>. <T> vs <B>: <exceeds→VIOLATED, joint_valid=false|fits→valid, joint_valid=true>.
   Corrected if needed: lower=<A>, upper=<C>. Confidence:<level>."

Prim /fr3/Geometry/base: material=steel because dark grey metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0: material=aluminium because light silver metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0/fr3_link1: material=steel because dark grey metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2: material=aluminium because light silver metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3: material=steel because dark grey metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4: material=aluminium because light silver metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5: material=steel because dark grey metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6: material=aluminium because light silver metallic appearance. Confidence:high.
Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_link7: material=steel because dark grey metallic appearance. Confidence:high.

Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_link7/fr3_joint7: lower=-172.79833984375°, upper=172.79833984375°. Within industrial robot range (-180° to 180°). Valid. Confidence:high.
Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_joint6: lower=31.197551727294922°, upper=258.79931640625°. Upper limit exceeds 180°, violating industrial robot joint constraints. VIOLATED. Corrected: lower=31.197551727294922°, upper=180°. Confidence:high.
Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_joint5: lower=-160.80059814453125°, upper=160.80059814453125°. Within industrial robot range (-180° to 180°). Valid. Confidence:high.
Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_joint4: lower=-174.2994842529297°, upper=-8.69749927520752°. Within industrial robot range (-180° to 180°). Valid. Confidence:high.
Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_joint3: lower=-166.19786071777344°, upper=166.19786071777344°. Within industrial robot range (-180° to 180°). Valid. Confidence:high.
Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_joint2: lower=-102.19847869873047°, upper=220.0°. Upper limit exceeds 180°, violating industrial robot joint constraints. VIOLATED. Corrected: lower=-102.19847869873047°, upper=180°. Confidence:high.
Joint /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_joint1: lower=-157.20242309570312°, upper=157.20242309570312°. Within industrial robot range (-180° to 180°). Valid. Confidence:high.

 STEP 2 — JSON OUTPUT

```json
{
  "geom_prims": [
    {
      "prim_path": "/fr3/Geometry/base",
      "material_type": "steel",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base: material=steel because dark grey metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0",
      "material_type": "aluminium",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base/fr3_link0: material=aluminium because light silver metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0/fr3_link1",
      "material_type": "steel",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base/fr3_link0/fr3_link1: material=steel because dark grey metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2",
      "material_type": "aluminium",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2: material=aluminium because light silver metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3",
      "material_type": "steel",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3: material=steel because dark grey metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4",
      "material_type": "aluminium",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4: material=aluminium because light silver metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5",
      "material_type": "steel",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5: material=steel because dark grey metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6",
      "material_type": "aluminium",
      "mass_kg": 0.0,
      "static_friction": 0.0,
      "dynamic_friction": 0.0,
      "restitution": 0.0,
      "collision_approximation": "convexHull",
      "is_rigid": true,
      "confidence": "high",
      "reasoning": "Prim /fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6: material=aluminium because light silver metallic appearance."
    },
    {
      "prim_path": "/fr3/Geometry/base/fr3_link0/fr3_link1/fr3_link2/fr3_link3/fr3_link4/fr3_link5/fr3_link6/fr3_link7",
      "material_type": 
```
