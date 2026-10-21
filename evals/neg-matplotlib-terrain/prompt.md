---
description: "Near miss: a procedural terrain, but as a matplotlib 3D surface plot."
tags: [negative]
expected_outcome: "plot_terrain.py builds a heightfield with numpy and saves a matplotlib 3D surface plot to terrain.png; the Blender skill does not fire."
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

For a lecture slide I need a 3D picture of a procedurally generated terrain: build a 128x128 heightfield from a few octaves of noise with numpy, plot it as a 3D surface with matplotlib using the terrain colormap, view it from about 35 degrees elevation, and save it as `terrain.png`. Put the script in `plot_terrain.py`. Only numpy and matplotlib, please.
