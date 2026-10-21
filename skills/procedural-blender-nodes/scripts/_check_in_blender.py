"""Run by `nodes_tools.py check` inside Blender: build every library group, lint it, and evaluate every Geometry
Nodes group on standard test inputs (a curve for curve/'Curve' inputs, an icosphere for other geometry), with
zero node warnings required. Exits 1 on any problem."""
import pathlib, sys, time
SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import bpy
from nodekit import inspect
from nodekit.graph import Graph
from nodekit.library import REGISTRY, build_all

problems = []
t0 = time.time()
try:
    trees = build_all()
except Exception as e:                                   # a builder that raises is a hard failure
    import traceback
    traceback.print_exc()
    sys.exit(1)
print(f"built {len(trees)} groups in {time.time() - t0:.2f}s")

for name, tree in trees.items():
    if tree.name != name:
        problems.append(f"{name}: builder returned a tree named {tree.name!r}")
problems += inspect.check_groups("NK ")

# evaluation on standard inputs
cu = bpy.data.curves.new("NK Test Curve", "CURVE")
cu.dimensions = "3D"
sp = cu.splines.new("BEZIER")
sp.bezier_points.add(3)
for bp, p in zip(sp.bezier_points, [(0, 0, 0), (4, 6, 0), (-3, 12, 1), (0, 20, 1)]):
    bp.co = p
    bp.handle_left_type = bp.handle_right_type = "AUTO"
curve_ob = bpy.data.objects.new("NK Test Curve", cu)
bpy.context.scene.collection.objects.link(curve_ob)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0)
mesh_ob = bpy.context.object

for name, tree in trees.items():
    if tree.bl_idname != "GeometryNodeTree":
        continue
    outs = [it for it in tree.interface.items_tree if it.item_type == "SOCKET" and it.in_out == "OUTPUT"]
    if not any(it.socket_type == "NodeSocketGeometry" for it in outs):
        continue                                          # field-only helper groups are checked by tests
    w = Graph(f"NKT {name}", description="check wrapper", modifier=True)
    ci = w.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=curve_ob)
    mi = w.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=mesh_ob)
    t = w.node("GeometryNodeInputSceneTime")
    gn = w.group(tree)
    for s in gn.b.inputs:
        if not s.enabled:
            continue
        if s.type == "GEOMETRY":
            w.connect(ci["Geometry"] if "curve" in s.name.lower() or "path" in s.name.lower() else mi["Geometry"], s)
        elif s.name == "Time":
            w.connect(t["Seconds"], s)
    j = w.node("GeometryNodeJoinGeometry")
    for s in gn.b.outputs:
        if s.enabled and s.type == "GEOMETRY":
            w.connect(s, j.i("Geometry"))
    w.output("Geometry", "GEOMETRY", j["Geometry"])
    w.finish()
    me = bpy.data.meshes.new(f"NKT {name}")
    ob = bpy.data.objects.new(f"NKT {name}", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("check", "NODES")
    mod.node_group = w.nt
    t1 = time.time()
    bpy.context.scene.frame_set(24)
    stats = inspect.evaluated_stats(ob)
    dt = (time.time() - t1) * 1000
    warns = [f"{x.type}: {x.message}" for x in mod.node_warnings]
    print(f"  {name:<32} {stats['verts']:>8} verts {dt:7.1f} ms  {'; '.join(warns)}")
    for x in warns:
        problems.append(f"{name}: node warning on test inputs: {x}")

for p in problems:
    print("ERROR", p)
print(f"blender: {len(problems)} problem(s)")
sys.exit(1 if problems else 0)
