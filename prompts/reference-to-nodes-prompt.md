# Prompt: recreate a reference as an editable Blender node system

Use the **procedural-blender-nodes** skill (read its `SKILL.md` first and follow its workflow) to recreate the
reference below as a native, editable Blender node system: Geometry Nodes for form, layout and motion, Shader
Nodes for materials, a compositor graph for atmosphere. Python builds the graph through `nodekit`; the
deliverable is the graph, not the script and not a baked mesh.

Fill these in before sending (leave a line blank to let the agent measure or propose it):

- **Reference:** `<video URL or path | image path(s) | image-sequence folder | written description>`
- **Reference kind:** `<video | image | views | sequence | text>`
- **Output name:** `<name>` (files become `<name>/build.py`, `<name>/<name>.blend`, ...)
- **Input the system should run on:** `<a path curve | any mesh | a point set | none (self-contained)>`
- **Must keep:** `<objects, beats or qualities you care about most, or blank>`
- **Allowed to skip:** `<anything you already know you do not want, or blank>`
- **Render target:** `<EEVEE | Cycles>`, `<resolution, fps, duration>`
- **Blender:** `<5.2.x>` at `<path>`

The reference is the visual specification; the graph is an editable explanation built for it, not a recovered
ground truth. Nothing in this document describes the reference's content: you derive it in section 1 and get the
breakdown approved before building.

## 0. Quality bar (read first; overrides anything below that conflicts)

**Done means every check below passes.** A failing check is listed as failing, never as "good enough".

- **Graph quality**
  - Every group and input has a description; inputs have ranges and subtypes; internals are in named frames;
    sub-groups are reusable parts. Zero `check_groups` lint and zero node warnings on every scene.
  - Two builds from nothing produce identical graph dumps.
  - A Primary panel of 6-10 macro controls comes first; every Primary control changes the result visibly over its
    whole range (proved by sweeps).
- **Reuse**
  - The same node groups run on at least three inputs the reference never showed (other curves, meshes, or
    layouts), five seeds, and every preset, with zero warnings and an acceptable result. Limits are written down.
- **Motion** (when the reference moves)
  - Analytic unless the motion needs state, interaction or accumulation (`animation-and-simulation.md`). The choice
    and its reason are stated.
  - Gait or rolling phase is integrated from distance; contacts (feet, wheels, objects at rest) do not slide.
    Prove it with numeric probes, not stills.
  - Secondary motion is spring-damped (lags, overshoots, settles). Wind is a gust envelope with per-piece response.
  - No popping or flicker: frame-to-frame differences are steady over the whole range.
  - A simulation is baked before it is rendered, and determinism is checked.
- **Detail**
  - Every object is built from its parts (a house: walls, openings, roof, chimney; a tree: trunk, limbs, crown).
    An object reduced to its most obvious part fails.
  - Anything covering more than 10 % of the frame shows silhouette, secondary forms and surface detail.
- **Reference**
  - Sizes, counts and distributions are measured, not guessed, and written in one unit (section 2).
  - Colours and light are matched by measurement per region (mean Oklab L, chroma, luma p10/p50/p90), with the
    numbers reported.
  - Every timeline row or view has a side-by-side with the remaining differences written down.

**Process.** Work in milestones (section 7). After each, render, look at every image, list the five biggest
differences, fix, re-render: at least three rounds. Do not stop or summarise while a check fails, and do not
invent content the reference does not show.

---

## 1. Reference breakdown (do this first, then stop for approval)

Write `docs/REFERENCE.md` (and `docs/reference_params.json` for the numbers) before writing any node code. Keep
measurement scripts in `reference/scripts/` so they can be rerun.

**For every reference kind:**

1. **Facts:** source, hash, resolution and aspect; for video: duration, fps, frame count, cuts, whether it loops.
   Verify it is the original (not an earlier reconstruction or a re-encode).
2. **Object inventory:** every object larger than about 2 % of the frame: its parts, shape language, size relative
   to a chosen ruler, position relative to other objects, and where it is best seen.
3. **Distributions, not instances:** for repeated things (houses, trees, props, stones, flags), measure ranges and
   frequencies (width, height, spacing, chance per piece, colour palette), since a generator reproduces
   distributions.
4. **Light and palette:** key direction and colour, fill and shadow colour, sky, haze; sampled sRGB per main
   surface.
5. **Style:** stylised or realistic, edge softness, saturation, grade, bloom, depth of field.
6. **What cannot be reproduced exactly**, and the substitute proposed for each (section 9 decides).
7. **Inconsistencies of the reference** (AI clips drift, morph, change object counts): name them so the system
   does not copy them.

**Video:** the value is over time.
- Timeline every 0.5 s (finer around fast action): time, beat, what the frame shows.
- Motion log: speeds, gait (stride, cadence), pauses, interactions, secondary motion amplitudes, wind; from tracks
  of points over frames (slit-scans, point tracking, autocorrelation for cadence).
- Camera log: height, distance, field of view (state the assumption if it cannot be measured), how it moves.
- Contact sheets and motion strips in `reference/sheets/`.

**Image or views:** the value is across views and within the image.
- Per view: camera position, height and field of view estimated from vanishing points and known sizes.
- Cross-check sizes between views; measurements that disagree are flagged, not averaged away.
- Crops of every object at the largest available size.

**Image sequence** (turntable, time-lapse, frames from a game): treat as video if ordered in time, as views if
ordered by angle; say which.

**Written description:** the value is the spec.
- Rewrite it as a numbered spec: objects with parts, sizes in one unit, counts, distributions, motion, light,
  camera. Mark every number you had to choose as an assumption, with a range.
- Collect 2-4 reference images (or describe the intended look precisely) and get the spec approved before
  building.

## 2. Contracts (write before building; `AGENTS.md` of the project)

- **Units:** 1 unit = the chosen ruler (the main character's height, a door, a metre). Every measurement uses it.
- **Spaces:** the local frame things are modelled in (curve space (s, d, h) through `NK Curve Frame`, surface
  space, piece-local space), and the rotation convention (+X along, +Y left, +Z up).
- **Shared input names:** `Curve`/`Path`, `Time` (seconds; only the top group reads Scene Time), `Seed`, and the
  shared dimensions.
- **Interfaces between parts:** extra outputs (anchor point clouds with typed attributes) and their attributes.
- **Attributes into materials:** `nk_color`, `nk_rand`, `nk_local`, project terms where 0 = no effect.
- **Naming:** project prefix for groups and materials; library groups stay `NK `.
- **Ownership** if several agents build parts in parallel.

## 3. Comparison tooling (before the first milestone)

- **Video:** `scripts/video.py` (extract, side-by-side video, contact sheet) and `scripts/compare.py` (colour,
  structure and motion metrics per screen region over time, with the reference's self-noise floor).
- **Images/views:** render the same camera as each view; crop the same regions; mean Oklab L, chroma, luma
  percentiles, edge density per region.
- **Probes:** stored probe attributes read from the evaluated geometry over frames (contacts, roots, pendulum
  tips), camera positions per frame (`render.py --report`).
- **Diff:** before/after image difference for changes that should not alter the look.

## 4. Build

- Route the subject (`references/subject-routing.md`) and start from the closest template; assemble from the
  library (`nodes_tools.py search`) and add project groups only for what the library lacks.
- One Python module per part family, each exposing `build()` returning its top group; a top modifier group that
  wires the input object, Time and shared inputs, applies the Primary macros and forwards part inputs to
  `"<Part> > <Panel>"` panels (`controls-and-presets.md`).
- Model in local frames and place; instance shared meshes; store per-piece decisions as attributes on piece points;
  realize once at the end.
- Test each part alone (`try_group.py`) on every test input before integrating, then integrate early and judge only
  the full build.
- Structure changes only in the builders; fitting to the reference changes only parameters (defaults, presets,
  light file, camera).

## 5. Animation

Choose analytic or simulation per motion with the decision rule, and state it. Analytic motion keys a timeline
(speeds, events, holds) to the breakdown and is a closed form of `Time`; simulations step with `Delta Time`, are
baked, and are checked for determinism. Cameras live outside Geometry Nodes: a rig on the same path driven by the
same modifier inputs, so retiming the motion retimes the camera.

## 6. Look

EEVEE (or Cycles if required) with AgX; exposure, sun, sky and look fitted by measurement in that order; distance
haze and glow in the compositor on premultiplied geometry; materials tinted by `nk_color` with small procedural
variation (`materials-and-look.md`).

## 7. Milestones

1. **Breakdown, contracts, tooling** (sections 1-3). Stop for approval.
2. **Blockout:** every part as stand-in geometry on the real input, the camera, timing or views in place. Check
   composition against every timeline row or view.
3. **Parts:** each part built from its parts, tested alone on all test inputs.
4. **Motion:** final motion, proved with probes and sequences.
5. **Look:** materials, light, compositor, matched by measurement.
6. **Reference pass:** walk every row or view and every object again; fix the biggest differences.
7. **Reuse pass:** transfers to new inputs, seeds, presets, control sweeps; fix what breaks or record the limit.
8. **Validation:** the definition of done in `references/validation-and-review.md`.

At every milestone: render, look, critique, fix, at least three rounds.

## 8. Variations and transfer

- **Presets:** 4-6 JSON presets that change the character of the result mostly through Primary controls (the
  reference is the empty preset).
- **Sweeps:** every Primary control, start to end, rendered at a moment where its effect shows.
- **Transfers:** the same node groups on new inputs, as extra scenes in the same .blend.
- These prove the result is a system, not a scene. A control or transfer that does not work is reported.

## 9. Simplifications

Allowed without asking: textures replaced by procedural shading; faces left unmodelled when the reference never
shows them; distant objects as simpler instances; background sky as a gradient.

Everything else needs approval first: dropping parts of objects, fewer object kinds, baking the generator instead
of keeping it live, a simulation replaced by analytic motion (or the reverse) against the decision rule, any change
to timing, composition or camera that departs from the reference.

## 10. Deliverables

- `build.py` that builds the .blend from nothing (deterministic) and writes a graph dump (`<name>.graph.json`).
- `<name>.blend`: the reference scene plus transfer scenes, all sharing the same node groups; small because it
  stores graphs, not geometry (except packed bakes, which are listed).
- `presets/*.json`, `light.json` (or equivalent parameter files).
- `docs/REFERENCE.md`, `docs/GRAPH.md` and `docs/CONTROLS.md` (generated by `graph_doc.py`), node-editor
  screenshots (`graph_shots.py`).
- Renders: the reconstruction, side-by-side with the reference, presets sheet, sweeps, transfers.
- `README.md`: how to build and use it, the Primary controls, how it is built, validation results with numbers,
  limitations.

## 11. Honesty rules

- Report measured numbers with what was measured and how; never invent accuracy figures.
- Separate verified, looked at, and not checked.
- Call the result an interpretation where it is one; name the visible differences from the reference.
- Do not claim novelty without a prior-work check.
- List every limit found: inputs that break it, control ranges that degrade, costs per frame, what is baked, what is
  experimental.
