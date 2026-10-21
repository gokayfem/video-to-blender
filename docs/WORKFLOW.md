# Workflow: from a reference video to a node system

How Storybook Street was built, written so the next example can follow it. It adapts the Video2GLSL workflow
(`shader-skills/prompts/video-to-shader-prompt.md`): the measurement and critique discipline carries over; the
target changes from one fragment shader to native, editable Blender node groups.

## What changes from Video2GLSL

| Video2GLSL | Video2Nodes |
|---|---|
| One `mainImage`, single pass, no textures | Native Geometry Nodes + Shader Nodes + compositor; textures allowed if documented (none used here) |
| SDFs raymarched per pixel | Real meshes: primitives, extrusions, booleans, instancing on points |
| `#define` constants as controls | Group inputs in named panels, plus a small Primary panel of macro controls |
| Everything a function of `iTime` | Everything a function of a `Time` input; only the top group reads Scene Time |
| Match one shot | Match the shot *and* stay valid on new inputs (path curves), seeds and control values |
| Bundler + glslang check | `v2n.inspect` lint (descriptions, dangling nodes, invalid links), node warnings, reopen-and-validate |

## Steps

1. **Find and verify the source.** Use the original AI-generated clip, not an earlier reconstruction
   (`~/Downloads/4jpNrAqB….mp4` looked like the source but was our GLSL render: 480 frames and our encoder;
   the source has 481). Record its URL and hash (README).
2. **Measure, don't guess** (`docs/REFERENCE.md`, `docs/reference_params.json`, `reference/scripts/`). For a
   generator, the video's value is *over time*: a 20 s dolly samples many houses, so it gives distributions
   (widths, storeys, prop frequency per house and side), motion (walk cadence, bunting sway), and the camera
   (height, field of view, follow behaviour). Note what the AI clip does inconsistently (the street drifts, the
   last 0.3 s morphs back to the start) so the generator does not copy it.
3. **Write the contracts before building** (`AGENTS.md`): units (1 unit = the walker's height), a shared street
   frame (`SS Street Point`: arc length s, offset d, height h), shared input names, the Facades → Props `Anchors`
   interface, and file ownership. This let five builders work in parallel without collisions.
4. **Build each part as a node group through `v2n.graph`.** Python constructs the graph; the deliverable is the
   graph. Frames name each block ("Parcels: split each side into houses"); sub-groups are reusable pieces
   (`SS Prop Barrel`, `SS House Window`). Every input has a description and range.
5. **Test each group alone** (`tools/try_group.py`) on five paths: reference, straight, S-bend, hill, spiral.
   Zero node warnings and zero lint on all of them.
6. **Integrate early and judge only the full build.** Parts that looked right alone failed together: a shared
   group rebuilt by each module silently unlinked the earlier ones (fixed with `v2n.graph.once`), props were
   ten times too dense against real facades, and light that suited one part hid another.
7. **Compare across time, not on one frame** (`tools/compare.py`, `docs/COMPARE.md`): region colour, luma
   percentiles, edge density and image motion every 0.5 s. Use it to set exposure and fill (for example, the
   render was 0.09 Oklab-L too dark overall before calibration). SSIM is reported but is weak for a generator.
8. **Critique rounds.** Each round: render 0 / 7 / 13 s next to the reference, list the five biggest differences
   in priority order (composition first, then silhouettes and density, then materials, then light), send each to
   the part's owner, rebuild, repeat.
9. **Prove reuse.** Variations (`street/presets/*.json`, mostly through the Primary panel) and transfers
   (other path curves in the same .blend, sharing the same node groups).
10. **Validate as a user meets it** (`tools/validate.py`): reopen the saved file, evaluate every scene, check
    warnings, counts and the follow camera's clearance along every path; render a continuous preview and judge
    motion as a sequence (foot slide, popping, flicker), not stills.

## Structure vs. parameters

Graph *structure* (what parts exist and how they connect) changes only in the Python builders and is reviewed as
code plus the generated `docs/GRAPH.md`. *Parameters* (defaults and presets) are plain values: group input
defaults in the builders, scene-level light in `street/light.json`, camera in `street/build.py`, variations in
`street/presets/`. Fitting to the reference (exposure, sun, densities, sizes) only touches parameters, so it never
breaks the graph's reuse on other inputs.
