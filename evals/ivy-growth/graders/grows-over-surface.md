---
type: llm
focus:
  source: file
  path: build.py
---

The file is a Python script that builds a Geometry Nodes ivy growth effect in Blender.

PASS if all hold:
- Growth carries state from frame to frame in a simulation zone: the stems (points or curves) found on one frame are extended on the next, rather than a precomputed path being revealed by a Time or frame threshold alone.
- New growth is kept on the target mesh (for example by sampling or projecting onto the nearest surface, or moving along it), and starts from seed points near the bottom of the mesh.
- Growth speed, branching and leaf density are inputs on the modifier, and leaves are instanced along the stems.

FAIL if there is no simulation zone, if the growth is a fixed animation independent of the previous frame, or if vines float freely off the surface.
