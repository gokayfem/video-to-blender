"""SS Props: the street furniture hung on and stood against the facades.

Everything is placed from the facades' ``Anchors`` point cloud (see AGENTS.md, "Facades -> Props interface"):

    anchor 1, 2  window sills        -> SS Prop Window Box   (terracotta trough, leaf mound, geranium blossoms)
    anchor 3     door base           -> SS Prop Ivy          (leaf mat around the door frame)
    anchor 4     shopfront top       -> SS Prop Awning       (striped canvas, scalloped valance, iron arms)
    anchor 5     lantern spot        -> SS Prop Lantern      (black iron box lantern, glowing panes)
    anchor 6     sign bracket spot   -> SS Prop Sign         (scroll bracket, bread board or round board)
    anchor 7     verge spot          -> SS Prop Barrel / SS Prop Pot clusters on the grass verge

Every prop is its own group modelled in local anchor space (+X along the wall, +Y out to the street, +Z up,
origin on the wall surface), so artists can drop any of them into their own trees. Width-dependent props
(window boxes, awnings, ivy) and swinging signs are built once per anchor in a For Each Element zone; fixed props
(lanterns, pots, barrels) are instanced. Animation reads only the Time input: signs swing as small pendulums with a
per-sign phase, and the lantern glow flickers through the ``ss_glow`` attribute the glass material reads.

``test_inputs`` builds mock anchors (SS Props Mock Anchors) for tools/try_group.py until SS Facades lands; in the
assembly, wire SS Facades.Anchors -> SS Props.Anchors instead.
"""
import math
from nodekit.graph import Graph
from street.groups import frame
from street.materials import props as pm
from street.materials import common

NAME = "SS Props"
TAU = 2.0 * math.pi
_MATS = {}


# ---- small node idioms (python helpers, not groups) -------------------------------------------------------------
def _xf(g, geo, t=(0, 0, 0), r=(0, 0, 0), s=(1, 1, 1)):
    return g.node("GeometryNodeTransform", Geometry=geo, Translation=t, Rotation=r, Scale=s)["Geometry"]


def _join(g, *geos):
    j = g.node("GeometryNodeJoinGeometry")
    for x in reversed(geos):        # the multi-input socket stacks the newest link first
        g.connect(x, j.i("Geometry"))
    return j["Geometry"]


def _mat(g, geo, key):
    return g.node("GeometryNodeSetMaterial", Geometry=geo, Material=_MATS[key])["Geometry"]


def _smooth(g, geo, sel=None):
    n = g.node("GeometryNodeSetShadeSmooth", Geometry=geo, **{"Shade Smooth": True})
    if sel is not None:
        g.connect(sel, n.i("Selection"))
    return n["Geometry"]


def _store(g, geo, name, value, dtype="FLOAT_COLOR", domain="POINT", sel=None):
    n = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": dtype, "domain": domain},
               Geometry=geo, Name=name, Value=value)
    if sel is not None:
        g.connect(sel, n.i("Selection"))
    return n["Geometry"]


def _attr(g, name, dtype="FLOAT"):
    return g.node("GeometryNodeInputNamedAttribute", props={"data_type": dtype}, Name=name)["Attribute"]


def _rand(g, lo, hi, seed, dtype="FLOAT", ident=None):
    n = g.node("FunctionNodeRandomValue", props={"data_type": dtype}, Min=lo, Max=hi, Seed=seed)
    if ident is not None:
        g.connect(ident, n.i("ID"))
    return n["Value"]


def _chance(g, p, seed, ident=None):
    n = g.node("FunctionNodeRandomValue", props={"data_type": "BOOLEAN"}, Probability=p, Seed=seed)
    if ident is not None:
        g.connect(ident, n.i("ID"))
    return n["Value"]


def _bool(g, op, a, b=None):
    n = g.node("FunctionNodeBooleanMath", props={"operation": op}, **{"Boolean": a})
    if b is not None:
        g.connect(b, n.i("Boolean#1"))
    return n["Boolean"]


def _cmp(g, op, a, b, dtype="FLOAT"):
    return g.node("FunctionNodeCompare", props={"data_type": dtype, "operation": op}, A=a, B=b)["Result"]


def _is_anchor(g, *types):
    a = _attr(g, "anchor", "INT")
    sel = None
    for t in types:
        e = _cmp(g, "EQUAL", a, t, "INT")
        sel = e if sel is None else _bool(g, "OR", sel, e)
    return sel


def _cmix(g, fac, a, b):
    return g.node("ShaderNodeMix", props={"data_type": "RGBA", "clamp_factor": True}, Factor=fac, A=a, B=b)["Result"]


def _switch(g, typ, cond, false=None, true=None):
    n = g.node("GeometryNodeSwitch", props={"input_type": typ}, Switch=cond)
    g.connect(false, n.i("False"))
    g.connect(true, n.i("True"))
    return n


def _seed(g, seed, k):
    return g.math("ADD", seed, k)


def _for_each(g, points, selection, items, body):
    """For Each Element zone over ``points``: ``items`` {name: (socket type, field)} are evaluated per point;
    ``body(fields, index)`` returns the geometry built for one element (already in world space)."""
    sel = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=points, Selection=selection)
    count = g.node("GeometryNodeAttributeDomainSize", props={"component": "MESH"}, Geometry=sel["Selection"])
    zi = g.node("GeometryNodeForeachGeometryElementInput")
    zo = g.node("GeometryNodeForeachGeometryElementOutput")
    zi.b.pair_with_output(zo.b)
    for name, (typ, _) in items.items():
        zo.b.input_items.new(typ, name)
    g.connect(sel["Selection"], zi.i("Geometry"))
    for name, (_, val) in items.items():
        g.connect(val, zi.i(name))
    geo = body({name: zi[name] for name in items}, zi["Index"])
    g.connect(geo, zo.i("Geometry"))
    # the switch is lazy: with nothing selected the zone is not evaluated (and raises no "no elements" note)
    return _switch(g, "GEOMETRY", _cmp(g, "GREATER_THAN", count["Point Count"], 0, "INT"), true=zo["Geometry#1"])


def _clean_points(g, pts, rot):
    """Capture the anchor frame, then drop the anchor attributes from the points so they do not leak onto the
    instances (Remove Named Attribute on instances would also strip nested instances, e.g. leaf colours)."""
    cap = g.node("GeometryNodeCaptureAttribute", props={"domain": "POINT"})
    cap.b.capture_items.new("ROTATION", "Rot")
    g.connect(pts, cap.i("Geometry"))
    g.connect(rot, cap.i("Rot"))
    a = g.node("GeometryNodeRemoveAttribute", Geometry=cap["Geometry"], Name="ss_*", **{"Pattern Mode": "Wildcard"})
    b = g.node("GeometryNodeRemoveAttribute", Geometry=a["Geometry"], Name="anchor")
    return b["Geometry"], cap["Rot"]


def _place(g, geo, pos, rot):
    """Local anchor space -> world: rotate by the anchor frame, then move to the anchor."""
    return g.node("GeometryNodeTransform", Geometry=geo, Translation=pos, Rotation=rot)["Geometry"]


# ---- shared primitives ----------------------------------------------------------------------------------------
def build_rounded_box():
    g = Graph("SS Prop Rounded Box", description="Box with rounded edges (toy-like bevel), centred at the origin. "
                                                 "A 4x4x4 cube whose inner rows sit Radius from the faces, smoothed "
                                                 "by subdivision")
    size = g.input("Size", "VECTOR", (1.0, 1.0, 1.0), subtype="XYZ", desc="Box dimensions")
    rad = g.input("Radius", "FLOAT", 0.03, min=0.0, max=1.0, subtype="DISTANCE", desc="Edge rounding radius")
    lvl = g.input("Level", "INT", 2, min=1, max=4, desc="Subdivision level (1 for small or far parts)")
    with g.frame("Cube with its inner vertex rows pulled to Radius from each face"):
        cube = g.node("GeometryNodeMeshCube", Size=(1, 1, 1), **{"Vertices X": 4, "Vertices Y": 4, "Vertices Z": 4})
        p = g.node("GeometryNodeInputPosition")
        sz = g.separate(size)
        rmax = g.math("MULTIPLY", g.math("MINIMUM", g.math("MINIMUM", sz["X"], sz["Y"]), sz["Z"]), 0.45)
        r = g.math("MINIMUM", rad, rmax)
        outer = g.vmath("FLOOR", g.vmath("SCALE", g.vmath("ABSOLUTE", p), scale=2.5), label="1 on faces, 0 inside")
        inner = g.vmath("SUBTRACT", (1, 1, 1), outer)
        half = g.vmath("SCALE", size, scale=0.5)
        coord = g.vmath("SUBTRACT", half, g.vmath("SCALE", inner, scale=r))
        newp = g.vmath("MULTIPLY", g.vmath("SIGN", p), coord)
        sp = g.node("GeometryNodeSetPosition", Geometry=cube["Mesh"], Position=newp)
    with g.frame("Round the edges"):
        sub = g.node("GeometryNodeSubdivisionSurface", Mesh=sp["Geometry"], Level=lvl)
        sm = _smooth(g, sub["Mesh"])
    g.output("Mesh", "GEOMETRY", sm)
    return g.finish()


def build_rod():
    g = Graph("SS Prop Rod", description="Round bar from Start to End (wrought-iron arms, hooks, posts)")
    a = g.input("Start", "VECTOR", (0, 0, 0), subtype="TRANSLATION", desc="Start point")
    b = g.input("End", "VECTOR", (0, 0, 1), subtype="TRANSLATION", desc="End point")
    r = g.input("Radius", "FLOAT", 0.015, min=0.001, max=0.5, subtype="DISTANCE", desc="Bar radius")
    line = g.node("GeometryNodeCurvePrimitiveLine", Start=a, End=b)
    prof = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=8, Radius=r)
    mesh = g.node("GeometryNodeCurveToMesh", Curve=line, **{"Profile Curve": prof["Curve"], "Fill Caps": True})
    g.output("Mesh", "GEOMETRY", _smooth(g, mesh["Mesh"]))
    return g.finish()


def build_ring():
    g = Graph("SS Prop Ring", description="Torus lying in the XY plane (pot rims, sign rims)")
    R = g.input("Radius", "FLOAT", 0.2, min=0.01, max=5, subtype="DISTANCE", desc="Ring radius")
    t = g.input("Thickness", "FLOAT", 0.02, min=0.001, max=1, subtype="DISTANCE", desc="Tube radius")
    circ = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=24, Radius=R)
    prof = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=8, Radius=t)
    mesh = g.node("GeometryNodeCurveToMesh", Curve=circ["Curve"], **{"Profile Curve": prof["Curve"]})
    g.output("Mesh", "GEOMETRY", _smooth(g, mesh["Mesh"]))
    return g.finish()


def build_leaf():
    g = Graph("SS Prop Leaf", description="One rounded leaf: a flattened ellipsoid lying in XY (normal +Z), tip "
                                          "towards +X")
    size = g.input("Size", "FLOAT", 0.09, min=0.005, max=1, subtype="DISTANCE", desc="Leaf length")
    sph = g.node("GeometryNodeMeshUVSphere", Segments=6, Rings=3, Radius=0.5)
    s = g.combine(size, g.math("MULTIPLY", size, 0.72), g.math("MULTIPLY", size, 0.18))
    leaf = g.node("GeometryNodeTransform", Geometry=sph["Mesh"], Scale=s,
                  Translation=g.combine(g.math("MULTIPLY", size, 0.3), 0, 0))
    g.output("Mesh", "GEOMETRY", _smooth(g, leaf["Geometry"]))
    return g.finish()


def build_blossom():
    g = Graph("SS Prop Blossom", description="A geranium head: a dome of four round florets, base at the origin, "
                                             "opening towards +Z")
    size = g.input("Size", "FLOAT", 0.075, min=0.005, max=1, subtype="DISTANCE", desc="Head diameter")
    with g.frame("Three florets in a ring and one on top"):
        ring = g.node("GeometryNodeMeshCircle", Vertices=3, Radius=0.27)
        top = g.node("GeometryNodePoints", Count=1, Position=(0, 0, 0.18))
        pts = _join(g, g.node("GeometryNodeMeshToPoints", Mesh=ring["Mesh"])["Points"], top["Points"])
        ico = g.node("GeometryNodeMeshUVSphere", Segments=6, Rings=4, Radius=0.27)
        inst = g.node("GeometryNodeInstanceOnPoints", Points=pts, Instance=ico["Mesh"])
        real = g.node("GeometryNodeRealizeInstances", Geometry=inst["Instances"])
        sc = g.node("GeometryNodeTransform", Geometry=real["Geometry"], Translation=g.combine(0, 0, g.math(
            "MULTIPLY", size, 0.2)), Scale=g.combine(size, size, size))
    g.output("Mesh", "GEOMETRY", _smooth(g, sc["Geometry"]))
    return g.finish()


def build_foliage(leaf, blossom):
    g = Graph("SS Prop Foliage", description="Clothes a mound mesh in leaves and geranium blossoms: leaves "
                                             "instanced on its faces facing outwards, blossoms on its upper and "
                                             "front faces, each blossom coloured per instance (ss_color)")
    mesh = g.input("Mesh", "GEOMETRY", desc="Mound to cover (its faces' normals point outwards)")
    show = g.input("Show Mound", "BOOL", True, desc="Keep the mound itself as a dark leafy under-layer")
    ld = g.input("Leaf Density", "FLOAT", 450.0, min=0, max=5000, desc="Leaves per square unit of mound")
    ls = g.input("Leaf Size", "FLOAT", 0.09, min=0.01, max=0.5, subtype="DISTANCE", desc="Leaf length")
    lc = g.input("Leaf Color", "COLOR", (0.10, 0.25, 0.04, 1), desc="Leaf colour (linear)")
    bd = g.input("Blossom Density", "FLOAT", 100.0, min=0, max=2000,
                 desc="Blossoms per square unit on the upper and front faces")
    bs = g.input("Blossom Size", "FLOAT", 0.075, min=0.01, max=0.5, subtype="DISTANCE", desc="Blossom diameter")
    ca = g.input("Color A", "COLOR", (0.66, 0.02, 0.012, 1), desc="Main blossom colour (red)")
    cb = g.input("Color B", "COLOR", (0.88, 0.17, 0.09, 1), desc="Second blossom colour (coral)")
    cc = g.input("Color C", "COLOR", (0.88, 0.83, 0.76, 1), desc="Third blossom colour (white)")
    bare = g.input("Bare Back", "BOOL", False, desc="No leaves on faces looking towards -Y (against a wall)")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    with g.frame("Where leaves go: not underneath, and not against the wall when Bare Back"):
        nrm = g.separate(g.node("GeometryNodeInputNormal"))
        hidden = _bool(g, "OR", _cmp(g, "LESS_THAN", nrm["Z"], -0.6),
                       _bool(g, "AND", bare, _cmp(g, "LESS_THAN", nrm["Y"], -0.6)))
        visible = _bool(g, "NOT", hidden)
    with g.frame("Mound as under-layer (darker leaf colour)"):
        under = _store(g, mesh, "ss_color", g.vmath("SCALE", lc, scale=0.55))
        under = _mat(g, _smooth(g, under), "foliage")
        under = _switch(g, "GEOMETRY", show, true=under)
    with g.frame("Leaves: scattered on the mound, lying on it with a random spin and tilt"):
        dl = g.node("GeometryNodeDistributePointsOnFaces", Mesh=mesh, Selection=visible, Density=ld, Seed=seed)
        tilt = g.combine(_rand(g, -0.6, 0.6, _seed(g, seed, 1)), _rand(g, -0.3, 0.3, _seed(g, seed, 2)),
                         _rand(g, 0.0, TAU, _seed(g, seed, 3)))
        lrot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=dl["Rotation"],
                      **{"Rotate By": g.node("FunctionNodeEulerToRotation", Euler=tilt)})
        lsc = _rand(g, 0.7, 1.3, _seed(g, seed, 4))
        li = g.node("GeometryNodeInstanceOnPoints", Points=dl["Points"], Instance=g.group(leaf), Rotation=lrot,
                    Scale=g.math("DIVIDE", g.math("MULTIPLY", lsc, ls), 0.09))
        ltint = g.vmath("MULTIPLY", lc, g.combine(_rand(g, 0.7, 1.35, _seed(g, seed, 5)),
                                                    _rand(g, 0.8, 1.3, _seed(g, seed, 6)), 1.0))
        leaves = _store(g, li["Instances"], "ss_color", ltint, domain="INSTANCE")
        leaves = _mat(g, leaves, "foliage")
    with g.frame("Blossoms: on faces looking up or out, pushed just above the leaves; colour A, B or C"):
        up = _bool(g, "AND", visible, _cmp(g, "GREATER_THAN", nrm["Z"], -0.3))
        db = g.node("GeometryNodeDistributePointsOnFaces", Mesh=mesh, Selection=up, Density=bd,
                    Seed=_seed(g, seed, 11))
        lift = g.node("GeometryNodeSetPosition", Geometry=db["Points"],
                      Offset=g.vmath("SCALE", db["Normal"], scale=g.math("MULTIPLY", ls, 0.25)))
        brot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=db["Rotation"],
                      **{"Rotate By": g.node("FunctionNodeEulerToRotation", Euler=g.combine(
                          _rand(g, -0.3, 0.3, _seed(g, seed, 12)), 0, _rand(g, 0, TAU, _seed(g, seed, 13))))})
        bsc = g.math("DIVIDE", g.math("MULTIPLY", _rand(g, 0.75, 1.3, _seed(g, seed, 14)), bs), 0.075)
        bi = g.node("GeometryNodeInstanceOnPoints", Points=lift["Geometry"], Instance=g.group(blossom), Rotation=brot,
                    Scale=bsc)
        u = _rand(g, 0.0, 1.0, _seed(g, seed, 15))
        col = _cmix(g, g.math("GREATER_THAN", u, 0.55), ca, _cmix(g, g.math("GREATER_THAN", u, 0.85), cb, cc))
        shade = _rand(g, 0.8, 1.1, _seed(g, seed, 16))
        blossoms = _store(g, bi["Instances"], "ss_color", g.vmath("SCALE", col, scale=shade), domain="INSTANCE")
        blossoms = _mat(g, blossoms, "petals")
    g.output("Geometry", "GEOMETRY", _join(g, under, leaves, blossoms))
    return g.finish()


def _bumpy(g, mesh, amp, scale, seed):
    """Displace a mesh along its normals with noise (lumpy leaf mounds)."""
    nz = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Scale=scale, Detail=1.0,
                W=g.math("MULTIPLY", seed, 1.37))
    off = g.vmath("SCALE", g.node("GeometryNodeInputNormal"), scale=g.math("MULTIPLY", g.math(
        "SUBTRACT", nz["Fac"], 0.5), amp))
    return g.node("GeometryNodeSetPosition", Geometry=mesh, Offset=off)["Geometry"]


# ---- the props -------------------------------------------------------------------------------------------------
def build_window_box(rbox, foliage):
    g = Graph("SS Prop Window Box", description="Terracotta window box overflowing with geraniums. Origin on the "
                                                "wall at the window sill; +X along the wall, +Y out, +Z up")
    w = g.input("Width", "FLOAT", 1.0, min=0.2, max=5, subtype="DISTANCE", desc="Trough length along the wall")
    fd = g.input("Flower Density", "FLOAT", 1.0, min=0, max=4, desc="Blossoms relative to the default (1)")
    lc = g.input("Leaf Color", "COLOR", (0.10, 0.25, 0.04, 1), desc="Leaf colour")
    ca = g.input("Color A", "COLOR", (0.66, 0.02, 0.012, 1), desc="Main blossom colour (red)")
    cb = g.input("Color B", "COLOR", (0.88, 0.17, 0.09, 1), desc="Second blossom colour (coral)")
    cc = g.input("Color C", "COLOR", (0.88, 0.83, 0.76, 1), desc="Third blossom colour (white)")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    with g.frame("Trough: rounded terracotta box under the sill, with a lip"):
        trough = g.group(rbox, Size=g.combine(w, 0.26, 0.24), Radius=0.03, Level=1)
        trough = _xf(g, trough, (0, 0.15, -0.17))
        lip = _xf(g, g.group(rbox, Size=g.combine(g.math("ADD", w, 0.05), 0.31, 0.05), Radius=0.02, Level=1), (0, 0.15, -0.06))
        trough = _mat(g, _join(g, trough, lip), "terracotta")
    with g.frame("Leaf mound: a lumpy rounded box spilling over the front"):
        mound = g.group(rbox, Size=g.combine(g.math("ADD", w, 0.06), 0.32, 0.26), Radius=0.12, Level=1)
        mound = _bumpy(g, _xf(g, mound, (0, 0.17, 0.0)), 0.09, 7.0, seed)
        plants = g.group(foliage, Mesh=mound, **{"Leaf Color": lc, "Color A": ca, "Color B": cb, "Color C": cc,
                                                  "Seed": seed, "Blossom Density": g.math("MULTIPLY", fd, 45.0), "Blossom Size": 0.11,
                                                  "Bare Back": True, "Leaf Density": 120.0, "Leaf Size": 0.12})
    with g.frame("Trailing leaves spilling over the trough front (ragged curtain, leaves only)"):
        cur = g.node("GeometryNodeMeshGrid", **{"Size X": g.math("MULTIPLY", w, 0.95), "Size Y": 0.2,
                                                "Vertices X": 14, "Vertices Y": 4})
        cur = _xf(g, cur["Mesh"], (0, 0.31, -0.11), (-math.pi / 2, 0, 0))
        nz = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Scale=3.0, Detail=1.0,
                    W=g.math("MULTIPLY", seed, 0.71))
        hang = g.math("ADD", nz["Fac"], g.math("MULTIPLY", g.separate(g.node("GeometryNodeInputPosition"))["Z"], 2.0))
        cur = g.node("GeometryNodeDeleteGeometry", props={"domain": "FACE"}, Geometry=cur,
                     Selection=_cmp(g, "LESS_THAN", hang, 0.45))
        trail = g.group(foliage, Mesh=cur["Geometry"], Seed=g.math("ADD", seed, 5), **{
            "Show Mound": False, "Leaf Density": 140.0, "Leaf Size": 0.1, "Leaf Color": lc,
            "Blossom Density": 0.0})
    g.output("Geometry", "GEOMETRY", _join(g, trough, plants, trail))
    return g.finish()


def build_awning(rod):
    g = Graph("SS Prop Awning", description="Striped shop awning: canvas sloping out from the wall with a "
                                            "scalloped valance and two iron arms. Origin on the wall at the top "
                                            "edge; +X along the wall, +Y out, +Z up. Writes ss_stripe and ss_color")
    w = g.input("Width", "FLOAT", 2.0, min=0.3, max=10, subtype="DISTANCE", desc="Width along the wall")
    dep = g.input("Depth", "FLOAT", 1.0, min=0.2, max=3, subtype="DISTANCE", desc="How far it reaches out")
    drop = g.input("Drop", "FLOAT", 0.36, min=0, max=2, subtype="DISTANCE", desc="Fall from wall to outer edge")
    sw = g.input("Stripe Width", "FLOAT", 0.24, min=0.04, max=1, subtype="DISTANCE",
                 desc="Width of one coloured + one cream stripe (also one scallop)")
    col = g.input("Stripe Color", "COLOR", (0.17, 0.30, 0.48, 1), desc="Colour of the coloured stripes")
    with g.frame("Stripe cells: a whole number across the width"):
        ncell = g.math("MAXIMUM", g.math("ROUND", g.math("DIVIDE", w, sw)), 1.0)
        cell = g.math("DIVIDE", w, ncell)
        vx = g.math("ADD", g.math("MULTIPLY", ncell, 12.0), 1.0)
        px = g.separate(g.node("GeometryNodeInputPosition"))
        u = g.math("DIVIDE", g.math("ADD", px["X"], g.math("MULTIPLY", w, 0.5)), cell, label="stripe coordinate")
    with g.frame("Canvas: grid sloping down and out, sagging a little in the middle"):
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": w, "Size Y": dep, "Vertices X": vx, "Vertices Y": 7})
        y = g.math("ADD", px["Y"], g.math("MULTIPLY", dep, 0.5))
        t = g.math("DIVIDE", y, dep)
        z = g.math("SUBTRACT", g.math("MULTIPLY", t, g.math("MULTIPLY", drop, -1.0)),
                   g.math("MULTIPLY", g.math("SINE", g.math("MULTIPLY", t, math.pi)), 0.04))
        sheet = g.node("GeometryNodeSetPosition", Geometry=grid["Mesh"], Position=g.combine(px["X"], g.math(
            "ADD", y, 0.02), z))
    with g.frame("Valance: a hanging band whose bottom edge is a row of half-disc scallops"):
        vh = 0.12
        vg = g.node("GeometryNodeMeshGrid", **{"Size X": w, "Size Y": vh, "Vertices X": vx, "Vertices Y": 4})
        vgr = _xf(g, vg["Mesh"], (0, 0, 0), (math.pi / 2, 0, 0))
        f = g.math("SUBTRACT", g.math("MULTIPLY", g.math("FRACT", u), 2.0), 1.0)
        bump = g.math("SQRT", g.math("MAXIMUM", g.math("SUBTRACT", 1.0, g.math("MULTIPLY", f, f)), 0.0))
        bottom = g.math("LESS_THAN", px["Z"], -0.5 * vh + 0.001)
        scz = g.math("MULTIPLY", g.math("MULTIPLY", bump, bottom), g.math("MULTIPLY", cell, -0.3))
        val = g.node("GeometryNodeSetPosition", Geometry=vgr, Offset=g.combine(0, 0, scz))
        val = _xf(g, val["Geometry"], g.combine(0, g.math("ADD", dep, 0.02), g.math("SUBTRACT", g.math(
            "MULTIPLY", drop, -1.0), 0.5 * vh)))
    with g.frame("Canvas attributes for the fabric shader: stripe coordinate and stripe colour"):
        canvas = _join(g, sheet["Geometry"], val)
        canvas = _store(g, canvas, "ss_stripe", u, dtype="FLOAT")
        canvas = _store(g, canvas, "ss_color", col)
        canvas = _mat(g, _smooth(g, canvas), "fabric")
    with g.frame("Iron: roller bar on the wall and two diagonal arms"):
        hx = g.math("SUBTRACT", g.math("MULTIPLY", w, 0.5), 0.1)
        nhx = g.math("MULTIPLY", hx, -1.0)
        tipz = g.math("MULTIPLY", drop, -1.0)
        arm1 = g.group(rod, Start=g.combine(hx, 0.0, -0.55), End=g.combine(hx, g.math("MULTIPLY", dep, 0.97),
                                                                           tipz), Radius=0.016)
        arm2 = g.group(rod, Start=g.combine(nhx, 0.0, -0.55), End=g.combine(nhx, g.math("MULTIPLY", dep, 0.97),
                                                                            tipz), Radius=0.016)
        half = g.math("MULTIPLY", w, 0.5)
        bar = g.group(rod, Start=g.combine(g.math("MULTIPLY", half, -1.0), 0.05, 0.02), End=g.combine(
            half, 0.04, 0.02), Radius=0.022)
        iron = _mat(g, _join(g, arm1, arm2, bar), "iron")
    g.output("Geometry", "GEOMETRY", _join(g, canvas, iron))
    return g.finish()


def build_lantern(rbox, rod):
    g = Graph("SS Prop Lantern", description="Black iron box lantern on a wall arm, warm glowing panes "
                                             "(SS Lantern Glass, emission from ss_color and ss_glow). Origin on "
                                             "the wall at the lantern's centre height; +X along the wall, +Y out")
    size = g.input("Size", "FLOAT", 0.7, min=0.2, max=4, desc="Overall scale")
    c = (0, 0.27, 0)
    with g.frame("Glass box"):
        glass = _xf(g, g.node("GeometryNodeMeshCube", Size=(0.15, 0.15, 0.2))["Mesh"], c)
        glass = _mat(g, glass, "glass")
    with g.frame("Iron cage: corner posts, base and cap plates, pyramid roof, finial"):
        parts = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                x, y = 0.08 * sx, 0.27 + 0.08 * sy
                parts.append(g.group(rod, Start=(x, y, -0.11), End=(x, y, 0.11), Radius=0.012))
        parts.append(_xf(g, g.group(rbox, Size=(0.2, 0.2, 0.035), Radius=0.012, Level=1), (0, 0.27, -0.12)))
        parts.append(_xf(g, g.group(rbox, Size=(0.19, 0.19, 0.03), Radius=0.01, Level=1), (0, 0.27, 0.115)))
        roof = g.node("GeometryNodeMeshCone", Vertices=4, **{"Radius Top": 0.025, "Radius Bottom": 0.135,
                                                             "Depth": 0.11})
        parts.append(_xf(g, roof["Mesh"], (0, 0.27, 0.185), (0, 0, math.pi / 4)))
        drip = g.node("GeometryNodeMeshCone", Vertices=4, **{"Radius Top": 0.06, "Radius Bottom": 0.0,
                                                             "Depth": 0.06})
        parts.append(_xf(g, drip["Mesh"], (0, 0.27, -0.165), (0, 0, math.pi / 4)))
        knob = g.node("GeometryNodeMeshUVSphere", Segments=10, Rings=6, Radius=0.022)
        parts.append(_smooth(g, _xf(g, knob["Mesh"], (0, 0.27, 0.255))))
    with g.frame("Wall arm: plate, bracket bent over the lantern"):
        parts.append(_xf(g, g.group(rbox, Size=(0.09, 0.03, 0.2), Radius=0.01, Level=1), (0, 0.015, 0.2)))
        parts.append(g.group(rod, Start=(0, 0.0, 0.17), End=(0, 0.2, 0.33), Radius=0.016))
        parts.append(g.group(rod, Start=(0, 0.2, 0.33), End=(0, 0.27, 0.28), Radius=0.014))
        cage = _mat(g, _join(g, *parts), "iron")
    out = _xf(g, _join(g, glass, cage), s=g.combine(size, size, size))
    g.output("Geometry", "GEOMETRY", out)
    return g.finish()


def build_sign(rbox, rod, ring):
    g = Graph("SS Prop Sign", description="Hanging shop sign: wall plate, iron bar with scrolls, and a board "
                                          "hanging from two hooks that swings about the bar. Origin on the wall "
                                          "at bar height; +X along the wall, +Y out (the bar), +Z up")
    rnd = g.input("Round", "BOOL", False, desc="Round board with a cup motif instead of the bread board")
    swing = g.input("Swing", "FLOAT", 0.0, min=-1.0, max=1.0, subtype="ANGLE",
                    desc="Board angle about the bar (animate this)")
    paint = g.input("Paint Color", "COLOR", (0.21, 0.42, 0.37, 1), desc="Colour of the round board's face")
    size = g.input("Size", "FLOAT", 0.8, min=0.2, max=3, desc="Overall scale (1 = 0.74 x 0.5 bread board)")
    reach = 0.9
    with g.frame("Bracket: wall plate, bar, diagonal brace, two scrolls, ball finial"):
        parts = [_xf(g, g.group(rbox, Size=(0.09, 0.04, 0.46), Radius=0.015, Level=1), (0, 0.02, -0.15)),
                 g.group(rod, Start=(0, 0, 0), End=(0, reach, 0), Radius=0.022),
                 g.group(rod, Start=(0, 0.02, -0.34), End=(0, 0.46, -0.02), Radius=0.017)]
        for (y, z, r, turns) in ((0.75, 0.12, 0.11, 1.6), (0.17, -0.13, 0.08, 1.4)):
            sp = g.node("GeometryNodeCurveSpiral", Resolution=24, Rotations=turns, **{
                "Start Radius": r, "End Radius": 0.012, "Height": 0.0})
            prof = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=6, Radius=0.012)
            m = g.node("GeometryNodeCurveToMesh", Curve=sp["Curve"], **{"Profile Curve": prof["Curve"]})
            parts.append(_xf(g, m["Mesh"], (0, y, z - r if z > 0 else z + r), (0, math.pi / 2, 0)))
        ball = g.node("GeometryNodeMeshUVSphere", Segments=10, Rings=6, Radius=0.035)
        parts.append(_xf(g, ball["Mesh"], (0, reach + 0.01, 0)))
        bracket = _mat(g, _smooth(g, _join(g, *parts)), "iron")
    with g.frame("Board (pivot on the bar): bread board or round board, two hooks"):
        hooks = _mat(g, _join(g, g.group(rod, Start=(0, -0.3, 0.02), End=(0, -0.3, -0.15), Radius=0.012),
                              g.group(rod, Start=(0, 0.3, 0.02), End=(0, 0.3, -0.15), Radius=0.012)), "iron")
        bread_b = _mat(g, _xf(g, g.group(rbox, Size=(0.07, 0.74, 0.5), Radius=0.035), (0, 0, -0.4)), "sign")
        loaf = g.node("GeometryNodeMeshUVSphere", Segments=16, Rings=8, Radius=1.0)
        loaves = _join(g, _xf(g, loaf["Mesh"], (0.04, 0, -0.37), s=(0.03, 0.25, 0.11)),
                       _xf(g, loaf["Mesh"], (-0.04, 0, -0.37), s=(0.03, 0.25, 0.11)))
        loaves = _mat(g, _store(g, _smooth(g, loaves), "ss_color", pm.lin((0.86, 0.58, 0.28))), "paint")
        bread = _join(g, bread_b, loaves)
        disc = g.node("GeometryNodeMeshCylinder", Vertices=32, Radius=0.3, Depth=0.06)
        disc_b = _mat(g, _xf(g, disc["Mesh"], (0, 0, -0.46), (0, math.pi / 2, 0)), "sign")
        rim = _mat(g, _xf(g, g.group(ring, Radius=0.29, Thickness=0.028), (0, 0, -0.46), (0, math.pi / 2, 0)),
                   "sign")
        face = g.node("GeometryNodeMeshCylinder", Vertices=32, Radius=0.23, Depth=0.066)
        face = _store(g, _xf(g, face["Mesh"], (0, 0, -0.46), (0, math.pi / 2, 0)), "ss_color", paint)
        cup = g.node("GeometryNodeMeshUVSphere", Segments=16, Rings=8, Radius=1.0)
        cup = _xf(g, cup["Mesh"], (0, 0, -0.5), s=(0.05, 0.13, 0.08))
        cup = _store(g, _smooth(g, cup), "ss_color", pm.lin((0.92, 0.86, 0.72)))
        roundb = _join(g, disc_b, rim, _mat(g, _join(g, face, cup), "paint"))
        board = _switch(g, "GEOMETRY", rnd, false=bread,
                       true=roundb)
        rot = g.combine(0, swing, 0)
        board = _xf(g, _join(g, board, hooks), g.combine(0, reach * 0.53, 0), rot)
    g.output("Geometry", "GEOMETRY", _xf(g, _join(g, bracket, board), s=g.combine(size, size, size)))
    return g.finish()


def build_barrel(rod):
    g = Graph("SS Prop Barrel", description="Wooden barrel: bulging staves (seams in the shader from ss_local) and "
                                            "two iron hoops. Origin at the base centre; +Z up")
    h = g.input("Height", "FLOAT", 0.56, min=0.1, max=3, subtype="DISTANCE", desc="Barrel height")
    r = g.input("Radius", "FLOAT", 0.25, min=0.05, max=2, subtype="DISTANCE", desc="Radius at the ends")
    bulge = g.input("Bulge", "FLOAT", 0.18, min=0, max=1, subtype="FACTOR", desc="Extra radius at the belly, "
                                                                                   "relative to Radius")
    with g.frame("Body: cylinder bulged by 1 - (2z - 1)^2"):
        cyl = g.node("GeometryNodeMeshCylinder", Vertices=32, **{"Side Segments": 8}, Radius=1.0, Depth=1.0)
        p = g.separate(g.node("GeometryNodeInputPosition"))
        zt = g.math("ADD", p["Z"], 0.5)
        k = g.math("MULTIPLY", g.math("SUBTRACT", g.math("MULTIPLY", zt, 2.0), 1.0), 1.0)
        rr = g.math("MULTIPLY", r, g.math("ADD", 1.0, g.math("MULTIPLY", bulge, g.math(
            "SUBTRACT", 1.0, g.math("MULTIPLY", k, k)))))
        body = g.node("GeometryNodeSetPosition", Geometry=cyl["Mesh"], Position=g.combine(
            g.math("MULTIPLY", p["X"], rr), g.math("MULTIPLY", p["Y"], rr), g.math("MULTIPLY", zt, h)))
        body = _store(g, body["Geometry"], "ss_local", g.node("GeometryNodeInputPosition"), dtype="FLOAT_VECTOR")
        body = _mat(g, _smooth(g, body, cyl["Side"]), "wood")
    with g.frame("Hoops: open bands just outside the staves at 22% and 78% height"):
        hoops = []
        for f in (0.2, 0.8):
            kk = 2 * f - 1
            hr = g.math("ADD", g.math("MULTIPLY", r, g.math("ADD", 1.0, g.math("MULTIPLY", bulge, 1 - kk * kk))),
                        0.008)
            band = g.node("GeometryNodeMeshCylinder", props={"fill_type": "NONE"}, Vertices=32, Radius=hr,
                          Depth=0.05)
            hoops.append(_xf(g, band["Mesh"], g.combine(0, 0, g.math("MULTIPLY", h, f))))
        hoops = _mat(g, _smooth(g, _join(g, *hoops)), "iron")
    g.output("Geometry", "GEOMETRY", _join(g, body, hoops))
    return g.finish()


def build_pot(rbox, ring, foliage):
    g = Graph("SS Prop Pot", description="Terracotta pot with a rolled rim and a plant: a leafy (optionally "
                                         "flowering) mound or a small conifer. Origin at the base centre; +Z up")
    kind = g.input("Plant", "INT", 0, min=0, max=2, desc="0 leafy, 1 flowering geranium, 2 small conifer")
    seed = g.input("Seed", "INT", 0, desc="Random seed for the leaves")
    with g.frame("Pot: tapered body, rolled rim, soil"):
        cone = g.node("GeometryNodeMeshCone", Vertices=24, **{"Side Segments": 2, "Radius Bottom": 0.13,
                                                              "Radius Top": 0.175, "Depth": 0.27})
        body = _smooth(g, _xf(g, cone["Mesh"], (0, 0, 0.135)), cone["Side"])
        rim = _xf(g, g.group(ring, Radius=0.17, Thickness=0.03), (0, 0, 0.27))
        pot = _mat(g, _join(g, body, rim), "terracotta")
        soil = g.node("GeometryNodeMeshCylinder", Vertices=24, Radius=0.16, Depth=0.02)
        soil = _mat(g, _xf(g, soil["Mesh"], (0, 0, 0.265)), "soil")
    with g.frame("Leafy plant: lumpy mound covered by large leaves (blossoms when flowering)"):
        mound = g.node("GeometryNodeMeshIcoSphere", Radius=0.2, Subdivisions=2)
        mound = _bumpy(g, _xf(g, mound["Mesh"], (0, 0, 0.36), s=(1.05, 1.05, 0.85)), 0.12, 5.0, seed)
        flowering = _cmp(g, "EQUAL", kind, 1, "INT")
        leafy = g.group(foliage, Mesh=mound, Seed=seed, **{
            "Leaf Size": 0.13, "Leaf Density": 150.0, "Leaf Color": (0.07, 0.17, 0.035, 1),
            "Blossom Density": g.math("MULTIPLY", flowering, 35.0), "Blossom Size": 0.1})
    with g.frame("Conifer: three stacked cones, slightly lumpy"):
        tiers = []
        for i, (rb, z) in enumerate(((0.17, 0.34), (0.13, 0.45), (0.09, 0.55))):
            c = g.node("GeometryNodeMeshCone", Vertices=10, **{"Side Segments": 2, "Radius Top": 0.0,
                                                               "Radius Bottom": rb, "Depth": 0.2})
            tiers.append(_xf(g, c["Mesh"], (0, 0, z)))
        tree = _bumpy(g, _join(g, *tiers), 0.05, 9.0, seed)
        tree = g.group(foliage, Mesh=tree, Seed=seed, **{"Leaf Size": 0.06, "Leaf Density": 260.0,
                                                          "Leaf Color": pm.lin((0.16, 0.30, 0.13)),
                                                          "Blossom Density": 0.0})
    plant = _switch(g, "GEOMETRY", _cmp(g, "EQUAL", kind, 2, "INT"), false=leafy, true=tree)
    g.output("Geometry", "GEOMETRY", _join(g, pot, soil, plant))
    return g.finish()


def build_ivy(foliage):
    g = Graph("SS Prop Ivy", description="Ivy mat climbing around a door: a band of leaves around the door "
                                         "frame and over its head, ragged at the edges. Origin on the wall at the "
                                         "door base centre; +X along the wall, +Y out")
    w = g.input("Door Width", "FLOAT", 0.9, min=0.3, max=4, subtype="DISTANCE", desc="Width of the door opening")
    dh = g.input("Door Height", "FLOAT", 2.0, min=0.5, max=5, subtype="DISTANCE", desc="Height of the door")
    spread = g.input("Spread", "FLOAT", 0.45, min=0.05, max=2, subtype="DISTANCE",
                     desc="How far the ivy reaches out from the door frame")
    dens = g.input("Density", "FLOAT", 170.0, min=0, max=3000, desc="Leaves per square unit")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    with g.frame("Wall patch: grid on the wall, keep faces in a ragged band around the door outline"):
        sx = g.math("ADD", w, g.math("MULTIPLY", spread, 2.0))
        sz = g.math("ADD", dh, spread)
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": sx, "Size Y": sz, "Vertices X": 24, "Vertices Y": 30})
        wall = _xf(g, grid["Mesh"], g.combine(0, 0.03, g.math("MULTIPLY", sz, 0.5)), (-math.pi / 2, 0, 0))
        p = g.separate(g.node("GeometryNodeInputPosition"))
        ex = g.math("SUBTRACT", g.math("ABSOLUTE", p["X"]), g.math("MULTIPLY", w, 0.5))
        ez = g.math("SUBTRACT", p["Z"], dh)
        outside = g.math("MAXIMUM", ex, ez, label="distance outside the door outline")
        nz = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Scale=2.2, Detail=2.0, W=seed)
        reach = g.math("MULTIPLY", spread, g.math("MULTIPLY", nz["Fac"], 1.8))
        lowfade = g.math("MULTIPLY", g.math("SUBTRACT", 1.0, g.math("DIVIDE", p["Z"], dh)), 0.6)
        keep = _bool(g, "AND", _cmp(g, "GREATER_THAN", outside, -0.04),
                     _cmp(g, "LESS_THAN", outside, g.math("SUBTRACT", reach, g.math("MULTIPLY", lowfade, spread))))
        patch = g.node("GeometryNodeDeleteGeometry", props={"domain": "FACE"}, Geometry=wall,
                       Selection=_bool(g, "NOT", keep))
    ivy = g.group(foliage, Mesh=patch["Geometry"], Seed=seed, **{
        "Show Mound": False, "Leaf Density": dens, "Leaf Size": 0.095, "Leaf Color": (0.08, 0.16, 0.03, 1),
        "Blossom Density": 0.0})
    g.output("Geometry", "GEOMETRY", ivy)
    return g.finish()


# ---- top group ---------------------------------------------------------------------------------------------------
def build():
    global _MATS
    _MATS = pm.build()
    rbox, rod, ring = build_rounded_box(), build_rod(), build_ring()
    leaf, blossom = build_leaf(), build_blossom()
    foliage = build_foliage(leaf, blossom)
    wbox, awning = build_window_box(rbox, foliage), build_awning(rod)
    lantern, sign = build_lantern(rbox, rod), build_sign(rbox, rod, ring)
    barrel, pot, ivy = build_barrel(rod), build_pot(rbox, ring, foliage), build_ivy(foliage)

    g = Graph(NAME, description="Window boxes, awnings, hanging signs, wall lanterns, ivy, and pots and barrels "
                                "on the verge, placed on the facades' Anchors. Signs swing and lanterns flicker "
                                "with Time")
    anchors = g.input("Anchors", "GEOMETRY", desc="Facade anchor points (SS Facades.Anchors): 'anchor' type, "
                                                  "ss_rot, ss_width, ss_house, ss_rand")
    g.input("Curve", "GEOMETRY", desc="Street path curve (unused: props follow the anchors, which already follow "
                                      "the curve; kept for the shared group contract)")
    seed = g.input("Seed", "INT", 0, desc="Random seed for which anchors get a prop and how it varies")
    time = g.input("Time", "FLOAT", 0.0, subtype="TIME_ABSOLUTE", desc="Seconds; drives sign swing and "
                                                                       "lantern flicker")
    # Window Boxes
    wb_ch = g.input("Window Box Chance", "FLOAT", 0.85, min=0, max=1, subtype="FACTOR", panel="Window Boxes",
                    desc="Share of window sills that get a flower box")
    wb_up = g.input("Upper Floor Share", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR", panel="Window Boxes",
                    desc="Upper-floor sills get a box at Chance times this")
    wb_fd = g.input("Box Flower Density", "FLOAT", 1.0, min=0, max=4, panel="Window Boxes",
                    desc="How many blossoms per box (1 = like the reference)")
    wb_ca = g.input("Flower Red", "COLOR", (0.66, 0.02, 0.012, 1), panel="Window Boxes",
                    desc="Main geranium colour (about half the blossoms)")
    wb_cb = g.input("Flower Coral", "COLOR", (0.88, 0.17, 0.09, 1), panel="Window Boxes",
                    desc="Second geranium colour (about a quarter)")
    wb_cc = g.input("Flower White", "COLOR", (0.88, 0.83, 0.76, 1), panel="Window Boxes",
                    desc="Third geranium colour (the rest)")
    wb_lc = g.input("Leaf Color", "COLOR", (0.10, 0.25, 0.04, 1), panel="Window Boxes",
                    desc="Leaf colour of window boxes and leafy pots")
    # Awnings
    aw_ch = g.input("Awning Chance", "FLOAT", 0.9, min=0, max=1, subtype="FACTOR", panel="Awnings",
                    desc="Share of shopfronts that get an awning")
    aw_c1 = g.input("Stripe Blue", "COLOR", pm.lin((0.42, 0.52, 0.50)) + (1,), panel="Awnings",
                    desc="Cool awnings (green-grey and cream in the reference, about half)")
    aw_c2 = g.input("Stripe Pink", "COLOR", pm.lin((0.70, 0.40, 0.27)) + (1,), panel="Awnings",
                    desc="Warm awnings (peach and cream in the reference, about 40%)")
    aw_c3 = g.input("Stripe Red", "COLOR", (0.58, 0.06, 0.04, 1), panel="Awnings", desc="Red-and-white awnings (rare)")
    aw_d = g.input("Awning Depth", "FLOAT", 1.0, min=0.3, max=2.5, subtype="DISTANCE", panel="Awnings",
                   desc="How far awnings reach out over the verge")
    aw_sw = g.input("Stripe Width", "FLOAT", 0.24, min=0.06, max=0.8, subtype="DISTANCE", panel="Awnings",
                    desc="One coloured plus one cream stripe (and one scallop)")
    # Signs
    sg_ch = g.input("Sign Chance", "FLOAT", 0.25, min=0, max=1, subtype="FACTOR", panel="Signs",
                    desc="Share of bracket spots that get a hanging sign")
    sg_rd = g.input("Round Share", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR", panel="Signs",
                    desc="Share of round boards (the rest are bread boards)")
    sg_pc = g.input("Sign Paint", "COLOR", (0.21, 0.42, 0.37, 1), panel="Signs", desc="Round board face colour")
    # Lanterns
    ln_ch = g.input("Wall Lantern Chance", "FLOAT", 0.3, min=0, max=1, subtype="FACTOR", panel="Lanterns",
                    desc="Share of lantern spots that get a lantern")
    ln_col = g.input("Wall Lantern Glow", "COLOR", (1.0, 0.55, 0.1, 1), panel="Lanterns", desc="Lantern light colour")
    ln_str = g.input("Wall Lantern Strength", "FLOAT", 1.6, min=0, max=100, panel="Lanterns",
                     desc="Emission strength of the panes")
    ln_fl = g.input("Flicker", "FLOAT", 0.12, min=0, max=1, subtype="FACTOR", panel="Lanterns",
                    desc="How much the glow flickers (0 = steady)")
    # Verge
    vg_pc = g.input("Pot Chance", "FLOAT", 0.65, min=0, max=1, subtype="FACTOR", panel="Verge Props",
                    desc="Chance that a verge slot holds a pot")
    vg_bc = g.input("Barrel Chance", "FLOAT", 0.25, min=0, max=1, subtype="FACTOR", panel="Verge Props",
                    desc="Chance that a verge spot starts with a pair of barrels")
    vg_n = g.input("Cluster Size", "INT", 2, min=1, max=8, panel="Verge Props",
                   desc="Slots per verge spot (pots and barrels stand side by side)")
    vg_ps = g.input("Pot Size", "FLOAT", 1.0, min=0.3, max=3, panel="Verge Props", desc="Average pot scale")
    # Ivy
    iv_ch = g.input("Ivy Chance", "FLOAT", 0.35, min=0, max=1, subtype="FACTOR", panel="Ivy",
                    desc="Share of doors framed by ivy")
    iv_sp = g.input("Ivy Spread", "FLOAT", 0.45, min=0.05, max=2, subtype="DISTANCE", panel="Ivy",
                    desc="How far ivy reaches from the door frame")
    # Wind
    wd_amp = g.input("Sign Swing", "FLOAT", math.radians(5.0), min=0, max=0.6, subtype="ANGLE", panel="Wind",
                     desc="Swing amplitude of hanging signs")
    wd_per = g.input("Swing Period", "FLOAT", 2.5, min=0.5, max=10, subtype="TIME_ABSOLUTE", panel="Wind",
                     desc="Seconds per swing (2.5 divides the 20 s loop)")

    with g.frame("Anchor fields: position, frame (ss_rot), width, per-anchor random"):
        pos = g.node("GeometryNodeInputPosition")
        rot = _attr(g, "ss_rot", "QUATERNION")
        width = _attr(g, "ss_width")
        arand = _rand(g, 0.0, 1.0, seed)

    def items(**extra):
        d = {"Pos": ("VECTOR", pos), "Rot": ("ROTATION", rot), "Width": ("FLOAT", width), "Rand": ("FLOAT", arand)}
        d.update(extra)
        return d

    with g.frame("Window boxes on sills (anchor 1, 2): one box per sill, as long as the window plus a margin"):
        ground = _bool(g, "AND", _is_anchor(g, 1), _chance(g, wb_ch, _seed(g, seed, 101)))
        upper = _bool(g, "AND", _is_anchor(g, 2), _chance(g, g.math("MULTIPLY", wb_ch, wb_up), _seed(g, seed, 101)))
        sel = _bool(g, "OR", ground, upper)

        def wb_body(f, idx):
            box = g.group(wbox, Width=g.math("ADD", f["Width"], 0.22), Seed=g.math("ADD", idx, g.math(
                "MULTIPLY", seed, 977)), **{"Flower Density": wb_fd, "Leaf Color": wb_lc, "Color A": wb_ca,
                                            "Color B": wb_cb, "Color C": wb_cc})
            box = _store(g, box, "ss_rand", f["Rand"], dtype="FLOAT")
            return _place(g, box, f["Pos"], f["Rot"])
        boxes = _for_each(g, anchors, sel, items(), wb_body)

    with g.frame("Awnings over shopfronts (anchor 4): width + 0.5, colour picked per shop"):
        sel = _bool(g, "AND", _is_anchor(g, 4), _chance(g, aw_ch, _seed(g, seed, 102)))

        def aw_body(f, idx):
            r = f["Rand"]
            col = _cmix(g, g.math("GREATER_THAN", r, 0.5), aw_c1,
                        _cmix(g, g.math("GREATER_THAN", r, 0.9), aw_c2, aw_c3))
            aw = g.group(awning, Width=g.math("ADD", f["Width"], 0.5), Depth=aw_d,
                         Drop=g.math("MULTIPLY", aw_d, 0.5), **{"Stripe Width": aw_sw, "Stripe Color": col})
            return _place(g, aw, f["Pos"], f["Rot"])
        awnings = _for_each(g, anchors, sel, items(), aw_body)

    with g.frame("Hanging signs (anchor 6): bread or round board, swinging as a pendulum with its own phase"):
        sel = _bool(g, "AND", _is_anchor(g, 6), _chance(g, sg_ch, _seed(g, seed, 103)))

        def sg_body(f, idx):
            r = f["Rand"]
            phase = g.math("ADD", g.math("MULTIPLY", g.math("DIVIDE", time, wd_per), TAU),
                           g.math("MULTIPLY", r, 31.4159))
            ang = g.math("MULTIPLY", wd_amp, g.math("ADD", g.math("SINE", phase), g.math(
                "MULTIPLY", g.math("SINE", g.math("ADD", g.math("MULTIPLY", phase, 2.0), 1.3)), 0.15)))
            sgn = g.group(sign, Round=g.math("LESS_THAN", g.math("FRACT", g.math("MULTIPLY", r, 7.31)), sg_rd),
                          Swing=ang, **{"Paint Color": sg_pc})
            return _place(g, sgn, f["Pos"], f["Rot"])
        signs = _for_each(g, anchors, sel, items(), sg_body)

    with g.frame("Ivy around doors (anchor 3)"):
        sel = _bool(g, "AND", _is_anchor(g, 3), _chance(g, iv_ch, _seed(g, seed, 104)))

        def iv_body(f, idx):
            iv = g.group(ivy, Seed=g.math("ADD", idx, g.math("MULTIPLY", seed, 131)), Spread=iv_sp,
                         **{"Door Width": g.math("MAXIMUM", f["Width"], 0.6)})
            return _place(g, iv, f["Pos"], f["Rot"])
        ivies = _for_each(g, anchors, sel, items(), iv_body)

    with g.frame("Wall lanterns (anchor 5): instanced; glow colour and flickering strength per lantern"):
        sel = _bool(g, "AND", _is_anchor(g, 5), _chance(g, ln_ch, _seed(g, seed, 105)))
        lpts = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=anchors, Selection=sel)
        lpts, lrot = _clean_points(g, lpts["Selection"], rot)
        li = g.node("GeometryNodeInstanceOnPoints", Points=lpts, Instance=g.group(lantern), Rotation=lrot)
        lr = _rand(g, 0.0, 100.0, _seed(g, seed, 106))
        nz = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "1D"}, Scale=1.0, Detail=1.0,
                    W=g.math("ADD", g.math("MULTIPLY", time, 3.0), lr))
        wob = g.math("SINE", g.math("ADD", g.math("MULTIPLY", time, TAU * 1.3), lr))
        flick = g.math("ADD", 1.0, g.math("MULTIPLY", ln_fl, g.math("ADD", g.math(
            "MULTIPLY", g.math("SUBTRACT", nz["Fac"], 0.5), 2.0), g.math("MULTIPLY", wob, 0.4))))
        lan = _store(g, li["Instances"], "ss_glow", g.math("MULTIPLY", ln_str, flick), dtype="FLOAT",
                     domain="INSTANCE")
        lan = _store(g, lan, "ss_color", ln_col, domain="INSTANCE")

    with g.frame("Verge clusters (anchor 7): Cluster Size slots side by side along the wall"):
        vsel = _is_anchor(g, 7)
        vpts = g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=anchors,
                      Selection=vsel)
        vpts = _store(g, vpts["Selection"], "ss_cluster", _rand(g, 0.0, 1.0, _seed(g, seed, 107)), dtype="FLOAT")
        dup = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=vpts, Amount=vg_n)
        n = dup["Duplicate Index"]
        spacing = g.math("MINIMUM", g.math("MAXIMUM", g.math("DIVIDE", _attr(g, "ss_width"), vg_n), 0.5), 0.75)
        x = g.math("ADD", g.math("MULTIPLY", g.math("SUBTRACT", n, g.math("MULTIPLY", g.math(
            "SUBTRACT", vg_n, 1), 0.5)), spacing), _rand(g, -0.08, 0.08, _seed(g, seed, 108)))
    with g.frame("Verge: what stands in each slot (0 barrel, 1 leafy pot, 2 flowering pot, 3 conifer, none)"):
        barrel_here = _bool(g, "AND", _cmp(g, "LESS_THAN", _attr(g, "ss_cluster"), vg_bc),
                            _cmp(g, "LESS_THAN", n, 2, "INT"))
        u = _rand(g, 0.0, 1.0, _seed(g, seed, 109))
        pot_here = _cmp(g, "LESS_THAN", _rand(g, 0.0, 1.0, _seed(g, seed, 110)), vg_pc)
        keep = _bool(g, "OR", barrel_here, pot_here)
        pot_kind = g.math("ADD", 1.0, g.math("ADD", g.math("GREATER_THAN", u, 0.55), g.math(
            "GREATER_THAN", u, 0.85)))
        kind = _switch(g, "INT", barrel_here, false=pot_kind,
                      true=0)
        pscale = g.math("MULTIPLY", vg_ps, _rand(g, 0.7, 1.35, _seed(g, seed, 111)))
        scale = _switch(g, "FLOAT", barrel_here, false=pscale,
                       true=_rand(g, 0.92, 1.05, _seed(g, seed, 112)))
        y = _switch(g, "FLOAT", barrel_here,
                   false=g.math("ADD", 0.08, g.math("MULTIPLY", pscale, 0.19)), true=0.34)
    with g.frame("Verge: move each slot out from the wall in the anchor frame, instance with a random turn"):
        vrot = _attr(g, "ss_rot", "QUATERNION")
        off = g.node("FunctionNodeRotateVector", Vector=g.combine(x, y, 0.0), Rotation=vrot)
        moved = g.node("GeometryNodeSetPosition", Geometry=dup["Geometry"], Offset=off)
        turn = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=vrot, **{
            "Rotate By": g.node("FunctionNodeEulerToRotation", Euler=g.combine(0, 0, _rand(
                g, 0, TAU, _seed(g, seed, 113))))})
        slots = g.node("GeometryNodeCaptureAttribute", props={"domain": "POINT"})
        for nm, typ in (("Turn", "ROTATION"), ("Kind", "INT"), ("Scale", "FLOAT"), ("Keep", "BOOLEAN")):
            slots.b.capture_items.new(typ, nm)
        slots.set(Geometry=moved["Geometry"], Turn=turn, Kind=kind, Scale=scale, Keep=keep)
        spts, _ = _clean_points(g, slots["Geometry"], vrot)
        pot_variants = [g.group(barrel)] + [g.group(pot, Plant=k, Seed=g.math("ADD", seed, 17 * k)) for k in range(3)]
        lib = g.node("GeometryNodeGeometryToInstance")
        for v in reversed(pot_variants):
            g.connect(v, lib.i("Geometry"))
        vi = g.node("GeometryNodeInstanceOnPoints", Points=spts, Selection=slots["Keep"],
                    Instance=lib["Instances"], Rotation=slots["Turn"], Scale=slots["Scale"], **{
                        "Pick Instance": True, "Instance Index": slots["Kind"]})
        verge = _store(g, vi["Instances"], "ss_rand", _rand(g, 0.0, 1.0, _seed(g, seed, 114)), dtype="FLOAT",
                       domain="INSTANCE")

    g.output("Geometry", "GEOMETRY", _join(g, boxes, awnings, signs, ivies, lan, verge))
    return g.finish()


# ---- mock anchors for testing until SS Facades lands ----------------------------------------------------------
# (type, offset along the house, height, width, chance) per house slot; houses are HOUSE units wide
HOUSE = 3.2
_SLOTS = [
    (3, 2.2, 0.0, 0.9, 1.0),      # door
    (5, 1.52, 1.65, 0.0, 0.6),    # lantern beside the door
    (1, 0.9, 0.85, 0.8, 1.0),     # ground-floor window
    (4, 0.9, 2.0, 1.0, 0.45),     # shopfront top over that window
    (2, 0.9, 2.75, 0.62, 1.0),    # first-floor windows
    (2, 2.3, 2.75, 0.62, 1.0),
    (2, 0.9, 4.35, 0.56, 1.0),    # second floor
    (2, 2.3, 4.35, 0.56, 1.0),
    (6, 2.95, 2.3, 0.0, 0.4),     # sign bracket past the door
    (7, 1.0, 0.0, 1.6, 0.8),      # verge spot in front of the window
]


def build_mock():
    pt = frame.build()
    g = Graph("SS Props Mock Anchors", description="TEST ONLY: plausible facade anchors on both facade lines "
                                                   "(|d| = 3) plus flat walls and dark openings for context. "
                                                   "Replace with SS Facades.Anchors")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    fd = g.input("Facade Offset", "FLOAT", 3.0, min=0.5, max=20, subtype="DISTANCE",
                 desc="Distance from the path to the facade line")
    with g.frame("Houses along the path, both sides"):
        length = g.node("GeometryNodeCurveLength", Curve=curve)
        nh = g.math("FLOOR", g.math("DIVIDE", g.math("SUBTRACT", length, 1.0), HOUSE))
    pts_all, ctx = [], []
    for k, (atype, off, h, wdt, ch) in enumerate(_SLOTS):
        with g.frame(f"Slot {k}: anchor {atype}"):
            line = g.node("GeometryNodeMeshLine", props={"mode": "OFFSET"}, Count=g.math("MULTIPLY", nh, 2.0),
                          Offset=(0, 0, 0))
            idx = g.node("GeometryNodeInputIndex")
            house = g.math("FLOOR", g.math("DIVIDE", idx, 2.0))
            side = g.math("SUBTRACT", g.math("MULTIPLY", g.math("MODULO", idx, 2.0), 2.0), 1.0)
            s = g.math("ADD", g.math("MULTIPLY", house, HOUSE), off + 0.5)
            s = g.math("ADD", s, g.math("MULTIPLY", side, 0.9))   # stagger the two sides
            sp = g.group(pt, Curve=curve, Length=s, Offset=g.math("MULTIPLY", side, fd), Height=h)
            back = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=sp["Rotation"],
                          **{"Rotate By": g.node("FunctionNodeEulerToRotation", Euler=(0, 0, math.pi))})
            rot = _switch(g, "ROTATION", g.math("GREATER_THAN", side, 0.0), false=sp["Rotation"], true=back["Rotation"])
            geo = g.node("GeometryNodeSetPosition", Geometry=line["Mesh"], Position=sp["Position"])["Geometry"]
            geo = _store(g, geo, "anchor", atype, dtype="INT")
            geo = _store(g, geo, "ss_rot", rot, dtype="QUATERNION")
            geo = _store(g, geo, "ss_width", g.math("ADD", wdt, _rand(g, -0.05, 0.1, _seed(g, seed, k))),
                         dtype="FLOAT")
            geo = _store(g, geo, "ss_house", g.math("ADD", g.math("MULTIPLY", house, 2.0), g.math(
                "MODULO", idx, 2.0)), dtype="INT")
            geo = _store(g, geo, "ss_rand", _rand(g, 0.0, 1.0, _seed(g, seed, 50 + k)), dtype="FLOAT")
            drop = _bool(g, "NOT", _chance(g, ch, _seed(g, seed, 90 + k)))
            pts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=geo, Selection=drop)
            pts_all.append(pts["Geometry"])
    with g.frame("Context: flat walls and ground along both facade lines"):
        walls = []
        for side in (-1.0, 1.0):
            line = g.node("GeometryNodeMeshLine", props={"mode": "OFFSET"},
                          Count=g.math("FLOOR", g.math("MULTIPLY", length, 2.0)), Offset=(0, 0, 0))
            s = g.math("MULTIPLY", g.node("GeometryNodeInputIndex"), 0.5)
            sp = g.group(pt, Curve=curve, Length=s, Offset=g.math("MULTIPLY", fd, side))
            base = g.node("GeometryNodeSetPosition", Geometry=line["Mesh"], Position=sp["Position"])["Geometry"]
            up = g.node("GeometryNodeExtrudeMesh", props={"mode": "EDGES"}, Mesh=base, Offset=g.combine(0, 0, 6.0))
            inward = g.vmath("SCALE", sp["Left"], scale=g.math("MULTIPLY", fd, -side))
            ground = g.node("GeometryNodeExtrudeMesh", props={"mode": "EDGES"}, Mesh=base, Offset=inward)
            walls.append(_mat_flat(g, up["Mesh"], "SS Props Mock Wall", (0.80, 0.55, 0.32)))
            walls.append(_mat_flat(g, ground["Mesh"], "SS Props Mock Ground", (0.36, 0.33, 0.26)))
    anchors = _join(g, *pts_all)
    with g.frame("Context: dark window and door openings at sill and door anchors"):
        a = _attr(g, "anchor", "INT")
        isw = _bool(g, "OR", _cmp(g, "EQUAL", a, 1, "INT"), _cmp(g, "EQUAL", a, 2, "INT"))
        isd = _cmp(g, "EQUAL", a, 3, "INT")
        sel = _bool(g, "OR", isw, isd)
        quad = g.node("GeometryNodeMeshGrid", **{"Size X": 1.0, "Size Y": 1.0, "Vertices X": 2, "Vertices Y": 2})
        quad = _xf(g, quad["Mesh"], (0, 0.01, 0.5), (math.pi / 2, 0, 0))
        hgt = _switch(g, "FLOAT", isd, false=1.15, true=2.0)
        holes = g.node("GeometryNodeInstanceOnPoints", Points=anchors, Selection=sel, Instance=quad,
                       Rotation=_attr(g, "ss_rot", "QUATERNION"),
                       Scale=g.combine(_attr(g, "ss_width"), 1.0, hgt))
        holes = g.node("GeometryNodeRealizeInstances", Geometry=holes["Instances"])["Geometry"]
        walls.append(_mat_flat(g, holes, "SS Props Mock Opening", (0.12, 0.09, 0.07)))
    g.output("Anchors", "GEOMETRY", anchors)
    g.output("Context", "GEOMETRY", _join(g, *walls))
    return g.finish()


def _mat_flat(g, geo, name, rgb):
    return g.node("GeometryNodeSetMaterial", Geometry=geo, Material=common.flat(name, pm.lin(rgb)))["Geometry"]


def test_inputs(w, gn, info):
    """tools/try_group.py hook: feed mock anchors into SS Props and add the mock walls to the test output.
    In the assembly, connect SS Facades.Anchors to SS Props.Anchors instead."""
    mock = w.group(build_mock(), label="MOCK anchors: replace with SS Facades.Anchors", Curve=info["Geometry"])
    w.connect(mock["Anchors"], gn.i("Anchors"))
    orig = w.output

    def output(name, stype, value=None, desc=""):
        if stype == "GEOMETRY" and value is not None:
            value = _join(w, value, mock["Context"])
        return orig(name, stype, value, desc)
    w.output = output
