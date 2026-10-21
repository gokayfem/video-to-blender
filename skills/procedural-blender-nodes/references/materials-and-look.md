# Materials and Look

Procedural Shader Nodes materials driven by attributes from Geometry Nodes, EEVEE settings for Blender 5.x, colour
management, light, the compositor, and calibrating all of it against a reference with measurements.

## Contents

- [Material structure](#material-structure)
- [Attribute-driven variation](#attribute-driven-variation)
- [Procedural texture recipes](#procedural-texture-recipes)
- [EEVEE in 5.x](#eevee-in-5x)
- [Colour management](#colour-management)
- [Light: sun, sky, fill](#light-sun-sky-fill)
- [Compositor: haze and glow](#compositor-haze-and-glow)
- [Calibrating against a reference](#calibrating-against-a-reference)

## Material structure

- One material per physical material (stone, plaster, wood, felt, glass), named `NK <Material>` in the library
  or with the project prefix. Assign in Geometry Nodes with **Set Material** before realizing.
- Base colour comes from the geometry (`nk_color`); the material adds only small procedural variation, so one
  material serves every tint and the palette stays a Geometry Nodes control.
- Textures: procedural only by default (Noise, Voronoi, Wave, Brick, Gradient, Checker; White Noise for per-id
  hashes). Image textures only if documented and justified.
- Coordinates: Object coordinates move with the object (fine for one-object generators). For patterns that must
  follow a wall or a part regardless of where it is placed, store a local coordinate in Geometry Nodes
  (`nk_local` = position before placing, FLOAT_VECTOR) and read it with an Attribute node.
- Picked hex colours are sRGB; colour sockets are linear. Convert with `nodekit.scene.srgb("#AABBCC")`.

```python
from nodekit.materials import material
m = material("NK Plaster")                          # get-or-create, tree emptied
nt = m.node_tree
attr = nt.nodes.new("ShaderNodeAttribute"); attr.attribute_type = "GEOMETRY"; attr.attribute_name = "nk_color"
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
out = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"]); nt.links.new(bsdf.outputs[0], out.inputs[0])
```

## Attribute-driven variation

| Attribute | Read as | Use |
|---|---|---|
| `nk_color` (FLOAT_COLOR) | Attribute `Color` | base tint per piece |
| `nk_rand` (FLOAT 0..1) | Attribute `Factor` | value jitter (`± 8 %`), roughness jitter, hue shift, wear chance |
| `nk_local` (FLOAT_VECTOR) | Attribute `Vector` | texture coordinates in the piece's own frame |
| project terms (`nk_wear`, `nk_glow`) | Attribute `Factor` | design so 0 = no effect: a missing attribute reads 0 |

Attribute type `GEOMETRY` reads realized geometry (the top group realizes once). Type `INSTANCER` reads instance
attributes when instances are rendered unrealized. Types `OBJECT` and `VIEW_LAYER` read custom properties.

Animated attributes (a lantern's `nk_glow` flicker) are computed in Geometry Nodes from Time and read by the
shader; the shader itself has no scene time.

## Procedural texture recipes

| Look | Shader Nodes |
|---|---|
| stucco, plaster relief | Noise (scale 8–20, detail 6) into Bump (strength 0.1–0.3); colour value ± a few % from a larger Noise |
| stone, cobbles | per-stone tint from geometry; Voronoi `Distance to Edge` darkens the rim; Noise roughness |
| wood | Wave (Bands, distortion 2–6) on `nk_local` stretched along the grain; colour ramp of two browns |
| felt, wool | low-contrast Noise, Sheen 0.3–0.6, roughness 0.9 |
| terracotta, clay | warm base, Noise mottling, roughness 0.7, a darker rim from Ambient Occlusion (EEVEE supports the AO node) |
| metal (stylised) | Metallic 1, roughness 0.3–0.5 broken by Noise, edge highlight from Layer Weight |
| glass, lantern | Emission strength from `nk_glow`, Blackbody 1800–2500 K colour |
| stripes on cloth | stored stripe coordinate (`nk_u`) through Math `FRACT` → `GREATER_THAN`, two colours from attributes |

Keep detail scales in world units tied to the subject's scale (1 unit = the reference ruler, see the project's
contract), so texture frequency stays right when sizes change.

## EEVEE in 5.x

Engine id is `BLENDER_EEVEE` (renamed from `BLENDER_EEVEE_NEXT` in 5.0). Settings on `scene.eevee` that matter:

| Setting | Recommended | Effect |
|---|---|---|
| `taa_render_samples` | 8 for iteration, 32–64 final | antialiasing, soft shadows, noise |
| `use_raytracing` | True | ray-traced reflections and GI |
| `ray_tracing_options.use_denoise` | True | |
| `fast_gi_method` | `"GLOBAL_ILLUMINATION"` | warm bounce light into shaded areas |
| `use_shadows`, `shadow_ray_count`, `shadow_step_count` | True, 2, 8 | soft contact shadows |
| `volumetric_*` | only for real volume objects | world volumes swallow the sun (use compositor haze) |
| `use_overscan` | True if screen-space effects fail at edges | |

`nodekit.scene.render_setup(width, height, samples, look, exposure)` sets these. `scene.eevee.gtao_distance` no
longer exists in 5.x. Use Cycles (`CYCLES`) when the look needs true GI, caustics or
pointiness; say so.

## Colour management

- View transform **AgX** (5.x also has `Standard`, `Filmic`, `Khronos PBR Neutral`, `ACES 2.0`).
- Looks are prefixed: `"AgX - Base Contrast"`, `"AgX - Medium High Contrast"`, `"AgX - Punchy"`,
  `"AgX - Low Contrast"`, …, `"AgX - Greyscale"`, or `"None"`. A bare `"Base Contrast"` raises.
- `view_settings.exposure` is the global brightness knob; fit it before touching material colours.
- Choose the look by measured saturation and contrast (luma p10/p90, Oklab chroma), not by eye.

## Light: sun, sky, fill

- **Sun**: `energy` 3–8 for daylight, `angle` 2–5° for soft shadows, warm colour (`#FFE2BC`–`#FFD7A3`).
  Direction from the reference's shadow directions; elevation from shadow lengths.
- **Sky**: a gradient world (horizon → zenith colours, `nodekit.scene.light_world`) gives controllable fill; the
  Sky Texture (`MULTIPLE_SCATTERING`, `SINGLE_SCATTERING`, `PREETHAM`, `HOSEK_WILKIE`) is physical but harder to
  match to a stylised grade.
- **Fill**: shadows in stylised references are warm and lifted. Get that from sky strength, fast GI bounce and
  exposure, not from extra lamps; add an area fill only if measurement says the shadow floor (luma p10) is still
  too low.
- Store light as parameters (`light.json`): sun elevation/azimuth/strength/colour, sky colours, exposure, look.

## Compositor: haze and glow

5.x compositor: the tree is a node group assigned to `scene.compositing_node_group`; the Group Output's first
Color input is the result (there is no Composite node); options like Glare `Type`/`Quality` and Set Alpha `Type`
are menu input sockets; Alpha Over inputs are `Background` and `Foreground`.

Distance haze (`nodekit.scene.post`):

1. `scene.render.film_transparent = True`; enable the Mist pass (`view_layer.use_pass_mist`); set
   `world.mist_settings.start/depth/falloff`.
2. Haze on **premultiplied** geometry: `hazed = mix(image, haze_colour * alpha, mist * amount)`. Mixing toward a
   premultiplied haze colour keeps antialiased silhouettes free of halos.
3. Mix also blends alpha: restore the render alpha with **Set Alpha** (`Type` = Replace Alpha).
4. Alpha Over the hazed geometry onto a sky drawn in screen space (Image Coordinates needs an image input; use
   `Normalized` Y for a gradient).
5. Glare `Fog Glow`, threshold ~0.9, low strength, for lanterns and highlights.

Why not a world volume: in EEVEE a world volume dense enough to haze the distance also dims the sun on everything.

## Calibrating against a reference

Never tune the look by eye alone. Measure the same regions in the reference and the render, over several frames.

1. Pick regions that mean the same thing in both (sky strip, left wall, road, subject); for a generator, compare
   regions, not pixel-aligned objects.
2. Measure mean Oklab L, chroma, b (warmth), luma p10/p50/p90 per region (`scripts/compare.py` does this over
   time for video; for stills, crop and compute the same numbers).
3. Fix in this order, re-measuring after each: exposure (whole-frame L), sun/sky balance (lit vs shaded region
   L), look (contrast: p90 − p10), sky colours, then material base colours per region (`nk_color` palette), then
   material detail.
4. Stop when differences are within the reference's own variation (the reference against itself 0.5 s later), or
   report the remaining differences with their numbers ("road highlights p90 +0.21 over the reference").
5. Keep the fitted values as parameters (light file, palette defaults); never as structural special cases.
