"""Render stills or sequences from the built .blend, optionally with control overrides (variations).

    blender -b street/storybook_street.blend --python tools/render.py -- --scene Reference \
        --frames 1,97,193 --width 640 --samples 8 --out out/lead/stills/f_
    blender -b street/storybook_street.blend --python tools/render.py -- --scene Reference \
        --range 1:481:1 --width 1280 --out out/lead/seq/f_
    # variations: --preset storm (street/presets/storm.json) and/or --set "Street Width=6" --set "Seed=7"
    # --report prints the evaluated stats and the camera position for each frame instead of rendering
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from v2n import inspect

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--scene", default="Reference")
ap.add_argument("--frames", default="")
ap.add_argument("--range", default="")
ap.add_argument("--width", type=int, default=640)
ap.add_argument("--samples", type=int, default=8)
ap.add_argument("--out", default="out/lead/r_")
ap.add_argument("--preset", default="")
ap.add_argument("--set", action="append", default=[])
ap.add_argument("--report", action="store_true")
ap.add_argument("--engine", default="")
a = ap.parse_args(argv)

sc = bpy.data.scenes[a.scene]
bpy.context.window.scene = sc
street = next(o for o in sc.objects if o.type == "MESH" and any(m.type == "NODES" for m in o.modifiers))
mod = next(m for m in street.modifiers if m.type == "NODES")
values = {}
if a.preset:
    values.update(json.loads((ROOT / "street" / "presets" / f"{a.preset}.json").read_text()))
for kv in a.set:
    k, v = kv.split("=", 1)
    values[k] = json.loads(v)
if values:
    inspect.set_modifier_inputs(mod, values)

r = sc.render
r.resolution_x = a.width
r.resolution_y = int(round(a.width * 704 / 1280 / 2)) * 2
r.resolution_percentage = 100
if a.engine:
    r.engine = a.engine
if hasattr(sc, "eevee"):
    sc.eevee.taa_render_samples = a.samples
if a.range:
    s, e, st = (int(x) for x in a.range.split(":"))
    frames = list(range(s, e + 1, st))
else:
    frames = [int(f) for f in a.frames.split(",") if f] or [sc.frame_current]

out = pathlib.Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
for f in frames:
    sc.frame_set(f)
    if a.report:
        cam = sc.camera
        print(f"FRAME {f} cam {tuple(round(x, 3) for x in cam.matrix_world.translation)} "
              f"stats {inspect.evaluated_stats(street, sc)}")
        continue
    r.filepath = str(out.resolve()) + f"{f:04d}"
    bpy.ops.render.render(write_still=True)
    print("RENDERED", r.filepath + ".png")
