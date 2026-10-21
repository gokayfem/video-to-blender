---
type: llm
focus:
  source: file
  path: build.py
---

The file is a Python script that builds a Geometry Nodes building generator in Blender that turns a closed footprint into a building.

PASS if all hold:
- The building is derived from the footprint geometry the modifier receives (a curve or flat mesh outline), and the script shows it on at least two different footprints using the same node group.
- The modifier exposes floor count, floor height, window width, window spacing and a wall colour variation control, with plain artist-facing names, ranges and descriptions.
- Windows are placed along every wall from the wall lengths (for example by resampling the footprint edges or distributing along them), and there is a ledge and a roof parapet.

FAIL if the building is a fixed box scaled to the footprint's bounding box, if any listed control is missing, or if each footprint gets its own copy of the generator with different hard-coded values.
