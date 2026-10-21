---
applyTo: "**/*.py"
---

Copy this file into your repository's `.github/instructions/`. It applies to Python files that use `bpy` to build
Blender node systems; ignore it for other Python. For agent mode, also install the skill with
`gh skill install gokayfem/video-to-blender procedural-blender-nodes`.

- Build node trees from Python for Blender 5.2+ with nodekit's `Graph` (from the `procedural-blender-nodes` skill),
  and instance the tested `NK` library groups instead of hand-writing copies.
- Give every group and input a description, inputs ranges and subtypes, put them in panels (Primary first), and
  frame each block with a sentence.
- Animated groups take a `Time` input in seconds; only the top-level modifier group reads Scene Time. Per-piece
  variation goes to materials through `nk_color` and `nk_rand` attributes.
- Build shared groups once; rebuilding one clears its interface and unlinks every user.
- Never set modifier inputs as ID properties (`mod["Socket_2"]`); use
  `nodekit.inspect.set_modifier_inputs(mod, {"Name": value})` (`mod.properties.inputs.<identifier>.value`).
- Run Blender as `blender -b --factory-startup --python build.py`, then validate the saved .blend with
  `scripts/validate.py`: zero node warnings, zero lint.
