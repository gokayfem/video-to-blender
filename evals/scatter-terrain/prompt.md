---
description: "Surface scatter with density and slope controls on a terrain mesh."
tags: [positive]
expected_outcome: "build.py builds a Geometry Nodes scatter that distributes rocks and flowers on a terrain mesh, masks them by slope, exposes density and slope controls, and saves scene.blend; the skill fires and its tools run."
max_turns: 50
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Can you make me a Blender 5.2 setup that scatters rocks and little flowers over a terrain mesh? Rocks should sit mostly on the steeper parts and flowers on the flatter ground, with nothing on near-vertical faces. I want controls for rock density, flower density, the slope threshold between them, the size range and a seed, so I can reuse it on other terrains. Make a simple hilly test terrain to show it on. Write everything as `build.py` so that `blender -b --python build.py` builds the nodes and saves `scene.blend`.
