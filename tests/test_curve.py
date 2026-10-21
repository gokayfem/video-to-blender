import numpy as np
import bpy
import nkt
from nodekit.graph import Graph
from library.curve import curve_frame, curve_bend, curve_samples, curve_parcels, curve_ribbon


# ---- local helpers -------------------------------------------------------------------------------------------
def _verts(points):
    me = bpy.data.meshes.new("NKT Verts")
    me.from_pydata([tuple(p) for p in points], [], [])
    ob = bpy.data.objects.new(me.name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _points(tree, inputs, output="Points", names=()):
    """Evaluate one geometry output of ``tree``; point clouds become mesh vertices so attributes can be read."""
    w = Graph(nkt._name("NKT Pts"), description="points test wrapper", modifier=True)
    gn = w.group(tree)
    nkt._wire(w, gn, inputs)
    real = w.node("GeometryNodeRealizeInstances", Geometry=gn[output])
    verts = w.node("GeometryNodePointsToVertices", Points=real["Geometry"])
    j = w.node("GeometryNodeJoinGeometry")
    w.connect(real["Geometry"], j.i("Geometry"))
    w.connect(verts["Mesh"], j.i("Geometry"))
    w.output("Geometry", "GEOMETRY", j["Geometry"])
    w.finish()
    ob = bpy.data.objects.new(w.nt.name, bpy.data.meshes.new(w.nt.name))
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("nkt", "NODES").node_group = w.nt
    bpy.context.scene.frame_set(1)
    return nkt.attrs(ob, ["position", *names])


def _quat_x(q):
    """+X axis of rotations given as (w, x, y, z) quaternions."""
    w, x, y, z = q.T
    return np.stack([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)], axis=1)


def _bezier():
    return nkt.curve([(0, 0, 0), (6, 8, 1), (-4, 16, 3), (2, 25, 2)])


def _length(curve_ob):
    return sum(sp.calc_length() for sp in curve_ob.data.splines)


# ---- NK Curve Frame ------------------------------------------------------------------------------------------
def test_frame_on_straight_poly():
    """On a straight poly curve along +Y, s maps to y, left is -X, offsets and heights add exactly."""
    path = nkt.poly([(0, 0, 0), (0, 10, 0)])
    s = [0.0, 2.5, 5.0, 9.0]
    out = nkt.field(curve_frame(), {"Curve": path, "Offset": 0.5, "Height": 1.0}, per_point={"Length": s},
                    outputs={"Position": "VECTOR", "Left": "VECTOR", "Tangent": "VECTOR"})
    assert nkt.close(out["Position"], [(-0.5, v, 1.0) for v in s]), out["Position"]
    assert nkt.close(out["Left"], [(-1, 0, 0)] * 4)
    assert nkt.close(out["Tangent"], [(0, 1, 0)] * 4)


def test_frame_orthonormal_on_hilly_bend():
    """Tangent and left stay unit length, level (z = 0) and perpendicular on a bent, climbing curve."""
    path = _bezier()
    out = nkt.field(curve_frame(), {"Curve": path}, per_point={"Length": np.linspace(0, 20, 21)},
                    outputs={"Tangent": "VECTOR", "Left": "VECTOR"})
    t, l = out["Tangent"], out["Left"]
    assert nkt.close(np.linalg.norm(t, axis=1), 1.0) and nkt.close(np.linalg.norm(l, axis=1), 1.0)
    assert nkt.close(t[:, 2], 0.0) and nkt.close(l[:, 2], 0.0)
    assert nkt.close(np.sum(t * l, axis=1), 0.0)


# ---- NK Curve Bend -------------------------------------------------------------------------------------------
def test_bend_maps_centreline_onto_curve():
    """(s, 0, 0) lands on the curve at arc length s (same as NK Curve Frame), and centreline spacing is kept."""
    path = _bezier()
    s = np.linspace(0.0, 20.0, 401)
    src = _verts([(v, 0.0, 0.0) for v in s])
    ob = nkt.evaluate(curve_bend(), {"Geometry": src, "Curve": path})
    p = nkt.attrs(ob)["position"]
    ref = nkt.field(curve_frame(), {"Curve": path}, per_point={"Length": s}, outputs={"Position": "VECTOR"})
    assert nkt.close(p, ref["Position"], 1e-4), np.abs(p - ref["Position"]).max()
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    assert abs(seg.sum() - 20.0) < 0.02, seg.sum()                     # arc length preserved on the centreline
    assert nkt.close(seg, 0.05, 2e-3), (seg.min(), seg.max())          # and locally uniform


def test_bend_offset_and_height_on_straight_poly():
    """On a straight curve the bend is a rigid map: (s, d, h) -> (-d, s, h) for a path along +Y."""
    path = nkt.poly([(0, 0, 0), (0, 10, 0)])
    pts = [(1.0, 0.5, 0.2), (4.0, -1.5, 0.0), (9.5, 2.0, 1.0)]
    ob = nkt.evaluate(curve_bend(), {"Geometry": _verts(pts), "Curve": path, "Height": 0.3})
    p = nkt.attrs(ob)["position"]
    assert nkt.close(p, [(-d, s, h + 0.3) for s, d, h in pts]), p


def test_bend_extends_past_the_ends():
    """X < 0 and X > L continue straight along the end tangents; with Extend off they clamp."""
    path = nkt.poly([(0, 0, 0), (0, 10, 0), (10, 10, 0)])               # L = 20, ends along +Y and +X
    pts = [(-2.0, 0.0, 0.0), (23.0, 0.0, 0.0)]
    p = nkt.attrs(nkt.evaluate(curve_bend(), {"Geometry": _verts(pts), "Curve": path}))["position"]
    assert nkt.close(p, [(0, -2, 0), (13, 10, 0)]), p
    p = nkt.attrs(nkt.evaluate(curve_bend(), {"Geometry": _verts(pts), "Curve": path, "Extend Ends": False}))[
        "position"]
    assert nkt.close(p, [(0, 0, 0), (10, 10, 0)]), p


def test_bend_inner_side_compresses():
    """At offset d on a circle of radius R, lengths scale by 1 -/+ d/R: one side shorter, the other longer."""
    bpy.ops.curve.primitive_bezier_circle_add(radius=10.0)
    circle = bpy.context.object
    half = _length(circle) * 0.5
    s = np.linspace(0.0, half, 201)
    ratio = {}
    for d in (2.0, -2.0):
        p = nkt.attrs(nkt.evaluate(curve_bend(), {"Geometry": _verts([(v, d, 0.0) for v in s]),
                                                  "Curve": circle}))["position"]
        ratio[d] = np.linalg.norm(np.diff(p, axis=0), axis=1).sum() / half
    assert nkt.close(sorted(ratio.values()), [0.8, 1.2], 0.01), ratio


# ---- NK Curve Samples ----------------------------------------------------------------------------------------
def test_samples_count_and_spacing():
    """floor(L / Spacing) + 1 points per side at s = i * Spacing, at +/-Offset on the two sides."""
    path = nkt.poly([(0, 0, 0), (0, 17.5, 0)])
    out = _points(curve_samples(), {"Curve": path, "Spacing": 2.0}, names=["nk_s", "nk_d", "nk_index"])
    assert out["_count"] == 9, out["_count"]
    assert nkt.close(out["nk_s"], np.arange(9) * 2.0) and nkt.close(out["nk_index"], np.arange(9))
    out = _points(curve_samples(), {"Curve": path, "Spacing": 2.0, "Both Sides": True, "Offset": 1.5},
                  names=["nk_s", "nk_d", "nk_side", "nk_rot"])
    assert out["_count"] == 18, out["_count"]
    assert nkt.close(out["nk_d"], out["nk_side"] * 1.5) and set(out["nk_side"].astype(int)) == {-1, 1}
    p, s, d = out["position"], out["nk_s"], out["nk_d"]
    assert nkt.close(p[:, 0], -d) and nkt.close(p[:, 1], s), np.c_[p, s, d]
    assert nkt.close(_quat_x(out["nk_rot"]), (0, 1, 0))                   # frame +X along travel
    for L, sp in ((_length(_bezier()), 0.7), (_length(_bezier()), 3.3)):
        out = _points(curve_samples(), {"Curve": _bezier(), "Spacing": sp, "Both Sides": True})
        assert out["_count"] == 2 * (int(np.floor(L / sp)) + 1), (out["_count"], L, sp)


def test_samples_jitter_stays_on_curve():
    """Jittered samples stay within half a spacing of their slot and on the curve's arc-length range."""
    path = _bezier()
    out = _points(curve_samples(), {"Curve": path, "Spacing": 1.0, "Jitter": 1.0, "Seed": 7},
                  names=["nk_s", "nk_index"])
    s, i = out["nk_s"], out["nk_index"]
    assert np.all(np.abs(s - i) <= 0.5 + 1e-5) and s.min() >= 0 and s.max() <= _length(path) + 1e-3
    assert np.std(s - i) > 0.1


# ---- NK Curve Parcels ----------------------------------------------------------------------------------------
def _check_parcels(out, L, wmin, wmax):
    for side in (-1, 1):
        sel = out["nk_side"] == side
        if not sel.any():
            continue
        w, s0 = out["nk_width"][sel], out["nk_s0"][sel]
        order = np.argsort(s0)
        w, s0 = w[order], s0[order]
        assert abs(w.sum() - L) < 2e-3, (side, w.sum(), L)              # widths sum to the curve length
        assert nkt.close(s0[1:], np.cumsum(w)[:-1], 2e-3)               # end to end, no gaps
        assert w.min() >= wmin - 1e-4 and w.max() <= wmax + 1e-4, (w.min(), w.max())


def test_parcels_tile_the_curve_exactly():
    """Per side: widths in [Min, Max] summing to the curve length, laid end to end; independent sides."""
    path = _bezier()
    L = _length(path)
    for seed in (0, 3, 11):
        out = _points(curve_parcels(), {"Curve": path, "Width Min": 1.5, "Width Max": 4.0, "Seed": seed},
                      names=["nk_width", "nk_s0", "nk_side", "nk_chord", "nk_fan", "nk_index"])
        _check_parcels(out, L, 1.5, 4.0)
        left, right = out["nk_width"][out["nk_side"] == 1], out["nk_width"][out["nk_side"] == -1]
        assert len(left) == len(right) and not nkt.close(np.sort(left), np.sort(right), 1e-3)
        assert np.std(left) > 0.2
    # narrow range: widths are forced close to L / n but still sum exactly
    out = _points(curve_parcels(), {"Curve": path, "Width Min": 2.9, "Width Max": 3.1, "Both Sides": False},
                  names=["nk_width", "nk_s0", "nk_side"])
    _check_parcels(out, L, 2.9, 3.1)


def test_parcels_chord_and_fan():
    """On a straight leg the chord equals the width and the fan is 0; around a corner the outside fans out."""
    path = nkt.poly([(0, 0, 0), (0, 30, 0)])
    out = _points(curve_parcels(), {"Curve": path, "Offset": 2.0, "Depth": 3.0},
                  names=["nk_width", "nk_chord", "nk_fan", "nk_s", "nk_d", "nk_rot", "nk_side"])
    assert nkt.close(out["nk_chord"], out["nk_width"], 1e-3) and nkt.close(out["nk_fan"], 0.0, 1e-4)
    assert nkt.close(out["position"][:, 0], -out["nk_d"]) and nkt.close(out["position"][:, 1], out["nk_s"], 1e-3)
    x = _quat_x(out["nk_rot"])                         # Face Centre: +Y towards the curve, so +X = side * travel
    assert nkt.close(x, np.outer(-out["nk_side"], (0, 1, 0)), 1e-4)
    bpy.ops.curve.primitive_bezier_circle_add(radius=12.0)
    circle = bpy.context.object
    out = _points(curve_parcels(), {"Curve": circle, "Offset": 2.0, "Depth": 3.0},
                  names=["nk_width", "nk_s0", "nk_chord", "nk_fan", "nk_side"])
    _check_parcels(out, _length(circle), 2.0, 4.0)
    fan = {sd: out["nk_fan"][out["nk_side"] == sd] for sd in (-1, 1)}
    assert (np.all(fan[1] > 0) and np.all(fan[-1] < 0)) or (np.all(fan[1] < 0) and np.all(fan[-1] > 0)), fan


# ---- NK Curve Ribbon -----------------------------------------------------------------------------------------
def test_ribbon_spans_width_and_uv():
    """A straight ribbon spans [Offset - W/2, Offset + W/2] across, U runs 0..L, faces point up."""
    path = nkt.poly([(0, 0, 0), (0, 12, 0)])
    ob = nkt.evaluate(curve_ribbon(), {"Curve": path, "Width": 3.0, "Offset": 1.0, "Height": 0.1, "Step": 0.5})
    p = nkt.attrs(ob)["position"]
    assert nkt.close([p[:, 0].min(), p[:, 0].max()], [-2.5, 0.5]) and nkt.close(p[:, 2], 0.1)
    assert nkt.close([p[:, 1].min(), p[:, 1].max()], [0.0, 12.0])
    me = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    uv = np.zeros(len(me.loops) * 2)
    me.attributes["UVMap"].data.foreach_get("vector", uv)
    uv = uv.reshape(-1, 2)
    assert nkt.close([uv[:, 0].min(), uv[:, 0].max(), uv[:, 1].min(), uv[:, 1].max()], [0, 12, 0, 3])
    nz = np.array([f.normal.z for f in me.polygons])
    assert len(me.polygons) == 24 and np.all(nz > 0.999), (len(me.polygons), nz.min())


def test_ribbon_follows_a_bend():
    """On a bent curve every ribbon vertex stays within Width/2 of the curve's offset line (level frame)."""
    path = _bezier()
    ob = nkt.evaluate(curve_ribbon(), {"Curve": path, "Width": 2.0, "Step": 0.2})
    p = nkt.attrs(ob)["position"]
    ref = nkt.field(curve_frame(), {"Curve": path}, per_point={"Length": np.linspace(0, _length(path), 2000)},
                    outputs={"Position": "VECTOR"})["Position"]
    dist = np.min(np.linalg.norm(p[:, None, :] - ref[None, :, :], axis=2), axis=1)
    assert dist.max() < 1.0 + 1e-2, dist.max()
