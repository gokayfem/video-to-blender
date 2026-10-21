"""Validate a saved .blend the way a user meets it: reopen, evaluate every scene, check the cameras, lint graphs.

    blender -b my_effect.blend --python scripts/validate.py -- [--step 24] [--out out/validate]
        [--hide "Show Walker"] [--min-clear 0.25] [--prefix "NK "] [--no-cameras]

For every scene with a Geometry Nodes object:
- node warnings on every Nodes modifier, evaluated vertex/face counts and evaluation time at the first frame;
- every --step frames, each camera's clearance: distance to the nearest evaluated geometry (BVH built once at
  the first frame from all Nodes objects; animated parts can be switched off for it with --hide <bool input>),
  and whether the camera is inside a closed mesh (odd number of hits on an upward ray);
- node-group lint (nodekit.inspect.check_groups) for groups whose names start with --prefix (default: all).
Writes report.json, prints a summary, exits 1 on any failure. Clearance is checked on the curves and cameras in
the file only; it is evidence, not a proof for every input.
"""
import argparse, json, pathlib, sys, time
SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from nodekit import inspect

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--step", type=int, default=24)
ap.add_argument("--out", default="out/validate")
ap.add_argument("--hide", action="append", default=[], help="bool modifier input set False for the BVH")
ap.add_argument("--min-clear", type=float, default=0.25)
ap.add_argument("--prefix", default="")
ap.add_argument("--no-cameras", action="store_true")
a = ap.parse_args(argv)
OUT = pathlib.Path(a.out)
OUT.mkdir(parents=True, exist_ok=True)
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


def nodes_objects(sc):
    return [(o, m) for o in sc.objects for m in o.modifiers if m.type == "NODES" and m.node_group]


for sc in bpy.data.scenes:
    objs = nodes_objects(sc)
    if not objs:
        continue
    if bpy.context.window:                 # drivers (camera rigs) only update in the window's scene
        bpy.context.window.scene = sc
    t0 = time.time()
    sc.frame_set(sc.frame_start)
    dg = sc.view_layers[0].depsgraph
    dg.update()
    rec = {"objects": {}, "eval_s": None}
    for o, m in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        rec["objects"][o.name] = {"modifier": m.name, "verts": len(me.vertices), "faces": len(me.polygons),
                                  "warnings": [w.message for w in m.node_warnings]}
        ev.to_mesh_clear()
        if rec["objects"][o.name]["warnings"]:
            failures.append(f"{sc.name}/{o.name}: node warnings {rec['objects'][o.name]['warnings']}")
    rec["eval_s"] = round(time.time() - t0, 3)
    cams = [] if a.no_cameras else [o for o in sc.objects if o.type == "CAMERA"]
    if cams:
        hidden = []
        for o, m in objs:
            ids = inspect.modifier_inputs(m)
            vals = {h: False for h in a.hide if h in ids}
            if vals:
                hidden.append((m, {h: inspect.get_modifier_inputs(m)[h] for h in vals}))
                inspect.set_modifier_inputs(m, vals)
        dg.update()
        verts, polys = [], []
        for o, m in objs:
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
            mw = o.matrix_world
            base = len(verts)
            verts += [mw @ v.co for v in me.vertices]
            polys += [tuple(base + i for i in p.vertices) for p in me.polygons]
            ev.to_mesh_clear()
        for m, vals in hidden:
            inspect.set_modifier_inputs(m, vals)
        bvh = BVHTree.FromPolygons(verts, polys) if polys else None
        rec["cameras"] = {}
        for cam in cams:
            samples = []
            for f in range(sc.frame_start, sc.frame_end + 1, a.step):
                sc.frame_set(f)
                p = cam.matrix_world.translation.copy()
                loc, nrm, idx, dist = bvh.find_nearest(p) if bvh else (None, None, None, None)
                samples.append({"frame": f, "clearance": None if dist is None else round(dist, 3),
                                "inside": bool(bvh) and inside(bvh, p)})
            clears = [s["clearance"] for s in samples if s["clearance"] is not None]
            c = {"min_clearance": min(clears) if clears else None,
                 "inside_frames": [s["frame"] for s in samples if s["inside"]], "samples": samples}
            rec["cameras"][cam.name] = c
            if c["inside_frames"]:
                failures.append(f"{sc.name}/{cam.name}: inside geometry at frames {c['inside_frames']}")
            if c["min_clearance"] is not None and c["min_clearance"] < a.min_clear:
                failures.append(f"{sc.name}/{cam.name}: clearance {c['min_clearance']} < {a.min_clear}")
    report["scenes"][sc.name] = rec
    cam_txt = ", ".join(f"{k} min clear {v['min_clearance']}" for k, v in rec.get("cameras", {}).items())
    print(f"SCENE {sc.name}: " + ", ".join(f"{k} {v['verts']} verts {len(v['warnings'])} warnings"
                                         for k, v in rec["objects"].items()) + f", eval {rec['eval_s']}s; {cam_txt}")

lint = inspect.check_groups(a.prefix)
report["lint"] = lint
failures += [f"lint: {x}" for x in lint]
report["failures"] = failures
(OUT / "report.json").write_text(json.dumps(report, indent=1))
print("FAILURES", len(failures))
for x in failures:
    print("  ", x)
sys.exit(1 if failures else 0)
