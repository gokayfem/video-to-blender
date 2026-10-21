"""Build ONE street group in a fresh scene, wire it to a test path, report stats and lint, optionally render.

    blender -b --factory-startup --python scripts/try_group.py -- --module groups.my_part --root path/to/project \
        --path reference --frame 1 --png out/try/part.png --cam 0,-6,1.6:0,8,1.0 --width 640
    # --set "Street Width=5" --set "Seed=3"   override group inputs by name
    # --save out/try/part.blend                keep the test file to open in the UI

The module must expose build() returning its top node group. The group's 'Curve' input gets the path curve
(via Object Info), 'Time' gets scene time in seconds (frame / 24), and other inputs keep their defaults unless
--set. Extra geometry inputs (e.g. 'Anchors') are left empty unless the module exposes test_inputs(graph) that
wires them.
"""
import argparse, importlib, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from nodekit.graph import Graph
from nodekit import inspect
from nodekit import scene

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--module", required=True)
ap.add_argument("--root", default=".", help="directory the module is imported from (default: cwd)")
ap.add_argument("--path", default="reference")
ap.add_argument("--frame", type=int, default=1)
ap.add_argument("--png")
ap.add_argument("--save")
ap.add_argument("--cam", default="0,-6,1.6:0,8,1.0", help="camera loc:target")
ap.add_argument("--lens", type=float, default=24)
ap.add_argument("--width", type=int, default=640)
ap.add_argument("--samples", type=int, default=8)
ap.add_argument("--set", action="append", default=[])
a = ap.parse_args(argv)
sys.path.insert(0, str(pathlib.Path(a.root).resolve()))

scene.reset()
path = scene.path_curve(a.path)
mod_py = importlib.import_module(a.module)
top = mod_py.build()

# wrapper: Object Info(path) -> group, Scene Time -> Time
w = Graph("TEST Wrapper", description="test wrapper", modifier=True)
info = w.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=path)
t = w.node("GeometryNodeInputSceneTime")
gn = w.group(top)
names = [s.name for s in gn.b.inputs if s.enabled]
if "Curve" in names:
    w.connect(info["Geometry"], gn.i("Curve"))
if "Time" in names:
    w.connect(t["Seconds"], gn.i("Time"))
for kv in a.set:
    k, v = kv.split("=", 1)
    v = json.loads(v)
    w.connect(v, gn.i(k))
if hasattr(mod_py, "test_inputs"):
    mod_py.test_inputs(w, gn, info)
outs = [s for s in gn.b.outputs if s.enabled and s.type == "GEOMETRY"]
j = w.node("GeometryNodeJoinGeometry")
for s in outs:
    w.connect(s, j.i("Geometry"))
real = w.node("GeometryNodeRealizeInstances", Geometry=j["Geometry"])
w.output("Geometry", "GEOMETRY", real["Geometry"])
w.finish()

ob, mod = scene.holder("Test Street", path, w.nt)
bpy.context.scene.frame_set(a.frame)
scene.light_world()
loc, tgt = [tuple(float(x) for x in p.split(",")) for p in a.cam.split(":")]
scene.camera(lens=a.lens, loc=loc, target=tgt)
scene.render_setup(a.width, int(a.width * 704 / 1280) // 2 * 2, a.samples)

print("STATS", json.dumps(inspect.evaluated_stats(ob)))
print("WARNINGS", [(w_.type, w_.message) for w_ in mod.node_warnings])
print("LINT", json.dumps(inspect.check_groups("SS ")))
if a.png:
    pathlib.Path(a.png).parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(pathlib.Path(a.png).resolve())
    bpy.ops.render.render(write_still=True)
    print("PNG", a.png)
if a.save:
    pathlib.Path(a.save).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(pathlib.Path(a.save).resolve()))
