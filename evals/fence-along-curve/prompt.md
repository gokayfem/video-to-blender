---
description: "Curve-following Geometry Nodes generator with exposed artist controls, built from a natural request."
tags: [positive]
expected_outcome: "build.py builds a Geometry Nodes fence group that follows any curve (posts at a spacing, rails between them) with named, described controls on the modifier, and saves scene.blend; the skill fires and its tools run."
max_turns: 50
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I want a reusable wooden fence for Blender 5.2 that I can drop onto any curve object: posts at a regular spacing, two horizontal rails between them, a bit of random lean and height variation per post so it doesn't look CG, and a weathered wood material. I need to be able to change post spacing, fence height, rail count, randomness and seed from the modifier panel without opening the node editor. Please write it as a Python script, `build.py`, that builds the node setup, puts it on a wavy test curve, and saves the file as `scene.blend` when I run `blender -b --python build.py`.
