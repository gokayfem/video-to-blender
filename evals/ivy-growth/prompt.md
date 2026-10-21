---
description: "Growth that depends on the previous frame: ivy creeping over a mesh, which needs a simulation zone."
tags: [positive]
expected_outcome: "build.py builds a Geometry Nodes ivy that grows over a target mesh over time using a simulation zone (state carried frame to frame), with growth speed and density controls, and saves scene.blend; the skill fires and its tools run."
max_turns: 50
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I'd like an ivy growth effect in Blender 5.2: vines start from a few seed points at the bottom of any mesh I pick, creep up and over its surface frame by frame, branch now and then, and get leaves along the older parts of the stems. Growth speed, branching and leaf density should be controls on the modifier. Show it on a simple stone column (a cylinder is fine) and keep the timeline at about 250 frames. Please write `build.py` that builds the node setup and saves `scene.blend` when run with `blender -b --python build.py`.
