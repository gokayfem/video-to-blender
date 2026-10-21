# Subject Routing

Start here when the request names a subject ("a fence along a path", "ivy on a statue", "falling leaves"). Each
row gives the technique, the library modules that do the heavy lifting, and the template to start from. Find exact
group names with `python3 scripts/nodes_tools.py search <words>` or `references/library-index.md`; the index is
generated from the library, this table is not, so trust the index for names and inputs.

## Contents

- [Choosing a technique](#choosing-a-technique)
- [Layouts along paths](#layouts-along-paths)
- [Things on surfaces](#things-on-surfaces)
- [Built things](#built-things)
- [Plants and growth](#plants-and-growth)
- [Motion, cloth and particles](#motion-cloth-and-particles)
- [Characters and crowds](#characters-and-crowds)
- [Landscapes, water and atmosphere](#landscapes-water-and-atmosphere)
- [Templates](#templates)

## Choosing a technique

Ask these questions in order. The first "yes" picks the technique; most subjects combine two or three.

| Question | Technique | Main nodes |
|---|---|---|
| Does it follow a line (road, fence, rail, river bank, cable, shelf row)? | **curve-space layout**: model in (s, d, h), place through `NK Curve Frame` | Sample Curve (Length), Resample Curve, Curve to Mesh |
| Is it many copies of a few things over an area or surface? | **scatter + instancing** | Distribute Points on Faces (Poisson), Instance on Points, Random Value on ID |
| Is it one parametric object (house, barrel, lamp, chair)? | **mesh modelling** from primitives, profiles and extrusion | Cube/Cylinder/Grid, Curve to Mesh with a profile, Extrude Mesh, Mesh Bevel (5.2), Set Position |
| Does each piece build its own sub-geometry from its own attributes? | **For Each Element zone** | `Graph.zone("FOREACH", ...)` |
| Is it an iterative construction (subdivide bays, relax spacing, L-system steps)? | **repeat zone** | `Graph.zone("REPEAT", ...)` |
| Does it move? Periodic, driven by time, or a function of a path? | **analytic animation** on a `Time` input | Math on Time, `motion` module (springs, gait, wind) |
| Does it keep state between frames (grows, accumulates, settles, collides, piles up)? | **simulation zone** | `Graph.zone("SIMULATION", ...)`, Delta Time; see `animation-and-simulation.md` |
| Is it cloth or hair that must collide and tear? | 5.2 **Cloth/Hair Dynamics** assets on the XPBD Solver (experimental) | Not wrapped by nodekit; add the asset modifier and say it is experimental |
| Is it soft, organic, blobby (smooth unions, rocks, ivy clumps)? | **SDF grids** (5.x volume nodes), meshed | Mesh to SDF Grid, SDF Grid Boolean/Fillet/Offset, Grid to Mesh |
| Is it fog, smoke, clouds, god rays? | **volume** object or world volume; distance haze in the compositor | Principled Volume, Mist pass; see `materials-and-look.md` |
| Is it only a surface pattern (bricks, wood, stripes, wear)? | **shader-only** | Shader Nodes on Object/Generated coords or a stored `nk_*` attribute |

Rules of thumb:

- Geometry that the camera sees in silhouette is modelled; flat detail (grain, stucco, mortar) is shading.
- Model in a local frame (curve space, house space, anchor space), then place. The same graph then works on new
  inputs: any curve, any mesh, any seed.
- Hash integer ids (`Index`, a stored `nk_*` id) for variation, never positions: ids survive edits to the input.

## Layouts along paths

| Subject | Build with | Template |
|---|---|---|
| fence, railing, balustrade | posts at Resample Curve (Length) points, rails as Curve to Mesh along the same curve with a profile; or both in (s, d, h) through `NK Curve Frame` | `curve-fence` |
| street, road, path, track | cross-section in (s, d, h): grid in (s, d) bent through the curve frame; stones as instances | `storybook-street` project |
| row of houses along a street | parcels: random widths accumulated along s (Accumulate Field), one point per house with attributes, then a For Each zone or field-driven parts | `parametric-house` + `storybook-street` (`SS Facades`) |
| river with banks | channel profile in (s, d, h) along the river curve, banks as a deformed grid, water a flat strip with a flow shader | `curve-fence` for the curve-space part |
| cable, rope, power line, bunting string | catenary between two anchor points (sag ∝ span²), Curve to Mesh with a circle profile | `wind-bunting` |
| rope bridge | two catenaries for rails, planks instanced at s along a lower catenary, ropes as Curve to Mesh, analytic sway | `wind-bunting` + `curve-fence` |
| train track, roller coaster | sleepers instanced at even s, rails as profiles; bank angle by rotating the frame about the tangent | `curve-fence` |
| shelf of books, row of bottles | points along a line with widths accumulated, per-item random height and tint | `curve-fence` |

## Things on surfaces

| Subject | Build with | Template |
|---|---|---|
| grass, pebbles, flowers, debris on terrain | Distribute Points on Faces (Poisson, density from a mask attribute), Instance on Points, align to Normal | `surface-scatter` |
| moss, snow, dust on top surfaces | mask = normal·up and noise; scatter with density from the mask, or shade only | `surface-scatter` |
| rivets, studs, tiles on a mesh | points on faces/edges by rule (Mesh to Points, Sample Index), instance | `surface-scatter` |
| stickers, posters, decals on walls | anchor points published by the wall generator (`Anchors` pattern in `storybook-street`) | `storybook-street` |
| props at doors and windows | anchor points with an `anchor` type INT and a stored rotation frame (`ss_rot` there); one group places all prop kinds | `storybook-street` (`SS Props`) |

## Built things

| Subject | Build with | Template |
|---|---|---|
| house, cottage, shop | wall boxes per storey, openings cut (Manifold boolean, ids recovered from positions), roof from a profile, chimney; all in house-local space | `parametric-house` |
| city block | parcels on the block outline (curve), a house per parcel, heights from a hashed id and a density field | `parametric-house` + `curve-fence` (parcels along the block curve) |
| tower, lighthouse, silo | stacked cylinders/cones from a radius profile (Curve to Mesh with a profile, or a revolved curve) | `parametric-house` |
| barrel, pot, vase, lamp | revolve a profile: Curve Circle swept along a vertical line, Scale field from a Float Curve | `parametric-house` |
| furniture, crates, boxes | rounded boxes from the `shapes` module; mortise-free, scale from inputs | `parametric-house` |
| windows, doors, shutters | instances of shared meshes sized per opening; boolean only the wall | `parametric-house` |

## Plants and growth

| Subject | Build with | Template |
|---|---|---|
| ivy over a statue, vines over a wall, lichen spreading | **simulation zone over any mesh**: tips walk on the surface (Sample Nearest Surface), leave a trail, branch with a probability per step; leaves instanced on the trail | `growth-sim` |
| tree (stylised) | trunk and limbs as curves (repeat zone for branching levels), Curve to Mesh with radius, leaf clumps from the `shapes` module | `growth-sim` (repeat-zone variant), `surface-scatter` |
| hedge, bush, foliage clump | lumpy mound (icosphere + noise displacement) covered by scattered leaves | `surface-scatter` |
| flowers in a window box | leaves and blossoms scattered on a mound by face orientation | `storybook-street` (`SS Props`) |
| grass field | scatter blades (instanced short curves or quads), wind as analytic bend | `surface-scatter` + `wind-bunting` (wind) |
| fruit growing, mould spreading | simulation zone that accumulates an age attribute; size and colour from age | `growth-sim` |

## Motion, cloth and particles

| Subject | Build with | Template |
|---|---|---|
| bunting, flags, banners, washing lines | analytic wind (gust envelope + damped ring); the cloth deforms as a function of Time | `wind-bunting` |
| swinging sign, lantern, pendulum | closed-form pendulum angle from Time, per-piece phase from the hashed id | `wind-bunting` |
| falling leaves, snow, confetti | **analytic** if each flake is independent: position = spawn + v·age + sway(age); recycle with `age = fract((t + phase)/life)`. **Simulation** only if they must land and stay (accumulate) | `wind-bunting` (analytic), `growth-sim` (accumulating) |
| a cloth that settles, a curtain hit by a door | stateful: simulation zone with springs, or the 5.2 Cloth Dynamics asset (experimental) | `growth-sim` (sim-zone pattern) |
| sparks, embers, bubbles with lifetimes | analytic recycling (above) unless they collide | `wind-bunting` |
| a rope that swings and settles after a hit | simulation zone (verlet points on a curve, distance constraints in a repeat zone inside) | `growth-sim` |

## Characters and crowds

| Subject | Build with | Template |
|---|---|---|
| a stylised character walking | parts modelled at rest with pivots; a rig group computes s(t), integrated gait phase, planted feet, bob, sway, arm swing and spring secondary motion as fields of Time | `storybook-street` (`SS Walker`, `SS Walker Rig`, `SS Walker Step`, `SS Walker Spring`) |
| a crowd on a plaza or along a street | points (one per agent) with id, speed, start offset; each agent is the walker rig evaluated with its own Time offset; instance the parts | `surface-scatter` (placement) + `storybook-street` walker |
| birds, fish schools | analytic flocking paths (Lissajous / noise curves per id); a simulation zone only for true interaction | `wind-bunting` (analytic per-id motion) |
| a real rigged character | outside Geometry Nodes: armature and actions; GN can read bones (Bone Info, 5.1) for attached props | none |

## Landscapes, water and atmosphere

| Subject | Build with | Template |
|---|---|---|
| terrain | Grid + Set Position with Noise Texture (fBM / Ridged / Hetero Terrain), material by slope and altitude from stored attributes | `surface-scatter` (scatter on it) |
| terrain with rivers | river as a curve; carve the grid by distance to the curve (Sample Nearest on the resampled curve, or Geometry Proximity), banks blended with Map Range Smoother Step; water as a curve-space strip | `curve-fence` (curve space) + `surface-scatter` |
| rocks, cliffs | icosphere + noise displacement, or SDF grid boolean of a few blobs, meshed; scatter at slope mask | `surface-scatter` |
| lake, pond | flat plane with a glossy shader, procedural normal ripples; shore by height mask | shader-only |
| sky, sun, haze | world Sky Texture or gradient, sun lamp, compositor mist haze | `materials-and-look.md` |
| clouds, fog banks, smoke | Volume object (Principled Volume, density from noise) or SDF/points to volume grids | none |

## Templates

| Template | What it shows | Technique |
|---|---|---|
| `templates/curve-fence.py` | posts and rails along any curve, gaps on tight bends | curve-space layout, instancing |
| `templates/surface-scatter.py` | density-masked scatter on any mesh, per-instance tint | scatter, instancing, named attributes into materials |
| `templates/parametric-house.py` | one house from a few inputs: storeys, openings, roof | mesh modelling, booleans, For Each |
| `templates/growth-sim.py` | growth over any mesh with stored state | simulation zone, baking |
| `templates/wind-bunting.py` | strings of flags between anchors moved by gusts | analytic animation, catenary |
| `prompts/storybook-street/` | a full shot: street generator, walker, camera rig, compositor | all of the above except simulation |

A template is a Blender script: `blender -b --factory-startup --python templates/<name>.py -- --out x.blend
[--render x.png]`. Copy it, then change the input object and the controls; do not start from an empty file.
