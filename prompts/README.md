# Prompts

Reusable prompts and worked projects for the **procedural-blender-nodes** skill.

| Path | What it is |
|---|---|
| [`reference-to-nodes-prompt.md`](reference-to-nodes-prompt.md) | A fill-in prompt for recreating any reference (a video clip, an image, several views, an image sequence, or a written description) as an editable Blender node system: quality bar, reference breakdown, contracts, build, comparison over time or views, variations and transfer, deliverables, honesty rules. |
| [`storybook-street/`](storybook-street/) | The first worked project, built with that workflow from a 20 s AI-generated clip: a curve-driven street generator (cobbled road, half-timbered houses, props, bunting, a walking character, a follow camera, compositor haze) in Geometry Nodes, Shader Nodes and a compositor graph. |

## Using the prompt

Copy `reference-to-nodes-prompt.md`, fill in the fields at the top (reference, kind, output name, the input the
system should run on), and send it to an agent with the skill installed. The agent stops after the reference
breakdown for approval, then builds in milestones.

## The storybook-street project

- `README.md`: the result, the demonstration media, validation numbers and limitations.
- `docs/WORKFLOW.md`: the process step by step; `docs/TRANSFER.md`: what carried over from the GLSL sibling
  (shader-skills) and what Blender replaces; `docs/COMPARE.md`: comparing renders with a reference over time.
- `docs/REFERENCE.md`, `docs/reference_params.json`, `reference/`: the measured breakdown, frames, sheets and the
  measurement scripts.
- `street/build.py`: builds `street/storybook_street.blend` (four scenes sharing one graph) from nothing;
  `street/groups/`: one module per part, with `assembly.py` as the top modifier group (Primary macros, forwarded
  part panels); `street/presets/`, `street/light.json`: parameters.
- `docs/GRAPH.md`, `docs/CONTROLS.md`, `docs/graphs/*.png`: the generated graph documentation and node-editor
  screenshots.

Demo:

```bash
cd prompts/storybook-street
blender -b --factory-startup --python street/build.py
blender -b street/storybook_street.blend --python ../../skills/procedural-blender-nodes/scripts/validate.py
```

Renders, comparisons, variation sheets and sweeps are produced with the skill's `scripts/render.py`,
`scripts/sweep.py`, `scripts/video.py` and `scripts/compare.py`, orchestrated by the project's `tools/demo.py`
(see the project README); `out/` is not in git.
