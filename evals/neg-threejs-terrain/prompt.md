---
description: "Near miss: a procedural terrain scene, but in three.js in the browser."
tags: [negative]
expected_outcome: "index.html is a single-page three.js scene with a noise-displaced terrain, lights and an animation loop; the Blender skill does not fire."
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Make me a single-file three.js page, `index.html`, that shows a procedural low-poly terrain: a plane displaced with layered noise, flat-shaded with colours by height (sand, grass, rock, snow), a directional light, fog, and a slow orbiting camera. Load three.js from a CDN as an ES module; no build step.
