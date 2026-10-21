---
description: "Parametric building generator that runs on any footprint."
tags: [positive]
expected_outcome: "build.py builds a Geometry Nodes building generator that extrudes a footprint (curve or mesh) into storeys with windows, a ledge and a roof, exposes floor count, floor height and similar controls, and saves scene.blend; the skill fires and its tools run."
max_turns: 50
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I need a procedural building generator for Blender 5.2 for a city block. It should take any closed footprint (I'll draw them as curves or flat mesh outlines) and turn it into a building: a number of floors, a ledge between ground floor and upper floors, windows spaced along every wall, and a flat roof with a parapet. Floor count, floor height, window width and spacing, and wall colour variation should be controls on the modifier, and it should still work when I change the footprint shape. Please put it in `build.py`, show it on two or three different footprints, and save the result to `scene.blend` when run with `blender -b --python build.py`.
