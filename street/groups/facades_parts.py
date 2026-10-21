"""House part groups for SS Facades (owner: facades). See street/groups/facades.py for the overview.

Every part group takes the ``Houses`` point cloud (one point per house, carrying the plan attributes ``h_*`` written
by SS House Plan) and returns instances modelled in HOUSE-LOCAL space:

    x along the wall (0 at the parcel centre, house spans -w/2..w/2), y out of the wall toward the street
    (0 = ground-floor facade plane, the house body extends to y = -depth), z up from the street surface.

Upper floor k (k = 1..storeys-1) has its facade at y = k * jetty; the floor bases are z = 0 (ground, from below the
street to hide slopes), G, G+F, ... SS House Place later moves every vertex to the world through its house's frame.
Pieces are unit shapes instanced at a centre with a size (SS House Boxes), so each part reads as a list of
"centre, size" formulas.
"""
import math
from v2n.graph import Graph
from street.materials import facades as fm

SPREAD = 60.0            # SS House Cut moves house i to x + i * SPREAD so each house is cut on its own
REVEAL = 0.24            # window reveal depth (how deep the glass sits behind the wall face)
DOOR_REVEAL = 0.2
FRAME_COLOR = fm.hexc("#E9DDC2")
STONE_COLOR = fm.hexc("#9A8670")
CHIMNEY_COLOR = fm.hexc("#8E6A55")
IRON_COLOR = fm.hexc("#222018")


# ---- field shorthands ----------------------------------------------------------------------------------------
def add(g, a, b): return g.math("ADD", a, b)
def sub(g, a, b): return g.math("SUBTRACT", a, b)
def mul(g, a, b): return g.math("MULTIPLY", a, b)
def div(g, a, b): return g.math("DIVIDE", a, b)
def mad(g, a, b, c): return g.math("MULTIPLY_ADD", a, b, c)
def mx(g, a, b): return g.math("MAXIMUM", a, b)
def mn(g, a, b): return g.math("MINIMUM", a, b)
def half(g, a): return g.math("MULTIPLY", a, 0.5)
def neg(g, a): return g.math("MULTIPLY", a, -1.0)


def vec(g, x=0.0, y=0.0, z=0.0):
    return g.combine(x, y, z)["Vector"]


def xyz(g, v):
    s = g.separate(v)
    return s["X"], s["Y"], s["Z"]


def attr(g, name, dt="FLOAT"):
    return g.node("GeometryNodeInputNamedAttribute", props={"data_type": dt}, Name=name)["Attribute"]


def store(g, geo, name, value, dt="FLOAT", domain="POINT"):
    return g.node("GeometryNodeStoreNamedAttribute", props={"data_type": dt, "domain": domain}, Geometry=geo,
                  Name=name, Value=value)["Geometry"]


def rnd(g, lo, hi, ident, seed, dt="FLOAT"):
    return g.node("FunctionNodeRandomValue", props={"data_type": dt}, Min=lo, Max=hi, ID=ident, Seed=seed)["Value"]


def chance(g, p, ident, seed):
    return g.node("FunctionNodeRandomValue", props={"data_type": "BOOLEAN"}, Probability=p, ID=ident,
                  Seed=seed)["Value"]


def sw(g, cond, if_false, if_true, dt="FLOAT"):
    return g.node("GeometryNodeSwitch", props={"input_type": dt}, Switch=cond,
                  **{"False": if_false, "True": if_true})["Output"]


def iswitch(g, idx, items, dt="FLOAT"):
    n = g.node("GeometryNodeIndexSwitch", props={"data_type": dt})
    while len([s for s in n.b.inputs if s.enabled and s.name not in ("", "Index")]) < len(items):
        n.b.index_switch_items.new()
    g.connect(idx, n.i("Index"))
    for k, v in enumerate(items):
        g.connect(v, n.i(str(k)))
    return n["Output"]


def cmp(g, a, b, op="GREATER_THAN"):
    return g.node("FunctionNodeCompare", props={"data_type": "FLOAT", "operation": op}, A=a, B=b)["Result"]


def both(g, a, b, op="AND"):
    n = g.node("FunctionNodeBooleanMath", props={"operation": op})
    g.connect(a, n.i(0))
    g.connect(b, n.i(1))
    return n["Boolean"]


def dup(g, geo, amount):
    n = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=geo, Amount=amount)
    return n["Geometry"], n["Duplicate Index"]


def euler(g, x=0.0, y=0.0, z=0.0):
    return g.node("FunctionNodeEulerToRotation", Euler=vec(g, x, y, z))["Rotation"]


def join(g, *geos):
    j = g.node("GeometryNodeJoinGeometry")
    for x in reversed(geos):
        g.connect(x, j.i("Geometry"))
    return j["Geometry"]


def strut_xz(g, ax, az, bx, bz):
    """A beam from (ax, az) to (bx, bz) in the wall plane: centre x, centre z, length, rotation (local X along it)."""
    dx, dz = sub(g, bx, ax), sub(g, bz, az)
    length = g.math("SQRT", add(g, mul(g, dx, dx), mul(g, dz, dz)))
    ang = g.math("ARCTAN2", neg(g, dz), dx)
    return half(g, add(g, ax, bx)), half(g, add(g, az, bz)), length, euler(g, 0.0, ang, 0.0)


def strut_yz(g, ay, az, by, bz):
    """A beam from (ay, az) to (by, bz) across the wall: centre y, centre z, length, rotation (local Z along it)."""
    dy, dz = sub(g, by, ay), sub(g, bz, az)
    length = g.math("SQRT", add(g, mul(g, dy, dy), mul(g, dz, dz)))
    ang = g.math("ARCTAN2", neg(g, dy), dz)
    return half(g, add(g, ay, by)), half(g, add(g, az, bz)), length, euler(g, ang, 0.0, 0.0)


class House:
    """Named-attribute reads of the house plan, created lazily inside the current frame."""

    def __init__(self, g):
        self.g = g

    def __getattr__(self, k):
        types = {"storeys": "INT", "timber": "INT", "cols": "INT", "gwin": "INT", "shutter": "BOOLEAN",
                 "shop": "BOOLEAN", "door_arch": "BOOLEAN", "gable": "BOOLEAN", "slate": "BOOLEAN",
                 "chimney": "BOOLEAN", "color": "FLOAT_COLOR", "door_color": "FLOAT_COLOR",
                 "shutter_color": "FLOAT_COLOR", "roof_color": "FLOAT_COLOR"}
        return attr(self.g, "h_" + k, types.get(k, "FLOAT"))


def floor_base(g, h, k):
    """z of floor k's base: 0 for the ground floor, G + (k-1) F above."""
    return sw(g, cmp(g, k, 0.5, "LESS_THAN"), mad(g, sub(g, k, 1.0), h.floor_h, h.ground_h), 0.0)


def floor_top(g, h, k):
    return mad(g, k, h.floor_h, h.ground_h)


def top_z(g, h):
    """Wall top (eaves line): G + (storeys - 1) F."""
    return mad(g, sub(g, h.storeys, 1.0), h.floor_h, h.ground_h)


def top_y(g, h):
    """Facade plane of the top floor: (storeys - 1) * jetty."""
    return mul(g, sub(g, h.storeys, 1.0), h.jetty)


# ---- SS House Boxes ------------------------------------------------------------------------------------------
_BOXES = None


def boxes():
    global _BOXES
    if _BOXES is not None:
        return _BOXES
    g = Graph("SS House Boxes", description="One shaped piece per point: a box, a roof prism, a cylinder or an "
                                            "arch ring, at Center with Size and Rotation (house-local). Writes "
                                            "ss_color, ss_size, ss_rand; the unit shape carries ss_unit")
    pts = g.input("Points", "GEOMETRY", desc="One point per piece; house attributes ride along")
    sel = g.input("Selection", "BOOL", True, desc="Which points get a piece")
    center = g.input("Center", "VECTOR", (0.0, 0.0, 0.0), subtype="TRANSLATION", desc="Piece centre (field)")
    size = g.input("Size", "VECTOR", (1.0, 1.0, 1.0), subtype="XYZ", desc="Piece size along its local axes")
    rot = g.input("Rotation", "ROTATION", desc="Piece rotation in the house frame")
    color = g.input("Color", "COLOR", (0.8, 0.8, 0.8, 1.0), desc="Tint written to ss_color")
    shape = g.input("Shape", "INT", 0, min=0, max=3,
                    desc="0 box, 1 prism (ridge along X on top), 2 cylinder along Y, 3 half arch ring in XZ")
    mat = g.input("Material", "MATERIAL", desc="Material of the pieces")
    with g.frame("Unit shapes (1 H cube bounds); ss_unit = position + 0.5 gives materials local coordinates"):
        cube = g.node("GeometryNodeMeshCube", Size=(1.0, 1.0, 1.0))["Mesh"]
        pz = xyz(g, g.node("GeometryNodeInputPosition")["Position"])
        top = cmp(g, pz[2], 0.0)
        ridge = g.node("GeometryNodeSetPosition", Geometry=cube, Selection=top, Position=vec(g, pz[0], 0.0, pz[2]))
        prism = g.node("GeometryNodeMergeByDistance", Geometry=ridge["Geometry"], Distance=0.001)["Geometry"]
        cyl = g.node("GeometryNodeMeshCylinder", props={"fill_type": "NGON"}, Vertices=24, Radius=0.5,
                     Depth=1.0)["Mesh"]
        cyl = g.node("GeometryNodeTransform", Geometry=cyl, Rotation=(math.pi / 2, 0.0, 0.0))["Geometry"]
        arc = g.node("GeometryNodeCurveArc", props={"mode": "RADIUS"}, Resolution=14, Radius=0.57,
                     **{"Start Angle": 0.0, "Sweep Angle": math.pi})["Curve"]
        prof = g.node("GeometryNodeCurvePrimitiveQuadrilateral", props={"mode": "RECTANGLE"}, Width=0.14,
                      Height=0.14)["Curve"]
        ring = g.node("GeometryNodeCurveToMesh", Curve=arc, **{"Profile Curve": prof, "Fill Caps": True})["Mesh"]
        ring = g.node("GeometryNodeTransform", Geometry=ring, Rotation=(math.pi / 2, 0.0, 0.0))["Geometry"]
        unit = iswitch(g, shape, [cube, prism, cyl, ring], "GEOMETRY")
        pos = g.node("GeometryNodeInputPosition")["Position"]
        unit = store(g, unit, "ss_unit", g.vmath("ADD", pos, (0.5, 0.5, 0.5)), "FLOAT_VECTOR")
        unit = g.node("GeometryNodeSetMaterial", Geometry=unit, Material=mat)["Geometry"]
    with g.frame("One piece per point: move to Center, record tint and size, instance the shape"):
        p = g.node("GeometryNodeSetPosition", Geometry=pts, Position=center)["Geometry"]
        p = store(g, p, "ss_color", color, "FLOAT_COLOR")
        p = store(g, p, "ss_size", size, "FLOAT_VECTOR")
        idx = g.node("GeometryNodeInputIndex")["Index"]
        p = store(g, p, "ss_rand", rnd(g, 0.0, 1.0, idx, attr(g, "ss_house", "INT")), "FLOAT")
        inst = g.node("GeometryNodeInstanceOnPoints", Points=p, Selection=sel, Instance=unit, Rotation=rot,
                      Scale=size)["Instances"]
        for pat in ("h_*", "w_*", "t_*"):
            inst = g.node("GeometryNodeRemoveAttribute", **{"Pattern Mode": "Wildcard"}, Geometry=inst,
                          Name=pat)["Geometry"]
    g.output("Instances", "GEOMETRY", inst)
    _BOXES = g.finish()
    return _BOXES


def reset():
    global _BOXES, _WINDOW
    _BOXES = None
    _WINDOW = None


def piece(g, pts, center, size, color, mat, rot=None, sel=None, shape=0):
    n = g.group(boxes(), Points=pts, Center=center, Size=size, Color=color, Material=fm.get(mat), Shape=shape)
    if rot is not None:
        g.connect(rot, n.i("Rotation"))
    if sel is not None:
        g.connect(sel, n.i("Selection"))
    return n["Instances"]


# ---- SS House Window (one window: reveal cutter, glass, frame, mullions, sill, shutters) ----------------------
_WINDOW = None


def window():
    global _WINDOW
    if _WINDOW is not None:
        return _WINDOW
    g = Graph("SS House Window", description="Builds one window per point from w_center (on the facade plane), "
                                             "w_size (width, 0, height), w_panes and w_shutter: a reveal cutter, "
                                             "glass set back in the reveal, a painted frame with crossbars, a "
                                             "sill and louvred shutters")
    pts = g.input("Windows", "GEOMETRY", desc="One point per window with w_* attributes")
    shutter_col = g.input("Shutter Color", "COLOR", fm.hexc("#4F6E58"), desc="Shutter paint")
    timber_col = g.input("Timber Color", "COLOR", fm.hexc("#4A2E1C"), desc="Sill timber")
    with g.frame("Window frame of reference: centre C on the wall plane, width ww, height wh"):
        cx, cy, cz = xyz(g, attr(g, "w_center", "FLOAT_VECTOR"))
        ww, _, wh = xyz(g, attr(g, "w_size", "FLOAT_VECTOR"))
        hc = attr(g, "h_color", "FLOAT_COLOR")
        yb = sub(g, cy, REVEAL)                         # back of the reveal
        yfr = add(g, yb, 0.075)                         # frame plane
    with g.frame("Reveal cutter (subtracted from the wall) and the glass deep in it"):
        cut = piece(g, pts, vec(g, cx, half(g, add(g, cy, add(g, yb, 0.06))), cz),
                    vec(g, ww, add(g, REVEAL, 0.06), wh), hc, "plaster")
        glass = piece(g, pts, vec(g, cx, add(g, yb, 0.04), cz), vec(g, ww, 0.02, wh), (1, 1, 1, 1), "glass")
    with g.frame("Frame: four bars, a transom and w_panes - 1 mullions"):
        fpts, q = dup(g, pts, 4)
        hw, hh = half(g, ww), half(g, wh)
        ft = 0.07
        fx = iswitch(g, q, [add(g, sub(g, cx, hw), ft / 2), sub(g, add(g, cx, hw), ft / 2), cx, cx])
        fz = iswitch(g, q, [cz, cz, sub(g, add(g, cz, hh), ft / 2), add(g, sub(g, cz, hh), ft / 2)])
        fsx = iswitch(g, q, [ft, ft, ww, ww])
        fsz = iswitch(g, q, [wh, wh, ft, ft])
        frame_ = piece(g, fpts, vec(g, fx, yfr, fz), vec(g, fsx, 0.08, fsz), FRAME_COLOR, "frame")
        tp, tq = dup(g, pts, 2)
        tz = mad(g, wh, sub(g, mul(g, tq, 0.36), 0.18), cz)       # transoms at -0.18 and +0.18 of the height
        tran = piece(g, tp, vec(g, cx, yfr, tz), vec(g, ww, 0.06, 0.045), FRAME_COLOR, "frame")
        panes = attr(g, "w_panes", "INT")
        mpts, mq = dup(g, pts, sub(g, panes, 1.0))
        mxp = mad(g, div(g, add(g, mq, 1.0), panes), ww, sub(g, cx, hw))
        mull = piece(g, mpts, vec(g, mxp, yfr, cz), vec(g, 0.045, 0.06, wh), FRAME_COLOR, "frame")
    with g.frame("Sill board under the window"):
        sill = piece(g, pts, vec(g, cx, add(g, cy, 0.03), sub(g, sub(g, cz, hh), 0.04)),
                     vec(g, add(g, ww, 0.2), 0.22 + 0.0, 0.08), timber_col, "timber")
    with g.frame("Surround (w_surround): a thick plaster casing around the reveal, paler than the wall"):
        cs = 0.11
        rp, rq = dup(g, pts, sw(g, attr(g, "w_surround", "BOOLEAN"), 0, 4, "INT"))
        rx = iswitch(g, rq, [sub(g, sub(g, cx, hw), cs / 2), add(g, add(g, cx, hw), cs / 2), cx, cx])
        rz = iswitch(g, rq, [cz, cz, add(g, add(g, cz, hh), cs / 2), sub(g, sub(g, cz, hh), cs / 2)])
        rsx = iswitch(g, rq, [cs, cs, add(g, ww, 2 * cs), add(g, ww, 2 * cs)])
        rsz = iswitch(g, rq, [add(g, wh, 2 * cs), add(g, wh, 2 * cs), cs, cs])
        pale = g.vmath("ADD", g.vmath("SCALE", attr(g, "h_color", "FLOAT_COLOR"), scale=0.55),
                       g.vmath("SCALE", FRAME_COLOR[:3], scale=0.45))
        surround = piece(g, rp, vec(g, rx, add(g, cy, 0.02), rz), vec(g, rsx, 0.07, rsz), pale, "plaster")
    with g.frame("Shutters: two louvred leaves folded back against the wall"):
        spts, sq = dup(g, pts, sw(g, attr(g, "w_shutter", "BOOLEAN"), 0, 2, "INT"))
        sgn = sub(g, mul(g, sq, 2.0), 1.0)
        push = sw(g, attr(g, "w_surround", "BOOLEAN"), 0.02, 0.02 + cs)
        sws = mx(g, mul(g, ww, 0.6), 0.2)                             # ~0.35 H leaves (REFERENCE 2)
        sx = add(g, cx, mul(g, sgn, add(g, add(g, half(g, ww), half(g, sws)), push)))
        shut = piece(g, spts, vec(g, sx, add(g, cy, 0.035), cz), vec(g, sws, 0.04, add(g, wh, 0.03)),
                     shutter_col, "shutter")
    g.output("Geometry", "GEOMETRY", join(g, glass, frame_, tran, mull, sill, surround, shut))
    g.output("Cutters", "GEOMETRY", cut)
    _WINDOW = g.finish()
    return _WINDOW


def window_points(g, pts, center, size, panes, shutter, surround=False):
    pts = store(g, pts, "w_surround", surround, "BOOLEAN")
    pts = store(g, pts, "w_center", center, "FLOAT_VECTOR")
    pts = store(g, pts, "w_size", size, "FLOAT_VECTOR")
    pts = store(g, pts, "w_panes", panes, "INT")
    pts = store(g, pts, "w_shutter", shutter, "BOOLEAN")
    return pts


def anchor_points(g, pts, kind, pos, width, seed):
    """Turn points into Facades->Props anchors (house-local; SS House Place adds the world frame and ss_rot)."""
    pts = g.node("GeometryNodeSetPosition", Geometry=pts, Position=pos)["Geometry"]
    pts = store(g, pts, "anchor", kind, "INT")
    pts = store(g, pts, "ss_width", width, "FLOAT")
    idx = g.node("GeometryNodeInputIndex")["Index"]
    pts = store(g, pts, "ss_rand", rnd(g, 0.0, 1.0, idx, add(g, seed, mul(g, kind, 101.0))), "FLOAT")
    return pts


# ---- SS House Body -------------------------------------------------------------------------------------------
def body():
    g = Graph("SS House Body", description="Plaster wall blocks per storey with jettied upper floors, the "
                                           "bressummer beams and joist ends at each jetty, carved corbels under "
                                           "them, and a stone plinth either side of the door")
    houses = g.input("Houses", "GEOMETRY", desc="House points with the plan attributes (SS House Plan)")
    tcol = g.input("Timber Color", "COLOR", fm.hexc("#4A2E1C"), desc="Colour of beams, joist ends and corbels")
    bw = g.input("Beam Width", "FLOAT", 0.16, min=0.04, max=0.4, subtype="DISTANCE",
                 desc="Thickness of the jetty beams and corbels")
    with g.frame("Wall blocks: one plaster box per storey, each jettied further toward the street"):
        fl, k = dup(g, houses, attr(g, "h_storeys", "INT"))
        h = House(g)
        z0 = sw(g, cmp(g, k, 0.5, "LESS_THAN"), floor_base(g, h, k), -1.0)
        z1 = sub(g, floor_top(g, h, k), 0.004)
        yf = mul(g, k, h.jetty)
        walls = piece(g, fl, vec(g, 0.0, half(g, sub(g, yf, h.depth)), half(g, add(g, z0, z1))),
                      vec(g, add(g, h.width, 0.04), add(g, yf, h.depth), sub(g, z1, z0)), h.color, "plaster")
    with g.frame("Bressummer at every floor line and the wall plate under the eaves"):
        bm, k = dup(g, houses, sub(g, attr(g, "h_storeys", "INT"), 1.0))
        h = House(g)
        k1 = add(g, k, 1.0)
        z = floor_base(g, h, k1)
        y = mul(g, k1, h.jetty)
        beams = piece(g, bm, vec(g, 0.0, sub(g, y, 0.06), z),
                      vec(g, add(g, h.width, 0.05), 0.24, mul(g, bw, 1.3)), tcol, "timber")
        top = piece(g, houses, vec(g, 0.0, sub(g, top_y(g, h), 0.06), sub(g, top_z(g, h), 0.05)),
                    vec(g, add(g, h.width, 0.05), 0.24, bw), tcol, "timber")
    with g.frame("Joist ends poking out under each jetty"):
        nj = mx(g, g.math("ROUND", div(g, attr(g, "h_width"), 0.62)), 2.0)
        jp, q = dup(g, houses, mul(g, sub(g, attr(g, "h_storeys", "INT"), 1.0), nj))
        h = House(g)
        nj2 = mx(g, g.math("ROUND", div(g, h.width, 0.62)), 2.0)
        kk = add(g, g.math("FLOOR", div(g, q, nj2)), 1.0)
        jj = g.math("FLOORED_MODULO", q, nj2)
        jx = sub(g, mul(g, div(g, add(g, jj, 0.5), nj2), h.width), half(g, h.width))
        y0 = mul(g, sub(g, kk, 1.0), h.jetty)
        y1 = add(g, mul(g, kk, h.jetty), 0.02)
        joists = piece(g, jp, vec(g, jx, half(g, add(g, y0, y1)), sub(g, floor_base(g, h, kk), 0.17)),
                       vec(g, 0.1, sub(g, y1, y0), 0.11), tcol, "timber")
    with g.frame("Carved corbels: angled struts from the lower wall up under each jetty, at posts and corners"):
        nc = add(g, attr(g, "h_cols", "INT"), 1.0)
        cp, q = dup(g, houses, mul(g, sub(g, attr(g, "h_storeys", "INT"), 1.0), nc))
        h = House(g)
        nc2 = add(g, h.cols, 1.0)
        kk = add(g, g.math("FLOOR", div(g, q, nc2)), 1.0)
        jj = g.math("FLOORED_MODULO", q, nc2)
        lim = sub(g, half(g, h.width), 0.1)
        cx = g.math("MINIMUM", g.math("MAXIMUM", sub(g, mul(g, div(g, jj, h.cols), h.width), half(g, h.width)),
                                      neg(g, lim)), lim)
        zb = floor_base(g, h, kk)
        cy, cz, cl, crot = strut_yz(g, mul(g, sub(g, kk, 1.0), h.jetty), sub(g, zb, 0.5),
                                    sub(g, mul(g, kk, h.jetty), 0.06), sub(g, zb, 0.16))
        corb = piece(g, cp, vec(g, cx, add(g, cy, 0.04), cz), vec(g, mul(g, bw, 1.1), 0.14, add(g, cl, 0.08)),
                     tcol, "timber", rot=crot)
        pad = piece(g, cp, vec(g, cx, add(g, mul(g, sub(g, kk, 1.0), h.jetty), 0.03), sub(g, zb, 0.6)),
                    vec(g, mul(g, bw, 1.25), 0.1, 0.16), tcol, "timber")
    with g.frame("Stone plinth (houses with h_plinth): two runs, either side of the door"):
        pp, q = dup(g, houses, sw(g, attr(g, "h_plinth", "BOOLEAN"), 0, 2, "INT"))
        h = House(g)
        hw = half(g, h.width)
        dl = sub(g, h.door_x, add(g, half(g, h.door_w), 0.16))
        dr = add(g, h.door_x, add(g, half(g, h.door_w), 0.16))
        x0 = sw(g, cmp(g, q, 0.5), neg(g, hw), dr)
        x1 = sw(g, cmp(g, q, 0.5), dl, hw)
        ztop = add(g, h.level, 0.4)
        plinth = piece(g, pp, vec(g, half(g, add(g, x0, x1)), -0.11, half(g, sub(g, ztop, 1.0))),
                       vec(g, mx(g, sub(g, x1, x0), 0.0), 0.38, add(g, ztop, 1.0)), STONE_COLOR, "stone",
                       sel=cmp(g, sub(g, x1, x0), 0.05))
    g.output("Walls", "GEOMETRY", walls)
    g.output("Geometry", "GEOMETRY", join(g, beams, top, joists, corb, pad, plinth))
    return g.finish()


# ---- SS House Timber -----------------------------------------------------------------------------------------
def timber():
    g = Graph("SS House Timber", description="Half-timber frames on the facades. Pattern per house (h_timber): "
                                             "0 plain plaster, 1 posts and rails, 2 posts, rails and full-height "
                                             "corner braces, 3 posts, rails and St Andrew's crosses under the "
                                             "windows")
    houses = g.input("Houses", "GEOMETRY", desc="House points with the plan attributes")
    tcol = g.input("Timber Color", "COLOR", fm.hexc("#4A2E1C"), desc="Colour of the frame timbers")
    bw = g.input("Beam Width", "FLOAT", 0.16, min=0.04, max=0.4, subtype="DISTANCE",
                 desc="Width of posts, rails and braces")
    with g.frame("Timbered storeys: one point per storey of every timbered house"):
        h = House(g)
        fl, k = dup(g, houses, sw(g, cmp(g, attr(g, "h_timber", "INT"), 0.5), 0, attr(g, "h_storeys", "INT"),
                                  "INT"))
        fl = store(g, fl, "t_k", k, "INT")
        h = House(g)
        tk = attr(g, "t_k", "INT")
        z0 = floor_base(g, h, tk)
        zc0 = sw(g, cmp(g, tk, 0.5, "LESS_THAN"), add(g, z0, 0.1), h.level)
        z1 = sub(g, floor_top(g, h, tk), 0.1)
        yf = mul(g, tk, h.jetty)
        fl = store(g, fl, "t_z0", zc0)
        fl = store(g, fl, "t_z1", z1)
        fl = store(g, fl, "t_y", yf)
        fl = store(g, fl, "t_win_lo", sub(g, add(g, z0, mul(g, h.floor_h, 0.5)), half(g, h.win_h)))
        fl = store(g, fl, "t_win_hi", add(g, add(g, z0, mul(g, h.floor_h, 0.5)), half(g, h.win_h)))
        upper = cmp(g, tk, 0.5)
    with g.frame("Corner posts on every timbered storey"):
        cp, q = dup(g, fl, 2)
        h = House(g)
        sgn = sub(g, mul(g, q, 2.0), 1.0)
        z0, z1, yf = attr(g, "t_z0"), attr(g, "t_z1"), attr(g, "t_y")
        posts = piece(g, cp, vec(g, mul(g, sgn, sub(g, half(g, h.width), half(g, bw))), add(g, yf, 0.01),
                                 half(g, add(g, z0, z1))), vec(g, bw, 0.08, sub(g, z1, z0)), tcol, "timber")
    with g.frame("Upper storeys: posts between the window columns"):
        mp, q = dup(g, fl, sw(g, upper, 0, sub(g, attr(g, "h_cols", "INT"), 1.0), "INT"))
        h = House(g)
        z0, z1, yf = attr(g, "t_z0"), attr(g, "t_z1"), attr(g, "t_y")
        x = sub(g, mul(g, div(g, add(g, q, 1.0), h.cols), h.width), half(g, h.width))
        mids = piece(g, mp, vec(g, x, add(g, yf, 0.01), half(g, add(g, z0, z1))),
                     vec(g, mul(g, bw, 0.9), 0.08, sub(g, z1, z0)), tcol, "timber")
    with g.frame("Upper storeys: sill rail under the windows, and a head rail over them in pattern 1"):
        p1 = cmp(g, attr(g, "h_timber", "INT"), 1.0, "EQUAL")
        rp, q = dup(g, fl, sw(g, upper, 0, sw(g, p1, 1, 2, "INT"), "INT"))
        h = House(g)
        yf = attr(g, "t_y")
        z = sw(g, cmp(g, q, 0.5), sub(g, attr(g, "t_win_lo"), 0.1), add(g, attr(g, "t_win_hi"), 0.09))
        rails = piece(g, rp, vec(g, 0.0, yf, z), vec(g, h.width, 0.08, mul(g, bw, 0.85)), tcol, "timber")
    with g.frame("Pattern 2: full-height braces in the corner bays"):
        is2 = both(g, upper, cmp(g, attr(g, "h_timber", "INT"), 2.0, "EQUAL"))
        bp, q = dup(g, fl, sw(g, is2, 0, 2, "INT"))
        h = House(g)
        sgn = sub(g, mul(g, q, 2.0), 1.0)
        z0, yf = attr(g, "t_z0"), attr(g, "t_y")
        hw = half(g, h.width)
        bay = mx(g, sub(g, sub(g, div(g, hw, h.cols), half(g, h.win_w)), 0.04), 0.3)
        ax = mul(g, sgn, sub(g, hw, bw))
        bx = mul(g, sgn, sub(g, sub(g, hw, bw), bay))
        cx, cz, cl, crot = strut_xz(g, ax, z0, bx, attr(g, "t_win_hi"))
        braces = piece(g, bp, vec(g, cx, add(g, yf, 0.0), cz), vec(g, cl, 0.075, mul(g, bw, 0.85)), tcol,
                       "timber", rot=crot)
    with g.frame("Pattern 3: St Andrew's crosses under every window"):
        is3 = both(g, upper, cmp(g, attr(g, "h_timber", "INT"), 3.0, "EQUAL"))
        xp, q = dup(g, fl, sw(g, is3, 0, mul(g, attr(g, "h_cols", "INT"), 2.0), "INT"))
        h = House(g)
        j = g.math("FLOOR", div(g, q, 2.0))
        d = g.math("FLOORED_MODULO", q, 2.0)
        xc = sub(g, mul(g, div(g, add(g, j, 0.5), h.cols), h.width), half(g, h.width))
        hx = half(g, h.win_w)
        z0, yf = attr(g, "t_z0"), attr(g, "t_y")
        zt = sub(g, attr(g, "t_win_lo"), 0.15)
        sgn = sub(g, mul(g, d, 2.0), 1.0)
        cx, cz, cl, crot = strut_xz(g, sub(g, xc, mul(g, sgn, hx)), z0, add(g, xc, mul(g, sgn, hx)), zt)
        cross = piece(g, xp, vec(g, cx, sub(g, yf, 0.005), cz), vec(g, cl, 0.07, mul(g, bw, 0.75)), tcol,
                      "timber", rot=crot)
    g.output("Geometry", "GEOMETRY", join(g, posts, mids, rails, braces, cross))
    return g.finish()


# ---- SS House Windows ----------------------------------------------------------------------------------------
def windows():
    g = Graph("SS House Windows", description="Window layout: h_cols windows on every upper storey, evenly "
                                              "spaced, and 0-2 ground-floor windows in the span beside the door "
                                              "(none on shop houses). Builds them with SS House Window and emits "
                                              "sill anchors (1 ground, 2 upper)")
    houses = g.input("Houses", "GEOMETRY", desc="House points with the plan attributes")
    seed = g.input("Seed", "INT", 0, desc="Random seed for anchor ss_rand")
    tcol = g.input("Timber Color", "COLOR", fm.hexc("#4A2E1C"), desc="Sill timber")
    with g.frame("Upper windows: storeys 1..n-1 x h_cols columns, centred in each column, mid-storey"):
        up, q = dup(g, houses, mul(g, sub(g, attr(g, "h_storeys", "INT"), 1.0), attr(g, "h_cols", "INT")))
        h = House(g)
        f = add(g, g.math("FLOOR", div(g, q, h.cols)), 1.0)
        j = g.math("FLOORED_MODULO", q, h.cols)
        x = sub(g, mul(g, div(g, add(g, j, 0.5), h.cols), h.width), half(g, h.width))
        z = add(g, floor_base(g, h, f), mul(g, h.floor_h, 0.5))
        plain = cmp(g, attr(g, "h_timber", "INT"), 0.5, "LESS_THAN")
        up = window_points(g, up, vec(g, x, mul(g, f, h.jetty), z), vec(g, h.win_w, 0.0, h.win_h), 2, h.shutter,
                           plain)
        up = store(g, up, "w_floor", f, "INT")
    with g.frame("Ground windows: h_gwin windows spread over the span beside the door"):
        gp, q = dup(g, houses, attr(g, "h_gwin", "INT"))
        h = House(g)
        x = add(g, h.span_c, mul(g, sub(g, add(g, q, 0.5), half(g, h.gwin)), div(g, h.span_len, h.gwin)))
        z = add(g, h.level, 1.12)
        gp = window_points(g, gp, vec(g, x, 0.0, z), vec(g, h.gwin_w, 0.0, h.gwin_h),
                           g.math("ROUND", mx(g, div(g, h.gwin_w, 0.34), 2.0)), h.shutter, True)
        gp = store(g, gp, "w_floor", 0, "INT")
    with g.frame("Build every window"):
        allw = join(g, up, gp)
        built = g.group(window(), Windows=allw, **{"Shutter Color": attr(g, "h_shutter_color", "FLOAT_COLOR"),
                                                   "Timber Color": tcol})
    with g.frame("Sill anchors on the wall plane: 1 ground floor, 2 upper floors"):
        cx, cy, cz = xyz(g, attr(g, "w_center", "FLOAT_VECTOR"))
        ww, _, wh = xyz(g, attr(g, "w_size", "FLOAT_VECTOR"))
        kind = sw(g, cmp(g, attr(g, "w_floor", "INT"), 0.5), 1, 2, "INT")
        anchors = anchor_points(g, allw, kind, vec(g, cx, cy, sub(g, cz, half(g, wh))), ww, seed)
    g.output("Geometry", "GEOMETRY", built["Geometry"])
    g.output("Cutters", "GEOMETRY", built["Cutters"])
    g.output("Anchors", "GEOMETRY", anchors)
    return g.finish()


# ---- SS House Doors & Shops ----------------------------------------------------------------------------------
def doors():
    g = Graph("SS House Doors", description="Ground floor openings: one door per house (square with a timber "
                                            "frame, or arched in a stone ring) set back in its reveal, and on "
                                            "shop houses a wide multi-pane shop window under a painted fascia. "
                                            "Emits door, shopfront, lantern, sign and verge anchors")
    houses = g.input("Houses", "GEOMETRY", desc="House points with the plan attributes")
    seed = g.input("Seed", "INT", 0, desc="Random seed for anchor ss_rand")
    tcol = g.input("Timber Color", "COLOR", fm.hexc("#4A2E1C"), desc="Door frame timber")
    with g.frame("Door frame of reference: centre x, width, height, arch springing line"):
        h = House(g)
        dx, dw, dh, lv = h.door_x, h.door_w, h.door_h, h.level
        arch = h.door_arch
        hr = sub(g, dh, sw(g, arch, 0.0, half(g, dw)))       # height of the straight part
        ycut = half(g, sub(g, 0.06, DOOR_REVEAL))
    with g.frame("Cut the opening: a box, plus a cylinder for the arch"):
        c1 = piece(g, houses, vec(g, dx, ycut, add(g, lv, half(g, hr))), vec(g, dw, DOOR_REVEAL + 0.06, hr),
                   h.color, "plaster")
        c2 = piece(g, houses, vec(g, dx, ycut, add(g, lv, hr)), vec(g, dw, DOOR_REVEAL + 0.06, dw), h.color,
                   "plaster", sel=arch, shape=2)
    with g.frame("Door leaf set back in the reveal, painted planks, iron handle"):
        yl = -DOOR_REVEAL + 0.04
        l1 = piece(g, houses, vec(g, dx, yl, add(g, lv, half(g, hr))), vec(g, dw, 0.06, hr), h.door_color,
                   "painted")
        l2 = piece(g, houses, vec(g, dx, yl - 0.006, add(g, lv, hr)), vec(g, dw, 0.06, dw), h.door_color,
                   "painted", sel=arch, shape=2)
        hx = sub(g, dx, mul(g, h.door_side, sub(g, half(g, dw), 0.13)))
        handle = piece(g, houses, vec(g, hx, yl + 0.05, add(g, lv, 0.95)), (0.05, 0.05, 0.12), IRON_COLOR,
                       "frame")
    with g.frame("Square doors: two timber posts and a lintel"):
        fp, q = dup(g, houses, sw(g, arch, 3, 0, "INT"))
        h = House(g)
        sgn = sub(g, mul(g, q, 2.0), 1.0)
        dx, dw, lv = h.door_x, h.door_w, h.level
        hr = h.door_h
        px = add(g, dx, mul(g, sgn, add(g, half(g, dw), 0.07)))
        isl = cmp(g, q, 1.5)
        fx = sw(g, isl, px, dx)
        fz = sw(g, isl, add(g, lv, half(g, add(g, hr, 0.1))), add(g, add(g, lv, hr), 0.08))
        fs = sw(g, isl, vec(g, 0.14, 0.14, add(g, hr, 0.1)), vec(g, add(g, dw, 0.36), 0.16, 0.16), "VECTOR")
        sq = piece(g, fp, vec(g, fx, 0.02, fz), fs, tcol, "timber")
    with g.frame("Arched doors: stone jambs and a stone arch ring"):
        ap, q = dup(g, houses, sw(g, attr(g, "h_door_arch", "BOOLEAN"), 0, 2, "INT"))
        h = House(g)
        sgn = sub(g, mul(g, q, 2.0), 1.0)
        dw = h.door_w
        hr = sub(g, h.door_h, half(g, dw))
        jx = add(g, h.door_x, mul(g, sgn, add(g, half(g, dw), mul(g, dw, 0.07))))
        jamb = piece(g, ap, vec(g, jx, 0.02, add(g, h.level, half(g, hr))), vec(g, mul(g, dw, 0.14), 0.14, hr),
                     STONE_COLOR, "stone")
        h = House(g)
        ring = piece(g, houses, vec(g, h.door_x, 0.02, add(g, h.level, sub(g, h.door_h, half(g, h.door_w)))),
                     vec(g, h.door_w, h.door_w, h.door_w), STONE_COLOR, "stone", sel=h.door_arch, shape=3)
    with g.frame("Shopfront: a wide window with many panes in the span beside the door, fascia above"):
        sp, _ = dup(g, houses, sw(g, attr(g, "h_shop", "BOOLEAN"), 0, 1, "INT"))
        h = House(g)
        sww = mn(g, mul(g, h.span_len, 0.92), 2.7)
        zb = add(g, h.level, 0.5)
        zt = sub(g, h.ground_h, 0.42)
        sp = window_points(g, sp, vec(g, h.span_c, 0.0, half(g, add(g, zb, zt))), vec(g, sww, 0.0, sub(g, zt, zb)),
                           g.math("ROUND", mx(g, div(g, sww, 0.42), 2.0)), False)
        shop = g.group(window(), Windows=sp, **{"Timber Color": tcol})
        h = House(g)
        fascia = piece(g, sp, vec(g, h.span_c, 0.05, sub(g, h.ground_h, 0.25)),
                       vec(g, add(g, sww, 0.3), 0.1, 0.2), h.door_color, "painted")
    with g.frame("Anchors: 3 door base, 4 shopfront top, 5 lantern beside the door, 6 sign bracket"):
        h = House(g)
        a3 = anchor_points(g, houses, 3, vec(g, h.door_x, 0.0, h.level), h.door_w, seed)
        a4 = anchor_points(g, sp, 4, vec(g, h.span_c, 0.0, sub(g, h.ground_h, 0.15)), sww, seed)
        lx = add(g, h.door_x, mul(g, h.door_side, add(g, half(g, h.door_w), 0.26)))
        a5 = anchor_points(g, houses, 5, vec(g, lx, 0.0, add(g, h.level, 1.72)), 0.0, seed)
        # bracket bar ~2.3 H on the first upper storey; on shop houses on the door side, clear of the awning
        sgn6 = sw(g, h.shop, neg(g, h.door_side), h.door_side)
        sx = mul(g, sgn6, sub(g, half(g, h.width), 0.28))
        a6 = anchor_points(g, houses, 6, vec(g, sx, h.jetty, mx(g, 2.3, add(g, h.ground_h, 0.2))), 0.6, seed)
    with g.frame("Anchors: 7 verge spots, the free wall base either side of the door"):
        vp, q = dup(g, houses, 2)
        h = House(g)
        s = sub(g, mul(g, sub(g, mul(g, q, 2.0), 1.0), h.door_side), 0.0)    # +door_side: outer, -: inner
        a = add(g, h.door_x, mul(g, s, add(g, half(g, h.door_w), 0.14)))
        b = mul(g, s, sub(g, half(g, h.width), 0.05))
        ln = g.math("ABSOLUTE", sub(g, b, a))
        ln = sw(g, cmp(g, mul(g, sub(g, b, a), s), 0.0), 0.0, ln)
        a7 = anchor_points(g, vp, 7, vec(g, half(g, add(g, a, b)), 0.08, h.level), ln, seed)
        a7 = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=a7,
                    Selection=cmp(g, attr(g, "ss_width"), 0.35, "LESS_THAN"))["Geometry"]
    g.output("Geometry", "GEOMETRY", join(g, l1, l2, handle, sq, jamb, ring, shop["Geometry"], fascia))
    g.output("Cutters", "GEOMETRY", join(g, c1, c2, shop["Cutters"]))
    g.output("Anchors", "GEOMETRY", join(g, a3, a4, a5, a6, a7))
    return g.finish()


# ---- SS House Roof -------------------------------------------------------------------------------------------
def roof():
    g = Graph("SS House Roof", description="Roof per house: eaves to the street (ridge along the wall) or a "
                                           "gable to the street (ridge into the block), two tiled slabs at the "
                                           "roof pitch with eaves overhang, a plaster attic prism under them, a "
                                           "ridge cap, timbered gables and an optional chimney")
    houses = g.input("Houses", "GEOMETRY", desc="House points with the plan attributes")
    pitch = g.input("Pitch", "FLOAT", math.radians(55), min=math.radians(20), max=math.radians(70),
                    subtype="ANGLE", desc="Roof slope; storybook roofs are steep")
    over = g.input("Overhang", "FLOAT", 0.5, min=0.0, max=1.2, subtype="DISTANCE",
                   desc="How far the eaves (and gable verges) reach past the walls")
    tcol = g.input("Timber Color", "COLOR", fm.hexc("#4A2E1C"), desc="Gable timbers")
    bw = g.input("Beam Width", "FLOAT", 0.16, min=0.04, max=0.4, subtype="DISTANCE", desc="Gable timber width")
    thick = 0.13
    with g.frame("Roof frame: wall top, ridge height, half-span; eaves roofs span the depth, gables the width"):
        h = House(g)
        tanp = g.math("TANGENT", pitch)
        zt, yt = top_z(g, h), top_y(g, h)
        gable = h.gable
        half_span = sw(g, gable, half(g, add(g, yt, h.depth)), half(g, h.width))
        rise = mul(g, half_span, tanp)
        yc = half(g, sub(g, yt, h.depth))            # centre of the block front-to-back
    with g.frame("Attic prism (plaster gable ends) under the slabs"):
        wx = sw(g, gable, add(g, h.width, 0.04), add(g, yt, h.depth))
        wy = sw(g, gable, add(g, yt, h.depth), add(g, h.width, 0.04))
        attic = piece(g, houses, vec(g, 0.0, yc, add(g, zt, half(g, rise))), vec(g, wx, wy, rise), h.color,
                      "plaster", rot=euler(g, 0.0, 0.0, sw(g, gable, 0.0, math.pi / 2)), shape=1)
    with g.frame("Two slabs: from the ridge down past the wall by the overhang"):
        sp, q = dup(g, houses, 2)
        h = House(g)
        tanp = g.math("TANGENT", pitch)
        cosp = g.math("COSINE", pitch)
        sinp = g.math("SINE", pitch)
        zt, yt = top_z(g, h), top_y(g, h)
        gable = h.gable
        yc = half(g, sub(g, yt, h.depth))
        half_span = sw(g, gable, half(g, add(g, yt, h.depth)), half(g, h.width))
        rise = mul(g, half_span, tanp)
        sgn = sub(g, 1.0, mul(g, q, 2.0))             # q0: front / right, q1: back / left
        run = add(g, half_span, over)
        slope_len = add(g, div(g, run, cosp), 0.12)
        # unit outward horizontal direction from the ridge
        ux = sw(g, gable, 0.0, sgn)
        uy = sw(g, gable, sgn, 0.0)
        # ridge-line midpoint: eaves roofs at yc; gables run from behind the house to the front verge
        y_front = add(g, yt, add(g, over, 0.12))
        y_back = sub(g, neg(g, h.depth), 0.05)
        rmid_y = sw(g, gable, yc, half(g, add(g, y_front, y_back)))
        rz = add(g, zt, rise)
        mid_r = mul(g, half(g, run), 1.0)
        cx = mul(g, ux, mid_r)
        cy = add(g, rmid_y, mul(g, uy, mid_r))
        cz = sub(g, rz, mul(g, mid_r, tanp))
        # lift by half the thickness along the slab normal (u * sin + z * cos)
        lift = thick / 2
        cx = add(g, cx, mul(g, mul(g, ux, sinp), lift))
        cy = add(g, cy, mul(g, mul(g, uy, sinp), lift))
        cz = add(g, cz, mul(g, cosp, lift))
        ridge_len = sw(g, gable, add(g, h.width, 0.24), sub(g, y_front, y_back))
        yaw = sw(g, gable, sw(g, cmp(g, q, 0.5), 0.0, math.pi), sw(g, cmp(g, q, 0.5), -math.pi / 2, math.pi / 2))
        rot = euler(g, neg(g, pitch), 0.0, yaw)
        slate = attr(g, "h_slate", "BOOLEAN")
        size = vec(g, ridge_len, slope_len, thick)
        tiles = piece(g, sp, vec(g, cx, cy, cz), size, h.roof_color, "tile", rot=rot, sel=g.node(
            "FunctionNodeBooleanMath", props={"operation": "NOT"}, Boolean=slate)["Boolean"])
        slates = piece(g, sp, vec(g, cx, cy, cz), size, h.roof_color, "slate", rot=rot, sel=slate)
        slabs = join(g, tiles, slates)
    with g.frame("Ridge cap"):
        h = House(g)
        zt, yt = top_z(g, h), top_y(g, h)
        gable = h.gable
        half_span = sw(g, gable, half(g, add(g, yt, h.depth)), half(g, h.width))
        rz = add(g, zt, mul(g, half_span, g.math("TANGENT", pitch)))
        y_front = add(g, yt, add(g, over, 0.12))
        y_back = sub(g, neg(g, h.depth), 0.05)
        cy = sw(g, gable, half(g, sub(g, yt, h.depth)), half(g, add(g, y_front, y_back)))
        size = sw(g, gable, vec(g, add(g, h.width, 0.24), 0.18, 0.14), vec(g, 0.18, sub(g, y_front, y_back), 0.14),
                  "VECTOR")
        cap = piece(g, houses, vec(g, 0.0, cy, add(g, rz, thick)), size, h.roof_color, "tile")
    with g.frame("Rafter tails under the front eave (eaves-to-street roofs)"):
        nr = mx(g, g.math("ROUND", div(g, attr(g, "h_width"), 0.5)), 2.0)
        rp, q = dup(g, houses, sw(g, attr(g, "h_gable", "BOOLEAN"), nr, 0.0))
        h = House(g)
        nr2 = mx(g, g.math("ROUND", div(g, h.width, 0.5)), 2.0)
        rx = sub(g, mul(g, div(g, add(g, q, 0.5), nr2), h.width), half(g, h.width))
        zt, yt = top_z(g, h), top_y(g, h)
        tanp = g.math("TANGENT", pitch)
        ry, rz, rl, rrot = strut_yz(g, sub(g, yt, 0.1), add(g, zt, mul(g, 0.1, tanp)),
                                    add(g, yt, over), sub(g, zt, mul(g, over, tanp)))
        rafters = piece(g, rp, vec(g, rx, ry, sub(g, rz, 0.06)), vec(g, 0.08, 0.09, rl), tcol, "timber",
                        rot=rrot)
    with g.frame("Gable timbers (timbered gable houses): collar beam and king post"):
        gp, q = dup(g, houses, sw(g, both(g, attr(g, "h_gable", "BOOLEAN"), cmp(g, attr(g, "h_timber", "INT"), 0.5)),
                                  0, 2, "INT"))
        h = House(g)
        zt, yt = top_z(g, h), top_y(g, h)
        rise = mul(g, half(g, h.width), g.math("TANGENT", pitch))
        iscol = cmp(g, q, 0.5, "LESS_THAN")
        tc = sw(g, iscol, vec(g, 0.0, add(g, yt, 0.01), add(g, zt, mul(g, rise, 0.45))),
                vec(g, 0.0, add(g, yt, 0.01), add(g, zt, mul(g, rise, 0.3))), "VECTOR")
        ts = sw(g, iscol, vec(g, bw, 0.08, mul(g, rise, 0.6)),
                vec(g, mul(g, h.width, 0.52), 0.08, bw), "VECTOR")
        gt = piece(g, gp, tc, ts, tcol, "timber")
    with g.frame("Chimney: a stone stack through the roof with a cap"):
        cp, q = dup(g, houses, sw(g, attr(g, "h_chimney", "BOOLEAN"), 0, 2, "INT"))
        h = House(g)
        zt, yt = top_z(g, h), top_y(g, h)
        gable = h.gable
        half_span = sw(g, gable, half(g, add(g, yt, h.depth)), half(g, h.width))
        rz = add(g, zt, mul(g, half_span, g.math("TANGENT", pitch)))
        ctop = add(g, rz, 0.55)
        ccy = sw(g, gable, sub(g, half(g, sub(g, yt, h.depth)), 0.35), mul(g, h.depth, -0.55))
        ccx = sw(g, gable, h.chimney_x, mul(g, h.chimney_x, 0.45))
        isstack = cmp(g, q, 0.5, "LESS_THAN")
        cz = sw(g, isstack, add(g, ctop, 0.04), half(g, add(g, zt, ctop)))
        cs = sw(g, isstack, vec(g, 0.6, 0.6, 0.09), vec(g, 0.46, 0.46, sub(g, ctop, zt)), "VECTOR")
        chim = piece(g, cp, vec(g, ccx, ccy, cz), cs, CHIMNEY_COLOR, "stone")
    g.output("Geometry", "GEOMETRY", join(g, attic, slabs, cap, rafters, gt, chim))
    return g.finish()
