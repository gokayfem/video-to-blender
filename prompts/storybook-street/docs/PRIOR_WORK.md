# Prior work and originality check

Researched October 2026 (web search plus abstracts and project pages; most papers were read at abstract level, not
in full). The question: does anything already turn a reference video into an editable, procedural Blender node
system (Geometry Nodes plus Shader Nodes, artist controls, reusable on new input curves)? Short answer: every
part exists separately. We found no published system that combines all of them, but two 2026 benchmarks
(CineRecon, BVB) come close on the "video to editable animated Blender scene by an agent" part, so our claims have
to be narrow.

Legend: **Graph?** = is the output an editable procedural graph or program that regenerates the result from
parameters (not a fixed scene)? **Video?** = does it use the input's evolution over time?

## 1. Inverse procedural modeling (buildings, facades, cities, plants)

| Work | Input → output | Graph? | Video? |
|---|---|---|---|
| Šťava, Beneš et al., *Inverse Procedural Modeling by Automatic Generation of L-systems*, EG 2010 ([link](https://diglib.eg.org/handle/10.2312/CGF.v29i2pp665-674)) | 2D vector drawing → parametric L-system | Yes (grammar) | No |
| Šťava et al., *Inverse Procedural Modeling of Trees*, CGF 2014 ([pdf](https://cs.purdue.edu/homes/bbenes/papers/Stava14CGF.pdf)) | tree mesh → parameters of a fixed tree generator (MCMC) | Parameters only | No |
| Vanegas, Garcia-Dorado, Aliaga, Beneš, Waddell, *Inverse Design of Urban Procedural Models*, SIGGRAPH Asia 2012 ([link](https://history.siggraph.org/?p=163321)) | target indicators → parameters of an urban model | Parameters only | No |
| Wu et al., *Inverse Procedural Modeling of Facade Layouts*, TOG 2014 ([link](https://deepai.org/publication/inverse-procedural-modeling-of-facade-layouts)) | labelled facade layout → split grammar (minimum description length) | Yes (grammar) | No |
| Demir, Aliaga, Beneš, *Proceduralization* of architectural / urban models, 2016–17 ([pdf](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Demir-2017-Proceduralization_of_urban_models.pdf)) | 3D mesh → hierarchical split grammar, editable | Yes (grammar) | No |
| Nishida et al., *Interactive Sketching of Urban Procedural Models*, SIGGRAPH 2016 (title from citations; not fetched) | user sketch → CNN-selected grammar snippet + parameters | Yes (fixed grammar library) | No |
| Nishida, Bousseau, Aliaga, *Procedural Modeling of a Building from a Single Image*, EG 2018 ([pdf](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Nishida-EUROGRAPHICS-2018-Procedured_Modeling_of_a_Building.pdf)) | one photo → mass + facade/window grammar | Yes (grammar) | No |
| Zhao et al., *DI-PCG*, CVPR 2025 ([link](https://openaccess.thecvf.com/content/CVPR2025/html/Zhao_DI-PCG_Diffusion-based_Efficient_Inverse_Procedural_Content_Generation_for_High-quality_3D_CVPR_2025_paper.html)) | image → parameters of 6 Infinigen generators | Parameters only | No |
| Stekovic et al., *PyTorchGeoNodes*, CVPR 2025 ([link](https://openaccess.thecvf.com/content/CVPR2025/html/Stekovic_PyTorchGeoNodes_Enabling_Differentiable_Shape_Programs_for_3D_Shape_Reconstruction_CVPR_2025_paper.html)) | images/scans → parameters of a hand-made **Geometry Nodes** program, via a differentiable PyTorch port | Parameters of an existing GN graph | No |

**Overlap.** This is the intellectual root of Video2Nodes: explain an observation with a procedural model whose
parameters an artist can edit. Wu and Nishida are the closest on subject (facades and urban massing).
**Difference.** These methods either fit parameters of a generator someone already wrote (Šťava 2014, Vanegas,
DI-PCG, PyTorchGeoNodes) or infer a grammar in a fixed formalism (split grammars, L-systems). None writes a new
Blender node graph, none handles materials and animation together, and none takes video. PyTorchGeoNodes is the
only one that targets Geometry Nodes, and it optimizes an existing graph rather than authoring one.

## 2. Image to procedural material graph

| Work | Input → output | Graph? | Video? |
|---|---|---|---|
| Shi et al., *MATch* + *DiffMat*, SIGGRAPH Asia 2020 ([link](https://research.adobe.com/publication/match/)) | photo → parameters of a Substance graph chosen from a library (differentiable) | Yes (Substance) | No |
| Guerrero et al., *MatFormer*, 2022 ([arXiv 2207.01044](https://arxiv.org/abs/2207.01044)) | nothing → new Substance node graph (unconditional transformer) | Yes | No |
| Hu et al., *Generating Procedural Materials from Text or Image Prompts*, SIGGRAPH 2023 ([arXiv 2304.13172](https://arxiv.org/abs/2304.13172)) | text / image / partial graph → Substance node graph | Yes | No |
| Li et al., *VLMaterial*, ICLR 2025 ([arXiv 2501.18623](https://arxiv.org/abs/2501.18623)) | image → Python that builds a **Blender shader node graph** (fine-tuned VLM) | Yes (Blender) | No |
| Gupta et al., *Reflecting Process Expertise in Procedural Material Generation*, ECCV 2026 ([arXiv 2607.13318](https://arxiv.org/abs/2607.13318)) | user intent → process trace → executable **Blender material graph**; tutorial videos mined for process knowledge | Yes (Blender) | Tutorial videos as *knowledge*, not as the target |

**Overlap.** VLMaterial already does "image → editable Blender Shader Nodes"; we must not claim to be first at
reference-to-Blender-material graphs. **Difference.** All are per-material, flat 2D texture appearance, single
image. Our materials are a small part of a scene system and are driven by per-instance attributes from Geometry
Nodes (`ss_color`, `ss_rand`), which these methods do not model.

## 3. LLM / agent systems that write Blender Python or node graphs

| Work | Input → output | Graph? | Video? |
|---|---|---|---|
| BlenderGPT add-on (Aarya, Phillips; [mirror](https://gitee.com/mirrors/BlenderGPT)) | text → one-shot `bpy` script | No | No |
| Sun et al., *3D-GPT*, 3DV 2025 ([arXiv 2310.12945](https://arxiv.org/abs/2310.12945)) | text → parameters for Infinigen's generators | Parameters of existing generators | No |
| Hu et al., *SceneCraft*, ICML 2024 ([link](https://proceedings.mlr.press/v235/hu24g.html)) | text → scene graph → Blender Python layout with retrieved assets, VLM render critique | Script, not node graph | No |
| Huang et al., *BlenderAlchemy*, 2024 ([arXiv 2404.17672](https://arxiv.org/abs/2404.17672)) | existing .blend + text/image intent → edited materials/lighting via VLM search | Edits existing graphs | No |
| Du et al., *BlenderLLM*, 2024 ([arXiv 2412.14203](https://arxiv.org/abs/2412.14203)) | text → CAD-style `bpy` script (fine-tuned Qwen) | Script | No |
| *BlenderGym*, CVPR 2025 ([arXiv 2504.01786](https://arxiv.org/abs/2504.01786)) | benchmark: VLM edits incl. procedural materials | — | No |
| Lu et al., *LL3M*, 2025 ([arXiv 2508.08228](https://arxiv.org/abs/2508.08228)) | text → multi-agent Blender Python asset (plan, retrieve, write, debug, refine); uses modifiers and shader nodes | Code, partly node-based | No |
| Dai et al., *MeshCoder*, NeurIPS 2025 ([arXiv 2508.14879](https://arxiv.org/abs/2508.14879)) | point cloud → structured Blender Python | Script | No |
| *Scene Co-pilot*, 2024 ([arXiv 2411.18644](https://arxiv.org/abs/2411.18644)) | text → Blender procedural assets via Infinigen's node transpiler (node graph ↔ Python), then video | Yes (edits transpiled node code) | Output is video; input is text |
| Raji et al., *Proc3D*, 2026 ([arXiv 2601.12234](https://arxiv.org/abs/2601.12234)) | text → "procedural compact graph" with sliders; LLM edits parameters | Yes (own format; Blender GN mapping per search snippet, unverified) | No |
| He et al., *Thinking in Blender (SEIG)*, 2026 ([arXiv 2606.02580](https://arxiv.org/abs/2606.02580)) | **single image** → staged editable Blender program | Program, not stated as node graph | No |
| *3DCodeBench*, 2026 ([arXiv 2606.01057](https://arxiv.org/abs/2606.01057)); *aDSL*, 2026 ([arXiv 2608.17975](https://arxiv.org/abs/2608.17975)) | text/image → procedural 3D code (benchmark; agent DSL) | Programs, object scale | No |
| **CineRecon**, Oct 2026 ([arXiv 2610.16577](https://arxiv.org/abs/2610.16577), [site](https://cinerecon.github.io)) | **video** (film, real, games) → agent writes Blender Python via MCP → editable animated .blend; all 12 models fail on motion | Editable scene; procedural graphs not mentioned | **Yes** |
| **BVB / Blender-VideoBench**, Sep 2026 ([arXiv 2609.15478](https://arxiv.org/abs/2609.15478)) | real **video** → agent-coded animated Blender scene; scored by VQA + perceptual similarity | Not stated | **Yes** |
| Products: NodeGenius ([link](https://superhivemarket.com/products/nodegenius)), Tree Gen LLM ([GitHub](https://github.com/YuutoSeki/treegen-llm)), Blender connector for Claude ([link](https://academy.claude.com/tutorials/using-the-blender-connector-in-claude)), BlenderMCP | text → Geometry Nodes presets / trees; MCP lets an agent run Python and explain GN trees | Small GN graphs | No |

**Overlap.** Agents writing Blender Python with render-and-critique loops are well established (SceneCraft, LL3M,
SEIG). Agents reconstructing a **video** as an editable animated Blender scene are now benchmarked (CineRecon,
BVB). Text-to-Geometry-Nodes add-ons exist. **Difference.** From their abstracts and pages, CineRecon and BVB
produce one fixed scene matching one clip (objects, keyframes, camera); neither describes a reusable generator,
artist-facing parameter panels, or re-running on new input geometry. The GN add-ons make small object-level
presets from text, not a scene system from a reference. Our uncertainty: we have not read CineRecon and BVB in
full; agents there may well emit some Geometry Nodes. We should cite them as the closest work.

## 4. Video to 3D/4D reconstruction

| Work | Input → output | Graph? | Video? |
|---|---|---|---|
| Wu et al., *4D Gaussian Splatting*, CVPR 2024 ([arXiv 2310.08528](https://arxiv.org/abs/2310.08528)); Wang et al., *Shape of Motion*, 2024 ([arXiv 2407.13764](https://arxiv.org/abs/2407.13764)) (IDs from recall) | multi-view or monocular video → time-varying Gaussians | No | Yes |
| Xia et al., *Video2Game*, CVPR 2024 ([arXiv 2404.09833](https://arxiv.org/abs/2404.09833)) | one video → NeRF → mesh with neural textures + rigid-body physics, browser game | No | Frames as views of a static scene |
| *Proc-GS*, 2024 ([arXiv 2412.07660](https://arxiv.org/abs/2412.07660)) | building images/models → procedural code + Gaussians for city assembly | Partly | No (not verified in detail) |
| *ActionMesh*, 2026 ([arXiv 2601.16148](https://arxiv.org/abs/2601.16148)) | video/text → animated mesh via temporal 3D diffusion | No | Yes |

**Why they output baked assets.** Their objective is photometric fidelity to observed pixels, so the
representation is whatever fits pixels best (Gaussians, radiance fields, per-frame deformations). Structure
(what is a house, a window, a repeat), semantics and the rule that generated it are not recovered; editing means
editing millions of primitives. They also need consistent multi-view geometry, which AI-generated clips often
lack (the street "regenerates" as the camera moves). Video2Nodes trades pixel accuracy for an explanation: a
graph that reads as "houses along a curve, windows in a grid, bunting with sag". We should say plainly that our
output will not match the clip pixel-for-pixel the way 4DGS does on its training views.

## 5. Blender procedural street / village / city generators

| Tool | What it does | Graph? | Video? |
|---|---|---|---|
| Buildify (Pavel Oliva, 2022) ([link](https://www.blendernation.com/2022/07/19/buildify-free-city-creation-add-on-with-geometry-nodes-and-osm/)) | footprint curves / OSM → GN buildings from a parts kit | Yes (GN) | No |
| ICity (Hothifa Smair) ([link](https://cgarchitect.com/features/articles/92288b81-icity-procedural-city-generator-for-blender-is-now-available)) | GN city: roads, buildings, vegetation, street furniture | Yes (GN) | No |
| Procedural City add-on, Procedural Building Generator ([1](https://superhivemarket.com/products/procedural-city-addon), [2](https://bazaar.blendernation.com/listing/procedural-building-generator-for-blender/)); SceneCity (not verified this session) | preset-based building/city generators | Yes | No |
| Infinigen / Infinigen Indoors (Raistrick et al., CVPR 2023/2024) ([link](https://openaccess.thecvf.com/content/CVPR2023/html/Raistrick_Infinite_Photorealistic_Worlds_Using_Procedural_Generation_CVPR_2023_paper.html)) | hand-written Blender node/Python generators for nature and interiors; node transpiler GN ↔ Python | Yes | No |

**Overlap.** Curve-driven Geometry Nodes building and street generators are mature products; a GN street
generator is not novel in itself. **Difference.** They are hand-authored to a style, not derived from a
reference, and none ships with a measured correspondence to a specific clip.

## What we can and cannot claim

**Cannot claim**
- First to reconstruct a video as an editable Blender scene with an agent (CineRecon, BVB).
- First to have an LLM/agent write Blender Python or node graphs (BlenderGPT, SceneCraft, LL3M, many more).
- First to infer an editable Blender material graph from an image (VLMaterial; Hu et al. for Substance).
- First inverse procedural modeling of buildings or facades (Wu 2014, Nishida 2016/2018, Demir 2017).
- First curve-driven Geometry Nodes street or city generator (Buildify, ICity and others).
- Any quantitative accuracy against the reference that we have not measured.

**Can claim (carefully worded)**
- "To our knowledge, we found no prior system that turns a single AI-generated video into a reusable Geometry
  Nodes + Shader Nodes generator: one whose exposed parameters regenerate the scene, its materials and its
  animation, and which runs on new input curves." Keep "to our knowledge" and the date.
- The output is a procedural *explanation* (organized, documented node groups with artist panels), not a fixed
  reconstruction; we demonstrate reuse on five test paths (straight, S-bend, hill, spiral, reference).
- Animation is expressed as graph logic on a `Time` input (analytic or simulation zone), not baked keyframes.
- The workflow is a port of a measured video-to-shader method (Video2GLSL) to native Blender nodes.

**Uncertain, re-check before publishing**: full texts of CineRecon and BVB (do agents emit GN?); Proc3D's Blender
mapping; recent commercial "video to 3D scene" products (not surveyed); SceneCity status; the 4DGS and Shape of
Motion arXiv IDs were cited from memory.
