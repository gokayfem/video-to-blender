"""Test helpers for node groups, used inside Blender by tests/test_*.py (run with `nodes_tools.py test`).

    import nkt
    from library.curve import curve_frame

    def test_frame_is_orthonormal():
        path = nkt.curve([(0, 0, 0), (5, 5, 0), (0, 10, 2)])
        out = nkt.field(curve_frame(), {"Curve": path, "Offset": 0.5},
                        per_point={"Length": [0, 1, 2, 3]}, outputs={"Position": "VECTOR", "Left": "VECTOR"})
        assert nkt.close(np.linalg.norm(out["Left"], axis=1), 1.0)

    def test_scatter_density():
        ob = nkt.evaluate(scatter(), {"Mesh": nkt.ico(), "Density": 10})
        arr = nkt.attrs(ob, ["position"])
        assert 100 < len(arr["position"]) < 140

Geometry inputs take Blender objects (wired through Object Info, relative space). Other inputs take constants.
`evaluate` returns the evaluated object; `attrs` reads point-domain attributes as numpy arrays; `field` evaluates
a field-only group per point with per-point input values.
"""
import numpy as np
import bpy
from nodekit.graph import Graph
from nodekit import inspect

_N = [0]


def _name(prefix):
    _N[0] += 1
    return f"{prefix} {_N[0]}"


def curve(points, name=None):
    cu = bpy.data.curves.new(name or _name("NKT Curve"), "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(points) - 1)
    for bp, p in zip(sp.bezier_points, points):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    ob = bpy.data.objects.new(cu.name, cu)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def poly(points, name=None):
    """A poly (straight-segment) curve: exact arc lengths for tests."""
    cu = bpy.data.curves.new(name or _name("NKT Poly"), "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for pt, p in zip(sp.points, points):
        pt.co = (*p, 1.0)
    ob = bpy.data.objects.new(cu.name, cu)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def ico(radius=1.0, subdivisions=3):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdivisions, radius=radius)
    return bpy.context.object


def grid(size=10.0, subdivisions=10):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=subdivisions, y_subdivisions=subdivisions, size=size)
    return bpy.context.object


def _wire(w, gn, inputs):
    for k, v in inputs.items():
        sock = gn.i(k)
        if isinstance(v, bpy.types.Object):
            info = w.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=v)
            w.connect(info["Geometry"], sock)
        else:
            w.connect(v, sock)


def evaluate(tree, inputs=None, frame=1, realize=True):
    """Instance ``tree`` in a fresh modifier with ``inputs``; join its geometry outputs; return the object
    evaluated at ``frame`` (warnings are on ``ob.nkt_mod.node_warnings``)."""
    w = Graph(_name("NKT Wrap"), description="test wrapper", modifier=True)
    gn = w.group(tree)
    _wire(w, gn, inputs or {})
    j = w.node("GeometryNodeJoinGeometry")
    for s in gn.b.outputs:
        if s.enabled and s.type == "GEOMETRY":
            w.connect(s, j.i("Geometry"))
    out = j["Geometry"]
    if realize:
        out = w.node("GeometryNodeRealizeInstances", Geometry=out)["Geometry"]
    w.output("Geometry", "GEOMETRY", out)
    w.finish()
    ob = bpy.data.objects.new(w.nt.name, bpy.data.meshes.new(w.nt.name))
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("nkt", "NODES")
    mod.node_group = w.nt
    bpy.context.scene.frame_set(frame)
    return ob


def warnings(ob):
    return [f"{w.type}: {w.message}" for m in ob.modifiers if m.type == "NODES" for w in m.node_warnings]


def attrs(ob, names=("position",), domain="POINT"):
    """Point-domain (or other domain) attributes of the evaluated mesh as numpy arrays (positions in world)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    out = {}
    for n in names:
        a = me.attributes.get(n)
        if a is None:
            out[n] = None
            continue
        size = {"FLOAT": 1, "INT": 1, "BOOLEAN": 1, "FLOAT_VECTOR": 3, "FLOAT_COLOR": 4, "QUATERNION": 4,
                "FLOAT2": 2, "INT32_2D": 2}.get(a.data_type, 1)
        field = {"FLOAT_VECTOR": "vector", "FLOAT_COLOR": "color", "QUATERNION": "value", "FLOAT2": "vector",
                 "INT32_2D": "value"}.get(a.data_type, "value")
        buf = np.zeros(len(a.data) * size, dtype=np.float64 if a.data_type != "BOOLEAN" else bool)
        a.data.foreach_get(field, buf)
        out[n] = buf.reshape(-1, size) if size > 1 else buf
    out["_count"] = len(me.vertices)
    ev.to_mesh_clear()
    return out


def field(tree, inputs=None, per_point=None, outputs=None, frame=1):
    """Evaluate a field group once per point. ``per_point`` maps input name -> list of values (all the same
    length); ``outputs`` maps output name -> type (FLOAT, INT, VECTOR, ROTATION, COLOR, BOOL). Returns numpy
    arrays; ROTATION comes back as quaternions (w, x, y, z)."""
    per_point = per_point or {}
    n = len(next(iter(per_point.values()))) if per_point else 1
    me = bpy.data.meshes.new(_name("NKT Points"))
    me.from_pydata([(i, 0, 0) for i in range(n)], [], [])
    for k, vals in per_point.items():
        vals = np.asarray(vals, dtype=np.float64)
        if vals.ndim == 1:
            a = me.attributes.new(f"in_{k}", "FLOAT", "POINT")
            a.data.foreach_set("value", vals)
        else:
            a = me.attributes.new(f"in_{k}", "FLOAT_VECTOR", "POINT")
            a.data.foreach_set("vector", vals.reshape(-1))
    ob = bpy.data.objects.new(me.name, me)
    bpy.context.scene.collection.objects.link(ob)
    w = Graph(_name("NKT Field"), description="field test wrapper", modifier=True)
    geo = w.input("Geometry", "GEOMETRY", desc="points")
    gn = w.group(tree)
    _wire(w, gn, inputs or {})
    for k, vals in per_point.items():
        dt = "FLOAT" if np.asarray(vals).ndim == 1 else "FLOAT_VECTOR"
        na = w.node("GeometryNodeInputNamedAttribute", props={"data_type": dt}, Name=f"in_{k}")
        w.connect(na["Attribute"], gn.i(k))
    cur = geo
    types = {"FLOAT": "FLOAT", "INT": "INT", "VECTOR": "FLOAT_VECTOR", "ROTATION": "QUATERNION",
             "COLOR": "FLOAT_COLOR", "BOOL": "BOOLEAN"}
    for k, t in (outputs or {}).items():
        st = w.node("GeometryNodeStoreNamedAttribute", props={"data_type": types[t], "domain": "POINT"},
                    Geometry=cur, Name=f"out_{k}")
        w.connect(gn[k], st.i("Value"))
        cur = st["Geometry"]
    w.output("Geometry", "GEOMETRY", cur)
    w.finish()
    mod = ob.modifiers.new("nkt", "NODES")
    mod.node_group = w.nt
    bpy.context.scene.frame_set(frame)
    got = attrs(ob, [f"out_{k}" for k in (outputs or {})])
    return {k: got[f"out_{k}"] for k in (outputs or {})}


def close(a, b, tol=1e-4):
    return bool(np.all(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)) <= tol))
