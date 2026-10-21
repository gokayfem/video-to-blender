import numpy as np
import bpy
import nkt
from nodekit.graph import Graph
from library.shapes import (rounded_box, chamfer_box, chamfer_boxes, rod, ring, profile_revolve, leaf, blossom,
                            foliage_mound)


def _pos(tree, inputs=None):
    return nkt.attrs(nkt.evaluate(tree, inputs or {}))["position"]


def _faces(tree, inputs=None):
    ob = nkt.evaluate(tree, inputs or {})
    me = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    out = [(np.array(f.normal), f.use_smooth, len(f.vertices), np.array(f.center)) for f in me.polygons]
    return out


def _abs_levels(v, tol=1e-4):
    """Distinct values of |v| (rounded), sorted."""
    a = np.sort(np.abs(v))
    keep = [a[0]]
    for x in a[1:]:
        if x - keep[-1] > tol:
            keep.append(x)
    return np.array(keep)


# ---- boxes ---------------------------------------------------------------------------------------------------
def test_rounded_box_is_exact():
    """Every vertex lies on the rounded-box surface: distance Radius from the core box (Size/2 - Radius)."""
    for size, r in (((1.2, 0.8, 0.6), 0.15), ((3.0, 0.5, 2.0), 0.15), ((1, 1, 1), 0.0)):
        p = _pos(rounded_box(), {"Size": size, "Radius": r, "Segments": 5})
        half = np.array(size) / 2
        assert nkt.close(np.abs(p).max(axis=0), half), np.abs(p).max(axis=0)
        q = np.maximum(np.abs(p) - (half - r), 0.0)
        assert nkt.close(np.linalg.norm(q, axis=1), r, 1e-4), (size, r)


def test_rounded_box_radius_clamped_and_smooth():
    """An oversized radius is clamped below half the smallest side; all faces are smooth shaded."""
    p = _pos(rounded_box(), {"Size": (1.0, 0.4, 2.0), "Radius": 5.0})
    assert nkt.close(np.abs(p).max(axis=0), (0.5, 0.2, 1.0))
    assert all(f[1] for f in _faces(rounded_box()))


def test_chamfer_box_chamfer_is_fixed_size():
    """Coordinates take only the values +/-Size/2 and +/-(Size/2 - Chamfer) on every axis, at any size."""
    for size in ((1.0, 1.0, 1.0), (4.0, 0.3, 2.5), (0.2, 6.0, 0.5)):
        p = _pos(chamfer_box(), {"Size": size, "Chamfer": 0.05})
        assert len(p) == 24, len(p)
        for k in range(3):
            assert nkt.close(_abs_levels(p[:, k]), [size[k] / 2 - 0.05, size[k] / 2]), (size, k)
        n = [f[0] for f in _faces(chamfer_box(), {"Size": size, "Chamfer": 0.05})]
        diag = [x for x in n if np.sum(np.abs(x) > 0.1) == 2]                 # 45-degree edge chamfers
        assert diag and nkt.close(np.abs(np.array(diag))[np.abs(np.array(diag)) > 0.1], np.sqrt(0.5), 1e-4)


def test_chamfer_boxes_keep_chamfer_per_point():
    """Per-point sizes (a field) and a rotation: every box keeps the same chamfer width and its own size."""
    sizes = np.array([(1.0, 1.0, 1.0), (3.0, 0.4, 0.8), (0.3, 0.3, 2.0)])
    centres = np.array([(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (0.0, 5.0, 1.0)])
    me = bpy.data.meshes.new("NKT Box Points")
    me.from_pydata([tuple(c) for c in centres], [], [])
    a = me.attributes.new("size", "FLOAT_VECTOR", "POINT")
    a.data.foreach_set("vector", sizes.reshape(-1))
    src = bpy.data.objects.new(me.name, me)
    bpy.context.scene.collection.objects.link(src)
    w = Graph(nkt._name("NKT Boxes"), description="boxes test wrapper", modifier=True)
    info = w.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=src)
    size = w.node("GeometryNodeInputNamedAttribute", props={"data_type": "FLOAT_VECTOR"}, Name="size")
    gn = w.group(chamfer_boxes(), Points=info["Geometry"], Size=size["Attribute"], Chamfer=0.04,
                 Rotation=w.node("FunctionNodeEulerToRotation", Euler=(0.0, 0.0, 0.5)))
    w.output("Geometry", "GEOMETRY", gn["Mesh"])
    w.finish()
    ob = bpy.data.objects.new(w.nt.name, bpy.data.meshes.new(w.nt.name))
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("nkt", "NODES").node_group = w.nt
    out = nkt.attrs(ob, ["position", "size", "_nk_cb_sign"])
    assert out["_nk_cb_sign"] is None and out["size"] is not None       # temporaries removed, user attrs kept
    p = out["position"]
    assert len(p) == 3 * 24
    c, s = np.cos(0.5), np.sin(0.5)
    for k in range(3):
        local = p[k * 24:(k + 1) * 24] - centres[k]
        local = local @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])     # undo the Z rotation
        for ax in range(3):
            assert nkt.close(_abs_levels(local[:, ax]), [sizes[k, ax] / 2 - 0.04, sizes[k, ax] / 2]), (k, ax)


# ---- tubes and turned shapes ---------------------------------------------------------------------------------
def test_rod_hits_both_endpoints():
    """Vertices sit at Radius from the axis, on the two end planes: from Start to End exactly."""
    a, b, r = np.array((0.2, -1.0, 0.5)), np.array((1.5, 2.0, 3.0)), 0.07
    p = _pos(rod(), {"Start": tuple(a), "End": tuple(b), "Radius": r, "Resolution": 10})
    axis = (b - a) / np.linalg.norm(b - a)
    t = (p - a) @ axis
    radial = np.linalg.norm((p - a) - np.outer(t, axis), axis=1)
    assert nkt.close(np.sort(np.unique(np.round(t, 4))), [0.0, np.linalg.norm(b - a)], 1e-4)
    assert nkt.close(radial, r, 1e-4)
    faces = _faces(rod(), {"Start": tuple(a), "End": tuple(b), "Radius": r, "Resolution": 10})
    assert sum(1 for f in faces if not f[1]) == 2 and sum(1 for f in faces if f[1]) == 10


def test_ring_extents():
    """Radial extent R +/- Tube Width/2, height +/- Tube Height/2; a partial sweep stays inside its angle."""
    p = _pos(ring(), {"Radius": 1.0, "Tube Width": 0.2, "Tube Height": 0.5, "Roundness": 0.0})
    rad = np.linalg.norm(p[:, :2], axis=1)
    assert nkt.close([rad.min(), rad.max()], [0.9, 1.1], 2e-3), (rad.min(), rad.max())
    assert nkt.close([p[:, 2].min(), p[:, 2].max()], [-0.25, 0.25], 2e-3)
    p = _pos(ring(), {"Radius": 1.0, "Sweep": 2.0})
    ang = np.arctan2(p[:, 1], p[:, 0])
    tol = 1.0 / 32 + 1e-3                                  # end caps sit square to the end segment (chord)
    assert ang.min() > -tol and 2.0 - 1e-3 < ang.max() < 2.0 + tol, (ang.min(), ang.max())
    faces = _faces(ring(), {"Radius": 1.0, "Sweep": 2.0})
    assert sum(1 for f in faces if not f[1]) == 2                              # the two flat end caps


def test_profile_revolve_passes_through_control_radii():
    """The surface radius equals each control radius at heights 0, H/4 .. H; base and top are capped."""
    r = (0.3, 0.42, 0.45, 0.38, 0.4)
    inputs = {"Height": 2.0, "Segments": 24, **{n: v for n, v in zip(
        ("Radius Bottom", "Radius Lower", "Radius Middle", "Radius Upper", "Radius Top"), r)}}
    p = _pos(profile_revolve(), inputs)
    rad = np.linalg.norm(p[:, :2], axis=1)
    assert nkt.close([p[:, 2].min(), p[:, 2].max()], [0.0, 2.0])
    for k, rk in enumerate(r):
        at = np.abs(p[:, 2] - 0.5 * k) < 1e-4
        assert nkt.close(rad[at].max(), rk, 1e-4), (k, rad[at].max(), rk)
    faces = _faces(profile_revolve(), inputs)
    caps = [f for f in faces if not f[1]]
    assert len(caps) == 2 and nkt.close(sorted(f[0][2] for f in caps), [-1, 1], 1e-4)


def test_profile_revolve_hollow_vessel():
    """A hollow vessel has an inner wall Wall Thickness inside, a floor at Wall Thickness and an open top."""
    inputs = {"Height": 1.0, "Wall Thickness": 0.05, "Segments": 24, "Smooth Profile": False,
              "Radius Bottom": 0.3, "Radius Lower": 0.325, "Radius Middle": 0.35, "Radius Upper": 0.375,
              "Radius Top": 0.4}
    p = _pos(profile_revolve(), inputs)
    rad = np.linalg.norm(p[:, :2], axis=1)
    top = np.abs(p[:, 2] - 1.0) < 1e-4
    assert nkt.close(_abs_levels(rad[top][rad[top] > 0.2]), [0.35, 0.4], 1e-4)
    floor = np.abs(p[:, 2] - 0.05) < 1e-4
    assert floor.any() and nkt.close(rad[floor].max(), 0.3 + 0.025 * 0.05 / 0.25 - 0.05, 1e-3)
    faces = _faces(profile_revolve(), inputs)
    ups = [f for f in faces if f[0][2] > 0.999]
    assert {round(float(f[3][2]), 3) for f in ups} == {0.05, 1.0}, [(f[3], f[2]) for f in ups]
    downs = [f for f in faces if f[0][2] < -0.999]
    assert {round(float(f[3][2]), 3) for f in downs} == {0.0}                         # only the base faces down


# ---- plants ----------------------------------------------------------------------------------------------------
def test_leaf_outline():
    """Base at the origin, tip at Length on +X, widest Width * Length near Widest At, face up."""
    p = _pos(leaf(), {"Length": 2.0, "Width": 0.4, "Widest At": 0.3, "Fold": 0.0, "Curl": 0.0, "Resolution": 20})
    assert nkt.close([p[:, 0].min(), p[:, 0].max()], [0.0, 2.0]) and nkt.close(p[:, 2], 0.0)
    assert abs(np.abs(p[:, 1]).max() - 0.4) < 0.01
    xw = p[np.argmax(np.abs(p[:, 1])), 0]
    assert abs(xw - 0.6) <= 0.1 + 1e-6, xw
    faces = _faces(leaf(), {"Fold": 0.0, "Curl": 0.0})
    assert all(f[0][2] > 0.999 for f in faces)


def test_blossom_size_and_parts():
    """Petal tips reach about Size/2 from the axis; the centre is tagged nk_part = 1."""
    ob = nkt.evaluate(blossom(), {"Size": 1.0, "Petals": 6, "Cup": 0.0, "Centre Size": 0.3})
    out = nkt.attrs(ob, ["position", "nk_part"])
    rad = np.linalg.norm(out["position"][:, :2], axis=1)
    assert 0.45 < rad.max() < 0.52, rad.max()
    centre = out["nk_part"] > 0.5
    assert centre.any() and rad[centre].max() <= 0.15 + 1e-4 and rad[~centre].max() > 0.45


def test_foliage_leaf_count_follows_density():
    """Leaf count ~ Leaf Density x mound area; blossoms only on faces looking up or out; colours stored."""
    mound = nkt.ico(radius=1.0, subdivisions=3)
    area = sum(f.area for f in mound.data.polygons)
    nl = len(nkt.attrs(nkt.evaluate(leaf(), {"Length": 1.0}))["position"])
    out = nkt.attrs(nkt.evaluate(foliage_mound(), {"Mound": mound, "Leaf Density": 200.0, "Underside": -1.0,
                                                   "Show Mound": False}), ["position", "nk_color", "nk_rand"])
    leaves = out["_count"] / nl
    assert abs(leaves - 200.0 * area) < 4 * np.sqrt(200.0 * area), (leaves, 200 * area)
    assert out["nk_color"] is not None and np.ptp(out["nk_rand"]) > 0.5
    ob = nkt.evaluate(foliage_mound(), {"Mound": mound, "Leaf Density": 0.0, "Blossom Density": 100.0,
                                        "Show Mound": False, "Blossom Size": 0.05})
    p = nkt.attrs(ob)["position"]
    assert len(p) > 0 and p[:, 2].min() > -0.35, p[:, 2].min()               # nothing on the underside
