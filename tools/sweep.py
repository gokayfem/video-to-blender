"""Render a control sweep: one moment of the street while a control moves between values (the "edit the graph"
part of the demo).

    blender -b street/storybook_street.blend --python tools/sweep.py -- --control "Timber Amount" \
        --values 0,1.7 --frames 48 --at 169 --out out/demo/sweep/timber_ [--scene Reference] [--width 960]

Values are interpolated with smoothstep (integers round). Each rendered frame is a full re-evaluation of the
node graph with that control value; nothing is baked.
"""
import argparse, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from v2n import inspect

argv = sys.argv[sys.argv.index("--") + 1:]
ap = argparse.ArgumentParser()
ap.add_argument("--control", required=True)
ap.add_argument("--values", required=True)
ap.add_argument("--frames", type=int, default=48)
ap.add_argument("--at", type=int, default=169)
ap.add_argument("--scene", default="Reference")
ap.add_argument("--camera", default="")
ap.add_argument("--width", type=int, default=960)
ap.add_argument("--samples", type=int, default=8)
ap.add_argument("--out", required=True)
a = ap.parse_args(argv)

sc = bpy.data.scenes[a.scene]
if bpy.context.window:
    bpy.context.window.scene = sc
if a.camera:
    sc.camera = bpy.data.objects[a.camera]
street = next(o for o in sc.objects if o.type == "MESH" and any(m.type == "NODES" for m in o.modifiers))
mod = next(m for m in street.modifiers if m.type == "NODES")
v0, v1 = (float(x) for x in a.values.split(","))
is_int = isinstance(inspect.get_modifier_inputs(mod)[a.control], int)
sc.render.resolution_x = a.width
sc.render.resolution_y = int(round(a.width * 704 / 1280 / 2)) * 2
sc.eevee.taa_render_samples = a.samples
sc.frame_set(a.at)
out = pathlib.Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
for i in range(a.frames):
    u = i / max(1, a.frames - 1)
    u = u * u * (3 - 2 * u)
    v = v0 + (v1 - v0) * u
    inspect.set_modifier_inputs(mod, {a.control: int(round(v)) if is_int else v})
    sc.frame_set(a.at)
    sc.render.filepath = str(out.resolve()) + f"{i + 1:04d}"
    bpy.ops.render.render(write_still=True, scene=sc.name)
    print("SWEEP", i + 1, a.control, round(v, 3))
