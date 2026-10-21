# Credits and Sources

All code in this repository is an original implementation released under the MIT license (see LICENSE): the
nodekit builder, the NK node-group library, templates, scripts and the worked projects. No third-party node
assets, add-ons or scripts are copied.

| Technique or material | Source | Notes |
|---|---|---|
| Geometry Nodes, Shader Nodes, compositor, simulation/repeat/for-each zones, EEVEE, AgX | Blender Foundation, Blender 5.2 manual and Python API (docs.blender.org) | used through the public API |
| Damped harmonic oscillator gain and phase; small-angle pendulum period | standard mechanics | math |
| Integrated gait phase, planted feet, spring-damped secondary motion | adapted from the analytic animation approach of the sibling project gokayfem/shader-skills (MIT) | reimplemented as node fields |
| Smoothstep / smootherstep easing (NK Time Remap, gait arcs) | Ken Perlin, "Improving Noise", SIGGRAPH 2002 (smootherstep) | math |
| Premultiplied-alpha compositing, Over operator (NK Haze Over Sky) | Porter and Duff, "Compositing Digital Images", SIGGRAPH 1984 | math |
| Rounded box as a Minkowski sum of a box and a sphere (NK Rounded Box) | standard computational geometry | math |
| Poisson-disk (minimum-distance) scattering (NK Scatter On Surface) | Blender's Distribute Points on Faces, Poisson Disk mode; Bridson, "Fast Poisson Disk Sampling", SIGGRAPH 2007 sketch | used through the node |
| Oklab (comparison tooling) | Björn Ottosson, bottosson.github.io/posts/oklab | public domain / MIT |
| Storybook Street reference clip | AI-generated video (fal.media), used as a visual specification; not redistributed | see prompts/storybook-street/README.md |

Prior work surveyed for the worked project is listed with links in `prompts/storybook-street/docs/PRIOR_WORK.md`.
