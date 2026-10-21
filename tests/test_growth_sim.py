"""Property tests for templates/growth_sim.py: the "Growth" simulation zone, read through its Debug State output
(state points as vertices with nk_age, -1 = not reached) while stepping frames in order from frame 1."""
import importlib, math, pathlib, sys
import numpy as np
import bpy
import nkt
from nodekit import inspect

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "skills" / "procedural-blender-nodes" / "templates"


def _template():
    if str(TEMPLATES) not in sys.path:
        sys.path.insert(0, str(TEMPLATES))
    import growth_sim
    return importlib.reload(growth_sim)       # rebind to the library modules re-imported for this test


def _mesh(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _patch(x0, x1, y0, y1, n, z=0.0, dip=0.0):
    """Grid patch; with dip > 0 its lowest point is its centre (so Seed Height Bias 1 seeds there)."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vs = [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * j / n, 0.0) for j in range(n + 1) for i in range(n + 1)]
    vs = [(x, y, z + dip * ((x - cx) ** 2 + (y - cy) ** 2)) for x, y, _ in vs]
    fs = [(j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i)
          for j in range(n) for i in range(n)]
    return vs, fs


def _grow(ob, inputs, frames, fps=24):
    """Put Growth on ``ob`` in debug mode and step frames 1..max(frames); return {frame: (positions, ages)}."""
    tpl = _template()
    sc = bpy.context.scene
    sc.render.fps, sc.frame_start, sc.frame_end = fps, 1, max(frames) + 1
    bpy.context.window.scene = sc
    mod = ob.modifiers.new("Growth", "NODES")
    mod.node_group = bpy.data.node_groups.get("Growth") or tpl.build_growth()
    vals = {"Debug State": True, "Moss Amount": 0.0, "Vine Amount": 0.0}
    vals.update(inputs)
    inspect.set_modifier_inputs(mod, vals)
    out = {}
    for f in range(1, max(frames) + 1):
        sc.frame_set(f)
        if f in frames:
            a = nkt.attrs(ob, ["position", "nk_age"])
            out[f] = (a["position"], a["nk_age"])
    return out


def _front_radius(pos, age):
    seed = pos[np.argmax(age)]
    cov = age >= 0
    return float(np.max(np.linalg.norm(pos[cov] - seed, axis=1)))


def test_coverage_monotonic_and_only_seeds_at_start():
    """Coverage never decreases while stepping, and at frame 1 exactly the seed points are covered."""
    ob = nkt.ico(1.0, 4)
    res = _grow(ob, {"Seeds": 3, "Growth Speed": 0.4}, list(range(1, 41)))
    pos0, age0 = res[1]
    assert int((age0 >= 0).sum()) == 3, (age0 >= 0).sum()
    prev = age0
    for f in range(2, 41):
        pos, age = res[f]
        assert len(age) == len(prev) and np.allclose(pos, res[1][0])        # the state points never move
        cov, pcov = age >= 0, prev >= 0
        assert np.all(cov[pcov]), f"frame {f}: a covered point was uncovered"
        assert np.all(age[pcov] >= prev[pcov] - 1e-6), f"frame {f}: an age decreased"
        prev = age
    assert (prev >= 0).sum() > 10 * 3, (prev >= 0).sum()


def test_front_speed_proportional_to_growth_speed_and_frame_rate_independent():
    """On a plane the covered radius after t seconds is about Growth Speed x (t + head start), doubles with the
    speed, and is the same at 24 and 48 fps."""
    vs, fs = _patch(-3, 3, -3, 3, 30, dip=0.002)
    t = 1.5
    radii = {}
    for speed, fps in ((0.2, 24), (0.4, 24), (0.4, 48)):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        ob = _mesh("Plane", vs, fs)
        f = 1 + round(t * fps)
        res = _grow(ob, {"Seeds": 1, "Seed Height Bias": 1.0, "Patchiness": 0.0, "Upward Bias": 0.0,
                         "Growth Speed": speed, "Spread Radius": 0.12}, [f], fps)
        radii[(speed, fps)] = _front_radius(*res[f])
    want = 0.4 * (t + 0.25)
    assert 0.8 * want < radii[(0.4, 24)] <= 1.02 * want, (radii, want)
    ratio = radii[(0.4, 24)] / radii[(0.2, 24)]
    assert abs(ratio - 2.0) < 0.2, (radii, ratio)
    assert abs(radii[(0.4, 48)] / radii[(0.4, 24)] - 1.0) < 0.05, radii


def test_spread_radius_stops_at_wider_gaps():
    """Two patches 0.3 apart: the growth crosses the gap with Spread Radius 0.45, never with 0.2."""
    va, fa = _patch(-1.6, -0.15, -0.7, 0.7, 14, dip=0.002)
    vb, fb = _patch(0.15, 1.6, -0.7, 0.7, 14, z=0.01)
    vs = va + vb
    fs = fa + [tuple(i + len(va) for i in f) for f in fb]
    covered_b = {}
    for radius in (0.2, 0.45):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        ob = _mesh("Two Patches", vs, fs)
        res = _grow(ob, {"Seeds": 1, "Seed Height Bias": 1.0, "Patchiness": 0.0, "Upward Bias": 0.0,
                         "Growth Speed": 0.8, "Spread Radius": radius}, [96])
        pos, age = res[96]
        a_side, b_side = pos[:, 0] < 0, pos[:, 0] > 0
        assert np.all(age[a_side] >= 0), (radius, (age[a_side] < 0).sum())  # patch A fully grown either way
        covered_b[radius] = float((age[b_side] >= 0).mean())
    assert covered_b[0.2] == 0.0 and covered_b[0.45] > 0.95, covered_b


def test_seed_changes_the_pattern():
    """Different Seed values give different state points and different covered sets."""
    out = []
    for seed in (0, 1):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        ob = nkt.ico(1.0, 4)
        out.append(_grow(ob, {"Seed": seed, "Seeds": 3}, [30])[30])
    (p0, a0), (p1, a1) = out
    assert len(a0) != len(a1) or not np.allclose(p0, p1)
    s0 = p0[a0 >= 0].mean(axis=0)
    s1 = p1[a1 >= 0].mean(axis=0)
    assert np.linalg.norm(s0 - s1) > 0.05, (s0, s1)


def test_vines_stay_on_the_surface():
    """Vine stem vertices on a unit sphere lie within Lift +- Thickness of the surface at every sampled frame."""
    tpl = _template()
    mats = tpl.build_materials()
    group = tpl.build_growth(mats)
    ob = nkt.ico(1.0, 5)
    sc = bpy.context.scene
    sc.render.fps, sc.frame_start, sc.frame_end = 24, 1, 100
    mod = ob.modifiers.new("Growth", "NODES")
    mod.node_group = group
    thick = 0.011
    inspect.set_modifier_inputs(mod, {"Moss Amount": 0.0, "Show Surface": False, "Thickness": thick,
                                      "Leaf Size": 0.0, "Blossom Share": 0.0, "Seeds": 4})
    lift = thick * 1.1
    for f in range(1, 61):
        sc.frame_set(f)
        if f % 20:
            continue
        ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        slot = [i for i, s in enumerate(ev.material_slots) if s.material and s.material.name == "Growth Vine"]
        vids = {v for p in me.polygons if p.material_index in slot for v in p.vertices}
        r = np.array([me.vertices[i].co.length for i in vids])
        ev.to_mesh_clear()
        assert len(r) > 100, (f, len(r))
        assert np.all(r > 1.0 + lift - thick - 0.004) and np.all(r < 1.0 + lift + thick + 0.004), (f, r.min(), r.max())
