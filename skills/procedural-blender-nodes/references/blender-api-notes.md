# Blender 5.2 API Notes

Gotchas met while building node systems from Python in Blender 5.2 (5.2.2 LTS). Items marked **verified** were
checked in 5.2.2 with `blender -b --factory-startup`; the others come from building the library and
storybook-street. Check `bpy.app.version_string` first: these notes assume 5.2+.

## Running Blender

- Always `blender -b --factory-startup --python <script> -- <args>`. Arguments after `--` are the script's;
  pass negative values as `--values=-1,3`, `--cam=-2,0,1:...` (argparse reads `-1` as a flag).
- `nodekit.scene.reset()` (`read_factory_settings(use_empty=True)`) frees every data-block. Build node groups
  **after** it; a tree built before raises `ReferenceError: StructRNA of type GeometryNodeTree has been removed`
  (verified). The `once` cache detects freed trees and rebuilds.
- Drivers update only for the window's scene in background mode: set `bpy.context.window.scene = sc` before
  `frame_set`, and render with `bpy.ops.render.render(scene=sc.name)`.
- `mod.execution_time` reads 0 in background mode (verified); time `scene.frame_set()` yourself.
- zsh: a loop variable named `path` overwrites `$PATH`.

## Modifiers and group interfaces

- Modifier inputs are RNA properties, not ID properties (5.2 release notes; verified): use
  `mod.properties.inputs.<identifier>.value` and `.attribute_name`, or `nodekit.inspect.set_modifier_inputs(mod,
  {"Name": v})`. `mod["Socket_2"]` raises `TypeError: this type doesn't support IDProperties`.
- `mod.node_warnings` lists evaluation warnings (`type`, `message`) after the object is evaluated at a frame.
- Group-level modifier flag: `node_group.is_modifier = True`.
- Empty objects can carry Geometry Nodes modifiers in 5.2 (verified); `nodekit.scene.holder` still uses an empty
  mesh object, which works in every version.
- Interface sockets: `subtype` is validated per type; float subtypes are `NONE PIXEL PERCENTAGE FACTOR MASS ANGLE
  TIME TIME_ABSOLUTE DISTANCE WAVELENGTH COLOR_TEMPERATURE FREQUENCY` (verified). Other item properties:
  `hide_in_modifier`, `force_non_field`, `structure_type` (`AUTO DYNAMIC FIELD GRID LIST SINGLE`), `default_input`
  (`VALUE INDEX ID_OR_INDEX NORMAL POSITION INSTANCE_TRANSFORM HANDLE_LEFT HANDLE_RIGHT SCENE_FRAME
  UNIFORM_IMAGE_COORDINATES SELF_OBJECT`), `attribute_domain` (verified). Panels have `default_closed`.
- A shared group rebuilt by a second module clears its interface and silently unlinks every earlier user; shared
  builders are build-once (`@nodegroup` does this; `nodekit.graph.once` for anything else).

## Nodes and sockets

- Look sockets up by **name among enabled sockets** (`find_socket`). Identifiers are unstable: 5.2 changed the
  socket identifiers of Compare and Random Value (release notes), and zone items are `Item_0`, `Generation_0`, ….
- `ShaderNodeMix` has several sockets named A/B (one pair per data type); `Graph.mix` and `find_socket` pick the
  enabled ones. Set `data_type` through `props` before linking.
- Many former node properties are menu **input sockets** in 5.x: Transform's mode, Set Curve Normal's mode,
  Resample Curve's `Mode` (`"Count"`, `"Length"`), Remove Named Attribute's `Pattern Mode` (`"Wildcard"`),
  compositor Glare `Type`/`Quality`, Set Alpha `Type` (`"Replace Alpha"`), Alpha Over `Type` (verified for the
  compositor ones). Set them like values: `Mode="Length"`.
- Texture outputs are displayed as `Factor` (identifier `Fac`) in 5.x, in both Geometry and Shader Nodes
  (verified for Noise and Wave); `find_socket` accepts either. Voronoi outputs `Distance`, `Color`, `Position`.
- Sockets whose default is an implicit field (Extrude Mesh `Offset` = normal, Set Position `Position`) ignore
  constant defaults in some nodes; link a node (Combine XYZ, Value) instead of setting `default_value`.
- Mesh Boolean solvers: `EXACT`, `FLOAT`, `MANIFOLD` (verified). Manifold does not reliably keep attributes;
  recover ids from positions after cutting (`geometry-nodes-patterns.md`).
- Realize Instances inputs: `Geometry`, `Selection`, `Realize All`, `Depth` (verified).
- Instance-domain attributes land on the **POINT** domain after Realize Instances (verified).
- Remove Named Attribute on instances also strips nested instances' attributes; remove on points first.
- Extrude Mesh on a bent grid shades with grid artefacts in EEVEE; use a flipped back sheet instead.

## Zones

- Simulation zone: input node output `Delta Time` (1/fps; verified 0.041667 at 24 fps); output node input `Skip`;
  state in `state_items`. Repeat zone: `Iterations` input, `Iteration` output, `repeat_items`. For Each Element:
  input node `Geometry`, `Selection`, output `Index`; items in `main_items` (per element), `input_items`,
  `generation_items`; the generated geometry is the output's second `Geometry` (`"Geometry#1"`) (verified).
- For Each over an empty selection gives an INFO warning; guard with a Switch on Domain Size > 0.
- Simulation without a cache: **jumping frames advances one step** (frame 3 → 10 added one Delta Time, verified);
  returning to the start frame resets. Step every frame in order from the start, or bake.
- Scene simulation range: `scene.use_custom_simulation_range`, `simulation_frame_start`, `simulation_frame_end`;
  before the start the initial state is shown (verified).
- Bakes: `mod.bakes[i]` with `bake_id`, `bake_mode`, `bake_target` (`INHERIT` → `mod.bake_target`, default
  `PACKED`), `frame_start/end`, `use_custom_simulation_frame_range`, `directory`. Operators
  `object.geometry_node_bake_single` / `geometry_node_bake_delete_single` / `geometry_node_bake_pack_single` /
  `geometry_node_bake_unpack_single` take `session_uid`, `modifier_name`, `bake_id`; run them under
  `temp_override(object=ob, active_object=ob, selected_objects=[ob])` (verified). `object.simulation_nodes_cache_bake`
  bakes all simulations of the selection.

## Evaluation and dependencies

- Any Scene Time node in a modifier's tree makes it re-evaluate on **every** frame change, even when its value is
  multiplied by 0 (verified: 0.13 s per frame vs 0 s for the same static graph). Only the top group should read it.
- `obj.evaluated_get(dg).to_mesh()` (and `inspect.evaluated_stats`) sees only the mesh component: point clouds
  (Points node, Distribute Points output not converted) and unconverted curves are not counted (verified).
- Read evaluated attributes with `ev.data.attributes[name].data[i].value` after `scene.frame_set(f)`.

## Materials and rendering

- New materials and worlds already have node trees; `Material.use_nodes` is deprecated and scheduled for removal
  in 6.0 (verified: DeprecationWarning). `nodekit.materials.material()` still sets it; harmless for now.
- A shader Attribute node returns 0 for a missing attribute: store terms where 0 means "no effect". Types:
  `GEOMETRY OBJECT INSTANCER VIEW_LAYER` (verified).
- EEVEE's engine id is `BLENDER_EEVEE` (renamed from `BLENDER_EEVEE_NEXT` in 5.0). `CYCLES` is available with
  factory settings (verified).
- View transforms include `AgX`, `Standard`, `Filmic`, `Khronos PBR Neutral`, `ACES 2.0`; AgX looks are prefixed:
  `"AgX - Base Contrast"`, `"AgX - Punchy"`, … (verified; `"Base Contrast"` raises).
- Sky Texture types: `SINGLE_SCATTERING MULTIPLE_SCATTERING PREETHAM HOSEK_WILKIE` (verified).
- World volumes swallow the sun in EEVEE; do distance haze in the compositor (mist pass, premultiplied).

## Compositor (5.x)

- The compositor tree is a node group: `scene.compositing_node_group = tree` (`CompositorNodeTree`). There is no
  `CompositorNodeComposite` (verified); the Group Output's first Color input is the result. `Viewer` still exists.
- Alpha Over inputs: `Background`, `Foreground`, `Factor`, `Type`, `Straight Alpha` (verified).
- Image Coordinates (`Uniform`, `Normalized`, `Pixel`) needs an image input to know the size.
- Mix also blends alpha; restore the render's alpha with Set Alpha (`Type` = `"Replace Alpha"`).
- Render Layers outputs `Image`, `Alpha` plus enabled passes (`Mist` after `view_layer.use_pass_mist = True`).
- `nodekit.graph.Graph.group` creates a `ShaderNodeGroup` for any non-geometry kind, so it cannot nest compositor
  groups.

## 5.2 features worth knowing

From the 5.2 release notes (not all used by the library yet): Lists (Field to List, Get List Item, Filter/Sort
List), Geometry Bundles (Set/Get Geometry Bundle), recursive Closures, Collection Children, Mesh Bevel node,
Capture Attribute with selection, Rename Attribute / Get Attribute Names / Transfer Attributes, String fields,
Scene Frame as a group-input default, Object inputs defaulting to the self object, and the experimental physics
system (Cloth Dynamics, Hair Dynamics, XPBD Solver, colliders and effectors). Mark anything built on the physics
system as experimental.

## Adding to this list

When a Blender API fact surprises you, verify it with a minimal `blender -b --factory-startup --python-expr ...`
probe, then add it here with "(verified)" and the version.
