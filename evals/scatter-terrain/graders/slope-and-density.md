---
type: llm
focus:
  source: file
  path: build.py
---

The file is a Python script that builds a Geometry Nodes scatter of rocks and flowers on a terrain mesh in Blender.

PASS if all hold:
- The slope of the surface is computed from the surface normal (for example the Z component of the Normal, or the angle between the normal and up) and used to send rocks to steeper ground and flowers to flatter ground, with nothing placed on near-vertical faces.
- The modifier exposes separate rock density and flower density controls, a slope threshold, a size range (minimum and maximum, or a size plus a variation) and a seed.
- The scatter works on whatever mesh the modifier is on (or a mesh passed as an input), not only on the test terrain.

FAIL if slope is ignored or faked (for example by height alone), if densities are not controls, or if points are placed with Python instead of nodes.
