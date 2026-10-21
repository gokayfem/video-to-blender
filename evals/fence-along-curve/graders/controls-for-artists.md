---
type: llm
focus:
  source: file
  path: build.py
---

The file is a Python script that builds a Geometry Nodes fence for Blender and puts it on a curve as a modifier. The user asked to change post spacing, fence height, rail count, randomness and seed from the modifier panel.

PASS if all hold:
- The top-level modifier group exposes inputs for post spacing, fence height, rail count, random variation (lean or height or both) and seed, named in plain words an artist understands (for example "Post Spacing", not "Socket_3", "val2" or "f_sp").
- Those inputs have sensible defaults and minimum/maximum ranges (at least spacing and height), and descriptions.
- The fence geometry is derived from the curve the modifier is on (or a curve passed in as an input), not from hard-coded coordinates, so it would follow a different curve.

FAIL if any control the user listed is missing, if controls are only Python variables that are baked into the nodes, or if the fence ignores the curve.
