# Technique transfer: shader-skills (Video2GLSL) → Blender nodes

Source: `/Users/gokay/shader-skills` (skill library `skills/shader-art-coding/glsl/*`, `references/*`,
`prompts/video-to-shader-prompt.md`, `prompts/village-loop/src/*`, and the Blender port notes in
`prompts/egypt-temple-blender/README.md`). Target: Blender 5.2.2 (5.2 LTS), Geometry Nodes (GN) and Shader Nodes
(SN). Feature versions below were checked against the release notes and the 5.2 manual in October 2026; items
marked (unverified) were not.

Four classes: **(a)** direct node math, **(b)** needs translation, **(c)** Blender replaces it, **(d)** needs a
new approach (no shader equivalent exists).

## (a) Transfers directly as node math

| Shader-skills | Blender | Notes |
|---|---|---|
| `hash11..hash44`, `pcgHash` (integer PCG on cell ids) | GN **Random Value** (ID + Seed), **Hash Value** (4.3+); SN **White Noise Texture** | Same principle: hash an integer id, never a sine. Feed `Index`/`ss_house`, not position, so values survive curve edits. |
| `remap`, `linearstep`, `saturate`, `smoothstep` | **Map Range** (Linear / Stepped / Smooth Step / Smoother Step, clamp), **Clamp** | One node per call. |
| `gain`, `parabola`, `cubicPulse`, `expImpulse`, `almostIdentity` | **Math** chains wrapped as `SS Shape <Name>` sub-groups; **Float Curve** when an artist should draw it | Prefer a Float Curve where the exact formula does not matter. |
| `fbm`, `ridgedFbm`, `billowFbm`, `hybridTerrainHeight` | **Noise Texture** (types fBM, Multifractal, Ridged, Hybrid, Hetero Terrain; Detail = octaves, Roughness = gain, Lacunarity) | Works in GN and SN. 4D noise with W = time for animated wobble. |
| `warpedFbm` | Noise Texture **Distortion**, or Noise → Vector Math → second Noise | Second form matches the library's two-stage warp. |
| `voronoi`, `voronoiBorder`, `smoothVoronoi` | **Voronoi Texture** (F1, F2, Smooth F1, Distance to Edge, Randomness, cell Color as id) | Cell colour output = per-cell id for stone/cobble tints. |
| `filteredStripes`, `filteredChecker`, `filteredGrid`, `triangleWave` | **Wave**, **Checker**, **Brick**, **Gradient** textures, or Math (Fract, Ping-Pong, Snap) | Box filtering is not needed: the renderer supersamples (see c). |
| `cosinePalette`, `srgbToLinear`, `luminance`, `saturation` | Math on Vector; **Color Ramp**; **Hue/Saturation/Value**; colours are linear in Blender | Picked sRGB hex values become linear automatically in colour sockets. |
| `blackbody` | **Blackbody** (SN, and GN since 4.1) | Lantern and sun temperatures. |
| `fresnelSchlick`, `shadePBR`, `wrapDiffuse`, `translucency`, `rimLight` | **Principled BSDF** (IOR, roughness, subsurface, sheen, coat), **Layer Weight** | Rim/wrap tricks only if the look needs them. |
| `rot2`, `cameraMatrix` | **Rotate Vector**, **Rotation** sockets, **Align Rotation to Vector**, Matrix nodes (4.2+) | Street-space frame is `SS Street Point`. |

## (b) Needs translation

| Shader-skills | Blender translation |
|---|---|
| SDF modelling (`sdBox`, `sdRoundBox`, `sdCapsule`, `sdCylinder`, `opExtrude`, `opRevolve`) | Default: mesh primitives (Cube, Cylinder, Cone, UV Sphere, Curve to Mesh with a profile curve = extrude/revolve) plus **Set Position** for shaping and bevel in SN. `opExtrude(sd2d)` → **Curve to Mesh** / **Fill Curve** + **Extrude Mesh**. |
| `opUnion`/`opSubtract`, `smin`/`smax`, `opRound`, `opOnion` | **Mesh Boolean** (Exact/Float/Manifold solvers; Manifold unverified) for hard booleans. For smooth blends: 5.x grids, **Mesh to SDF Grid** / **Points to SDF Grid** → **SDF Grid Boolean**, **SDF Grid Fillet**, **SDF Grid Offset** (round/onion) → **Grid to Mesh**. Or write the SDF formula itself as field math into **Field to Grid** over **Cube Grid Topology** (5.1) and mesh it. Costs: voxel resolution, irregular topology, no UVs; reserve for organic pieces (walker body, rocks, ivy clumps). |
| `domRepeat`, `domRepeatId`, `domRepeatLimited`, `domPolar*`, `domRepeatMirror` | **Instance on Points** over **Resample Curve** / **Mesh Line** / **Points**; id = `Index`; limited = point count; polar = points on a **Curve Circle**; mirror = instance with scale −1 on Y (+ **Flip Faces**) or a second side pass. The SDF neighbour-check problem disappears. |
| `domTwist`, `domBend`, `domFold` | **Set Position** with field math on a subdivided mesh; bend along a path = model straight then deform in street space via `SS Street Point`. |
| `buildingProfile` (stable parcel id → height, widths, roof style), `facadeWindowMask` | Parcel = one point per house along the curve with attributes (`ss_house`, width from Random Value on id, roof type as INT → **Index Switch**/**Menu Switch**); windows = **Grid** or points inside each facade quad; **For Each Element** zone when every house builds its own sub-geometry. |
| `opEngrave`, relief/cavity masks, edge wear (`formula-code-couples-materials`) | SN **Bump**/**Displacement** on procedural masks; cavity from **Ambient Occlusion** node or **Geometry › Pointiness** (Cycles); edge wear from **Bevel** normal difference. The egypt port baked GLSL to height maps; we avoid bakes unless justified. |
| Analytic animation on `iTime` (gait phase ∫speed, ballistic arcs, `springSine` closed-form springs in `village-loop/src/40-character.glsl`) | Same formulas as field math on the group's `Time` input (never Scene Time inside a group). Closed-form springs translate one-to-one. Use a **Simulation zone** only when state is genuinely needed (wind-driven bunting that should settle, accumulated paths); it must be baked for render farms and scrubbing. |
| Camera follow (critically damped, closed form) | GN cannot move the camera object. Use the same closed form in a driver or a Python-keyed camera from `street/scene.py`, or a constraint stack (Follow Path + Damped Track). |
| Per-pixel material ids (`MAT_WINDOW = 33.0`) | Separate `SS <Material>` materials via **Set Material** / **Set Material Index**, plus `ss_color`, `ss_rand` attributes read by an Attribute node (GEOMETRY). |
| Oklab / OkLCh mixing (`mixOklab`, `oklchToLinearSrgb`) | No native node. A small `SS Mix Oklab` group (two 3×3 matrix multiplies + cube roots in Vector Math), or accept Mix Color in linear RGB where the difference is invisible. |
| `const` precomputed tables (heights, rotations) | Named attributes stored once (**Store Named Attribute**, **Capture Attribute**), or 5.2 **Lists** (Field to List, Get List Item). |

## (c) Replaced by Blender

| Shader-skills | Blender |
|---|---|
| `raymarch`, `calcNormal`, `iBox`/`iSphere` culling, bounding volumes, LOD by distance | Rasterised/path-traced meshes in EEVEE or Cycles. Culling is the renderer's job; our budget is instance and polygon count. |
| `softShadow`, `calcAO`, `sdfThickness` | Sun lamp angle (soft shadows), EEVEE ray-traced/horizon-scan AO and GI, Cycles path tracing; SN AO node only as a material mask. |
| `simpleSky`, `atmosphereSky`, `sunDisk`, `distanceFog`, `heightFog`, `phaseHG` | World **Sky Texture**, world/scene volume (**Principled Volume**, **Volume Scatter** anisotropy = HG g), mist pass. |
| `tonemapAgX`, exposure, `linearToSrgb` | Colour Management: **AgX** view transform + look + exposure. Do it once, as the skill already insists. |
| AA (`aaOffset`, `fillAA`, filtered patterns), `ditherTPDF`, `vignette`, `filmGrain`, `thinLensRay` | Render samples + pixel filter; compositor nodes (Lens Distortion, Glare, vignette by mask); camera DOF. Motion blur is free here (it was a stated simplification in the GLSL prompt). |
| `DEBUG_MODE` 1–6 | **Viewer** node (5.0 shows non-geometry values inline), spreadsheet, render passes (normal, AO, cryptomatte for ids), `v2n.inspect`. |

## (d) Needs a new approach

- **Curve-following layout.** The shader street was a straight periodic corridor (`PERIOD`, wrapped position). Here
  everything lives in (s, d, h) street space on an arbitrary curve: arc length from **Sample Curve** (Length mode),
  frame from `SS Street Point`, and gaps where curvature is high so facades do not interpenetrate on the inside of
  tight bends (spiral test path). No GLSL precedent.
- **Topology.** Meshes need sensible quads for bevels, subdivision, displacement and booleans; SDFs never did.
  Prefer construction from primitives and Curve to Mesh over grid remeshing.
- **UVs.** Procedural SN textures can use Object/Generated coordinates, but brick and timber patterns that must
  follow a wall need UVs or a stored `ss_uv` attribute (Store Named Attribute on face corners, wall-local).
- **Instancing budgets.** Count instances per 100 H of street; realize once at the end (contract). Detail like
  window panes as instances of shared meshes, not per-house unique geometry.
- **Artist controls.** The GLSL "named constants at the top" become modifier panels with ranges and subtypes;
  only the few controls that change the look (AGENTS.md). Menu Switch for styles, gizmos for spatial ones.
- **Reuse on new inputs.** Must work on five test paths, any length, any seed; the shader only ever had to match
  one shot. Loop seams are no longer exact by construction unless the path closes.

## Workflow transfer from `video-to-shader-prompt.md`

| Step | Status |
|---|---|
| §0 quality bar: motion continuity, no foot sliding, integrated gait phase, spring secondary motion, three detail levels, parts-based objects, measured colour | **Unchanged.** Same checks, proven with frame strips from Blender renders. |
| §1 reference breakdown (clip facts, timeline, object inventory, subject sheet, motion log, camera log, palette, style, what cannot be reproduced) | **Unchanged**, and largely reusable: `prompts/village-loop/REFERENCE.md` already measures this clip in H units. |
| §2 priorities (motion > composition > detail > light > particles) | **Unchanged**, plus a new top priority: the graph stays readable and reusable. |
| §3 comparison tooling | **Mostly unchanged** (side-by-side, crop RGB stats, diff). Probes change: read evaluated attributes and object transforms through `v2n.inspect` instead of shader debug signals. |
| §4 scene construction (SDF raymarch, `map()` contract, bounds, static const data) | **Changes completely**: node groups per family, street space, instancing, attributes (sections b and d). |
| §5 analytic animation, key timeline | **Same maths**, different host: field math on `Time`; simulation zone only where state is needed. |
| §6 camera, light, atmosphere | Camera maths same, lives outside GN; light and atmosphere become renderer settings (c). |
| §7 milestones with ≥3 critique passes | **Unchanged.** Add a milestone "runs on all five paths with zero warnings". |
| §8 controls and deliverables | Constants → panels; bundle/check → `check_groups` + zero `node_warnings`; README tuning guide stays. |
| §9 simplifications | DOF and motion blur no longer need skipping; new simplifications (e.g. grid-meshed organics) still need approval. |

## Blender 5.x Geometry Nodes features we should use

| Feature (version) | How we would use it |
|---|---|
| **Simulation zone** (3.6+) | Bunting/lantern sway that lags and settles under wind; only where analytic springs are not enough. |
| **Repeat zone** (4.0) | Iterative relaxation (spacing houses on bends), recursive subdivision of facades into bays. |
| **For Each Element zone** (4.3) | One iteration per house: build its facade, windows, roof from its own attributes; also per anchor in Props. |
| **Panels** in group interfaces (4.x) | "Houses", "Timber", "Windows", "Palette", "Wind" panels on every top group. |
| **Menu Switch** (4.1) | Artist-facing enums: roof style, shopfront type, palette preset. |
| **Index Switch** (4.1) | Pick a variant by hashed integer id (`buildingProfile` roof id). |
| **Gizmos** (Linear, Dial, Transform; 4.3) | Drag street width, bunting sag and walk start directly in the viewport. |
| **Bake node** / simulation bake | Freeze expensive or simulated parts for playback and farm rendering. |
| **Hash Value** (4.3) | Stable per-id variation, mirroring the library's integer hashes. |
| **Bundles** (5.0; Get/Store Bundle Item 5.1; Geometry Bundles 5.2) | Pass a street "style" (palette, proportions) as one socket between groups instead of 20 wires. |
| **Closures** (5.0; recursion 5.2) | Pass a "how to build a window" function into the facade group so artists can swap motifs. |
| **Lists** (5.2: Field to List, Get List Item, Filter/Sort List) | Measured tables from REFERENCE.md (bunting spacing, house widths) as data rather than wired constants. |
| **Volume/SDF grid nodes** (5.0, more in 5.1): Mesh/Points to SDF Grid, SDF Grid Boolean/Fillet/Offset, Field to Grid, Cube Grid Topology, Grid to Mesh | Smooth-union organic parts translated from SDF recipes; not for houses. |
| **Viewer** improvements (5.0) | Debug views replacing `DEBUG_MODE`. |
| **Bone Info** (5.1) | Read an armature if the walker ever moves from analytic GN to a rig. |
| **Collection Children** (5.2) | Let artists drop custom prop meshes into a collection the Props group instances. |

Sources: release notes for
[4.0](https://developer.blender.org/docs/release_notes/4.0/geometry_nodes/),
[4.1](https://developer.blender.org/docs/release_notes/4.1/nodes_physics/),
[4.3](https://developer.blender.org/docs/release_notes/4.3/geometry_nodes/),
[5.0](https://developer.blender.org/docs/release_notes/5.0/geometry_nodes/),
[5.1](https://developer.blender.org/docs/release_notes/5.1/geometry_nodes/),
[5.2](https://developer.blender.org/docs/release_notes/5.2/geometry_nodes/), and the
[5.2 manual, Volume nodes](https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/volume/index.html)
(none marked experimental). Panels (4.0) and the Bake node's first version, and the Manifold boolean solver, were
not re-verified.
