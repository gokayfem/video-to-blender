---
name: procedural-blender-nodes
description: >-
  Builds, debugs, and art-directs procedural Blender node systems from Python: Geometry Nodes generators and
  modifiers, Shader Node materials, simulation and repeat zones, analytic animation, and compositor looks, as
  readable node groups with artist controls that work on new input geometry. Ships nodekit (a graph builder and
  inspector), a tested NK node-group library (curve placement, shapes, scatter, motion, materials, post), templates,
  and a checker. Use when the user wants a Geometry Nodes setup, a procedural asset or generator in Blender, a
  bpy script that creates node trees, node-based materials or effects, or wants such a script fixed, ported to
  Blender 5.x, organised, or explained; also for recreating a reference (image, clip or description) as an
  editable node system. Not for Unity/Unreal/Houdini graphs, three.js, or plain mesh modelling without nodes.
license: MIT
metadata:
  hermes:
    tags:
      - blender
      - geometry-nodes
      - shader-nodes
      - procedural
      - bpy
    category: development
---

# Procedural Blender Nodes

Treat a node system as an explanation of an effect: decide what it must produce and on what inputs, build it as
named node groups an artist can read, expose the few controls that matter, and prove it by rendering it, changing
those controls, and running it on other inputs.

## Workflow

1. **Target.** State the effect: what geometry, materials and motion; the input it runs on (a curve, a mesh, a
   point set, nothing); what an artist should be able to change; the shot or use that judges it.
2. **Route.** Pick the technique and a starting template from `references/subject-routing.md`: curve-space layout,
   surface scatter, instanced assemblies, mesh modelling, analytic animation, simulation zone, shader-only.
3. **Assemble from the library.** Find groups with `python3 scripts/nodes_tools.py search <words>` or
   `references/library-index.md`, and instance them (`Graph.group(builder(), ...)`). Do not rebuild what the
   library has; it is tested.
4. **Build through nodekit.** Write a Python build script: `nodekit.graph.Graph` creates each group (inputs with
   descriptions, ranges and panels; frames around each block), a top-level modifier group composes them, and the
   script creates the scene and saves the .blend. The .blend's node graph is the deliverable; the script makes it
   reproducible. See `references/nodekit-guide.md`.
5. **First result fast.** One part, its test input, one render: `python3 scripts/nodes_tools.py try -- --module
   <your.module> --root <dir> --png out/try.png`. Look at the image. Then grow part by part, judging the full
   assembly, not parts alone.
6. **Refine in order:** silhouette and proportions, layout and density, materials, light and look, motion.
   Calibrate against the reference (if any) with measurements over time or across views, not one frame.
7. **Controls.** A Primary panel with a handful of macro controls; detailed panels per part; presets as JSON.
   Sweep each primary control and look at the results (`scripts/sweep.py`).
8. **Validate.** `scripts/validate.py` reopens the saved file: zero node warnings, zero lint, evaluation time,
   camera clearance. Run the effect on other inputs. For animation, render a continuous sequence and check it for
   sliding, popping and flicker. Rebuild twice and diff the graph dumps.

Run the scripts from this skill's directory. They need Python 3 and Blender 5.2+ (`$BLENDER`, `blender` on PATH, or
the macOS app); `nodes_tools.py` starts Blender itself.

## Conventions

- **Python builds native nodes.** Every tree is built with `Graph` (Geometry, Shader or Compositor). Sockets are
  found by name among enabled sockets (`"Value#1"` for duplicates); set node properties via `props=` before
  inputs, because properties change which sockets exist.
- **Groups explain.** Name groups for what they make (`NK Curve Parcels`, `My Effect Roof`), describe every group
  and input, frame every block with a sentence (`"Parcels: split each side into houses"`). Split reusable parts
  into sub-groups. `Graph.finish()` lays out frames left to right and gives each frame its own Group Input.
- **Time.** Animated groups take a `Time` input in seconds. Only the top-level modifier group reads Scene Time
  (with Time Scale and Time Offset controls), so parts stay testable and retimable.
- **Space.** Model in the input's space (curve space: s along, d left, h up; or object space) and place through
  the library's frame groups, so the effect follows any curve or mesh.
- **Variation into materials.** Store `nk_color` (FLOAT_COLOR) and `nk_rand` (FLOAT 0–1) per piece; materials read
  them with an Attribute node (type GEOMETRY) after realize.
- **Shared groups build once** (`@nodegroup` or `nodekit.graph.once`). Rebuilding a group other groups use clears
  its interface and silently unlinks them.
- **Analytic first.** Periodic or driven motion is a function of `Time`. Use a simulation zone only for state:
  accumulation, growth, collisions, anything whose next frame depends on the last.

## Hard rules (these break Blender 5.2 scripts)

- Modifier inputs are not ID properties: use `nodekit.inspect.set_modifier_inputs(mod, {"Name": value})`, never
  `mod["Socket_2"]`.
- Never rebuild a shared node group in place after other groups use it (see Conventions).
- Mode switches on Transform, Resample and Set Curve Normal, and Remove Named Attribute's pattern mode, are input
  sockets, not node properties. Texture outputs are named "Factor".
- Field-default sockets (Extrude Mesh `Offset`) ignore constants; link a node.
- In background mode, drivers update only for the window's scene: set `bpy.context.window.scene` before
  `frame_set`, render with `bpy.ops.render.render(scene=...)`.
- EEVEE world volumes swallow the sun: do distance haze in the compositor on premultiplied geometry.
- Always run Blender as `blender -b --factory-startup --python script.py -- args`; pass negative CLI values as
  `--x=-1`.
- Every input gets a description, every group a description; zero node warnings, zero `check_groups` lint.

The full list with fixes is in `references/blender-api-notes.md`.

## Reference routing

Read only what the task needs:

| File | Read when |
|---|---|
| `references/subject-routing.md` | starting from a subject ("a fence along a path", "ivy over a statue"): technique, groups, template |
| `references/library-index.md` | choosing groups: every NK group with inputs, summary and uses |
| `references/nodekit-guide.md` | writing the build script: Graph API, zones, frames, layout, inspect, the scripts |
| `references/geometry-nodes-patterns.md` | fields and domains, instancing vs realize, attributes into materials, booleans, budgets, per-frame cost |
| `references/animation-and-simulation.md` | motion: analytic vs simulation zone, integrated phase, planted feet, springs, wind, loops, caches |
| `references/controls-and-presets.md` | designing the modifier panel, macro controls, presets, sweeps |
| `references/materials-and-look.md` | Shader Node materials, attribute variation, EEVEE, AgX, light, compositor haze and glow, calibration |
| `references/validation-and-review.md` | before delivering: determinism, reopen-and-validate, reuse, temporal checks, honest reporting |
| `references/blender-api-notes.md` | a Blender 5.x API error or surprise |
| `../../prompts/reference-to-nodes-prompt.md` (repository) | recreating a reference video, image or description as a node system |

Templates in `templates/` are complete, render-verified build scripts (gallery in the repository README); each
builds a .blend whose top modifier group runs on its own test input and on others.

## Output expectations

When building an effect:

- Deliver the build script and the .blend it saves. The .blend holds native node groups, not baked geometry or
  image sequences (state any image texture you use and why).
- The top-level modifier group has a Primary panel, then per-part panels; every group and input is described.
- End with a short guide: the primary controls, what each part group does, how to run it on new input, and how it
  was validated (check/validate output, renders looked at, inputs tried).
- Separate what is implemented from what is approximated or out of scope; do not call an analytic sway a cloth
  simulation, or a texture mask modelled geometry.

When fixing or porting an existing node script:

- Identify how it builds trees and where it breaks on Blender 5.2 (modifier inputs, socket names, modes as inputs).
- Preserve the graph's interface (input names and order) unless asked; call out any change.
- Fix correctness first, then readability (frames, descriptions, layout), then performance.
