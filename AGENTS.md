# AGENTS.md

Guidance for coding agents (Claude Code, Codex, Cursor, Copilot, Gemini) working on this repository. To use the
skill rather than develop it, see the README.

## Layout

```text
skills/procedural-blender-nodes/   the skill (this is what gets installed)
  SKILL.md                         entry point: workflow, conventions, hard rules, reference routing
  nodekit/                         Python that builds and inspects native node trees (runs inside Blender)
    graph.py                       Graph: node(), group(), input()/output() with panels, zones, frames, layout
    inspect.py                     dump_groups(), check_groups() lint, modifier inputs by name, evaluated_stats()
    library.py                     @nodegroup registry for library builders
    scene.py, materials.py         scene scaffolding (curves, sun/sky, cameras, render, compositor), materials
  library/                         reusable node-group builders, one module per family (MODULE_ORDER)
  templates/                       complete effects built from the library (rendered in gallery/)
  references/                      guides; library-index.md is generated
  scripts/nodes_tools.py           search | index | check | test | try   (plain Python; starts Blender itself)
  scripts/*.py                     try_group, render, sweep, validate, graph_shots, graph_doc, compare, video
tests/                             numeric property tests, run inside Blender
evals/                             `claude plugin eval` suite: skill vs no skill (paid to run)
gallery/                           rendered PNGs of each template (generated)
prompts/                           worked projects and reusable prompts (reference-to-nodes, storybook-street)
adapters/                          copy-in prompts for tools without skill support
.claude-plugin/                    Claude Code plugin + marketplace manifests
```

## Commands

```bash
python3 skills/procedural-blender-nodes/scripts/nodes_tools.py check      # static rules + build/lint/evaluate all groups
python3 skills/procedural-blender-nodes/scripts/nodes_tools.py test       # property tests in Blender
python3 skills/procedural-blender-nodes/scripts/nodes_tools.py index      # regenerate references/library-index.md
python3 tests/build_gallery.py                                            # build every template, render gallery/*.png
python3 tests/check_evals.py                                              # validate evals/ without running them (free)
```

Blender 5.2+ is required (`$BLENDER`, `blender` on PATH, or the macOS app bundle). Always run Blender as
`blender -b --factory-startup --python <script> -- <args>`.

## Rules for library code (`library/`)

- Every group is built through `nodekit.graph.Graph`, by a builder decorated with
  `@nodegroup("NK <Name>", kind=..., tags=[...], use="concrete subjects")`. The name starts with `NK `; the
  builder's docstring starts with a one-sentence summary. `check` enforces this.
- Every group and every input has a description; inputs have ranges and subtypes; internals are organised with
  `g.frame("What this block does")`; zero node warnings on the standard test inputs; zero `check_groups` lint.
- A module may only build groups from modules listed before it in `library/__init__.py` `MODULE_ORDER`.
- Animated groups take a `Time` input (seconds). Only a top-level modifier group reads Scene Time.
- Per-piece variation reaches materials through named attributes: `nk_color` (FLOAT_COLOR) and `nk_rand`
  (FLOAT 0..1), read in shaders with an Attribute node (type GEOMETRY) after realize.
- Every new group gets a property test in `tests/test_<module>.py` that checks something numeric (positions,
  orthonormal frames, conserved lengths, counts that follow a density, a spring that settles, a bounded wind).
- Original implementations only. Credit techniques in CREDITS.md; never copy third-party node assets or code.
- After changing `library/`, regenerate the index (`nodes_tools.py index`).

## Blender 5.2 API notes

- Modifier inputs are not ID properties: use `nodekit.inspect.set_modifier_inputs(mod, {"Name": v})`
  (`mod.properties.inputs.<identifier>.value`).
- Never keep a modifier input slot (`mod.properties.inputs.<id>`) across `set_modifier_inputs` or any interface
  change: the pointer goes stale and reading it crashes Blender. Fetch it again.
- A shared group rebuilt by a second module clears its interface and silently unlinks every earlier user; shared
  builders are build-once (`@nodegroup` does this; `nodekit.graph.once` for anything else).
- `ShaderNodeMix` has several sockets named A/B; `Graph.mix` and `find_socket` pick the enabled ones.
- Transform's, Set Curve Normal's and Resample's modes are input sockets, not node properties. Remove Named
  Attribute's "Pattern Mode" is a menu socket (`"Wildcard"`). Texture outputs are named "Factor".
- Sockets whose default is a field (Extrude Mesh `Offset`) ignore constant defaults; link a node.
- Remove Named Attribute on instances also strips nested instances' attributes; remove on points first.
- For-each zones: the generated geometry is the output `"Geometry#1"`; an empty selection gives an INFO warning
  (guard with a Switch on Domain Size). Zones: `Graph.zone("SIMULATION" | "REPEAT" | "FOREACH", items)`.
- The Manifold boolean does not reliably keep attributes; recover ids from positions after cutting.
- Extrude Mesh on a bent grid shades with grid artefacts in EEVEE; use a flipped back sheet.
- World volumes swallow the sun in EEVEE; do distance haze in the compositor (mist pass, premultiplied).
- Compositor: Image Coordinates needs an image input; Mix also blends alpha (restore it with Set Alpha).
- Drivers only update for the window's scene in background mode: set `bpy.context.window.scene` before
  `frame_set`, and render with `bpy.ops.render.render(scene=...)`.
- A shader Attribute node returns 0 for a missing attribute: store terms where 0 means "no effect".
- Simulation zones: Delta Time = 1/fps; without a bake, jumping frames advances only one step, so step every
  frame from the start (or bake first); going back to the start frame resets. Any Scene Time node makes the whole
  modifier re-evaluate every frame, even multiplied by 0.
- Looks need the full name (`"AgX - Base Contrast"`); there is no Composite node (group output instead);
  Compare/Random Value socket identifiers changed in 5.2: look sockets up by name.
- argparse: pass negative values as `--values=-1,3`, `--cam=-2,0,1:...`.

## Definition of done

`nodes_tools.py check` and `nodes_tools.py test` pass; `library-index.md` is regenerated; every template builds
with zero warnings and its gallery render was looked at; `tests/check_evals.py` passes.
