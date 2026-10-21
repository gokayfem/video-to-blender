# Geometry Nodes Patterns

How to structure a Geometry Nodes graph so it is correct, fast and reusable. Node snippets use nodekit
(`nodekit-guide.md`).

## Contents

- [Fields and geometry](#fields-and-geometry)
- [Domains](#domains)
- [Instancing, realizing and attribute propagation](#instancing-realizing-and-attribute-propagation)
- [Named attributes into materials](#named-attributes-into-materials)
- [Curve-space modelling](#curve-space-modelling)
- [Per-piece decisions: points with attributes](#per-piece-decisions-points-with-attributes)
- [Booleans](#booleans)
- [Budgets and LOD](#budgets-and-lod)
- [Performance: what re-evaluates and why](#performance-what-re-evaluates-and-why)
- [Baking](#baking)

## Fields and geometry

A geometry socket (round, solid) carries data. A field socket (diamond) carries a **function** that is evaluated
later, per element, by the node that consumes it, on that node's geometry and domain.

- `Position`, `Index`, `Normal`, `ID`, Named Attribute: evaluated in the context of the node they flow into. The
  same `Index` field means different things in Set Position on a mesh and in Instance on Points.
- To freeze a field's value on one geometry before the geometry changes (topology, realize, transform), **Capture
  Attribute** it, or **Store Named Attribute** it. Read later with the captured output or Named Attribute.
- To read a value from a different geometry, use **Sample Index** (by id), **Sample Nearest** / **Sample Nearest
  Surface**, **Raycast**, **Geometry Proximity** or **Sample Curve**. Never expect a field to "see" another
  geometry.
- Group inputs are fields by default (`structure_type` AUTO). A value that must be single (a count, a seed for a
  whole layout) is linked from single values only; a field into a single-value socket shows a red link.

## Domains

| Domain | On | Typical attributes |
|---|---|---|
| POINT | mesh vertices, curve control points, point cloud points | position, `nk_rand` after realize |
| EDGE | mesh edges | crease, seams |
| FACE | mesh faces | material index, per-face tint |
| CORNER | face corners | UV maps |
| CURVE | whole splines | per-strand id, radius scale |
| INSTANCE | instances | per-instance id, tint, transform |

Reading an attribute on another domain interpolates (face → point averages). Store per-piece values on the domain
of the piece: INSTANCE before realizing, or POINT on the instancing points (they move to the instance domain
in Instance on Points).

## Instancing, realizing and attribute propagation

Instances are references: 10,000 instances of one picket cost one picket mesh plus 10,000 transforms. Realizing
copies the geometry.

- **Instance as long as possible, realize once at the end** (top group), and only if something needs real
  geometry: per-vertex deformation of the whole, booleans, merge by distance, export, or the material reading
  attributes with an Attribute node of type GEOMETRY.
- Attributes on the instancing points become INSTANCE attributes; after Realize Instances they land on the
  **POINT** domain of the realized mesh (checked in 5.2: an INSTANCE float on 3 cube instances realizes to a
  24-point POINT attribute).
- Realize Instances (4.3+) has `Selection`, `Realize All` and `Depth` inputs: realize only what needs it.
- Without realizing, a shader reads instance attributes with an Attribute node of type **INSTANCER**.
- Store `nk_rand`/`nk_color` on the instancing points, not inside the instanced mesh, so one shared mesh can carry
  many tints.
- Remove Named Attribute on instances also strips the same names from nested instances. Remove on the points
  before instancing.
- Pick variants with Instance on Points' `Pick Instance` over a Geometry to Instance of several meshes and a
  hashed `Instance Index`, or with Index Switch / Menu Switch for whole sub-graphs.

## Named attributes into materials

The library convention (AGENTS.md):

| Name | Type | Meaning |
|---|---|---|
| `nk_color` | FLOAT_COLOR | the piece's base tint |
| `nk_rand` | FLOAT 0..1 | per-piece random, for value jitter, wear, hue shifts |

```python
rnd = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=g.node("GeometryNodeInputIndex"),
             Seed=seed)
pts = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
             Geometry=pts, Name="nk_rand", Value=rnd["Value"])
```

The shader reads `Attribute` (`attribute_type="GEOMETRY"`, `attribute_name="nk_rand"`) → `Factor`. A missing
attribute reads 0, so design terms where 0 means "no effect" (store `nk_wear`, not `nk_clean`). See
`materials-and-look.md`.

## Curve-space modelling

Anything along a path is modelled in curve space (s, d, h): arc length, lateral offset (+ left), height. `NK Curve
Frame` maps (s, d, h) to world Position and a level Rotation (+X along, +Y left, +Z up).

```python
cf = g.group(curve_frame(), Curve=curve, Length=s, Offset=d, Height=h)
geo = g.node("GeometryNodeSetPosition", Geometry=grid, Position=cf["Position"])
```

- Build flat in (s, d, h): a Grid whose X is s and Y is d, then Set Position through the frame. Instances get
  `cf["Position"]` and `cf["Rotation"]`.
- Layout by arc length: Resample Curve (Length) for even spacing, Accumulate Field for random widths laid end to
  end (`s_i = sum of widths before i`), drop pieces whose end exceeds the curve length (Curve Length node).
- Tight bends: the inside of a bend compresses. Fan widths by curvature, or skip pieces where the radius is
  below the piece depth; test on an S-bend and a spiral, not only a straight line.
- Hills: the frame is level (tangent flattened), so posts stay vertical on slopes. Use the true tangent only for
  things that should tilt (rails, roads).

## Per-piece decisions: points with attributes

For anything with many varied pieces (houses, props, agents):

1. One point per piece, with an integer id (`Index` or a stored `nk_id`).
2. Every random decision is a stored attribute computed from the id: width, storeys, roof type, colour, flags
   (`Random Value` with `ID` = id and a different `Seed` offset per decision, so decisions are independent).
3. Parts read those attributes. Either fields over all pieces at once (fast, flat graph), or a **For Each
   Element** zone when each piece needs its own topology (a different window count per house).
4. Publish interface points (`Anchors`) for downstream groups: position, a frame rotation, a type INT, a width.

Fields over all pieces are much faster than For Each. Use For Each only when topology varies per piece.

## Booleans

Mesh Boolean solvers in 5.2: `EXACT`, `FLOAT`, `MANIFOLD`.

- **Manifold** is fast and robust for closed meshes, but does not reliably keep attributes. Recover ids from
  positions afterwards: before cutting, spread pieces apart by `id * SPREAD` along X; after, `id = round(x /
  SPREAD)`, move back, re-sample attributes by id (Sample Index on the piece points). See
  `prompts/storybook-street/street/groups/facades.py` (`SS House Cut`).
- **Exact** keeps attributes better but is slow; **Float** is fast and fragile on coplanar faces.
- Cut each piece only with its own cutters; never boolean a whole city at once.
- Prefer construction over subtraction: a window reveal can be four boxes or an inset face (Extrude Mesh with
  negative offset) instead of a cut.
- For soft unions use SDF grids (Mesh to SDF Grid → SDF Grid Boolean / Fillet → Grid to Mesh). Voxel size sets
  cost and detail; output has no UVs.

## Budgets and LOD

- State a budget before building: vertices per unit of path or per piece, instance counts, evaluation time per
  frame. Measure with `inspect.evaluated_stats` and wall time around `scene.frame_set`.
- Instance shared meshes for repeated detail (window panes, stones, leaves).
- Distance LOD: compute camera distance per piece (Object Info on the camera, or Active Camera node) and switch
  subdivision levels, segment counts or the instanced variant; keep switches per piece (hash-stable) so pieces do
  not flicker between levels as the camera moves. A popping LOD switch is a temporal defect
  (`validation-and-review.md`).
- Cull what the camera never sees (behind it, beyond the haze end) with Delete Geometry on piece points, not on
  the realized mesh.
- Expose the budget as controls (`Detail`, `Density`) so artists can trade quality for speed.

## Performance: what re-evaluates and why

The depsgraph re-evaluates a Nodes modifier when one of its dependencies changes:

| Dependency | Re-evaluates when |
|---|---|
| **Scene Time** node (anywhere in the tree, including nested groups) | **every frame change**, even if the value is multiplied by 0 (verified in 5.2: the dependency is structural) |
| Object Info / Collection Info | that object or collection changes (transform, its own evaluation) |
| a driver or keyframe on a modifier input | every frame the animation system touches it |
| Active Camera, Self Object | camera switch / own transform |
| Simulation zone | every frame (steps or reads the cache) |

So:

- **Only the top group reads Scene Time**; parts take a `Time` input. A graph whose time branch is switched off by
  a boolean still re-evaluates per frame if Scene Time is in the tree; put static and animated parts on separate
  objects when scrubbing speed matters (static layout evaluated once, animated walker per frame).
- Keep expensive static work (layout, booleans) out of the time path, or bake it (below).
- A `Time Scale` input of 0 freezes motion but not evaluation.
- Measured 5.2 example: a 2.25M-vertex static grid costs 0 s per frame change; the same graph with Scene Time
  costs about 0.13 s per frame.

## Baking

| Option | What it stores | Use when | Cost |
|---|---|---|---|
| No bake (live) | nothing | the graph is fast and must stay editable; analytic animation | evaluation every frame |
| **Bake node** (still) | the geometry at that point in the graph | an expensive static part (city layout, booleans) under animated parts | re-bake after edits to upstream nodes |
| Bake node (animation) | that point in the graph per frame | heavy animated geometry for playback or a farm | disk per frame |
| **Simulation zone bake** | sim state per frame | always, before rendering a simulation on a farm or scrubbing | re-bake after any upstream change |
| Apply the modifier | real mesh | final export only | loses all controls |

- Bakes live on `mod.bakes` (one per Bake node or simulation zone): `bake_mode`, `bake_target` (`INHERIT` uses
  `mod.bake_target`, default `PACKED` into the .blend; `DISK` with `mod.bake_directory`), `frame_start`,
  `frame_end`, `use_custom_simulation_frame_range`.
- Bake from Python (verified in 5.2):

```python
with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
    bpy.ops.object.geometry_node_bake_single(session_uid=ob.session_uid, modifier_name=mod.name,
                                             bake_id=mod.bakes[0].bake_id)
```

  `geometry_node_bake_delete_single` (same arguments) frees it; `simulation_nodes_cache_bake` bakes all simulations
  of selected objects.
- A bake is a snapshot: after changing an input upstream of it, delete and re-bake. Say in the report which parts
  are baked and which controls stop working until re-bake.
- Prefer no bake for generators meant to be edited; bake only for speed or for simulation, and document it.
