"""Validate a saved .blend the way a user meets it: reopen, evaluate every scene, check the cameras.

    blender -b street/storybook_street.blend --python tools/validate.py -- [--step 24] [--out out/validate]

Per scene: Geometry Nodes warnings, evaluated vertex/face/material counts (and evaluation time) at frame 1, then
every --step frames the follow camera's clearance: the distance from the camera to the nearest street geometry
(BVH over the evaluated mesh at frame 1; houses, road and props are static) and whether the camera point is
inside a closed mesh (odd number of hits on an upward ray). Also lints every node group. Writes report.json and
prints a summary; exits 1 on any failure.
"""
import json, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from v2n import inspect

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opts = dict(zip(argv[::2], argv[1::2]))
STEP = int(opts.get("--step", 24))
OUT = pathlib.Path(opts.get("--out", ROOT / "out" / "validate"))
OUT.mkdir(parents=True, exist_ok=True)
MIN_CLEAR = 0.25                     # H; closer than this the camera would graze a wall, sign or awning
report, failures = {"file": bpy.data.filepath, "scenes": {}}, []


def inside(bvh, p):
    hits, origin = 0, p.copy()
    for _ in range(64):
        loc, nrm, idx, dist = bvh.ray_cast(origin, Vector((0, 0, 1)))
        if loc is None:
            break
        hits += 1
        origin = loc + Vector((0, 0, 1e-4))
    return hits % 2 == 1


for sc in bpy.data.scenes:
    street = next(o for o in sc.objects if o.type == "MESH" and any(m.type == "NODES" for m in o.modifiers))
    mod = next(m for m in street.modifiers if m.type == "NODES")
    if bpy.context.window:                 # drivers (the camera rigs) only update in the window's scene
        bpy.context.window.scene = sc
    t0 = time.time()
    sc.frame_set(1)
    dg = sc.view_layers[0].depsgraph
    dg.update()
    ev = street.evaluated_get(dg)
    me = ev.to_mesh()
    dt = time.time() - t0
    rec = {"verts": len(me.vertices), "faces": len(me.polygons), "eval_s": round(dt, 2),
           "warnings": [w.message for w in mod.node_warnings]}
    ev.to_mesh_clear()
    # clearance is measured against the static street only (the walker moves; it is checked by its own tests)
    inspect.set_modifier_inputs(mod, {"Show Walker": False})
    dg.update()
    ev = street.evaluated_get(dg)
    me = ev.to_mesh()
    bvh = BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [tuple(p.vertices) for p in me.polygons])
    ev.to_mesh_clear()
    inspect.set_modifier_inputs(mod, {"Show Walker": True})
    follow = bpy.data.objects.get(f"{sc.name} Camera")
    clear = []
    for f in range(1, sc.frame_end + 1, STEP):
        sc.frame_set(f)
        p = follow.matrix_world.translation.copy()
        loc, nrm, idx, dist = bvh.find_nearest(p)
        clear.append({"frame": f, "clearance": round(dist, 3) if dist is not None else None,
                      "inside": inside(bvh, p)})
    rec["camera"] = {"min_clearance": min(c["clearance"] for c in clear),
                     "inside_frames": [c["frame"] for c in clear if c["inside"]], "samples": clear}
    if rec["warnings"]:
        failures.append(f"{sc.name}: node warnings {rec['warnings']}")
    if rec["camera"]["inside_frames"]:
        failures.append(f"{sc.name}: camera inside geometry at frames {rec['camera']['inside_frames']}")
    if rec["camera"]["min_clearance"] < MIN_CLEAR:
        failures.append(f"{sc.name}: camera clearance {rec['camera']['min_clearance']} < {MIN_CLEAR}")
    report["scenes"][sc.name] = rec
    print(f"SCENE {sc.name}: {rec['verts']} verts, eval {dt:.2f}s, warnings {len(rec['warnings'])}, "
          f"camera min clearance {rec['camera']['min_clearance']}, inside {rec['camera']['inside_frames']}")

lint = inspect.check_groups("SS ") + inspect.check_groups("Storybook")
report["lint"] = lint
failures += [f"lint: {x}" for x in lint]
report["failures"] = failures
(OUT / "report.json").write_text(json.dumps(report, indent=1))
print("FAILURES", len(failures))
for x in failures:
    print("  ", x)
sys.exit(1 if failures else 0)
