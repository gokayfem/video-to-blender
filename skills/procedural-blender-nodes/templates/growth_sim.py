"""Moss and flowering vines creeping over any mesh, grown by a simulation zone.

    blender -b --factory-startup --python templates/growth_sim.py -- --out growth.blend
        [--render growth.png] [--width 960] [--samples 16] [--frame 100] [--scene Statue]
        [--strip out/dir --strip-frames 1,30,60,90,120] [--bake]

The top group "Growth" goes on any mesh object as a Geometry Nodes modifier. Its simulation zone holds the state
that makes this an accumulation effect, not an analytic one:

- a Poisson point set on the surface, each point with an arrival age `nk_age` (-1 = not reached). Each step the
  covered points age by Delta Time and the front captures uncovered points within Spread Radius of a covered
  one, at a sub-step arrival time `age_j - d / v` (v = Growth Speed x patchiness x upward bias), so the front
  moves at Growth Speed whatever the frame rate;
- vine tips (`nk_dir`, `nk_vine`, `nk_tage`) that crawl along the surface (steered by noise and Upward Bias,
  projected onto the tangent plane, snapped back with Sample Nearest Surface), branch at Branch Rate per second
  and die after Vine Life, leaving a trail of points stamped with their birth time.

After the zone the visible geometry is derived from the state: moss tufts scattered on the surface whose size
and colour follow the local coverage (young moss is yellow-green, mature moss dark), a moss stain `nk_moss` on
the input mesh for its material, vine tubes from the trails (thicker where older), NK Leaf leaves that unfurl
after Leaf Delay, and NK Blossom flowers that bud and open Bloom Time after their spot was reached.

Simulation zones only advance when frames are stepped in order from the start frame (a jump moves one step).
This script therefore steps every frame from 1 to the render frame before rendering, or bakes the zone with
`--bake` (packed into the .blend, so any frame then renders directly). Re-bake after changing any control that
feeds the zone (everything in Primary, Spread and Vines).
"""
import argparse, math, pathlib, sys, time

SKILL = pathlib.Path(__file__).resolve().parents[1]
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

import bpy
from nodekit.graph import Graph
from nodekit import scene as nks, inspect
from library.shapes import leaf, blossom
from library.scatter import scatter_on_surface
from library.materials import make_material, attribute_tint, felt, wood_grain, stone, terracotta, lin

TAU = 2.0 * math.pi
FPS = 24
FRAMES = (1, 120)


# ---- small node idioms (python helpers, not groups) ------------------------------------------------------------
def _attr(g, name, dt="FLOAT"):
    return g.node("GeometryNodeInputNamedAttribute", props={"data_type": dt}, Name=name)["Attribute"]


def _store(g, geo, name, value, dt="FLOAT", domain="POINT", sel=None):
    n = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": dt, "domain": domain},
               Geometry=geo, Name=name, Value=value)
    if sel is not None:
        g.connect(sel, n.i("Selection"))
    return n["Geometry"]


def _rand(g, lo, hi, seed, k, ident=None, dt="FLOAT"):
    n = g.node("FunctionNodeRandomValue", props={"data_type": dt}, Min=lo, Max=hi,
               Seed=g.math("ADD", seed, float(k)))
    if ident is not None:
        g.connect(ident, n.i("ID"))
    return n["Value"]


def _chance(g, p, seed, k, ident=None):
    n = g.node("FunctionNodeRandomValue", props={"data_type": "BOOLEAN"}, Probability=p,
               Seed=g.math("ADD", seed, float(k)))
    if ident is not None:
        g.connect(ident, n.i("ID"))
    return n["Value"]


def _cmp(g, op, a, b):
    return g.node("FunctionNodeCompare", props={"data_type": "FLOAT", "operation": op}, A=a, B=b)["Result"]


def _and(g, *xs):
    out = xs[0]
    for x in xs[1:]:
        n = g.node("FunctionNodeBooleanMath", props={"operation": "AND"}, Boolean=out)
        g.connect(x, n.i("Boolean#1"))
        out = n["Boolean"]
    return out


def _switch(g, kind, cond, false, true):
    n = g.node("GeometryNodeSwitch", props={"input_type": kind}, Switch=cond)
    g.connect(false, n.i("False"))
    g.connect(true, n.i("True"))
    return n["Output"]


def _join(g, *geos):
    j = g.node("GeometryNodeJoinGeometry")
    for x in reversed(geos):          # the multi-input socket stacks the newest link first
        g.connect(x, j.i("Geometry"))
    return j["Geometry"]


def _sample(g, geo, value, index, dt="FLOAT"):
    return g.node("GeometryNodeSampleIndex", props={"data_type": dt, "domain": "POINT"},
                  Geometry=geo, Value=value, Index=index)["Value"]


def _surface(g, mesh, value, pos, dt="FLOAT_VECTOR"):
    return g.node("GeometryNodeSampleNearestSurface", props={"data_type": dt}, Mesh=mesh, Value=value,
                  **{"Sample Position": pos})["Value"]


def _smooth01(g, x, a, b):
    return g.map_range(x, a, b, 0.0, 1.0, interp="SMOOTHSTEP")["Result"]


def _pos(g):
    return g.node("GeometryNodeInputPosition")["Position"]


def _local_age(g, state, speed, pos):
    """Arrival age at an arbitrary position: the nearest covered state point's age minus the travel time from it
    (d / v). Negative where the front has not arrived. Returns the age field."""
    covered = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=state,
                     Selection=_cmp(g, "GREATER_EQUAL", _attr(g, "nk_age"), 0.0))["Selection"]
    idx = g.node("GeometryNodeSampleNearest", props={"domain": "POINT"}, Geometry=covered,
                 **{"Sample Position": pos})["Index"]
    pj = _sample(g, covered, _pos(g), idx, "FLOAT_VECTOR")
    aj = _sample(g, covered, _attr(g, "nk_age"), idx)
    vj = g.math("MULTIPLY", speed, _sample(g, covered, _attr(g, "nk_speed"), idx))
    d = g.vmath("DISTANCE", pos, pj)["Value"]
    age = g.math("SUBTRACT", aj, g.math("DIVIDE", d, g.math("MAXIMUM", vj, 1e-4)))
    has = _cmp(g, "GREATER_THAN", g.node("GeometryNodeAttributeDomainSize", props={"component": "POINTCLOUD"},
                                         Geometry=covered)["Point Count"], 0.5)
    return _switch(g, "FLOAT", has, -1.0, age)


# ---- part groups ----------------------------------------------------------------------------------------------
def build_sample_points():
    g = Graph("Growth Sample Points", description="The simulation's state points: a Poisson set on the surface "
              "Point Spacing apart, each with a static speed factor nk_speed (patchy noise) and an arrival age "
              "nk_age that is the head start for the Seeds lowest-ranked points and -1 (not reached) elsewhere. "
              "Ranking mixes randomness with height, so Seed Height Bias 1 starts growth at the bottom")
    surf = g.input("Surface", "GEOMETRY", desc="Mesh the growth covers")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed for the points, patches and seed choice")
    spacing = g.input("Point Spacing", "FLOAT", 0.04, min=0.005, max=10.0, subtype="DISTANCE",
                      desc="Distance between state points; smaller is finer and slower")
    seeds = g.input("Seeds", "INT", 5, min=0, max=10000, desc="Number of points where growth starts")
    hbias = g.input("Seed Height Bias", "FLOAT", 0.7, min=0.0, max=1.0, subtype="FACTOR",
                    desc="0 seeds anywhere, 1 seeds at the lowest points of the mesh")
    patch = g.input("Patchiness", "FLOAT", 0.5, min=0.0, max=0.95, subtype="FACTOR",
                    desc="Spread speed varies by +- this share in soft patches, so the front is ragged")
    head = g.input("Head Start", "FLOAT", 0.25, min=0.0, max=10.0, subtype="TIME",
                   desc="Age the seed points start with (seconds), so they show at the first frame")
    with g.frame("Poisson points Point Spacing apart on the surface"):
        dens = g.math("DIVIDE", 4.0, g.math("MULTIPLY", spacing, spacing))
        dist = g.node("GeometryNodeDistributePointsOnFaces", props={"distribute_method": "POISSON"}, Mesh=surf,
                      Seed=seed, **{"Distance Min": spacing, "Density Max": dens})
        pts = _store(g, dist["Points"], "nk_normal", dist["Normal"], "FLOAT_VECTOR")
    with g.frame("Patchy speed factor from soft noise"):
        nz = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Vector=_pos(g), W=seed, Scale=2.5,
                    Detail=2.0)["Factor"]
        speed = g.map_range(nz, 0.3, 0.7, g.math("SUBTRACT", 1.0, patch), g.math("ADD", 1.0, patch))["Result"]
        pts = _store(g, pts, "nk_speed", speed)
    with g.frame("Rank by randomness mixed with height; the first Seeds points start covered"):
        bb = g.node("GeometryNodeBoundBox", Geometry=pts)
        zmin, zmax = g.separate(bb["Min"])["Z"], g.separate(bb["Max"])["Z"]
        h = g.math("DIVIDE", g.math("SUBTRACT", g.separate(_pos(g))["Z"], zmin),
                   g.math("MAXIMUM", g.math("SUBTRACT", zmax, zmin), 1e-6))
        key = g.mix(hbias, _rand(g, 0.0, 1.0, seed, 3), h)["Result"]
        pts = g.node("GeometryNodeSortElements", props={"domain": "POINT"}, Geometry=pts,
                     **{"Sort Weight": key})["Geometry"]
        is_seed = _cmp(g, "LESS_THAN", g.node("GeometryNodeInputIndex")["Index"], seeds)
        pts = _store(g, pts, "nk_age", _switch(g, "FLOAT", is_seed, -1.0, head))
    g.output("Points", "GEOMETRY", pts, desc="State points (nk_age, nk_speed, nk_normal), seeds first")
    return g.finish()


def build_spread_pass():
    g = Graph("Growth Spread Pass", description="One pass of the front: every uncovered point within Spread "
              "Radius of its nearest covered point is captured if the front has had time to travel there, with "
              "the arrival age age_j - d / v (v = Growth Speed x nk_speed x upward factor). Arrival ages are "
              "continuous, so the front speed does not depend on the step length")
    pts = g.input("Points", "GEOMETRY", desc="State points with nk_age (-1 = not reached) and nk_speed")
    speed = g.input("Growth Speed", "FLOAT", 0.3, min=0.0, max=100.0, subtype="DISTANCE",
                    desc="Front speed in metres per second")
    radius = g.input("Spread Radius", "FLOAT", 0.1, min=0.0, max=100.0, subtype="DISTANCE",
                     desc="Longest jump from a covered point to a new one; wider gaps stop the growth")
    up = g.input("Upward Bias", "FLOAT", 0.5, min=-1.0, max=1.0, subtype="FACTOR",
                 desc="Faster upwards (positive) or downwards (negative): v x (1 + bias x direction z)")
    with g.frame("Nearest covered point: its position and age"):
        covered = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=pts,
                         Selection=_cmp(g, "GREATER_EQUAL", _attr(g, "nk_age"), 0.0))["Selection"]
        count = g.node("GeometryNodeAttributeDomainSize", props={"component": "POINTCLOUD"}, Geometry=covered)
        idx = g.node("GeometryNodeSampleNearest", props={"domain": "POINT"}, Geometry=covered,
                     **{"Sample Position": _pos(g)})["Index"]
        pj = _sample(g, covered, _pos(g), idx, "FLOAT_VECTOR")
        aj = _sample(g, covered, _attr(g, "nk_age"), idx)
    with g.frame("Arrival age: travel time d / v with the upward factor"):
        delta = g.vmath("SUBTRACT", _pos(g), pj)["Vector"]
        d = g.vmath("LENGTH", delta)["Value"]
        dirz = g.math("DIVIDE", g.separate(delta)["Z"], g.math("MAXIMUM", d, 1e-6))
        upf = g.math("MAXIMUM", g.math("MULTIPLY_ADD", up, dirz, 1.0), 0.15)
        v = g.math("MULTIPLY", g.math("MULTIPLY", speed, _attr(g, "nk_speed")), upf)
        cand = g.math("SUBTRACT", aj, g.math("DIVIDE", d, g.math("MAXIMUM", v, 1e-4)))
    with g.frame("Capture: not yet reached, within Spread Radius, front already there"):
        cap = _and(g, _cmp(g, "LESS_THAN", _attr(g, "nk_age"), 0.0), _cmp(g, "LESS_EQUAL", d, radius),
                   _cmp(g, "GREATER_EQUAL", cand, 0.0), _cmp(g, "GREATER_THAN", count["Point Count"], 0.5))
        out = _store(g, pts, "nk_age", cand, sel=cap)
    g.output("Points", "GEOMETRY", out, desc="State points with newly captured ages")
    return g.finish()


def build_vine_start():
    g = Graph("Growth Vine Start", description="The first vine tips: the first Count state points (the lowest "
              "ranked seeds), lifted off the surface, heading up the surface; each tip gets nk_vine (its "
              "curve id), nk_dir and nk_tage = 0. The trail starts with the same points")
    pts = g.input("Points", "GEOMETRY", desc="Ranked state points from Growth Sample Points")
    count = g.input("Count", "INT", 6, min=0, max=1000, desc="Number of vines that start")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed for the start directions")
    lift = g.input("Lift", "FLOAT", 0.012, min=0.0, max=1.0, subtype="DISTANCE",
                   desc="Height of the vine axis above the surface")
    with g.frame("Take the first Count points"):
        tips = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=pts,
                      Selection=_cmp(g, "LESS_THAN", g.node("GeometryNodeInputIndex")["Index"], count))["Selection"]
    with g.frame("Heading: up the surface plus a random sideways lean, in the tangent plane"):
        n = _attr(g, "nk_normal", "FLOAT_VECTOR")
        upv = g.vmath("SUBTRACT", (0.0, 0.0, 1.0), g.vmath("SCALE", n, scale=g.separate(n)["Z"]))["Vector"]
        side = g.vmath("CROSS_PRODUCT", n, (0.0, 0.0, 1.0))["Vector"]
        dirv = g.vmath("ADD", upv, g.vmath("SCALE", side, scale=_rand(g, -0.8, 0.8, seed, 21))["Vector"])["Vector"]
        dirv = g.vmath("NORMALIZE", dirv)["Vector"]
        tips = g.node("GeometryNodeSetPosition", Geometry=tips, Offset=g.vmath("SCALE", n, scale=lift))["Geometry"]
        tips = _store(g, tips, "nk_dir", dirv, "FLOAT_VECTOR")
        tips = _store(g, tips, "nk_vine", g.node("GeometryNodeInputIndex")["Index"], "INT")
        tips = _store(g, tips, "nk_tage", 0.0)
        tips = _store(g, tips, "nk_birth", 0.0)
        for name in ("nk_age", "nk_speed", "nk_normal"):
            tips = g.node("GeometryNodeRemoveAttribute", Geometry=tips, Name=name)["Geometry"]
    g.output("Tips", "GEOMETRY", tips, desc="Vine tips")
    return g.finish()


def build_vine_step():
    g = Graph("Growth Vine Step", description="One step of the vines: tips age and die after Vine Life, branch "
              "with probability Branch Rate x dt (a copy turned by Branch Angle, a new nk_vine id from a hash of "
              "the parent and the step), steer by noise and Upward Bias in the surface's tangent plane, advance "
              "Speed x dt and snap back onto the surface. Trail points (nk_vine, nk_birth) are stamped where "
              "branches start and where every tip arrives")
    tips = g.input("Tips", "GEOMETRY", desc="Vine tips with nk_dir, nk_vine, nk_tage")
    trail = g.input("Trail", "GEOMETRY", desc="Trail points so far")
    surf = g.input("Surface", "GEOMETRY", desc="Mesh the vines crawl on")
    t = g.input("Time", "FLOAT", 0.0, min=0.0, max=100000.0, subtype="TIME", desc="Simulated time before this step")
    dt = g.input("Delta Time", "FLOAT", 1.0 / FPS, min=0.0, max=10.0, subtype="TIME", desc="Step length (seconds)")
    step = g.input("Step", "INT", 0, min=0, max=10000000, desc="Step counter, seeds the per-step random choices")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    speed = g.input("Speed", "FLOAT", 0.4, min=0.0, max=100.0, subtype="DISTANCE", desc="Tip speed, metres per second")
    wander = g.input("Wander", "FLOAT", 3.0, min=0.0, max=100.0, desc="Random steering strength (per second)")
    up = g.input("Upward Bias", "FLOAT", 0.5, min=-1.0, max=1.0, subtype="FACTOR",
                 desc="Steering towards up the surface (negative: down)")
    rate = g.input("Branch Rate", "FLOAT", 0.6, min=0.0, max=100.0, subtype="FREQUENCY",
                   desc="Branches per tip per second")
    angle = g.input("Branch Angle", "FLOAT", 0.7, min=0.0, max=math.pi, subtype="ANGLE",
                    desc="Turn of a new branch from its parent")
    life = g.input("Vine Life", "FLOAT", 3.0, min=0.0, max=1000.0, subtype="TIME", desc="Seconds a tip grows")
    maxt = g.input("Max Tips", "INT", 40, min=0, max=100000, desc="No branching once this many tips grow")
    lift = g.input("Lift", "FLOAT", 0.012, min=0.0, max=1.0, subtype="DISTANCE",
                   desc="Height of the vine axis above the surface")
    t1 = g.math("ADD", t, dt)
    with g.frame("Age the tips; tips older than Vine Life stop"):
        tips = _store(g, tips, "nk_tage", g.math("ADD", _attr(g, "nk_tage"), dt))
        tips = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=tips,
                      Selection=_cmp(g, "GREATER_THAN", _attr(g, "nk_tage"), life))["Geometry"]
    with g.frame("Branch: copies of some tips, turned by +- Branch Angle, with new ids"):
        count = g.node("GeometryNodeAttributeDomainSize", props={"component": "POINTCLOUD"}, Geometry=tips)["Point Count"]
        vid = _attr(g, "nk_vine", "INT")
        pick = _and(g, _chance(g, g.math("MULTIPLY", rate, dt), g.math("ADD", step, g.math("MULTIPLY", seed, 7919.0)),
                               31, vid), _cmp(g, "LESS_THAN", count, maxt))
        dup = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=tips, Selection=pick,
                     Amount=1)["Geometry"]
        nrm = g.vmath("NORMALIZE", _surface(g, surf, g.node("GeometryNodeInputNormal")["Normal"], _pos(g)))["Vector"]
        sgn = g.math("SUBTRACT", g.math("MULTIPLY", _rand(g, 0, 1, step, 37, vid, "INT"), 2.0), 1.0)
        turned = g.node("ShaderNodeVectorRotate", props={"rotation_type": "AXIS_ANGLE"},
                        Vector=_attr(g, "nk_dir", "FLOAT_VECTOR"), Axis=nrm, Angle=g.math("MULTIPLY", angle, sgn))
        dup = _store(g, dup, "nk_dir", turned["Vector"], "FLOAT_VECTOR")
        newid = g.node("FunctionNodeHashValue", props={"data_type": "INT"}, Value=vid,
                       Seed=g.math("ADD", step, g.math("MULTIPLY", seed, 7919.0)))["Hash"]
        dup = _store(g, dup, "nk_vine", newid, "INT")
        dup = _store(g, dup, "nk_tage", 0.0)
        dup = _store(g, dup, "nk_birth", t)
        tips = _join(g, tips, dup)
    with g.frame("Steer: noise and up, kept in the tangent plane of the surface"):
        n = g.vmath("NORMALIZE", _surface(g, surf, g.node("GeometryNodeInputNormal")["Normal"], _pos(g)))["Vector"]
        w = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Vector=_pos(g), Scale=4.0, Detail=1.0,
                   W=g.math("ADD", g.math("MULTIPLY", t, 0.7), g.math("MULTIPLY", g.math("MODULO", vid, 997.0), 1.37)))
        wv = g.vmath("SCALE", g.vmath("SUBTRACT", w["Color"], (0.5, 0.5, 0.5)), scale=g.math("MULTIPLY", wander, 2.0))
        steer = g.vmath("ADD", wv, g.vmath("SCALE", (0.0, 0.0, 1.0), scale=g.math("MULTIPLY", up, 4.0)))
        d = g.vmath("ADD", _attr(g, "nk_dir", "FLOAT_VECTOR"), g.vmath("SCALE", steer, scale=dt))["Vector"]
        d = g.vmath("SUBTRACT", d, g.vmath("SCALE", n, scale=g.vmath("DOT_PRODUCT", d, n)["Value"]))["Vector"]
        d = g.vmath("NORMALIZE", d)["Vector"]
    with g.frame("Advance Speed x dt and snap back onto the surface, Lift above it"):
        p = g.vmath("ADD", _pos(g), g.vmath("SCALE", d, scale=g.math("MULTIPLY", speed, dt)))["Vector"]
        q = _surface(g, surf, _pos(g), p)
        n2 = g.vmath("NORMALIZE", _surface(g, surf, g.node("GeometryNodeInputNormal")["Normal"], p))["Vector"]
        moved = _store(g, tips, "nk_dir", d, "FLOAT_VECTOR")
        moved = g.node("GeometryNodeSetPosition", Geometry=moved,
                       Position=g.vmath("ADD", q, g.vmath("SCALE", n2, scale=lift)))["Geometry"]
    with g.frame("Trail: stamp the branch starts and the new tip positions"):
        stamp = _store(g, moved, "nk_birth", t1)
        add = _join(g, dup, stamp)
        add = g.node("GeometryNodeRemoveAttribute", Geometry=add, **{"Pattern Mode": "Wildcard"},
                     Name="nk_[dt]*")["Geometry"]
        trail = _join(g, trail, add)
    g.output("Tips", "GEOMETRY", moved, desc="Tips after the step")
    g.output("Trail", "GEOMETRY", trail, desc="Trail with this step's points")
    return g.finish()


def build_bloom_heads(blossom_tree):
    g = Graph("Growth Bloom Heads", description="Four NK Blossom heads of unit size from a closed bud to a wide "
              "open flower, as instances 0..3 for Pick Instance by bloom stage")
    petals = g.input("Petals", "INT", 5, min=1, max=64, desc="Petals per flower")
    stages = [(1.35, 0.55, 0.6), (0.95, 0.45, 0.8), (0.5, 0.35, 0.95), (0.15, 0.3, 1.0)]
    with g.frame("Bud, half open, open, wide open"):
        gi = g.node("GeometryNodeGeometryToInstance")
        heads = [g.group(blossom_tree, Petals=petals, Size=s, Cup=c, **{"Centre Size": ctr,
                                                                          "Petal Width": 0.7})
                 for c, ctr, s in stages]
        for h in reversed(heads):
            g.connect(h["Mesh"], gi.i("Geometry"))
    g.output("Heads", "GEOMETRY", gi["Instances"], desc="Instances 0 (bud) to 3 (open)")
    return g.finish()


def build_tuft(leaf_tree):
    g = Graph("Growth Moss Tuft", description="One moss tuft of unit radius: a ring of narrow NK Leaf fronds rising "
              "from a low dome, like a cushion of star moss; base at the origin, growing along +Z")
    fronds = g.input("Fronds", "INT", 6, min=1, max=64, desc="Fronds around the tuft")
    rise = g.input("Rise", "FLOAT", 0.9, min=0.0, max=1.5, subtype="ANGLE", desc="Frond angle up from the surface")
    with g.frame("Fronds: narrow leaves in a ring, tipped up by Rise"):
        ring = g.node("GeometryNodePoints", Count=fronds)["Points"]
        idx = g.node("GeometryNodeInputIndex")["Index"]
        ang = g.math("MULTIPLY", g.math("DIVIDE", idx, fronds), TAU)
        rot = g.node("FunctionNodeEulerToRotation", Euler=g.combine(0.0, g.math("MULTIPLY", rise, -1.0), ang))
        blade = g.group(leaf_tree, Length=1.0, Width=0.3, Fold=0.5, Curl=-0.1, Resolution=2)
        fr = g.node("GeometryNodeInstanceOnPoints", Points=ring, Instance=blade, Rotation=rot["Rotation"],
                    Scale=_rand(g, 0.7, 1.15, 0, 1))["Instances"]
        fr = g.node("GeometryNodeRealizeInstances", Geometry=fr)["Geometry"]
    with g.frame("Core: a low dome the fronds rise from"):
        ico = g.node("GeometryNodeMeshUVSphere", Segments=6, Rings=3, Radius=0.45)["Mesh"]
        core = g.node("GeometryNodeTransform", Geometry=ico, Translation=(0.0, 0.0, -0.1),
                      Scale=(1.0, 1.0, 0.6))["Geometry"]
        core = g.node("GeometryNodeSetShadeSmooth", Mesh=core)["Mesh"]
    g.output("Mesh", "GEOMETRY", _join(g, core, fr), desc="The tuft")
    return g.finish()


def build_moss(heads_tree, tuft_tree):
    g = Graph("Growth Moss", description="Moss from the state: tufts scattered on the surface (NK Scatter On "
              "Surface) kept and scaled by the local coverage, coloured from young yellow-green to mature dark "
              "green by age; tiny flowers on some state points opening Bloom Time after the front passed; and "
              "nk_moss on the input mesh for its material to stain under the moss")
    surf = g.input("Surface", "GEOMETRY", desc="The input mesh")
    state = g.input("State", "GEOMETRY", desc="State points with nk_age and nk_speed")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    speed = g.input("Growth Speed", "FLOAT", 0.3, min=0.0, max=100.0, subtype="DISTANCE",
                    desc="Front speed (m/s), to extrapolate ages between state points")
    amount = g.input("Moss Amount", "FLOAT", 1.0, min=0.0, max=2.0, subtype="FACTOR",
                     desc="Scales tuft density and size; 0 no moss")
    density = g.input("Moss Density", "FLOAT", 900.0, min=0.0, max=100000.0, desc="Tufts per square metre")
    size = g.input("Tuft Size", "FLOAT", 0.035, min=0.0, max=10.0, subtype="DISTANCE", desc="Mature tuft radius")
    mature = g.input("Mature Time", "FLOAT", 1.0, min=0.01, max=100.0, subtype="TIME",
                     desc="Seconds for a tuft to grow to full size")
    young = g.input("Young Color", "COLOR", lin("#9DB043"), desc="Colour of fresh moss at the front")
    old = g.input("Mature Color", "COLOR", lin("#3F5A1E"), desc="Colour of mature moss")
    stain = g.input("Stain", "FLOAT", 0.85, min=0.0, max=1.0, subtype="FACTOR",
                    desc="nk_moss written on the input mesh (its material darkens and greens by it)")
    mat = g.input("Moss Material", "MATERIAL", desc="Material of the tufts (reads nk_color, nk_rand)")
    fshare = g.input("Flower Share", "FLOAT", 0.08, min=0.0, max=1.0, subtype="FACTOR",
                     desc="Share of state points that grow a tiny flower")
    fsize = g.input("Flower Size", "FLOAT", 0.03, min=0.0, max=10.0, subtype="DISTANCE", desc="Moss flower diameter")
    bloom = g.input("Bloom Time", "FLOAT", 1.5, min=0.0, max=100.0, subtype="TIME",
                    desc="Seconds after the front passes before flowers start to open")
    bdur = g.input("Bloom Duration", "FLOAT", 1.0, min=0.01, max=100.0, subtype="TIME",
                   desc="Seconds from bud to open flower")
    fcol = g.input("Flower Color", "COLOR", lin("#F4EEDC"), desc="Moss flower colour")
    heads = g.input("Heads", "GEOMETRY", desc="Bloom stage instances 0..3 (Growth Bloom Heads)")
    bmat = g.input("Blossom Material", "MATERIAL", desc="Material of the flowers")
    with g.frame("Tufts: scatter on the surface, aligned to it"):
        tuft = g.group(tuft_tree)
        sc = g.group(scatter_on_surface(), Surface=surf, Instance=tuft, Seed=seed, Align=1.0,
                     Density=g.math("MULTIPLY", density, g.math("MINIMUM", amount, 1.0)),
                     **{"Scale Min": 0.6, "Scale Max": 1.4, "Random Tilt": 0.3})
    with g.frame("Coverage at each tuft from the state; keep covered tufts, size and colour by age"):
        age = _local_age(g, state, speed, _pos(g))
        cov = _smooth01(g, age, 0.0, mature)
        mdens = g.math("MULTIPLY", density, g.math("MINIMUM", amount, 1.0))
        # NK Scatter On Surface warns (nk_normal missing) when it distributes nothing: skip it lazily at 0
        tufts = _switch(g, "GEOMETRY", _cmp(g, "GREATER_THAN", mdens, 0.0), None, sc["Instances"])
        ins = g.node("GeometryNodeDeleteGeometry", props={"domain": "INSTANCE"}, Geometry=tufts,
                     Selection=_cmp(g, "LESS_EQUAL", cov, 0.02))["Geometry"]
        k = g.math("MULTIPLY", g.math("MULTIPLY", size, g.math("POWER", cov, 0.7)), g.math("MAXIMUM", amount, 0.0))
        ins = g.node("GeometryNodeScaleInstances", Instances=ins, Scale=g.combine(k, k, k))["Instances"]
        ripe = _smooth01(g, age, 0.0, g.math("MULTIPLY", mature, 3.0))
        ins = _store(g, ins, "nk_color", g.mix(ripe, young, old, data_type="RGBA")["Result"], "FLOAT_COLOR",
                     "INSTANCE")
        ins = g.node("GeometryNodeSetMaterial", Geometry=ins, Material=mat)["Geometry"]
    with g.frame("Moss flowers on some state points, opening Bloom Time after the front"):
        fpts = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=state,
                      Selection=_chance(g, fshare, seed, 41))["Selection"]
        stage = g.map_range(_attr(g, "nk_age"), bloom, g.math("ADD", bloom, bdur), 0.0, 1.0)["Result"]
        fpts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=fpts,
                      Selection=_cmp(g, "LESS_EQUAL", stage, 0.0))["Geometry"]
        n = _attr(g, "nk_normal", "FLOAT_VECTOR")
        fpts = g.node("GeometryNodeSetPosition", Geometry=fpts,
                      Offset=g.vmath("SCALE", n, scale=g.math("MULTIPLY", size, 0.45)))["Geometry"]
        rot = g.node("FunctionNodeAlignRotationToVector", props={"axis": "Z", "pivot_axis": "AUTO"}, Vector=n)
        fs = g.math("MULTIPLY", fsize, g.math("MULTIPLY_ADD", stage, 0.6, 0.4))
        fl = g.node("GeometryNodeInstanceOnPoints", Points=fpts, Instance=heads, Rotation=rot["Rotation"],
                    Scale=fs, **{"Pick Instance": True,
                                 "Instance Index": g.math("FLOOR", g.math("MULTIPLY", stage, 3.999))})["Instances"]
        fl = _store(g, fl, "nk_color", fcol, "FLOAT_COLOR", "INSTANCE")
        fl = g.node("GeometryNodeSetMaterial", Geometry=fl, Material=bmat)["Geometry"]
    with g.frame("Stain: nk_moss on the input mesh"):
        sage = _local_age(g, state, speed, _pos(g))
        smesh = _store(g, surf, "nk_moss", g.math("MULTIPLY", _smooth01(g, sage, -0.2, g.math("MULTIPLY", mature, 2.0)),
                                                   g.math("MULTIPLY", stain, g.math("MINIMUM", amount, 1.0))))
    g.output("Moss", "GEOMETRY", _join(g, ins, fl), desc="Tuft and flower instances")
    g.output("Surface", "GEOMETRY", smesh, desc="The input mesh with nk_moss")
    return g.finish()


def build_vines(leaf_tree, heads_tree):
    g = Graph("Growth Vines", description="Vines from the trail: one curve per nk_vine ordered by birth time, "
              "a tube thicker where older; NK Leaf leaves along it, alternating sides, that unfurl Leaf Delay "
              "after the tip passed; flowers on some leaf nodes that bud and open Bloom Time after it")
    trail = g.input("Trail", "GEOMETRY", desc="Trail points with nk_vine and nk_birth")
    surf = g.input("Surface", "GEOMETRY", desc="The mesh the vines crawl on (for leaf orientation)")
    t = g.input("Time", "FLOAT", 0.0, min=0.0, max=100000.0, subtype="TIME", desc="Simulated time now")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    thick = g.input("Thickness", "FLOAT", 0.012, min=0.0, max=1.0, subtype="DISTANCE", desc="Radius of old stems")
    vmat = g.input("Vine Material", "MATERIAL", desc="Stem material")
    lsize = g.input("Leaf Size", "FLOAT", 0.07, min=0.0, max=10.0, subtype="DISTANCE", desc="Grown leaf length")
    lspace = g.input("Leaf Spacing", "FLOAT", 0.045, min=0.005, max=10.0, subtype="DISTANCE",
                     desc="Distance between leaves along a stem")
    ldelay = g.input("Leaf Delay", "FLOAT", 0.25, min=0.0, max=100.0, subtype="TIME",
                     desc="Seconds after the tip passes before a leaf appears")
    lgrow = g.input("Leaf Grow", "FLOAT", 0.8, min=0.01, max=100.0, subtype="TIME", desc="Seconds to full leaf size")
    lcol = g.input("Leaf Color", "COLOR", lin("#3E6B23"), desc="Grown leaf colour (young leaves are paler)")
    lmat = g.input("Leaf Material", "MATERIAL", desc="Leaf material (reads nk_color, nk_rand)")
    bshare = g.input("Blossom Share", "FLOAT", 0.3, min=0.0, max=1.0, subtype="FACTOR",
                     desc="Share of leaf nodes that also flower")
    bsize = g.input("Blossom Size", "FLOAT", 0.06, min=0.0, max=10.0, subtype="DISTANCE", desc="Open flower diameter")
    bloom = g.input("Bloom Time", "FLOAT", 1.5, min=0.0, max=100.0, subtype="TIME",
                    desc="Seconds after the tip passes before flowers start to open")
    bdur = g.input("Bloom Duration", "FLOAT", 1.0, min=0.01, max=100.0, subtype="TIME", desc="Seconds bud to open")
    ca = g.input("Blossom Color A", "COLOR", lin("#E2577A"), desc="Main flower colour")
    cb = g.input("Blossom Color B", "COLOR", lin("#F2C4D0"), desc="Second flower colour")
    heads = g.input("Heads", "GEOMETRY", desc="Bloom stage instances 0..3 (Growth Bloom Heads)")
    bmat = g.input("Blossom Material", "MATERIAL", desc="Flower material")
    with g.frame("Curves: trail points joined per vine in birth order; arc length from the vine's start"):
        cu = g.node("GeometryNodePointsToCurves", Points=trail, **{"Curve Group ID": _attr(g, "nk_vine", "INT"),
                                                                   "Weight": _attr(g, "nk_birth")})["Curves"]
        spl = g.node("GeometryNodeSplineParameter")
        cu = _store(g, cu, "nk_s", spl["Length"])
        cu = _store(g, cu, "nk_k", spl["Index"], "INT")
    with g.frame("Stem tube: radius grows with age since the tip passed"):
        age = g.math("SUBTRACT", t, _attr(g, "nk_birth"))
        r = g.math("MULTIPLY", thick, g.math("MULTIPLY_ADD", g.math("SQRT", g.math("MINIMUM", g.math(
            "DIVIDE", g.math("MAXIMUM", age, 0.0), 2.5), 1.0)), 0.75, 0.25))
        prof = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=6, Radius=1.0)["Curve"]
        tube = g.node("GeometryNodeCurveToMesh", Curve=cu, Scale=r, **{"Profile Curve": prof, "Fill Caps": True})["Mesh"]
        tube = g.node("GeometryNodeSetShadeSmooth", Mesh=tube)["Mesh"]
        tube = g.node("GeometryNodeSetMaterial", Geometry=tube, Material=vmat)["Geometry"]
    with g.frame("Leaf nodes: the first trail point past every Leaf Spacing of arc length (fixed as the vine grows)"):
        lp = g.node("GeometryNodeCurveToPoints", props={"mode": "EVALUATED"}, Curve=cu)
        pts = _store(g, lp["Points"], "nk_tan", lp["Tangent"], "FLOAT_VECTOR")
        k = g.math("FLOOR", g.math("DIVIDE", _attr(g, "nk_s"), lspace))
        kprev = g.node("GeometryNodeFieldAtIndex", props={"data_type": "FLOAT", "domain": "POINT"}, Value=k,
                       Index=g.math("SUBTRACT", g.node("GeometryNodeInputIndex")["Index"], 1.0))["Value"]
        first = g.node("FunctionNodeCompare", props={"data_type": "INT", "operation": "EQUAL"},
                       A=_attr(g, "nk_k", "INT"), B=0)["Result"]
        node = g.node("FunctionNodeBooleanMath", props={"operation": "OR"}, Boolean=first)
        g.connect(_cmp(g, "GREATER_THAN", k, kprev), node.i("Boolean#1"))
        pts = _store(g, pts, "nk_side", g.math("MODULO", k, 2.0))
        pts = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=pts,
                     Selection=node["Boolean"])["Selection"]
        nid = g.node("FunctionNodeHashValue", props={"data_type": "INT"}, Value=_attr(g, "nk_vine", "INT"),
                     Seed=k)["Hash"]
        pts = _store(g, pts, "nk_id", nid, "INT")
        ident = _attr(g, "nk_id", "INT")
        n = g.vmath("NORMALIZE", _surface(g, surf, g.node("GeometryNodeInputNormal")["Normal"], _pos(g)))["Vector"]
        pts = _store(g, pts, "nk_n", n, "FLOAT_VECTOR")
    with g.frame("Leaf orientation: on the surface, alternating sides, tips lifted"):
        nn, tt = _attr(g, "nk_n", "FLOAT_VECTOR"), _attr(g, "nk_tan", "FLOAT_VECTOR")
        side = g.math("SUBTRACT", g.math("MULTIPLY", _attr(g, "nk_side"), 2.0), 1.0)
        sdir = g.vmath("ADD", g.vmath("SCALE", tt, scale=0.5),
                       g.vmath("SCALE", g.vmath("CROSS_PRODUCT", nn, tt), scale=side))["Vector"]
        r1 = g.node("FunctionNodeAlignRotationToVector", props={"axis": "Z", "pivot_axis": "AUTO"}, Vector=nn)
        r2 = g.node("FunctionNodeAlignRotationToVector", props={"axis": "X", "pivot_axis": "Z"},
                    Rotation=r1["Rotation"], Vector=sdir)
        lift = g.node("FunctionNodeEulerToRotation", Euler=g.combine(_rand(g, -0.3, 0.3, seed, 51, ident),
                                                                     _rand(g, -0.6, -0.15, seed, 52, ident), 0.0))
        lrot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=r2["Rotation"],
                      **{"Rotate By": lift["Rotation"]})["Rotation"]
        lage = g.math("SUBTRACT", g.math("SUBTRACT", t, _attr(g, "nk_birth")), ldelay)
    with g.frame("Leaves unfurl after Leaf Delay; young leaves paler"):
        grow = _smooth01(g, lage, 0.0, lgrow)
        lpts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=pts,
                      Selection=_cmp(g, "LESS_EQUAL", grow, 0.01))["Geometry"]
        blade = g.group(leaf_tree, Length=1.0, Width=0.6, Fold=0.25, Curl=0.12, Resolution=6)
        li = g.node("GeometryNodeInstanceOnPoints", Points=lpts, Instance=blade, Rotation=lrot,
                    Scale=g.math("MULTIPLY", g.math("MULTIPLY", lsize, grow), _rand(g, 0.7, 1.25, seed, 53, ident)))
        pale = g.mix(grow, g.vmath("ADD", g.vmath("SCALE", lcol, scale=0.6), (0.18, 0.22, 0.04)), lcol,
                     data_type="RGBA")["Result"]
        li = _store(g, li["Instances"], "nk_color", pale, "FLOAT_COLOR", "INSTANCE")
        li = _store(g, li, "nk_rand", _rand(g, 0.0, 1.0, seed, 54, ident), "FLOAT", "INSTANCE")
        li = g.node("GeometryNodeSetMaterial", Geometry=li, Material=lmat)["Geometry"]
    with g.frame("Flowers on some nodes: bud to open over Bloom Duration after Bloom Time"):
        bpts = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=pts,
                      Selection=_chance(g, bshare, seed, 61, ident))["Selection"]
        bage = g.math("SUBTRACT", g.math("SUBTRACT", t, _attr(g, "nk_birth")), bloom)
        stage = g.map_range(bage, 0.0, bdur, 0.0, 1.0)["Result"]
        bpts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=bpts,
                      Selection=_cmp(g, "LESS_EQUAL", stage, 0.0))["Geometry"]
        bpts = g.node("GeometryNodeSetPosition", Geometry=bpts,
                      Offset=g.vmath("SCALE", _attr(g, "nk_n", "FLOAT_VECTOR"),
                                     scale=g.math("MULTIPLY", thick, 1.2)))["Geometry"]
        brot = g.node("FunctionNodeAlignRotationToVector", props={"axis": "Z", "pivot_axis": "AUTO"},
                      Vector=g.vmath("ADD", _attr(g, "nk_n", "FLOAT_VECTOR"), g.node(
                          "FunctionNodeRandomValue", props={"data_type": "FLOAT_VECTOR"}, Min=(-0.35, -0.35, -0.35),
                          Max=(0.35, 0.35, 0.35), ID=ident, Seed=g.math("ADD", seed, 62.0))["Value"]))
        bi = g.node("GeometryNodeInstanceOnPoints", Points=bpts, Instance=heads, Rotation=brot["Rotation"],
                    Scale=g.math("MULTIPLY", g.math("MULTIPLY", bsize, g.math("MULTIPLY_ADD", stage, 0.55, 0.45)),
                                 _rand(g, 0.8, 1.2, seed, 63, ident)),
                    **{"Pick Instance": True,
                       "Instance Index": g.math("FLOOR", g.math("MULTIPLY", stage, 3.999))})["Instances"]
        col = g.mix(_chance(g, 0.3, seed, 64, ident), ca, cb, data_type="RGBA")["Result"]
        bi = _store(g, bi, "nk_color", col, "FLOAT_COLOR", "INSTANCE")
        bi = _store(g, bi, "nk_rand", _rand(g, 0.0, 1.0, seed, 65, ident), "FLOAT", "INSTANCE")
        bi = g.node("GeometryNodeSetMaterial", Geometry=bi, Material=bmat)["Geometry"]
    g.output("Vines", "GEOMETRY", _join(g, tube, li, bi), desc="Stem tubes, leaf and flower instances")
    return g.finish()


# ---- top group --------------------------------------------------------------------------------------------------
def build_growth(mats=None):
    """Build "Growth" and its part groups; ``mats`` maps Moss/Vine/Leaf/Blossom to materials (input defaults)."""
    mats = mats or {}
    lf, bl, sc_ = leaf(), blossom(), scatter_on_surface()
    sample, spread, vstart, vstep = build_sample_points(), build_spread_pass(), build_vine_start(), build_vine_step()
    heads_t = build_bloom_heads(bl)
    moss_t, vines_t = build_moss(heads_t, build_tuft(lf)), build_vines(lf, heads_t)
    g = Graph("Growth", modifier=True, description="Moss and flowering vines that creep over any mesh from seed "
              "points, grown by a simulation zone (state: covered points with arrival ages, vine tips and their "
              "trails). Frame-rate independent (Delta Time); step frames in order from the start or bake")
    geo = g.input("Geometry", "GEOMETRY", desc="The mesh to grow over")
    P = "Primary"
    seed = g.input("Seed", "INT", 0, min=0, max=100000, panel=P, desc="Random seed: seed points, patches, vines")
    speed = g.input("Growth Speed", "FLOAT", 0.55, min=0.0, max=10.0, subtype="DISTANCE", panel=P,
                    desc="How fast the moss front spreads, metres per second (vines move Vine Speed x this)")
    radius = g.input("Spread Radius", "FLOAT", 0.1, min=0.0, max=10.0, subtype="DISTANCE", panel=P,
                     desc="Longest jump the growth makes; gaps in the surface wider than this stop it")
    up = g.input("Upward Bias", "FLOAT", 0.5, min=-1.0, max=1.0, subtype="FACTOR", panel=P,
                 desc="Grow upwards faster (positive) or downwards (negative), moss and vines alike")
    moss_amt = g.input("Moss Amount", "FLOAT", 1.0, min=0.0, max=2.0, subtype="FACTOR", panel=P,
                       desc="Moss tuft density and size; 0 no moss")
    vine_amt = g.input("Vine Amount", "FLOAT", 1.0, min=0.0, max=2.0, subtype="FACTOR", panel=P,
                       desc="Number of vines (x Vine Starts) and their branching; 0 no vines")
    bloom = g.input("Bloom Time", "FLOAT", 1.2, min=0.0, max=100.0, subtype="TIME", panel=P,
                    desc="Seconds after the growth reaches a spot before its flowers open")
    S = "Spread"
    seeds = g.input("Seeds", "INT", 5, min=1, max=10000, panel=S, desc="Number of points where moss starts")
    hbias = g.input("Seed Height Bias", "FLOAT", 0.7, min=0.0, max=1.0, subtype="FACTOR", panel=S,
                    desc="0 seeds anywhere, 1 seeds at the lowest points")
    spacing = g.input("Point Spacing", "FLOAT", 0.04, min=0.005, max=10.0, subtype="DISTANCE", panel=S,
                      desc="Resolution of the simulated state (keep well under Spread Radius)")
    patch = g.input("Patchiness", "FLOAT", 0.5, min=0.0, max=0.95, subtype="FACTOR", panel=S,
                    desc="Speed varies by +- this share in soft patches: a ragged front")
    passes = g.input("Front Passes", "INT", 2, min=1, max=16, panel=S,
                     desc="Capture passes per step: the front can jump this many points per frame")
    mature = g.input("Mature Time", "FLOAT", 1.0, min=0.01, max=100.0, subtype="TIME", panel=S,
                     desc="Seconds for moss to grow to full size after the front passes")
    M = "Moss"
    mdens = g.input("Moss Density", "FLOAT", 2600.0, min=0.0, max=100000.0, panel=M, desc="Tufts per square metre")
    tsize = g.input("Tuft Size", "FLOAT", 0.03, min=0.0, max=10.0, subtype="DISTANCE", panel=M,
                    desc="Mature tuft radius")
    young = g.input("Young Color", "COLOR", lin("#9DB043"), panel=M, desc="Colour of fresh moss at the front")
    old = g.input("Mature Color", "COLOR", lin("#3A5218"), panel=M, desc="Colour of mature moss")
    stain = g.input("Stain", "FLOAT", 0.85, min=0.0, max=1.0, subtype="FACTOR", panel=M,
                    desc="nk_moss on the input mesh; its material can darken and green by it")
    fshare = g.input("Moss Flowers", "FLOAT", 0.06, min=0.0, max=1.0, subtype="FACTOR", panel=M,
                     desc="Share of moss points that grow a tiny flower")
    fcol = g.input("Moss Flower Color", "COLOR", lin("#F4EEDC"), panel=M, desc="Moss flower colour")
    mmat = g.input("Moss Material", "MATERIAL", mats.get("Moss"), panel=M, desc="Tuft material")
    V = "Vines"
    starts = g.input("Vine Starts", "INT", 6, min=0, max=1000, panel=V,
                     desc="Vines that start at the lowest seed points (x Vine Amount)")
    vspeed = g.input("Vine Speed", "FLOAT", 1.4, min=0.0, max=20.0, panel=V,
                     desc="Tip speed as a multiple of Growth Speed")
    wander = g.input("Wander", "FLOAT", 3.0, min=0.0, max=100.0, panel=V, desc="Random steering of the tips")
    brate = g.input("Branch Rate", "FLOAT", 0.7, min=0.0, max=100.0, subtype="FREQUENCY", panel=V,
                    desc="Branches per tip per second (x Vine Amount)")
    bangle = g.input("Branch Angle", "FLOAT", 0.7, min=0.0, max=math.pi, subtype="ANGLE", panel=V,
                     desc="Turn of a new branch from its parent")
    life = g.input("Vine Life", "FLOAT", 3.2, min=0.0, max=1000.0, subtype="TIME", panel=V,
                   desc="Seconds each tip grows before it stops")
    maxt = g.input("Max Tips", "INT", 40, min=0, max=100000, panel=V, desc="No more branching once this many grow")
    thick = g.input("Thickness", "FLOAT", 0.011, min=0.0, max=1.0, subtype="DISTANCE", panel=V,
                    desc="Radius of old stems")
    vmat = g.input("Vine Material", "MATERIAL", mats.get("Vine"), panel=V, desc="Stem material")
    L = "Leaves"
    lsize = g.input("Leaf Size", "FLOAT", 0.09, min=0.0, max=10.0, subtype="DISTANCE", panel=L,
                    desc="Grown leaf length")
    lspace = g.input("Leaf Spacing", "FLOAT", 0.04, min=0.005, max=10.0, subtype="DISTANCE", panel=L,
                     desc="Distance between leaves along a stem")
    ldelay = g.input("Leaf Delay", "FLOAT", 0.25, min=0.0, max=100.0, subtype="TIME", panel=L,
                     desc="Seconds after the tip passes before a leaf appears")
    lgrow = g.input("Leaf Grow", "FLOAT", 0.8, min=0.01, max=100.0, subtype="TIME", panel=L,
                    desc="Seconds for a leaf to grow to full size")
    lcol = g.input("Leaf Color", "COLOR", lin("#2C5A2C"), panel=L, desc="Grown leaf colour")
    lmat = g.input("Leaf Material", "MATERIAL", mats.get("Leaf"), panel=L, desc="Leaf material")
    B = "Blossoms"
    bdur = g.input("Bloom Duration", "FLOAT", 1.0, min=0.01, max=100.0, subtype="TIME", panel=B,
                   desc="Seconds from bud to open flower")
    bshare = g.input("Blossom Share", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR", panel=B,
                     desc="Share of vine leaf nodes that flower")
    bsize = g.input("Blossom Size", "FLOAT", 0.08, min=0.0, max=10.0, subtype="DISTANCE", panel=B,
                    desc="Open flower diameter on the vines")
    petals = g.input("Petals", "INT", 5, min=1, max=64, panel=B, desc="Petals per flower")
    ca = g.input("Blossom Color A", "COLOR", lin("#E2577A"), panel=B, desc="Main vine flower colour")
    cb = g.input("Blossom Color B", "COLOR", lin("#F6D2DA"), panel=B, desc="Second vine flower colour")
    bmat = g.input("Blossom Material", "MATERIAL", mats.get("Blossom"), panel=B, desc="Flower material")
    O = "Output"
    show = g.input("Show Surface", "BOOL", True, panel=O, desc="Output the input mesh under the growth")
    debug = g.input("Debug State", "BOOL", False, panel=O,
                    desc="Output only the simulation's state points as vertices (nk_age, nk_coverage)")
    for p in (S, M, V, L, B, O):
        g._panels[p].default_closed = True
    lift = g.math("MULTIPLY", thick, 1.1, label="vine axis height")
    vamt = g.math("MAXIMUM", vine_amt, 0.0)
    with g.frame("Initial state: ranked surface points with seed ages; first vine tips and trail"):
        pts0 = g.group(sample, Surface=geo, Seed=seed, **{"Point Spacing": spacing, "Seeds": seeds,
                                                           "Seed Height Bias": hbias, "Patchiness": patch})
        nv = g.math("ROUND", g.math("MULTIPLY", starts, vamt))
        tips0 = g.group(vstart, Points=pts0, Count=nv, Seed=seed, Lift=lift)
        sim_in, sim_out = g.zone("SIMULATION", [("GEOMETRY", "Tips"), ("GEOMETRY", "Trail"), ("FLOAT", "Time"),
                                                ("INT", "Step")], label="Growth")
        g.connect(pts0, sim_in.i("Geometry"))
        g.connect(tips0, sim_in.i("Tips"))
        g.connect(tips0, sim_in.i("Trail"))
    with g.frame("Simulation step: age covered points by Delta Time, spread the front, move the vines"):
        dt = sim_in["Delta Time"]
        age = _attr(g, "nk_age")
        aged = _store(g, sim_in["Geometry"], "nk_age", g.math("ADD", age, dt),
                      sel=_cmp(g, "GREATER_EQUAL", age, 0.0))
        rin, rout = g.zone("REPEAT", [], label="Front passes")
        g.connect(passes, rin.i("Iterations"))
        g.connect(aged, rin.i("Geometry"))
        sp = g.group(spread, Points=rin["Geometry"], **{"Growth Speed": speed, "Spread Radius": radius,
                                                        "Upward Bias": up})
        g.connect(sp, rout.i("Geometry"))
        vs = g.group(vstep, Tips=sim_in["Tips"], Trail=sim_in["Trail"], Surface=geo, Time=sim_in["Time"],
                     Step=sim_in["Step"], Seed=seed, Wander=wander, Lift=lift, **{
                         "Delta Time": dt, "Speed": g.math("MULTIPLY", speed, vspeed), "Upward Bias": up,
                         "Branch Rate": g.math("MULTIPLY", brate, vamt), "Branch Angle": bangle,
                         "Vine Life": life, "Max Tips": maxt})
        g.connect(rout["Geometry"], sim_out.i("Geometry"))
        g.connect(vs["Tips"], sim_out.i("Tips"))
        g.connect(vs["Trail"], sim_out.i("Trail"))
        g.connect(g.math("ADD", sim_in["Time"], dt), sim_out.i("Time"))
        g.connect(g.math("ADD", sim_in["Step"], 1.0), sim_out.i("Step"))
        g.connect(_cmp(g, "LESS_EQUAL", dt, 0.0), sim_out.i("Skip"))   # the first frame runs with dt = 0
    state, now = sim_out["Geometry"], sim_out["Time"]
    with g.frame("Bloom stages shared by moss flowers and vine flowers"):
        heads = g.group(heads_t, Petals=petals)
    with g.frame("Moss tufts, moss flowers and the moss stain from the state"):
        moss = g.group(moss_t, Surface=geo, State=state, Seed=seed, Stain=stain, Heads=heads, **{
            "Growth Speed": speed, "Moss Amount": moss_amt, "Moss Density": mdens, "Tuft Size": tsize,
            "Mature Time": mature, "Young Color": young, "Mature Color": old, "Moss Material": mmat,
            "Flower Share": fshare, "Bloom Time": bloom, "Bloom Duration": bdur, "Flower Color": fcol,
            "Blossom Material": bmat, "Flower Size": g.math("MULTIPLY", bsize, 0.5)})
    with g.frame("Vines, leaves and vine flowers from the trail"):
        vines = g.group(vines_t, Trail=sim_out["Trail"], Surface=geo, Time=now, Seed=seed, Thickness=thick,
                        Heads=heads, **{"Vine Material": vmat, "Leaf Size": lsize, "Leaf Spacing": lspace,
                                        "Leaf Delay": ldelay, "Leaf Grow": lgrow, "Leaf Color": lcol,
                                        "Leaf Material": lmat, "Blossom Share": bshare, "Blossom Size": bsize,
                                        "Bloom Time": bloom, "Bloom Duration": bdur, "Blossom Color A": ca,
                                        "Blossom Color B": cb, "Blossom Material": bmat})
    with g.frame("Output: surface, moss and vines realized (materials read nk_color); or the debug state"):
        surf = _switch(g, "GEOMETRY", show, None, moss["Surface"])
        out = g.node("GeometryNodeRealizeInstances", Geometry=_join(g, surf, moss["Moss"], vines["Vines"]))
        cov = _store(g, state, "nk_coverage", g.map_range(_attr(g, "nk_age"), 0.0, mature, 0.0, 1.0)["Result"])
        dbg = g.node("GeometryNodePointsToVertices", Points=cov)["Mesh"]
        result = _switch(g, "GEOMETRY", debug, out["Geometry"], dbg)
    g.output("Geometry", "GEOMETRY", result, desc="The input mesh with moss, vines, leaves and flowers")
    return g.finish()


# ---- materials ----------------------------------------------------------------------------------------------------
def _tint_into(m, target_group_input, **tint):
    """Put an NK Attribute Tint node in material ``m`` and wire its Color into the main group's ``target`` input."""
    nt = m.node_tree
    main = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeGroup")
    tn = nt.nodes.new("ShaderNodeGroup")
    tn.node_tree = attribute_tint()
    tn.label = "NK Attribute Tint"
    for k, v in tint.items():
        tn.inputs[k].default_value = v
    nt.links.new(tn.outputs["Color"], main.inputs[target_group_input])
    tn.location = (main.location.x - 300, main.location.y)
    return m


def _stain(m, color, strength=1.0):
    """Mix the material's base colour toward ``color`` by the geometry attribute nk_moss (0 when absent)."""
    nt = m.node_tree
    pb = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    link = next(l for l in nt.links if l.to_socket == pb.inputs["Base Color"])
    src = link.from_socket
    nt.links.remove(link)
    at = nt.nodes.new("ShaderNodeAttribute")
    at.attribute_type, at.attribute_name = "GEOMETRY", "nk_moss"
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(at.outputs["Factor"], mul.inputs[0])
    mul.inputs[1].default_value = strength
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.clamp_factor = "RGBA", True
    nt.links.new(mul.outputs[0], mix.inputs["Factor"])
    nt.links.new(src, [s for s in mix.inputs if s.enabled and s.name == "A"][0])
    [s for s in mix.inputs if s.enabled and s.name == "B"][0].default_value = color
    nt.links.new([s for s in mix.outputs if s.enabled][0], pb.inputs["Base Color"])
    for n_, x in ((at, -500), (mul, -300), (mix, -100)):
        n_.location = (pb.location.x + x, pb.location.y - 450)
    return m


def build_materials():
    moss = make_material("Growth Moss", felt, Color=lin("#4E6B26"), Mottle=0.18, Fuzz=0.7, Sheen=0.35,
                         **{"Fuzz Scale": 900.0})
    _tint_into(moss, "Color", **{"Value Variation": 0.35, "Hue Variation": 0.04})
    vine = make_material("Growth Vine", wood_grain, **{"Light Color": lin("#6E5A38"), "Dark Color": lin("#3A2E1C"),
                                                        "Ring Scale": 260.0, "Distortion": 6.0, "Fibre": 0.8})
    leaf_m = make_material("Growth Leaf", attribute_tint, bsdf={"Specular IOR Level": 0.35, "Subsurface Weight": 0.15},
                           **{"Base Color": lin("#3E6B23"), "Value Variation": 0.3, "Hue Variation": 0.03,
                              "Roughness": 0.45})
    bl = make_material("Growth Blossom", attribute_tint, bsdf={"Subsurface Weight": 0.3, "Sheen Weight": 0.3},
                       **{"Base Color": lin("#E2577A"), "Value Variation": 0.15, "Roughness": 0.5})
    nt = bl.node_tree
    pb = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    link = next(l for l in nt.links if l.to_socket == pb.inputs["Base Color"])
    src = link.from_socket
    nt.links.remove(link)
    part = nt.nodes.new("ShaderNodeAttribute")
    part.attribute_type, part.attribute_name = "GEOMETRY", "nk_part"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.clamp_factor = "RGBA", True
    nt.links.new(part.outputs["Factor"], mix.inputs["Factor"])
    nt.links.new(src, [s for s in mix.inputs if s.enabled and s.name == "A"][0])
    [s for s in mix.inputs if s.enabled and s.name == "B"][0].default_value = lin("#F2B92B")
    nt.links.new([s for s in mix.outputs if s.enabled][0], pb.inputs["Base Color"])
    part.location, mix.location = (pb.location.x - 500, pb.location.y - 450), (pb.location.x - 250, pb.location.y - 450)
    return {"Moss": moss, "Vine": vine, "Leaf": leaf_m, "Blossom": bl}


# ---- scenes ---------------------------------------------------------------------------------------------------------
def _mesh_object(name, sc, build):
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    return ob


def _statue_mesh(bm):
    """A two-step plinth, a tapered column and a capital, with Suzanne on top, as one mesh."""
    import bmesh
    from mathutils import Matrix

    def box(sx, sy, sz, z0, cuts=3):
        r = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"])
        bmesh.ops.translate(bm, vec=(0, 0, z0 + sz / 2), verts=r["verts"])
        edges = list({e for v in r["verts"] for e in v.link_edges})
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cuts, use_grid_fill=True)

    box(1.25, 1.25, 0.18, 0.0, 5)
    box(1.0, 1.0, 0.22, 0.18, 4)
    r = bmesh.ops.create_cone(bm, cap_ends=False, segments=24, radius1=0.3, radius2=0.27, depth=1.15,
                              matrix=Matrix.Translation((0, 0, 0.40 + 0.575)))
    edges = [e for e in bm.edges if all(v in set(r["verts"]) for v in e.verts) and
             abs(e.verts[0].co.z - e.verts[1].co.z) > 0.1]
    bmesh.ops.subdivide_edges(bm, edges=edges, cuts=10)
    box(0.8, 0.8, 0.14, 1.55, 3)
    m = bmesh.ops.create_monkey(bm, matrix=Matrix.Translation((0, 0, 2.02)) @ Matrix.Rotation(math.radians(-8), 4, "X")
                                @ Matrix.Scale(0.5, 4))
    mverts = m["verts"]
    faces = list({f for v in mverts for f in v.link_faces})
    bmesh.ops.subdivide_edges(bm, edges=list({e for f in faces for e in f.edges}), cuts=1, use_grid_fill=True,
                              smooth=1.0)
    for f in bm.faces:
        f.smooth = True


def _knot_mesh(bm, p=2, q=3, R=0.9, r=0.38, tube=0.2, n=360, m=16):
    """A (p, q) torus knot tube: the transfer input."""
    from mathutils import Vector
    pts = []
    for i in range(n):
        t = TAU * i / n
        rr = R + r * math.cos(q * t)
        pts.append(Vector((rr * math.cos(p * t), rr * math.sin(p * t), r * math.sin(q * t) + 1.15)))
    rings = []
    for i in range(n):
        tan = (pts[(i + 1) % n] - pts[i - 1]).normalized()
        ref = Vector((0, 0, 1)) if abs(tan.z) < 0.9 else Vector((1, 0, 0))
        nrm = tan.cross(ref).normalized()
        bi = tan.cross(nrm)
        rings.append([bm.verts.new(pts[i] + tube * (math.cos(TAU * j / m) * nrm + math.sin(TAU * j / m) * bi))
                      for j in range(m)])
    for i in range(n):
        a, b = rings[i], rings[(i + 1) % n]
        for j in range(m):
            f = bm.faces.new((a[j], a[(j + 1) % m], b[(j + 1) % m], b[j]))
            f.smooth = True
    bm.normal_update()
    import bmesh
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    # a low block for it to stand on
    r_ = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(2.6, 1.4, 0.35), verts=r_["verts"])
    bmesh.ops.translate(bm, vec=(0, 0, 0.175), verts=r_["verts"])
    bmesh.ops.subdivide_edges(bm, edges=list({e for v in r_["verts"] for e in v.link_edges}), cuts=6,
                              use_grid_fill=True)


def _ground(sc, name, mat, size=80.0):
    def build(bm):
        import bmesh
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    ob = _mesh_object(name, sc, build)
    ob.data.materials.append(mat)
    return ob


def _camera(sc, name, loc, target, lens, fstop=2.2):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    cam.dof.use_dof = True
    cam.dof.aperture_fstop = fstop
    cam.dof.focus_distance = (sum((a - b) ** 2 for a, b in zip(loc, target)) ** 0.5)
    ob = bpy.data.objects.new(name, cam)
    ob.location = loc
    sc.collection.objects.link(ob)
    t = bpy.data.objects.new(name + " Target", None)
    t.location = target
    sc.collection.objects.link(t)
    c = ob.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = t, "TRACK_NEGATIVE_Z", "UP_Y"
    sc.camera = ob
    return ob


def _setup_scene(sc, w, h, samples):
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = FRAMES
    nks.render_setup(w, h, samples, sc=sc, look="Medium High Contrast")
    nks.light_world(sun_elev=32.0, sun_azim=338.0, strength=4.2, sun_color="#FFDDB0", sky_top="#7FA8CB",
                    sky_horizon="#EAD8BC", sky_strength=0.8, sun_angle=2.5, sc=sc)


def build_scenes(group, mats, w=960, h=528, samples=16):
    stone_m = make_material("Statue Stone", stone, Color=lin("#A29A88"), **{"Mortar Color": lin("#8A8478"),
                            "Stone Scale": 2.0, "Mortar Width": 0.0, "Edge Wear": 0.2, "Variation": 0.18,
                            "Bump": 0.15})
    _stain(stone_m, lin("#4C5C26", 1.0), 1.0)
    ground_m = make_material("Courtyard Cobbles", stone, Color=lin("#6E6656"), **{"Mortar Color": lin("#3E3A2E"),
                             "Stone Scale": 7.0, "Mortar Width": 0.08, "Variation": 0.4})
    clay = make_material("Garden Clay", terracotta, Color=lin("#C27A55"), Bloom=0.35)
    _stain(clay, lin("#4C5C26", 1.0), 1.0)

    sc = bpy.context.scene
    sc.name = "Statue"
    _setup_scene(sc, w, h, samples)
    statue = _mesh_object("Statue", sc, _statue_mesh)
    statue.data.materials.append(stone_m)
    mod = statue.modifiers.new("Growth", "NODES")
    mod.node_group = group
    _ground(sc, "Statue Ground", ground_m)
    _camera(sc, "Camera", (4.0, -6.1, 1.35), (0.0, 0.0, 1.27), 46.0, 1.4)
    statue.rotation_euler.z = math.radians(30.0)

    tr = bpy.data.scenes.new("Growth Transfer")
    bpy.context.window.scene = tr
    _setup_scene(tr, w, h, samples)
    knot = _mesh_object("Knot", tr, _knot_mesh)
    knot.data.materials.append(clay)
    mod2 = knot.modifiers.new("Growth", "NODES")
    mod2.node_group = group
    inspect.set_modifier_inputs(mod2, {"Seed": 3, "Seeds": 6, "Vine Starts": 7, "Seed Height Bias": 0.85})
    _ground(tr, "Transfer Ground", ground_m)
    _camera(tr, "Transfer Camera", (3.0, -4.6, 2.7), (0.0, 0.0, 0.8), 40.0, 2.0)
    bpy.context.window.scene = sc
    return {"Statue": (statue, mod), "Growth Transfer": (knot, mod2)}


# ---- stepping, baking, rendering --------------------------------------------------------------------------------
def step_to(sc, frame):
    """Simulation zones advance one step per frame change: evaluate every frame from the start in order."""
    bpy.context.window.scene = sc
    t0 = time.time()
    for f in range(sc.frame_start, frame + 1):
        sc.frame_set(f)
    return time.time() - t0


def bake(objs):
    """Bake every Growth simulation zone over the frame range, packed into the .blend."""
    for sc_name, (ob, mod) in objs.items():
        sc = bpy.data.scenes[sc_name]
        bpy.context.window.scene = sc
        sc.frame_set(sc.frame_start)
        for b in mod.bakes:
            b.bake_target = "PACKED"
            b.use_custom_simulation_frame_range = False
            with bpy.context.temp_override(scene=sc, object=ob, active_object=ob, selected_objects=[ob]):
                bpy.ops.object.geometry_node_bake_single(session_uid=ob.session_uid, modifier_name=mod.name,
                                                         bake_id=b.bake_id)


def render(sc, frame, path, stepped_from=None):
    bpy.context.window.scene = sc
    if stepped_from is None:
        took = step_to(sc, frame)
    else:
        took = 0.0
        sc.frame_set(frame)
    sc.render.filepath = str(path)
    t0 = time.time()
    bpy.ops.render.render(write_still=True, scene=sc.name)
    print(f"RENDER {sc.name} frame {frame}: stepped {took:.1f}s, render {time.time() - t0:.1f}s -> {path}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--render", default="")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--frame", type=int, default=100)
    ap.add_argument("--scene", default="Statue")
    ap.add_argument("--strip", default="", help="directory: render --strip-frames of both scenes")
    ap.add_argument("--strip-frames", default="1,30,60,90,120")
    ap.add_argument("--bake", action="store_true", help="bake the simulation (packed) before saving")
    a = ap.parse_args(argv)
    nks.reset()
    mats = build_materials()
    group = build_growth(mats)
    h = int(round(a.width * 0.55 / 8) * 8)
    objs = build_scenes(group, mats, a.width, h, a.samples)
    for sc_name, (ob, mod) in objs.items():
        bpy.context.window.scene = bpy.data.scenes[sc_name]
        bpy.data.scenes[sc_name].frame_set(1)
        warns = [w.message for w in mod.node_warnings]
        print(f"BUILD {sc_name}: warnings {warns}")
    if a.bake:
        t0 = time.time()
        bake(objs)
        print(f"BAKE {time.time() - t0:.1f}s")
    for sc_name in objs:
        bpy.data.scenes[sc_name].frame_set(1)
    bpy.context.window.scene = bpy.data.scenes["Statue"]
    out = pathlib.Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    if a.render:
        render(bpy.data.scenes[a.scene], a.frame, pathlib.Path(a.render).resolve(),
               stepped_from=1 if a.bake else None)
    if a.strip:
        d = pathlib.Path(a.strip).resolve()
        d.mkdir(parents=True, exist_ok=True)
        frames = [int(x) for x in a.strip_frames.split(",")]
        for sc_name in objs:
            sc = bpy.data.scenes[sc_name]
            bpy.context.window.scene = sc
            sc.frame_set(sc.frame_start)
            last = sc.frame_start
            for f in frames:
                for ff in range(last + 1, f + 1):
                    sc.frame_set(ff)
                last = f
                sc.frame_set(f)
                tag = sc_name.lower().replace(" ", "_")
                sc.render.filepath = str(d / f"{tag}_f{f:03d}.png")
                bpy.ops.render.render(write_still=True, scene=sc.name)
                print(f"STRIP {sc_name} frame {f}")


if __name__ == "__main__":
    main()
