"""Try light/world variants on a built .blend and render each (lead's tuning tool).

    blender -b out/lead/full.blend --python tools/light_probe.py -- --frame 169 --out out/lead/light/ \
        --variant 'a={"sun_elev":40,"sun_azim":160}' --variant 'b={...}'
"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from street import scene as S

argv = sys.argv[sys.argv.index("--") + 1:]
opts = {"--frame": "169", "--out": "out/lead/light/", "--width": "640"}
variants = []
i = 0
while i < len(argv):
    if argv[i] == "--variant":
        k, v = argv[i + 1].split("=", 1)
        variants.append((k, json.loads(v)))
    else:
        opts[argv[i]] = argv[i + 1]
    i += 2
sc = bpy.context.scene
base = json.loads((ROOT / "street" / "light.json").read_text())
out = pathlib.Path(opts["--out"]).resolve()
out.mkdir(parents=True, exist_ok=True)
sc.render.resolution_x = int(opts["--width"])
sc.render.resolution_y = int(int(opts["--width"]) * 704 / 1280) // 2 * 2
sc.eevee.taa_render_samples = 16
sc.frame_set(int(opts["--frame"]))
for name, var in variants:
    for o in [o for o in sc.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(o)
    cfg = {**base, **var}
    render = cfg.pop("render", {})
    cfg.pop("post", None)
    S.light_world(sc=sc, **cfg)
    S.render_setup(sc=sc, width=sc.render.resolution_x, height=sc.render.resolution_y, samples=16, **render)
    sc.render.filepath = str(out / name)
    bpy.ops.render.render(write_still=True)
    print("VARIANT", name, cfg, render)
