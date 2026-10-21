# Validation and Review

An effect is done when it is proven, not when one render looks right. This file is the definition of done for a
node effect (a template, a project, a library group), the checks that prove each item, and the critique loop.

## Contents

- [Definition of done](#definition-of-done)
- [Static checks](#static-checks)
- [Rebuild determinism](#rebuild-determinism)
- [Reopen and validate](#reopen-and-validate)
- [Reuse on other inputs](#reuse-on-other-inputs)
- [Temporal checks](#temporal-checks)
- [Render and look: the critique loop](#render-and-look-the-critique-loop)
- [Honest reporting](#honest-reporting)

## Definition of done

| # | Check | How | Pass |
|---|---|---|---|
| 1 | Library rules | `nodes_tools.py check`, `nodes_tools.py test` | both exit 0 |
| 2 | Graph lint | `inspect.check_groups(prefix)` | empty list |
| 3 | Node warnings | `mod.node_warnings` on every Nodes modifier, every scene | empty (INFO included) |
| 4 | Deterministic rebuild | two builds from nothing, `dump_groups` JSON diff | identical |
| 5 | Reopen-and-validate | `scripts/validate.py` on the saved .blend | exit 0 |
| 6 | Camera clearance | `validate.py` (`--min-clear`) every `--step` frames | never inside geometry, clearance above the bound |
| 7 | Reuse | the same groups on ≥ 3 other inputs (curves, meshes), seeds and every preset | 1–3 pass on each |
| 8 | Controls | sweep of every Primary control | visible, continuous change, no warnings at the ends |
| 9 | Temporal | frame differences over the whole range; motion probes | no spikes; planted contacts; loops close |
| 10 | Look | rendered frames looked at and critiqued; measured against the reference if there is one | differences listed with numbers |
| 11 | Docs | `GRAPH.md`/`CONTROLS.md` regenerated (`graph_doc.py`); README states limits | regenerated from the final build |

Run checks on the **saved file**, as a user meets it, not only in the build session.

## Static checks

- `check_groups` flags: groups without descriptions, inputs without descriptions, invalid links (type mismatch,
  field into single value), nodes whose outputs go nowhere, graphs with more than 25 nodes and no frames.
- Node warnings appear only after evaluation: set inputs, `scene.frame_set(f)`, then read `mod.node_warnings`.
  Evaluate at several frames for animated graphs.
- `try_group.py` prints `STATS`, `WARNINGS` and `LINT` for one group on a test path; its LINT line only covers
  groups starting with `SS `, so lint your own prefix with `check_groups` as well.

## Rebuild determinism

```bash
blender -b --factory-startup --python build.py -- --out out/a.blend     # writes out/a.graph.json
blender -b --factory-startup --python build.py -- --out out/b.blend
diff out/a.graph.json out/b.graph.json && echo identical
```

`inspect.dump_groups` records every group's interface, node types and properties, unlinked input values, frame
labels and links. A diff means the build depends on something outside the code (order of a set or dict, data left
from a previous build, a timestamp, a random value without a seed). Also diff after `nodes_tools.py index` to
confirm the generated index is current (`index --check`).

## Reopen and validate

```bash
blender -b my_effect.blend --python scripts/validate.py -- --step 12 --prefix "NK " --hide "Show Walker"
```

For every scene with a Nodes object it records warnings, vertex/face counts and evaluation time at the first
frame; builds a BVH of the evaluated geometry and checks every camera every `--step` frames for clearance (nearest
surface distance) and for being inside a closed mesh (odd ray hits upward); lints groups by `--prefix`. It writes
`report.json` and exits 1 on any failure. `--hide` switches off animated bool-controlled parts for the BVH (so a
character in front of a follow camera does not count as an obstacle). Clearance is evidence on the curves and
cameras in the file, not a proof for every input; say so.

## Reuse on other inputs

The point of a procedural system is that it works on inputs it was not tuned on.

- Curves: straight, S-bend, hill, spiral, a very short one, a closed loop if supported (`nodekit.scene.path_curve`
  provides the first four plus the reference). Meshes: an icosphere, a cube, a character-like mesh, a mesh with
  holes, a non-manifold sheet.
- Seeds: at least 5 seeds per input; look at all of them in one contact sheet.
- Presets: every preset on the reference input.
- Ends of ranges: each Primary control at min and max.
- Pass = zero warnings, zero lint, no self-intersections you would not accept, camera clear, render looks
  intended. Record limits honestly ("bends tighter than half the street width overlap").
- Keep transfer inputs as extra scenes in the deliverable .blend sharing the same node groups, so anyone can check.

## Temporal checks

Stills hide motion bugs. Judge animation as sequences and numbers.

- **Popping and flicker**: render a contiguous range (or every frame at low resolution) and compute the mean
  absolute luma difference between consecutive frames. A steady curve is good; isolated spikes are pops (pieces
  appearing, LOD switches, reshuffled random choices, a seed depending on a moving value). In storybook-street the
  steady median was 9.4 and max 10.6 (0–255) over 480 steps; the reference ranged 8.9–12.5.

```python
# numpy on two frames already loaded as float arrays a, b (H×W×3, 0..1)
luma = lambda x: x @ [0.2126, 0.7152, 0.0722]
mad = abs(luma(b) - luma(a)).mean() * 255
```

  `scripts/video.py` and `scripts/compare.py` (`mad`, `flutter` metrics) do this per region over time.
- **Sliding contacts**: probe planted feet, wheels on ground, objects resting on surfaces; per-frame world motion
  during contact below 1e-4 units (`animation-and-simulation.md`).
- **Jumps and kinks**: first and second differences of probe signals; only physical events may spike.
- **Loops**: first and loop-end frames identical.
- **Random stability over time**: a hashed decision must depend on ids and seeds, never on Time or on positions
  that move; otherwise pieces reshuffle every frame.
- **Simulation**: bake, then compare stepped-from-start and baked states at a few frames.

## Render and look: the critique loop

Every round:

1. Render the same 3–6 key frames (or views) at preview quality (640 px, 8 samples). For a reference, place them
   side by side with the reference at the same times or views (`video.py sheet`).
2. **Look at every image** (open the PNG). A render that was not looked at does not count.
3. Write the five biggest differences, in this priority order: composition and camera; silhouettes, proportions
   and density; motion; materials and colour; light and atmosphere; small detail.
4. Fix them (parameters first; structure only when the parameters cannot express it), rebuild, re-render, repeat.
5. At least three rounds before calling the look done; after the last round, the remaining differences go in the
   report.

Questions to ask of every render: does each object read as itself from its parts (a house has walls, openings,
roof, chimney; a tree has trunk, limbs, crown)? Are there three levels of detail (silhouette, secondary forms,
surface)? Does anything float, intersect, or z-fight? Is anything an obvious repeat? Do the shadows lie on the
ground they should?

## Honest reporting

- Report measurements as measurements: what was measured, on which inputs, with which tool. Never invent accuracy
  numbers or describe an unmeasured property as verified.
- Separate **verified** (checked by a tool, numbers given), **looked at** (inspected renders), and **not checked**.
- List the limits found: inputs that break it, control ranges that degrade, visible differences from the
  reference, what is baked, what is experimental, render cost per frame.
- Call the result an interpretation when it is one: a generator rebuilt from a reference matches its
  distributions, motion and look, not its exact objects.
