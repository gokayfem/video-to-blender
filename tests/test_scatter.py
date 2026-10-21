import math
import numpy as np
import bpy
import nkt
from nodekit.graph import Graph
from library.scatter import scatter_on_surface, scatter_along_curve, clumps, facade_frame


def _out(tree, inputs, output="Points", names=(), points=True):
    """One geometry output of ``tree`` as mesh vertices (point clouds converted), with named attributes."""
    w = Graph(nkt._name("NKT Out"), description="output test wrapper", modifier=True)
    gn = w.group(tree)
    nkt._wire(w, gn, inputs)
    real = w.node("GeometryNodeRealizeInstances", Geometry=gn[output])
    if points:
        real = w.node("GeometryNodePointsToVertices", Points=real["Geometry"])
    w.output("Geometry", "GEOMETRY", real.out)
    w.finish()
    ob = bpy.data.objects.new(w.nt.name, bpy.data.meshes.new(w.nt.name))
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("nkt", "NODES").node_group = w.nt
    bpy.context.scene.frame_set(1)
    return nkt.attrs(ob, ["position", *names])


def _vertex():
    me = bpy.data.meshes.new("NKT Vertex")
    me.from_pydata([(0, 0, 0)], [], [])
    ob = bpy.data.objects.new(me.name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _min_dist(p):
    d = np.linalg.norm(p[:, None, :] - p[None, :, :], axis=2)
    np.fill_diagonal(d, np.inf)
    return d.min()


def _quat_z(q):
    w, x, y, z = q.T
    return np.stack([2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)], axis=1)


# ---- NK Scatter On Surface -----------------------------------------------------------------------------------
def test_surface_count_tracks_density():
    """Point count ~ Density x area (Poisson noise) on a 10 x 10 grid, for two densities; instances match."""
    grid = nkt.grid(size=10.0, subdivisions=10)
    for dens in (2.0, 8.0):
        out = _out(scatter_on_surface(), {"Surface": grid, "Density": dens, "Seed": 3})
        n, want = out["_count"], dens * 100.0
        assert abs(n - want) < 4 * math.sqrt(want), (n, want)
    inst = _out(scatter_on_surface(), {"Surface": grid, "Density": 2.0, "Seed": 3, "Instance": _vertex()},
                output="Instances", points=False)
    pts = _out(scatter_on_surface(), {"Surface": grid, "Density": 2.0, "Seed": 3})
    assert inst["_count"] == pts["_count"]


def test_surface_min_distance_is_respected():
    """With Min Distance, no two points are closer than it, and the cover is reasonably dense."""
    grid = nkt.grid(size=6.0, subdivisions=6)
    out = _out(scatter_on_surface(), {"Surface": grid, "Density": 50.0, "Min Distance": 0.4, "Seed": 1})
    p = out["position"]
    assert _min_dist(p) >= 0.4 - 1e-4, _min_dist(p)
    assert out["_count"] > 0.4 * 36 / (0.4 * 0.4 * 2), out["_count"]          # well packed, not sparse


def test_surface_slope_and_attribute_masks():
    """Slope Max drops steep faces; a 0/1 Mask Attribute keeps only the marked half."""
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = bpy.context.object
    out = _out(scatter_on_surface(), {"Surface": cube, "Density": 50.0, "Slope Max": math.radians(30)},
               names=["nk_rot"])
    assert out["_count"] > 100 and nkt.close(out["position"][:, 2], 1.0, 1e-4)  # only the top face
    out = _out(scatter_on_surface(), {"Surface": cube, "Density": 50.0, "Slope Max": math.radians(91)})
    assert np.all(out["position"][:, 2] > -1 + 1e-4) and np.any(out["position"][:, 2] < 0.9)
    grid = nkt.grid(size=4.0, subdivisions=8)
    a = grid.data.attributes.new("keep", "FLOAT", "POINT")
    a.data.foreach_set("value", [1.0 if v.co.x > 0.01 else 0.0 for v in grid.data.vertices])
    out = _out(scatter_on_surface(), {"Surface": grid, "Density": 40.0, "Mask Attribute": "keep"})
    x = out["position"][:, 0]
    assert out["_count"] > 200 and x.min() > -0.5 - 1e-4, (out["_count"], x.min())   # only where keep ramps up


def test_surface_alignment_and_scale():
    """Align 1: instance Z = surface normal; Align 0: world up. Scales stay within Min..Max."""
    sphere = nkt.ico(radius=2.0, subdivisions=3)
    out = _out(scatter_on_surface(), {"Surface": sphere, "Density": 5.0, "Align": 1.0, "Scale Min": 0.5,
                                      "Scale Max": 1.5}, names=["nk_rot", "nk_scale"])
    z = _quat_z(out["nk_rot"])
    radial = out["position"] / np.linalg.norm(out["position"], axis=1)[:, None]
    assert np.all(np.sum(z * radial, axis=1) > 0.97)
    assert out["nk_scale"].min() >= 0.5 - 1e-5 and out["nk_scale"].max() <= 1.5 + 1e-5
    out = _out(scatter_on_surface(), {"Surface": sphere, "Density": 5.0, "Align": 0.0}, names=["nk_rot"])
    assert nkt.close(_quat_z(out["nk_rot"]), (0, 0, 1), 1e-4)


def test_empty_scatter_is_warning_free():
    """Density 0, an all-zero Mask Attribute, Poisson at Density 0 and Clump Density 0 give empty outputs and no
    node warnings (the runner fails a test on any warning)."""
    grid = nkt.grid(size=4.0, subdivisions=4)
    grid.data.attributes.new("zero", "FLOAT", "POINT")
    cases = [(scatter_on_surface(), {"Surface": grid, "Instance": _vertex(), "Density": 0.0}),
             (scatter_on_surface(), {"Surface": grid, "Instance": _vertex(), "Density": 20.0,
                                     "Mask Attribute": "zero"}),
             (scatter_on_surface(), {"Surface": grid, "Instance": _vertex(), "Density": 0.0, "Min Distance": 0.3}),
             (clumps(), {"Surface": grid, "Instance": _vertex(), "Clump Density": 0.0})]
    for tree, inputs in cases:
        ob = nkt.evaluate(tree, inputs)
        assert nkt.attrs(ob)["_count"] == 0 and not nkt.warnings(ob), (inputs, nkt.warnings(ob))
        for out in ("Points", "Instances"):
            assert _out(tree, inputs, output=out, points=out == "Points")["_count"] == 0


# ---- NK Scatter Along Curve ----------------------------------------------------------------------------------
def test_along_curve_follows_frame():
    """Count floor(L/Spacing)+1 per side; Follow Curve puts instance +X along the curve, off keeps world X."""
    path = nkt.poly([(0, 0, 0), (0, 12.5, 0)])
    out = _out(scatter_along_curve(), {"Curve": path, "Spacing": 2.5, "Both Sides": True, "Offset": 1.0},
               names=["nk_rot", "nk_d"])
    assert out["_count"] == 12
    q = out["nk_rot"]
    w, x, y, z = q.T
    xa = np.stack([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)], axis=1)
    assert nkt.close(xa, (0, 1, 0), 1e-4) and nkt.close(out["position"][:, 0], -out["nk_d"])
    out = _out(scatter_along_curve(), {"Curve": path, "Spacing": 2.5, "Follow Curve": False}, names=["nk_rot"])
    assert nkt.close(np.abs(out["nk_rot"][:, 0]), 1.0, 1e-4)                  # identity rotation
    inst = _out(scatter_along_curve(), {"Curve": path, "Spacing": 2.5, "Instance": _vertex()}, output="Instances", points=False)
    assert inst["_count"] == 6


# ---- NK Clumps -----------------------------------------------------------------------------------------------
def test_clumps_members_stay_in_their_clump():
    """Members lie within Clump Radius of their centre, Min..Max per clump; centres follow Clump Density."""
    grid = nkt.grid(size=20.0, subdivisions=10)
    inputs = {"Surface": grid, "Clump Density": 0.25, "Clump Radius": 0.8, "Members Min": 2, "Members Max": 7,
              "Seed": 4, "Snap To Surface": False}                       # no snapping at the grid's edges
    cen = _out(clumps(), inputs, output="Centres", names=["nk_clump"])
    mem = _out(clumps(), inputs, output="Points", names=["nk_clump", "nk_dist", "nk_scale"])
    assert abs(cen["_count"] - 100) < 40, cen["_count"]
    centre_of = {int(k): p for k, p in zip(cen["nk_clump"], cen["position"])}
    ids = mem["nk_clump"].astype(int)
    d = np.linalg.norm(mem["position"] - np.array([centre_of[i] for i in ids]), axis=1)
    assert d.max() <= 0.8 + 1e-4 and nkt.close(d / 0.8, mem["nk_dist"], 1e-3), d.max()
    counts = np.bincount(ids, minlength=cen["_count"])
    assert counts.min() >= 2 and counts.max() <= 7 and len(set(counts)) > 2, counts
    near, far = mem["nk_dist"] < 0.3, mem["nk_dist"] > 0.8                    # Falloff: smaller at the rim
    assert mem["nk_scale"][near].mean() > mem["nk_scale"][far].mean()


def test_clumps_snap_to_curved_surface():
    """On a sphere, members are snapped back onto the surface."""
    sphere = nkt.ico(radius=3.0, subdivisions=4)
    out = _out(clumps(), {"Surface": sphere, "Clump Density": 0.3, "Clump Radius": 1.0})
    r = np.linalg.norm(out["position"], axis=1)
    assert out["_count"] > 50 and r.max() <= 3.0 + 1e-4 and r.min() > 2.9, (r.min(), r.max())


# ---- NK Facade Frame -----------------------------------------------------------------------------------------
def _quat_axes(q):
    w, x, y, z = q.T
    X = np.stack([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)], axis=1)
    Y = np.stack([2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)], axis=1)
    return X, Y, _quat_z(q)


def test_facade_frame_on_a_rotated_box():
    """A 6 x 4 x 3 box turned 30 degrees: four points at the wall centres, +Y out of each wall, +Z up, +X along
    it, sizes (6 or 4, 0, 3); roof and floor are not walls. A tilted (gable) face beyond Max Tilt is skipped."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.0, 2.0, 1.5), rotation=(0, 0, math.radians(30)),
                                    scale=(6.0, 4.0, 3.0))
    box = bpy.context.object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    out = _out(facade_frame(), {"Mesh": box}, names=["nk_rot", "nk_size", "nk_face"])
    assert out["_count"] == 4, out["_count"]
    X, Y, Z = _quat_axes(out["nk_rot"])
    c = np.array([1.0, 2.0, 1.5])
    rel = out["position"] - c
    assert nkt.close(Z, (0, 0, 1), 1e-4) and nkt.close(rel[:, 2], 0.0, 1e-4)
    out_dir = rel / np.linalg.norm(rel, axis=1)[:, None]
    assert nkt.close(np.sum(Y * out_dir, axis=1), 1.0, 1e-4)                 # +Y points out of the box
    assert nkt.close(np.cross(Y, Z), X, 1e-4)
    w, h = out["nk_size"][:, 0], out["nk_size"][:, 2]
    dist = np.linalg.norm(rel[:, :2], axis=1)                                # 2 from the long walls, 3 from the short
    assert nkt.close(h, 3.0, 1e-4) and nkt.close(out["nk_size"][:, 1], 0.0)
    assert nkt.close(np.sort(w), [4, 4, 6, 6], 1e-4) and nkt.close(w[np.isclose(dist, 2.0, atol=1e-3)], 6.0, 1e-4)
    me = bpy.data.meshes.new("NKT Lean")                                     # a quad leaning 40 degrees: not a wall
    me.from_pydata([(0, 0, 0), (2, 0, 0), (2, 0.84, 1), (0, 0.84, 1)], [], [(0, 1, 2, 3)])
    lean = bpy.data.objects.new("NKT Lean", me)
    bpy.context.scene.collection.objects.link(lean)
    assert _out(facade_frame(), {"Mesh": lean})["_count"] == 0
    assert _out(facade_frame(), {"Mesh": lean, "Max Tilt": math.radians(45)})["_count"] == 1
