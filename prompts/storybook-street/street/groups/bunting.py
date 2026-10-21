"""SS Bunting: pennant strings across the street with paper lanterns, moved by an analytic wind.

Measured from the reference (2-4 s at 24 fps, out/bunting/ref; see the module report):
- strings cross the street every 2.4-3.8 H, anchored in the facades at ~3.9 H and sagging ~0.65 H, a few diagonal;
- pennants ~0.28 H wide, 1.15x as long, one every ~0.5 H; palette sampled as salmon #C27D6A, cream #D3A684,
  grey-sage #AFA894 (dusty blue is rare);
- ribbed paper lanterns ~0.5 H tall, taller than wide, hung close under the rope near the facade ends;
- motion is a light breeze: tracked lantern swing below 1 deg, pennant flutter a few degrees, no visible period.

Wind is analytic, not a simulation zone. Every part is a damped oscillator driven by a slow gust envelope, and at
these amplitudes (a few degrees) the response is linear: a lagged copy of the gust (the steady deflection) plus a
ring at the part's own pendulum period scaled by the gust. That is a closed form in Time, so any frame can be
evaluated alone (scrubbing, retiming, render farms, the 20 s loop) and the graph stays readable; a simulation
zone would add state and caching for motion the reference does not show.
"""
import math
from nodekit.graph import Graph
from street.groups import frame
from street.materials import bunting as mats

NAME = "SS Bunting"
ROPE_N = 17            # points per rope (enough for a smooth parabola)
H_METRES = 1.1         # 1 H in metres, only used to turn pendulum lengths into periods
GUST_SPEED = 5.0       # gust fronts travel down the street at this speed (H/s)
TAU = 2.0 * math.pi


# ---- sub-groups -------------------------------------------------------------------------------------------------
def build_string():
    g = Graph("SS Bunting String", description="Per-string random layout: where string i crosses the street, "
                                               "its diagonal slope, anchor height, sag and a phase")
    i = g.input("String", "INT", 0, desc="String index along the street (field)")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    spacing = g.input("Spacing", "FLOAT", 3.2, subtype="DISTANCE", desc="Mean distance between strings")
    length = g.input("Curve Length", "FLOAT", 60.0, subtype="DISTANCE", desc="Length of the path curve")
    height = g.input("Height", "FLOAT", 3.9, subtype="DISTANCE", desc="Anchor height at the facades")
    sag = g.input("Sag", "FLOAT", 0.65, subtype="DISTANCE", desc="Drop of the rope at mid-street")
    skew = g.input("Skew", "FLOAT", 0.12, desc="Largest diagonal slope (ds per unit d)")

    def rnd(k):
        return g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=i,
                      Seed=g.math("ADD", seed, 101 * k))["Value"]

    with g.frame("Position along the street: even spacing with +-25 % jitter, kept on the curve"):
        s = g.math("MULTIPLY", g.math("ADD", i, 0.5), spacing)
        jit = g.math("MULTIPLY", g.math("SUBTRACT", rnd(1), 0.5), g.math("MULTIPLY", spacing, 0.5))
        s = g.node("ShaderNodeClamp", Value=g.math("ADD", s, jit), Min=0.3,
                   Max=g.math("SUBTRACT", length, 0.3))
    with g.frame("Shape: diagonal slope, anchor height +-0.1, sag +-15 %"):
        slope = g.math("MULTIPLY", g.math("SUBTRACT", g.math("MULTIPLY", rnd(2), 2.0), 1.0), skew)
        h = g.math("ADD", height, g.math("MULTIPLY", g.math("SUBTRACT", rnd(3), 0.5), 0.2))
        sg = g.math("MULTIPLY", sag, g.math("ADD", 0.85, g.math("MULTIPLY", rnd(4), 0.3)))
        phase = g.math("MULTIPLY", rnd(5), TAU)
    g.output("S", "FLOAT", s)
    g.output("Slope", "FLOAT", slope)
    g.output("Height", "FLOAT", h)
    g.output("Sag", "FLOAT", sg)
    g.output("Phase", "FLOAT", phase)
    return g.finish()


def build_wind():
    g = Graph("SS Bunting Wind", description="Wind drive at a street position: Strength x gust envelope "
                                             "(1D noise of time, travelling down the street), delayed by Lag")
    t = g.input("Time", "FLOAT", 0.0, desc="Scene time in seconds")
    lag = g.input("Lag", "FLOAT", 0.0, desc="Response delay of the part (s): heavier parts follow gusts later")
    s = g.input("S", "FLOAT", 0.0, subtype="DISTANCE", desc="Arc length of the part (gusts travel along s)")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    strength = g.input("Strength", "FLOAT", 1.0, desc="Overall wind strength")
    gust = g.input("Gust", "FLOAT", 0.6, desc="How much the wind varies (0 steady, 1 calm to double)")
    with g.frame("Gust envelope: slow noise at (t - lag - s / gust speed), mean 1"):
        tt = g.math("SUBTRACT", g.math("SUBTRACT", t, lag), g.math("DIVIDE", s, GUST_SPEED))
        w = g.math("ADD", g.math("MULTIPLY", tt, 0.3), g.math("MULTIPLY", seed, 7.31))
        n = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "1D"}, W=w, Scale=1.0, Detail=1.0)
        # noise factor sits mostly in 0.3..0.7: map to -1..1, scale by Gust, never below calm
        v = g.math("MULTIPLY", g.math("SUBTRACT", n["Factor"], 0.5), 4.0)
        env = g.math("MAXIMUM", g.math("ADD", 1.0, g.math("MULTIPLY", v, gust)), 0.0)
        drive = g.math("MULTIPLY", env, strength)
    g.output("Drive", "FLOAT", drive)
    return g.finish()


def _ring(g, t, period, phase, amp):
    """amp * sin(2 pi t / period + phase)"""
    a = g.math("ADD", g.math("MULTIPLY", g.math("DIVIDE", t, period), TAU), phase)
    return g.math("MULTIPLY", g.math("SINE", a), amp)


def _pendulum_period(g, length_h):
    """2 pi sqrt(L / g) with L in H converted to metres."""
    return g.math("MULTIPLY", g.math("SQRT", g.math("MULTIPLY", length_h, H_METRES / 9.81)), TAU,
                  label="Pendulum period (s)")


def build_swing(wind):
    g = Graph("SS Bunting Swing", description="Rope swing angle about its chord: steady push from the "
                                              "along-street wind plus a ring at the rope's pendulum period")
    t = g.input("Time", "FLOAT", 0.0, desc="Scene time in seconds")
    s = g.input("S", "FLOAT", 0.0, subtype="DISTANCE", desc="Where the string crosses the street")
    sag = g.input("Sag", "FLOAT", 0.65, subtype="DISTANCE", desc="Rope sag")
    phase = g.input("Phase", "FLOAT", 0.0, desc="Per-string phase (radians)")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    strength = g.input("Strength", "FLOAT", 1.0, desc="Wind strength")
    gust = g.input("Gust", "FLOAT", 0.6, desc="Gust variation")
    along = g.input("Along", "FLOAT", 1.0, desc="Wind component along the street (cos of direction)")
    with g.frame("Drive: gust at this string, lagging 0.3 s"):
        dr = g.group(wind, Time=t, Lag=0.3, S=s, Seed=seed, Strength=strength, Gust=gust)
    with g.frame("Swing = drive x (0.5 deg steady x along + 0.4 deg ring); period of a 2/3 sag pendulum"):
        per = _pendulum_period(g, g.math("MULTIPLY", sag, 2.0 / 3.0))
        steady = g.math("MULTIPLY", along, math.radians(0.5))
        ring = _ring(g, t, per, phase, math.radians(0.4))
        ang = g.math("MULTIPLY", dr, g.math("ADD", steady, ring))
    g.output("Swing", "FLOAT", ang)
    g.output("Drive", "FLOAT", dr)
    return g.finish()


def build_rope_point(pt):
    g = Graph("SS Bunting Rope Point", description="A point on a sagging string, swung about its chord, in "
                                                   "street space and world space")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    u = g.input("U", "FLOAT", 0.5, desc="0 = right facade anchor, 1 = left facade anchor")
    s0 = g.input("S", "FLOAT", 0.0, subtype="DISTANCE", desc="Arc length where the string crosses the centre")
    slope = g.input("Slope", "FLOAT", 0.0, desc="Diagonal slope ds/dd")
    h0 = g.input("Height", "FLOAT", 3.9, subtype="DISTANCE", desc="Anchor height")
    sag = g.input("Sag", "FLOAT", 0.65, subtype="DISTANCE", desc="Drop at mid-span")
    half = g.input("Half Span", "FLOAT", 3.0, subtype="DISTANCE", desc="Anchor offset |d| (facade line)")
    swing = g.input("Swing", "FLOAT", 0.0, subtype="ANGLE", desc="Swing about the chord, + toward +s")
    with g.frame("Street space: d across, parabola sag y below the chord, swung by the angle"):
        d = g.math("MULTIPLY", g.math("SUBTRACT", g.math("MULTIPLY", u, 2.0), 1.0), half)
        y = g.math("MULTIPLY", g.math("MULTIPLY", u, g.math("SUBTRACT", 1.0, u)), g.math("MULTIPLY", sag, 4.0))
        s = g.math("ADD", g.math("ADD", s0, g.math("MULTIPLY", slope, d)),
                   g.math("MULTIPLY", y, g.math("SINE", swing)))
        h = g.math("SUBTRACT", h0, g.math("MULTIPLY", y, g.math("COSINE", swing)))
    with g.frame("World placement"):
        sp = g.group(pt, Curve=curve, Length=s, Offset=d, Height=h)
    g.output("Position", "VECTOR", sp["Position"])
    g.output("Rotation", "ROTATION", sp["Rotation"])
    return g.finish()


def build_flag_shape():
    g = Graph("SS Bunting Flag Shape", description="One pennant: a triangle hanging from its top edge (on the "
                                                   "rope, x along the rope, -z down) with a soft belly and "
                                                   "a little thickness")
    w = g.input("Width", "FLOAT", 0.26, subtype="DISTANCE", desc="Width of the top edge")
    ln = g.input("Length", "FLOAT", 0.30, subtype="DISTANCE", desc="Top edge to tip")
    with g.frame("Grid -> triangle: rows shrink toward the tip, cloth bellies out a little"):
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": 1.0, "Size Y": 1.0, "Vertices X": 5, "Vertices Y": 7})
        p = g.separate(g.node("GeometryNodeInputPosition"))
        u = g.math("ADD", p["X"], 0.5)
        v = g.math("SUBTRACT", 0.5, p["Y"])
        # rows narrow to a 3 % stub at the tip instead of a point: no degenerate faces to merge
        x = g.math("MULTIPLY", g.math("MULTIPLY", p["X"], w), g.math("SUBTRACT", 1.0, g.math("MULTIPLY", v, 0.97)))
        belly = g.math("MULTIPLY", g.math("MULTIPLY", g.math("MULTIPLY", u, g.math("SUBTRACT", 1.0, u)),
                                          g.math("MULTIPLY", v, g.math("SUBTRACT", 1.0, v))),
                       g.math("MULTIPLY", ln, 0.35))
        z = g.math("MULTIPLY", v, g.math("MULTIPLY", ln, -1.0))
        pos = g.node("GeometryNodeSetPosition", Geometry=grid["Mesh"], Position=g.combine(x, belly, z))
    with g.frame("Cloth thickness: a flipped back sheet 6 mm behind (Extrude Mesh shaded the grid faces)"):
        back = g.node("GeometryNodeFlipFaces", Mesh=pos["Geometry"])
        back_t = g.node("GeometryNodeTransform", Geometry=back["Mesh"], Translation=(0.0, -0.006, 0.0))
        both = g.node("GeometryNodeJoinGeometry")
        g.connect(pos["Geometry"], both.i("Geometry"))
        g.connect(back_t["Geometry"], both.i("Geometry"))
        smooth = g.node("GeometryNodeSetShadeSmooth", Mesh=both["Geometry"])
    g.output("Geometry", "GEOMETRY", smooth["Mesh"])
    return g.finish()


def build_lantern_shape():
    g = Graph("SS Bunting Lantern Shape", description="A round ribbed paper lantern with dark caps, hanging "
                                                      "on a cord from the origin (the rope)")
    size = g.input("Size", "FLOAT", 0.47, subtype="DISTANCE", desc="Height of the paper body")
    with g.frame("Proportions (measured: radius 0.40 x size, rope to centre 0.62 x size)"):
        hh = g.math("MULTIPLY", size, 0.5)
        r = g.math("MULTIPLY", size, 0.40)
        drop = g.math("MULTIPLY", size, 0.62)
    with g.frame("Paper body: cylinder bulged to a round barrel, six folds"):
        cyl = g.node("GeometryNodeMeshCylinder", Vertices=20, **{"Side Segments": 24, "Fill Segments": 1},
                     Radius=1.0, Depth=2.0)
        p = g.separate(g.node("GeometryNodeInputPosition"))
        zn = p["Z"]                                                         # -1 .. 1
        prof = g.math("SQRT", g.math("SUBTRACT", 1.0, g.math("MULTIPLY", g.math("MULTIPLY", zn, zn), 0.6)))
        fold = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", g.math("ABSOLUTE", g.math("COSINE",
                      g.math("MULTIPLY", zn, math.pi * 3.0))), 0.04))
        rad = g.math("MULTIPLY", g.math("MULTIPLY", prof, fold), r)
        body = g.node("GeometryNodeSetPosition", Geometry=cyl["Mesh"],
                      Position=g.combine(g.math("MULTIPLY", p["X"], rad), g.math("MULTIPLY", p["Y"], rad),
                                         g.math("SUBTRACT", g.math("MULTIPLY", zn, hh), drop)))
        lz = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                    Geometry=body["Geometry"], Name="ss_lz", Value=zn)
        smooth = g.node("GeometryNodeSetShadeSmooth", Mesh=lz["Geometry"])
        paper = g.node("GeometryNodeSetMaterial", Geometry=smooth["Mesh"], Material=mats.lantern())
    with g.frame("Caps and cord"):
        capr = g.math("MULTIPLY", r, 0.55)
        top = g.node("GeometryNodeMeshCylinder", Vertices=12, Radius=capr, Depth=0.04)
        top_t = g.node("GeometryNodeTransform", Geometry=top["Mesh"],
                       Translation=g.combine(0, 0, g.math("SUBTRACT", g.math("ADD", hh, 0.0), drop)))
        bot = g.node("GeometryNodeMeshCylinder", Vertices=12, Radius=g.math("MULTIPLY", r, 0.35), Depth=0.03)
        bot_t = g.node("GeometryNodeTransform", Geometry=bot["Mesh"],
                       Translation=g.combine(0, 0, g.math("SUBTRACT", g.math("MULTIPLY", hh, -1.0), drop)))
        cord_len = g.math("SUBTRACT", drop, hh)
        cord = g.node("GeometryNodeMeshCylinder", Vertices=6, Radius=0.008, Depth=cord_len)
        cord_t = g.node("GeometryNodeTransform", Geometry=cord["Mesh"],
                        Translation=g.combine(0, 0, g.math("MULTIPLY", cord_len, -0.5)))
        caps = g.node("GeometryNodeJoinGeometry")
        for n in (top_t, bot_t, cord_t):
            g.connect(n["Geometry"], caps.i("Geometry"))
        capm = g.node("GeometryNodeSetMaterial", Geometry=caps["Geometry"], Material=mats.cap())
        allg = g.node("GeometryNodeJoinGeometry")
        g.connect(paper["Geometry"], allg.i("Geometry"))
        g.connect(capm["Geometry"], allg.i("Geometry"))
    g.output("Geometry", "GEOMETRY", allg["Geometry"])
    return g.finish()


# ---- top group --------------------------------------------------------------------------------------------------
def build():
    pt = frame.build()
    g_string, wind = build_string(), build_wind()
    swing_g, rope_pt = build_swing(wind), build_rope_point(pt)
    flag_shape, lantern_shape = build_flag_shape(), build_lantern_shape()

    g = Graph(NAME, description="Strings of pastel pennants across the street between the facades, with warm "
                                "paper lanterns, swaying in an analytic gusty breeze")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    time = g.input("Time", "FLOAT", 0.0, desc="Time in seconds (drives the wind)")
    seed = g.input("Seed", "INT", 0, min=0, desc="Random seed for layout, colours and wind")
    sw = g.input("Street Width", "FLOAT", 4.0, min=1, max=20, subtype="DISTANCE", panel="Street",
                 desc="Curb-to-curb width")
    cw = g.input("Curb Width", "FLOAT", 0.2, min=0, max=2, subtype="DISTANCE", panel="Street",
                 desc="Width of each curb")
    vw = g.input("Verge Width", "FLOAT", 0.8, min=0, max=5, subtype="DISTANCE", panel="Street",
                 desc="Grass verge between curb and facade (strings anchor at the facade line)")
    spacing = g.input("String Spacing", "FLOAT", 3.0, min=0.8, max=50, subtype="DISTANCE", panel="Strings",
                      desc="Mean distance between strings along the street (jittered +-25 %)")
    height = g.input("String Height", "FLOAT", 3.9, min=1, max=15, subtype="DISTANCE", panel="Strings",
                     desc="Rope height at the facades")
    sag = g.input("String Sag", "FLOAT", 0.65, min=0, max=3, subtype="DISTANCE", panel="Strings",
                  desc="How far the rope drops at mid-street")
    skew = g.input("String Skew", "FLOAT", 0.12, min=0, max=1, panel="Strings",
                   desc="Largest diagonal slope of a string (along-street shift per unit across)")
    rope_col = g.input("Rope Color", "COLOR", (0.088, 0.048, 0.025, 1.0), panel="Strings",
                       desc="Colour of the rope")
    fsize = g.input("Flag Size", "FLOAT", 0.28, min=0.05, max=1.5, subtype="DISTANCE", panel="Flags",
                    desc="Pennant width (length is 1.15x)")
    fspace = g.input("Flag Spacing", "FLOAT", 0.50, min=0.1, max=3, subtype="DISTANCE", panel="Flags",
                     desc="Distance between pennants along the rope")
    cols = [g.input(f"Flag Color {k + 1}", "COLOR", c, panel="Flags", desc=d) for k, (c, d) in enumerate([
        ((0.70, 0.22, 0.15, 1), "Salmon pennants (30 %)"),
        ((0.92, 0.58, 0.30, 1), "Cream pennants (35 %)"),
        ((0.42, 0.46, 0.31, 1), "Sage pennants (23 %)"),
        ((0.28, 0.38, 0.49, 1), "Dusty blue pennants (12 %)")])]
    missing = g.input("Missing Flag Chance", "FLOAT", 0.04, min=0, max=1, subtype="FACTOR", panel="Flags",
                      desc="Chance that a pennant is missing from the rope")
    lchance = g.input("Paper Lantern Chance", "FLOAT", 0.6, min=0, max=1, subtype="FACTOR", panel="Lanterns",
                      desc="Chance of a lantern in each of the two lantern slots of a string")
    lsize = g.input("Paper Lantern Size", "FLOAT", 0.52, min=0.1, max=2, subtype="DISTANCE", panel="Lanterns",
                    desc="Lantern paper height (its centre hangs 0.62x that below the rope)")
    lglow = g.input("Paper Lantern Glow", "COLOR", (1.0, 0.36, 0.05, 1.0), panel="Lanterns",
                    desc="Colour of the light inside the paper")
    lstr = g.input("Paper Lantern Strength", "FLOAT", 1.8, min=0, max=50, panel="Lanterns",
                   desc="Emission strength of the lanterns")
    wstr = g.input("Wind Strength", "FLOAT", 1.0, min=0, max=20, panel="Wind",
                   desc="Wind strength. 1 = the reference's light breeze (lanterns < 1 deg, flags ~3 deg); "
                        "4-6 = a clearly windy day")
    wgust = g.input("Wind Gust", "FLOAT", 0.6, min=0, max=1, subtype="FACTOR", panel="Wind",
                    desc="How much the wind comes and goes (slow noise of time, travelling down the street)")
    wflut = g.input("Flutter Speed", "FLOAT", 0.6, min=0, max=5, panel="Wind",
                    desc="Pennant flutter frequency (Hz)")
    wdir = g.input("Wind Direction", "FLOAT", 0.0, subtype="ANGLE", panel="Wind",
                   desc="Wind heading relative to the street: 0 = blowing along it (+s), 90 deg = across")

    def strparams(idx, clen):
        return g.group(g_string, String=idx, Seed=seed, Spacing=spacing, **{"Curve Length": clen},
                       Height=height, Sag=sag, Skew=skew)

    with g.frame("Street: anchor at the facade line, wind components in street space"):
        clen = g.node("GeometryNodeCurveLength", Curve=curve)
        half = g.math("ADD", g.math("ADD", g.math("ADD", g.math("MULTIPLY", sw, 0.5), cw), vw), 0.08,
                      label="Anchor |d| (just inside the walls)")
        nstr = g.math("MAXIMUM", g.math("FLOOR", g.math("DIVIDE", g.math("SUBTRACT", clen, 0.6), spacing)), 1.0)
        along = g.math("COSINE", wdir)
        across = g.math("SINE", wdir)

    with g.frame("Ropes: ROPE_N points per string, parabola sag, swung by the wind, joined into curves"):
        pts = g.node("GeometryNodePoints", Count=g.math("MULTIPLY", nstr, ROPE_N))
        idx = g.node("GeometryNodeInputIndex")
        sid = g.math("FLOOR", g.math("DIVIDE", idx, ROPE_N), label="String index")
        u = g.math("DIVIDE", g.math("MODULO", idx, ROPE_N), ROPE_N - 1, label="u across")
        sp = strparams(sid, clen)
        swing = g.group(swing_g, Time=time, S=sp["S"], Sag=sp["Sag"], Phase=sp["Phase"], Seed=seed,
                        Strength=wstr, Gust=wgust, Along=along)
        rp = g.group(rope_pt, Curve=curve, U=u, S=sp["S"], Slope=sp["Slope"], Height=sp["Height"],
                     Sag=sp["Sag"], **{"Half Span": half}, Swing=swing["Swing"])
        placed = g.node("GeometryNodeSetPosition", Geometry=pts["Points"], Position=rp["Position"])
        st_s = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                      Geometry=placed["Geometry"], Name="bunt_string", Value=sid)
        st_w = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                      Geometry=st_s["Geometry"], Name="bunt_swing", Value=swing["Swing"])
        st_d = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                      Geometry=st_w["Geometry"], Name="bunt_drive", Value=swing["Drive"])
        ropes = g.node("GeometryNodePointsToCurves", Points=st_d["Geometry"], **{"Curve Group ID": sid},
                       Weight=u)

    with g.frame("Rope mesh"):
        prof = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=6, Radius=0.012)
        rmesh = g.node("GeometryNodeCurveToMesh", Curve=ropes["Curves"], **{"Profile Curve": prof["Curve"]})
        rcol = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "POINT"},
                      Geometry=rmesh["Mesh"], Name="ss_color", Value=rope_col)
        rmat = g.node("GeometryNodeSetMaterial", Geometry=rcol["Geometry"], Material=mats.rope())

    with g.frame("Pennant spots: every Flag Spacing along each rope, clear of the walls, some missing"):
        slen = g.node("GeometryNodeSplineLength")
        trim = g.node("GeometryNodeTrimCurve", props={"mode": "LENGTH"}, Curve=ropes["Curves"], Start=0.3,
                      End=g.math("SUBTRACT", slen["Length"], 0.3))
        fpts = g.node("GeometryNodeCurveToPoints", props={"mode": "LENGTH"}, Curve=trim["Curve"], Length=fspace)
        fid = g.node("GeometryNodeInputID")
        r_miss = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=fid,
                        Seed=g.math("ADD", seed, 17))
        kept = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=fpts["Points"],
                      Selection=g.math("LESS_THAN", r_miss["Value"], missing))

    with g.frame("Pennant colour: salmon 30 %, cream 35 %, sage 23 %, dusty blue 12 %"):
        r_col = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=fid,
                       Seed=g.math("ADD", seed, 23))
        ci = g.math("ADD", g.math("ADD", g.math("GREATER_THAN", r_col["Value"], 0.30),
                                  g.math("GREATER_THAN", r_col["Value"], 0.65)),
                    g.math("GREATER_THAN", r_col["Value"], 0.88))
        sw_c = g.node("GeometryNodeIndexSwitch", props={"data_type": "RGBA"})
        sw_c.b.index_switch_items.new()
        sw_c.b.index_switch_items.new()
        g.connect(ci, sw_c.i("Index"))
        for k in range(4):
            g.connect(cols[k], sw_c.i(str(k)))

    with g.frame("Pennant flutter about the top edge: steady lean + travelling wave + rope swing"):
        tan = g.vmath("NORMALIZE", fpts["Tangent"])
        f_drive = g.node("GeometryNodeInputNamedAttribute", props={"data_type": "FLOAT"}, Name="bunt_drive")
        f_swing = g.node("GeometryNodeInputNamedAttribute", props={"data_type": "FLOAT"}, Name="bunt_swing")
        x_along = g.vmath("DOT_PRODUCT", g.node("GeometryNodeInputPosition"), tan)
        r_ph = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=fid, Max=0.8,
                      Seed=g.math("ADD", seed, 29))
        # phase = 2 pi f t - k x : a wave running along the rope at f / k * 2 pi ~ 1.5 H/s
        ph = g.math("ADD", g.math("SUBTRACT", g.math("MULTIPLY", g.math("MULTIPLY", time, wflut), TAU),
                                  g.math("MULTIPLY", x_along["Value"], 2.5)), r_ph["Value"])
        flut = g.math("ADD", g.math("MULTIPLY", g.math("SINE", ph), math.radians(3.0)),
                      g.math("MULTIPLY", g.math("SINE", g.math("ADD", g.math("MULTIPLY", ph, 2.3), 1.3)),
                             math.radians(1.0)))
        lean = g.math("MULTIPLY", along, math.radians(2.0))
        alpha = g.math("ADD", g.math("MULTIPLY", f_drive["Attribute"], g.math("ADD", lean, flut)),
                       f_swing["Attribute"])
        # local frame: X along the rope, Z up, so local Y = up x rope = -s; a tip swung to +s is -alpha about X
        base = g.node("FunctionNodeAxesToRotation", props={"primary_axis": "X", "secondary_axis": "Z"},
                      **{"Primary Axis": tan, "Secondary Axis": (0.0, 0.0, 1.0)})
        rot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=base["Rotation"],
                     **{"Rotate By": g.node("FunctionNodeEulerToRotation",
                                            Euler=g.combine(g.math("MULTIPLY", alpha, -1.0), 0.0, 0.0))})

    with g.frame("Pennant instances"):
        fshape = g.group(flag_shape, Width=fsize, Length=g.math("MULTIPLY", fsize, 1.15))
        fsm = g.node("GeometryNodeSetMaterial", Geometry=fshape["Geometry"], Material=mats.flag())
        fcol = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "POINT"},
                      Geometry=kept["Geometry"], Name="ss_color", Value=sw_c["Output"])
        frnd = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                      Geometry=fcol["Geometry"], Name="ss_rand",
                      Value=g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=fid,
                                   Seed=g.math("ADD", seed, 31))["Value"])
        flags = g.node("GeometryNodeInstanceOnPoints", Points=frnd["Geometry"], Instance=fsm["Geometry"],
                       Rotation=rot["Rotation"])

    with g.frame("Lantern slots: two per string near the sides (the middle stays clear), kept by Chance"):
        lp = g.node("GeometryNodePoints", Count=g.math("MULTIPLY", nstr, 2.0))
        lidx = g.node("GeometryNodeInputIndex")
        lsid = g.math("FLOOR", g.math("DIVIDE", lidx, 2.0))
        r_lu = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=lidx, Min=-0.06, Max=0.06,
                      Seed=g.math("ADD", seed, 41))
        lu = g.math("ADD", g.math("ADD", 0.16, g.math("MULTIPLY", g.math("MODULO", lidx, 2.0), 0.68)),
                    r_lu["Value"])
        lsp = strparams(lsid, clen)
        lswing = g.group(swing_g, Time=time, S=lsp["S"], Sag=lsp["Sag"], Phase=lsp["Phase"], Seed=seed,
                         Strength=wstr, Gust=wgust, Along=along)
        lrp = g.group(rope_pt, Curve=curve, U=lu, S=lsp["S"], Slope=lsp["Slope"], Height=lsp["Height"],
                      Sag=lsp["Sag"], **{"Half Span": half}, Swing=lswing["Swing"])
        lplaced = g.node("GeometryNodeSetPosition", Geometry=lp["Points"], Position=lrp["Position"])
        r_lk = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=lidx,
                      Seed=g.math("ADD", seed, 43))
        lkept = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=lplaced["Geometry"],
                       Selection=g.math("GREATER_THAN", r_lk["Value"], lchance))

    with g.frame("Lantern swing: lagged rope swing + steady push + ring at the cord pendulum period"):
        ldrive = g.group(wind, Time=time, Lag=0.6, S=lsp["S"], Seed=seed, Strength=wstr, Gust=wgust)
        lper = _pendulum_period(g, g.math("MULTIPLY", lsize, 0.62))
        lph = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, ID=lidx, Max=TAU,
                     Seed=g.math("ADD", seed, 47))["Value"]
        ring_s = _ring(g, time, lper, lph, math.radians(1.0))
        ring_d = _ring(g, time, g.math("MULTIPLY", lper, 1.07), g.math("ADD", lph, 1.9), math.radians(0.5))
        th_s = g.math("ADD", g.math("MULTIPLY", ldrive, g.math("ADD", g.math("MULTIPLY", along,
                                                                             math.radians(0.6)), ring_s)),
                      lswing["Swing"], label="Swing toward +s")
        th_d = g.math("MULTIPLY", ldrive, g.math("ADD", g.math("MULTIPLY", across, math.radians(1.2)), ring_d),
                      label="Swing toward +d")
        # street frame: X = +s, Y = +d, Z up; tip at -Z goes to +s for -angle about Y and to +d for +angle about X
        lrot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=lrp["Rotation"],
                      **{"Rotate By": g.node("FunctionNodeEulerToRotation",
                                             Euler=g.combine(th_d, g.math("MULTIPLY", th_s, -1.0), 0.0))})

    with g.frame("Lantern instances: glow colour and strength for the material"):
        lshape = g.group(lantern_shape, Size=lsize)
        lcol = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "POINT"},
                      Geometry=lkept["Geometry"], Name="ss_color", Value=lglow)
        lgl = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                     Geometry=lcol["Geometry"], Name="ss_glow", Value=lstr)
        lrnd = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                      Geometry=lgl["Geometry"], Name="ss_rand", Value=r_lk["Value"])
        lanterns = g.node("GeometryNodeInstanceOnPoints", Points=lrnd["Geometry"], Instance=lshape["Geometry"],
                          Rotation=lrot["Rotation"])

    with g.frame("Output: ropes, pennants, lanterns; drop the internal bunt_* attributes"):
        j = g.node("GeometryNodeJoinGeometry")
        for n in (rmat, flags, lanterns):
            g.connect(n.out, j.i("Geometry"))
        clean = g.node("GeometryNodeRemoveAttribute", Geometry=j["Geometry"], Name="bunt_*")
        clean.i("Pattern Mode").default_value = "Wildcard"
    g.output("Geometry", "GEOMETRY", clean["Geometry"])
    return g.finish()
