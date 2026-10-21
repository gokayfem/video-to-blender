"""Smoke test for v2n.graph: blender -b --factory-startup --python tools/smoke_graph.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import bpy
from nodekit.graph import Graph
from nodekit import inspect

g = Graph("T Grid", description="Test grid", modifier=True)
g.input("Geometry", "GEOMETRY", desc="unused")
w = g.input("Width", "FLOAT", 4.0, min=0.5, max=20, subtype="DISTANCE", panel="Street", desc="Grid width")
with g.frame("Grid"):
    grid = g.node("GeometryNodeMeshGrid", **{"Size X": w, "Size Y": g.math("MULTIPLY", w, 2.0), "Vertices X": 8})
    pos = g.node("GeometryNodeInputPosition")
    z = g.math("SINE", g.separate(pos)["X"])
    sp = g.node("GeometryNodeSetPosition", Geometry=grid["Mesh"], Offset=g.combine(0, 0, z))
g.output("Geometry", "GEOMETRY", sp["Geometry"])
g.finish()
bpy.ops.mesh.primitive_plane_add()
o = bpy.context.object
m = o.modifiers.new("T", "NODES")
m.node_group = g.nt
inspect.set_modifier_inputs(m, {"Width": 6.0})
print("STATS", inspect.evaluated_stats(o), inspect.get_modifier_inputs(m))
print("CHECK", inspect.check_groups("T "))
d = inspect.dump_groups("/dev/stdout" if False else "/tmp/v2n_smoke.json", "T ")
print("NODES", [n["type"] for n in d[0]["nodes"]])
