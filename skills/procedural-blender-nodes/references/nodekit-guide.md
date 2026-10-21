# nodekit Guide

`nodekit` builds native Blender node trees from Python and reads them back. Every library group, template and
project graph goes through it, so graphs are linked, documented, framed and laid out the same way. It runs inside
Blender only: `blender -b --factory-startup --python my_build.py -- <args>`.

## Contents

- [Graph basics](#graph-basics)
- [Sockets](#sockets)
- [Inputs, outputs and panels](#inputs-outputs-and-panels)
- [Nodes and properties](#nodes-and-properties)
- [Math shorthands](#math-shorthands)
- [Groups, once and @nodegroup](#groups-once-and-nodegroup)
- [Zones](#zones)
- [Frames, split inputs and layout](#frames-split-inputs-and-layout)
- [Materials and the compositor](#materials-and-the-compositor)
- [Putting a group on an object](#putting-a-group-on-an-object)
- [Inspect](#inspect)
- [Scripts](#scripts)

## Graph basics

```python
import sys; sys.path.insert(0, "<skill dir>")          # so `nodekit` and `library` import
from nodekit.graph import Graph

g = Graph("NK Picket Row", kind="GEOMETRY", description="Pickets at even spacing along a curve")
curve = g.input("Curve", "GEOMETRY", desc="Path the row follows")
spacing = g.input("Spacing", "FLOAT", 0.15, min=0.02, max=2.0, subtype="DISTANCE",
                  desc="Distance between pickets along the curve")
with g.frame("Points every Spacing along the curve"):
    pts = g.node("GeometryNodeResampleCurve", Curve=curve, Mode="Length", Length=spacing)
    pts = g.node("GeometryNodeCurveToPoints", props={"mode": "EVALUATED"}, Curve=pts["Curve"])
with g.frame("A picket on every point, upright, facing along the curve"):
    picket = g.node("GeometryNodeMeshCube", Size=(0.04, 0.1, 1.0))
    inst = g.node("GeometryNodeInstanceOnPoints", Points=pts["Points"], Instance=picket["Mesh"],
                  Rotation=pts["Rotation"])
g.output("Geometry", "GEOMETRY", inst["Instances"])
tree = g.finish()                                    # split inputs, auto layout, frames; returns the node group
```

- `Graph(name, kind, description, modifier=False)`: kind is `"GEOMETRY"`, `"SHADER"` or `"COMPOSITOR"`. An
  existing group of that name is **cleared and rebuilt** (nodes and interface), so builds are repeatable. Set
  `modifier=True` on the top group that goes on a Nodes modifier.
- `g.finish()` must be called last. Nothing is laid out or framed before it.
- The Graph's node tree is `g.nt` (a `bpy.types.NodeTree`).
- Call `nodekit.scene.reset()` (factory settings) **before** building: it frees every data-block, and a tree built
  earlier raises `ReferenceError: StructRNA ... has been removed` when used.

## Sockets

A value passed to an input can be a constant, a tuple (vector/colour; padded with 1.0), a socket, a `Node` (its
first enabled output), a data-block (`bpy.data.materials["NK Bark"]`), or `None` (leave as is).

Sockets are looked up by name among **enabled** sockets only:

| Key | Meaning | Example |
|---|---|---|
| `"Name"` | first enabled socket with that name (or that identifier) | `n["Mesh"]`, `n.i("Size X")` |
| `"Name#k"` | k-th enabled socket with that name | Math has three inputs named `Value`: `"Value#1"` |
| `k` (int) | k-th enabled socket | `n.i(0)` |

`n["Out"]` is an output, `n.i("In")` an input, `n.out` the first enabled output, `n.set(**inputs)` links later.
Names with spaces go through `**{"Size X": w}`. Zone outputs repeat names: the For Each zone's generated geometry
is `zout["Geometry#1"]` (`zout["Geometry"]` is the main item).

Look up by name, never by identifier: 5.2 changed the identifiers of Compare and Random Value sockets, and
identifiers like `Item_0` or `Socket_3` depend on creation order.

## Inputs, outputs and panels

```python
w = g.input("Width", "FLOAT", 4.0, min=0.5, max=20, subtype="DISTANCE", panel="Street",
            desc="Curb-to-curb width")              # returns the socket on the Group Input node
g.output("Anchors", "GEOMETRY", anchors, desc="Points where props attach")
```

- Types: `FLOAT INT BOOL VECTOR COLOR ROTATION MATRIX STRING MENU GEOMETRY OBJECT COLLECTION MATERIAL SHADER`.
- Float subtypes in 5.2: `NONE PIXEL PERCENTAGE FACTOR MASS ANGLE TIME TIME_ABSOLUTE DISTANCE WAVELENGTH
  COLOR_TEMPERATURE FREQUENCY`. Vector: `XYZ TRANSLATION EULER DIRECTION VELOCITY ACCELERATION` and others. An
  invalid subtype raises.
- `panel="Name"` creates the panel on first use, in call order. Panels appear in the modifier in creation order,
  so declare the Primary panel's inputs first. Closed by default: `g._panels["Detail"].default_closed = True`.
- Every input needs `desc` (lint fails without it), a range, and a subtype where one fits. See
  `controls-and-presets.md`.
- Interface items also have `hide_in_modifier`, `force_non_field`, `structure_type` (`AUTO DYNAMIC FIELD GRID
  LIST SINGLE`) and `default_input` (`INDEX POSITION NORMAL ID_OR_INDEX SCENE_FRAME SELF_OBJECT` …); set them on
  the interface item (`g.nt.interface.items_tree[name]`) after `g.input` when needed.

## Nodes and properties

```python
n = g.node("GeometryNodeDistributePointsOnFaces", props={"distribute_method": "POISSON"},
           Mesh=mesh, **{"Distance Min": 0.2, "Density Max": 50.0})
```

`props` are node properties (`operation`, `data_type`, `domain`, `mode`) and are set **before** inputs are
connected, because they change which sockets are enabled: `Distance Min` only exists in Poisson mode. Many
options that were properties are input sockets in 5.x (Transform's mode, Resample Curve's `Mode`, Set Curve
Normal's mode, Remove Named Attribute's `Pattern Mode`, compositor Glare `Type`/`Quality`, Set Alpha `Type`).
Pass those as inputs with the menu item's name: `Mode="Length"`.

Find a node's `bl_idname` from the Python tooltip in the UI, or list sockets in Blender:

```python
n = g.node("GeometryNodeRaycast"); print([(s.name, s.type) for s in n.b.inputs if s.enabled])
```

## Math shorthands

| Call | Node | Note |
|---|---|---|
| `g.math(op, a, b, c, clamp=False)` | Math | `op` is the enum: `ADD MULTIPLY MULTIPLY_ADD POWER SINE ARCTAN2 FLOOR FRACT PINGPONG SMOOTH_MIN …` |
| `g.vmath(op, a, b, c, scale=s)` | Vector Math | `SCALE` takes `scale=` |
| `g.combine(x, y, z)` / `g.separate(v)` | Combine / Separate XYZ | `g.separate(v)["Z"]` |
| `g.mix(fac, a, b, data_type="RGBA")` | Mix | picks the enabled A/B pair for the data type |
| `g.map_range(v, a0, a1, b0, b1, interp="SMOOTHSTEP")` | Map Range | `LINEAR STEPPED SMOOTHSTEP SMOOTHERSTEP` |
| `g.value(v)` | Value | a named constant node |

Long chains read better through a small local helper (the walker uses `M(g, x, ("MULTIPLY", 2.0), ("ADD", 1.0))`).

## Groups, once and @nodegroup

```python
from library.curve import curve_frame
cf = g.group(curve_frame(), Curve=curve, Length=s, Offset=d)    # a group node; outputs cf["Position"], cf["Rotation"]
```

`g.group(tree_or_graph, label, **inputs)` instances another group (GEOMETRY and SHADER graphs).

Rebuilding a group clears its interface, which **silently unlinks every group node already using it**. So a
group used by several builders must be built once per session:

```python
from nodekit.graph import once

@once
def build_hinge():                      # second call returns the same tree
    g = Graph("SS Hinge", description="...")
    ...
    return g.finish()
```

Library groups use `@nodegroup`, which applies `once` and registers metadata for `search`, `index` and `check`:

```python
from nodekit.library import nodegroup

@nodegroup("NK Catenary", kind="GEOMETRY", tags=["curve", "rope"], use="bunting, power lines, rope bridges")
def catenary():
    """A hanging curve between two points with a given sag."""
    g = Graph("NK Catenary", description=catenary.__doc__.strip().splitlines()[0])
    ...
    return g.finish()
```

The decorator name must equal the Graph name and start with `NK `; a module may only use builders from modules
earlier in `library/__init__.py` `MODULE_ORDER`.

## Zones

```python
zin, zout = g.zone("SIMULATION", [("FLOAT", "Age"), ("VECTOR", "Velocity")])
g.connect(seed_points, zin.i("Geometry"))
age = g.math("ADD", zin["Age"], zin["Delta Time"])
g.connect(zin["Geometry"], zout.i("Geometry"))
g.connect(age, zout.i("Age"))
result, final_age = zout["Geometry"], zout["Age"]
```

| Kind | Inside, read | Inside, write | After the zone | Extra |
|---|---|---|---|---|
| `"SIMULATION"` | `zin[name]`, `zin["Delta Time"]` | `zout.i(name)` | `zout[name]` | `zout.i("Skip")` passes state through |
| `"REPEAT"` | `zin[name]`, `zin["Iteration"]` | `zout.i(name)` | `zout[name]` | `zin.i("Iterations")` sets the count |
| `"FOREACH"` | `zin[name]` (per element), `zin["Index"]` | `zout.i("Geometry")` (generated) | `zout["Geometry#1"]` | `zin.i("Selection")`; items are `main_items` |

`items` are `(socket type, name)` pairs added after the default Geometry item. Wire inputs to the zone input
node (`zin.i(...)`) before the zone, read state from `zin`, write to `zout.i`. A For Each zone over an empty
selection raises an INFO warning; guard it with a Switch on Domain Size > 0 (Switch is lazy). For extra
generated items use `zout.b.generation_items.new(type, name)`; per-element inputs are `zout.b.input_items`.

## Frames, split inputs and layout

```python
with g.frame("Parcels: split each side into houses"):
    ...                                        # every node created here goes in this frame
```

- Name frames as sentences that explain the block. Graphs over 25 nodes without frames fail lint.
- `g.finish()` calls `split_inputs()`: each frame gets its own Group Input node showing only the sockets it uses,
  so a graph with 40 inputs reads frame by frame. Pass `finish(split_inputs=False)` for small graphs.
- Layout is automatic: longest-path columns inside each frame, frames placed as blocks left to right. Do not set
  `location` by hand; the next rebuild would discard it.

## Materials and the compositor

`Graph(kind="SHADER")` builds a shader **node group** (reusable, e.g. `NK Attribute Tint`), not a material. A
material's own tree is built with `nodekit.materials.material(name)` (get-or-create, emptied) and a small helper
over `m.node_tree` (see `prompts/storybook-street/street/materials/road.py`), or contains a `ShaderNodeGroup`
that instances a shader Graph. New materials in 5.x already have a node tree; `Material.use_nodes` is deprecated.

`Graph(kind="COMPOSITOR")` builds a compositor node group; assign it with `scene.compositing_node_group = g.nt`.
The Group Output's first Color input is the result (5.0 removed the Composite node). `Graph.group` does not
instance compositor groups (it creates a shader group node); nest compositor groups by hand if you need to.
`nodekit.scene.post()` is a complete example.

## Putting a group on an object

```python
from nodekit import scene, inspect
ob, mod = scene.holder("Fence", curve_obj, tree)        # empty mesh object + Nodes modifier
inspect.set_modifier_inputs(mod, {"Path": curve_obj.name, "Spacing": 0.2})
bpy.context.scene.frame_set(1)
print(inspect.evaluated_stats(ob), [w.message for w in mod.node_warnings])
```

Modifier inputs are RNA properties in 5.2 (`mod.properties.inputs.<identifier>.value`, `.attribute_name`);
`mod["Socket_2"]` raises. Use `set_modifier_inputs` / `get_modifier_inputs` by display name. Object inputs accept
an object name. Read a curve or mesh object inside the graph through an Object input and an Object Info node
(`transform_space="RELATIVE"`).

`nodekit.scene` also has `reset()`, `path_curve(kind)` (`reference straight s_bend hill spiral`),
`light_world(...)`, `camera(...)`, `render_setup(...)`, `post(...)`, `ground(...)`, `srgb("#hex")`.

## Inspect

| Call | Returns | Use |
|---|---|---|
| `inspect.dump_groups(path, prefix="")` | JSON of every group: interface, nodes, props, unlinked input values, frames, links | determinism diff, `graph_doc.py` |
| `inspect.check_groups(prefix="")` | list of problems | must be empty: missing descriptions, invalid links, unused outputs, unframed big graphs |
| `inspect.modifier_inputs(mod)` | `{name: identifier}` | |
| `inspect.set_modifier_inputs(mod, {...})` / `get_modifier_inputs(mod)` | | presets, sweeps, drivers |
| `inspect.evaluated_stats(obj, scene=None)` | verts, faces, materials of the evaluated **mesh** | proof it evaluates; point clouds and curves not converted to mesh are not counted |
| `mod.node_warnings` | evaluation warnings (`type`, `message`) | must be empty |

`mod.execution_time` reads 0 in background mode; time `scene.frame_set(f)` yourself.

## Scripts

All in `scripts/`. Blender scripts take their arguments after `--`; negative values as `--values=-1,3`.

| Script | Does | Example |
|---|---|---|
| `nodes_tools.py search <words>` | rank library groups | `search curve rope` |
| `nodes_tools.py index [--check]` | regenerate `references/library-index.md` | after changing `library/` |
| `nodes_tools.py check` | static rules, then build/lint/evaluate every library group in Blender | before done |
| `nodes_tools.py test [-k name]` | numeric property tests in `tests/` | |
| `try_group.py` (`nodes_tools.py try --`) | build one module's `build()` group on a test path, print STATS / WARNINGS / LINT, optional PNG and .blend | `--module groups.road --root proj --path spiral --png out/t.png --set "Seed=3"` |
| `render.py` | stills, sequences, presets from a saved .blend | `--scene Main --frames 1,97 --preset festive --set "Wind=4"`; `--report` prints stats and camera per frame |
| `sweep.py` | one control moving between two values at a fixed frame | `--control "Timber Amount" --values 0,1.7 --frames 48 --at 169` |
| `validate.py` | reopen a .blend: warnings, counts, eval time, camera clearance, lint; exits 1 on failure | `-- --step 12 --prefix "NK "` |
| `graph_shots.py` | node-editor screenshots (needs a display, no `-b`) | `--groups "My Effect,NK Curve Frame" --out out/graphs` |
| `graph_doc.py` | `GRAPH.md` and `CONTROLS.md` from a graph dump | `my.graph.json --top "My Effect" --out docs/` |
| `video.py` | extract frames, assemble mp4, side-by-side video, contact sheet | `sheet --ref ref.mp4 --render out/seq --times 0:20:2.5 --out s.png` |
| `compare.py` | colour, structure and motion metrics per region over time | `--ref ref.mp4 --render out/seq --times 0:20:0.5 --out out/cmp` |

`try_group.py` wires `Curve` (path through Object Info) and `Time` (scene seconds) automatically; extra geometry
inputs come from an optional `test_inputs(w, gn, info)` in the module. `render.py` and `sweep.py` act on the first
mesh object with a Nodes modifier in the scene and render at a 1280×704 aspect.
