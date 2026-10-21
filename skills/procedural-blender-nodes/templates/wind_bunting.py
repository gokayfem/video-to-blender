"""Bunting and paper lanterns strung across any path between pairs of poles, swaying and fluttering in the wind.

    blender -b --factory-startup --python templates/wind_bunting.py -- --out out/bunting.blend [--render f.png]
        [--width 960] [--samples 16] [--frame 30] [--scene "Bunting Transfer"] [--frames 1:24 (--render is a folder)]

Technique: curve-space placement plus analytic motion. NK Curve Samples puts a pair of poles every Spacing along
the Path (both sides); each pair carries one rope. A rope point at u (0..1) is the chord point lowered by a
catenary sag, and the sag vector is rotated about the chord by the rope's swing angle (NK Catenary Point), so
rope, pennants and lanterns all hang off the same closed form. The motion is a function of Time only:
NK Wind Gust gives a gust that travels down the path, NK Pendulum Sway turns it into the rope's lean and ring,
NK Damped Spring adds each pennant's lagging flutter on top, and the lanterns swing as heavier pendulums on a
lagged gust (NK Wind Gust Lag). Lantern paper glows with NK Glow Glass, flickered per lantern by NK Flicker.
Nothing is simulated, so any frame renders alone and the motion is bounded by construction.

Scenes (one shared "Wind Bunting" group):
  Bunting            a market lane at dusk, eye level under the strings (rendered for the gallery)
  Bunting Transfer   the same group on a curved promenade seen from above
Adapt: pick your own curve as Path; change Palette, Festivity and Wind in the Primary panel; replace the pennant
or lantern shape inside "Wind Bunting Pennant" / "Wind Bunting Lantern".
"""
import argparse, math, pathlib, sys

SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import bpy
from nodekit import inspect
from nodekit import scene as S
from nodekit.graph import Graph, once
from library.curve import curve_samples, curve_ribbon, catenary_point
from library.shapes import rod, profile_revolve
from library.motion import wind_gust, pendulum_sway, damped_spring, flicker
from library.materials import make_material, wood_grain, attribute_tint, glow_glass, stone, store_local_coords, lin

NAME = "Wind Bunting"
TAU = 2 * math.pi
ROPE_POINTS = 24                       # points per rope: enough for a smooth parabola
PALETTES = {                           # menu item -> four pennant colours (sRGB hex)
    "Festival": ("#D94A3A", "#F2B33D", "#2F7FA8", "#F4EBD8"),
    "Pastel": ("#E8A0A0", "#F3D9A0", "#A8C8D8", "#C8D8A8"),
    "Seaside": ("#1F4E79", "#F4EBD8", "#C8423A", "#7FB8C8"),
}


# ---- small node idioms ---------------------------------------------------------------------------------------
def store(g, geo, name, value, dtype="FLOAT", domain="POINT"):
    return g.node("GeometryNodeStoreNamedAttribute", props={"data_type": dtype, "domain": domain},
                  Geometry=geo, Name=name, Value=value)["Geometry"]


def attr(g, name, dtype="FLOAT"):
    return g.node("GeometryNodeInputNamedAttribute", props={"data_type": dtype}, Name=name)["Attribute"]


def rand(g, lo, hi, seed, k, ident=None):
    n = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT"}, Min=lo, Max=hi, Seed=g.math("ADD", seed, k))
    if ident is not None:
        g.connect(ident, n.i("ID"))
    return n["Value"]


def join(g, *geos):
    j = g.node("GeometryNodeJoinGeometry")
    for x in reversed(geos):
        g.connect(x, j.i("Geometry"))
    return j["Geometry"]


# ---- template-local groups -----------------------------------------------------------------------------------
@once
def build_pennant():
    """A triangular pennant hanging from its top edge (along X) down -Z, with a slight cup."""
    g = Graph("Wind Bunting Pennant",
              description="A cloth pennant: a grid shaped into a triangle whose top edge runs along X at the "
                          "origin and whose tip hangs Length below, cupped a little in Y so it catches light")
    w = g.input("Width", "FLOAT", 0.24, min=0.01, max=10.0, subtype="DISTANCE", desc="Top edge width")
    ln = g.input("Length", "FLOAT", 0.3, min=0.01, max=10.0, subtype="DISTANCE", desc="Top edge to tip")
    cup = g.input("Cup", "FLOAT", 0.03, min=-1.0, max=1.0, subtype="DISTANCE", desc="Bulge towards +Y at the middle")
    with g.frame("Grid to triangle: t = 0 at the top edge, 1 at the tip; width shrinks with t"):
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": 1.0, "Size Y": 1.0, "Vertices X": 5,
                                                "Vertices Y": 6})["Mesh"]
        p = g.separate(g.node("GeometryNodeInputPosition"))
        t = g.math("SUBTRACT", 0.5, p["Y"])
        x = g.math("MULTIPLY", g.math("MULTIPLY", p["X"], w), g.math("SUBTRACT", 1.0, g.math("MULTIPLY", t, 0.97)))
        bulge = g.math("MULTIPLY", cup, g.math("SINE", g.math("MULTIPLY", t, math.pi)))
        tri = g.node("GeometryNodeSetPosition", Geometry=grid, Position=g.combine(
            x, bulge, g.math("MULTIPLY", t, g.math("MULTIPLY", ln, -1.0))))["Geometry"]
        tri = g.node("GeometryNodeSetShadeSmooth", Geometry=tri)["Geometry"]
    g.output("Mesh", "GEOMETRY", tri, desc="The pennant")
    return g.finish(split_inputs=False)


@once
def build_lantern():
    """A ribbed paper lantern hanging from the origin on a short cord, body along -Z."""
    g = Graph("Wind Bunting Lantern",
              description="A paper lantern 1 unit tall hanging from the origin: a cord, a dark top and bottom cap, "
                          "and an NK Profile Revolve body pinched into Ribs by a cosine of height")
    cord = g.input("Cord", "FLOAT", 0.9, min=0.0, max=10.0, subtype="DISTANCE", desc="Cord length (in body heights)")
    ribs = g.input("Ribs", "INT", 9, min=0, max=60, desc="Paper ribs along the body")
    depth = g.input("Rib Depth", "FLOAT", 0.03, min=0.0, max=0.3, subtype="FACTOR", desc="How deep the ribs pinch")
    paper = g.input("Paper Material", "MATERIAL", desc="Material of the glowing body")
    trim = g.input("Trim Material", "MATERIAL", desc="Material of the caps and cord")
    with g.frame("Body: revolved profile pinched into ribs, hanging below the cord"):
        body = g.group(profile_revolve(), Height=1.0, Segments=24, Rings=6, **{
            "Radius Bottom": 0.22, "Radius Lower": 0.38, "Radius Middle": 0.42, "Radius Upper": 0.38,
            "Radius Top": 0.22})["Mesh"]
        p = g.node("GeometryNodeInputPosition")["Position"]
        z = g.separate(p)["Z"]
        pinch = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", depth, g.math("POWER", g.math("ABSOLUTE", g.math(
            "COSINE", g.math("MULTIPLY", z, g.math("MULTIPLY", ribs, math.pi)))), 4.0)))
        body = g.node("GeometryNodeSetPosition", Geometry=body,
                      Position=g.vmath("MULTIPLY", p, g.combine(pinch, pinch, 1.0)))["Geometry"]
        body = g.node("GeometryNodeTransform", Geometry=body, Translation=g.combine(
            0.0, 0.0, g.math("SUBTRACT", -1.0, cord)))["Geometry"]
        body = g.node("GeometryNodeSetMaterial", Geometry=body, Material=paper)["Geometry"]
    with g.frame("Caps and cord"):
        cap = g.node("GeometryNodeMeshCylinder", Vertices=16, Radius=0.24, Depth=0.06)["Mesh"]
        top = g.node("GeometryNodeTransform", Geometry=cap, Translation=g.combine(0.0, 0.0, g.math(
            "MULTIPLY", cord, -1.0)))["Geometry"]
        bot = g.node("GeometryNodeTransform", Geometry=cap, Translation=g.combine(0.0, 0.0, g.math(
            "SUBTRACT", -1.0, cord)), Scale=(0.8, 0.8, 1.0))["Geometry"]
        line = g.group(rod(), Start=(0.0, 0.0, 0.0), End=g.combine(0.0, 0.0, g.math("MULTIPLY", cord, -1.0)),
                       Radius=0.02, Resolution=6)["Mesh"]
        trims = g.node("GeometryNodeSetMaterial", Geometry=join(g, top, bot, line), Material=trim)["Geometry"]
    g.output("Mesh", "GEOMETRY", join(g, body, trims), desc="The lantern")
    return g.finish()


# ---- the top group -------------------------------------------------------------------------------------------
def build_bunting(mats):
    rp, pennant, lantern = catenary_point(), build_pennant(), build_lantern()
    g = Graph(NAME, modifier=True,
              description="Bunting across any path: pairs of poles every Spacing along the Path, a sagging rope "
                          "between each pair, triangle pennants every Pennant Spacing and paper lanterns, all "
                          "moved by an analytic wind (gust, pendulum sway, damped flutter) of Scene Time")
    g.input("Geometry", "GEOMETRY", desc="Ignored; the bunting is generated from Path", hide_value=True)
    # Primary
    path = g.input("Path", "OBJECT", panel="Primary", desc="The curve the bunting follows")
    spacing = g.input("Spacing", "FLOAT", 3.6, min=0.5, max=50.0, subtype="DISTANCE", panel="Primary",
                      desc="Distance between strings (pole pairs) along the path")
    sag = g.input("Sag", "FLOAT", 0.6, min=0.0, max=5.0, subtype="DISTANCE", panel="Primary",
                  desc="How far each rope hangs below its anchors at the middle")
    fest = g.input("Festivity", "FLOAT", 1.0, min=0.2, max=3.0, panel="Primary",
                   desc="Pennant density and lantern chance: 0.2 sparse, 1 a market day, 3 a festival")
    wind = g.input("Wind", "FLOAT", 1.0, min=0.0, max=6.0, panel="Primary",
                   desc="0 still air, 1 a light breeze, 3+ a blustery day (swing and flutter)")
    palette = g.input("Palette", "MENU", panel="Primary", desc="Pennant colours: Festival, Pastel, Seaside or Custom")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, panel="Primary", desc="Changes every random choice")
    # Detailed
    width = g.input("Path Width", "FLOAT", 5.0, min=0.5, max=50.0, subtype="DISTANCE", panel="Poles",
                    desc="Distance between the two poles of a pair (the lane width)")
    pole_h = g.input("Pole Height", "FLOAT", 3.6, min=0.5, max=20.0, subtype="DISTANCE", panel="Poles",
                     desc="Pole height; ropes are tied just below the top")
    pole_r = g.input("Pole Radius", "FLOAT", 0.06, min=0.01, max=1.0, subtype="DISTANCE", panel="Poles",
                     desc="Pole radius")
    show_lane = g.input("Show Lane", "BOOL", True, panel="Poles", desc="A cobbled strip along the path")
    p_space = g.input("Pennant Spacing", "FLOAT", 0.34, min=0.05, max=5.0, subtype="DISTANCE", panel="Pennants",
                      desc="Distance between pennants on a rope at Festivity 1")
    p_w = g.input("Pennant Width", "FLOAT", 0.26, min=0.02, max=2.0, subtype="DISTANCE", panel="Pennants",
                  desc="Pennant top edge")
    p_l = g.input("Pennant Length", "FLOAT", 0.34, min=0.02, max=2.0, subtype="DISTANCE", panel="Pennants",
                  desc="Pennant length")
    rope_r = g.input("Rope Radius", "FLOAT", 0.008, min=0.001, max=0.2, subtype="DISTANCE", panel="Pennants",
                     desc="Rope thickness")
    l_chance = g.input("Lantern Chance", "FLOAT", 0.45, min=0.0, max=1.0, subtype="FACTOR", panel="Lanterns",
                       desc="Chance of a lantern at each of three slots per rope, at Festivity 1")
    l_size = g.input("Lantern Size", "FLOAT", 0.42, min=0.05, max=3.0, subtype="DISTANCE", panel="Lanterns",
                     desc="Lantern body height")
    glow = g.input("Lantern Glow", "FLOAT", 1.2, min=0.0, max=1000.0, panel="Lanterns",
                   desc="Emission strength of the lantern paper")
    gusty = g.input("Gustiness", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", panel="Wind",
                    desc="0 a steady wind, 1 calm spells between gusts")
    period = g.input("Gust Period", "FLOAT", 4.0, min=0.2, max=60.0, subtype="TIME_ABSOLUTE", panel="Wind",
                     desc="Typical seconds between gusts")
    swing = g.input("Rope Swing", "FLOAT", 0.12, min=0.0, max=1.0, subtype="ANGLE", panel="Wind",
                    desc="Rope lean and ring per unit Wind (radians)")
    flutter = g.input("Flutter", "FLOAT", 0.35, min=0.0, max=1.5, subtype="ANGLE", panel="Wind",
                      desc="Pennant flutter per unit Wind (radians)")
    tscale = g.input("Time Scale", "FLOAT", 1.0, min=0.0, max=10.0, panel="Wind", desc="Speed of all motion")
    toffset = g.input("Time Offset", "FLOAT", 0.0, subtype="TIME_ABSOLUTE", panel="Wind",
                      desc="Seconds added to scene time, to pick another moment")
    custom = [g.input(f"Custom Color {i + 1}", "COLOR", lin(c), panel="Palette",
                      desc=f"Pennant colour {i + 1} when Palette is Custom")
              for i, c in enumerate(PALETTES["Festival"])]
    for p in ("Poles", "Pennants", "Lanterns", "Wind", "Palette"):
        g._panels[p].default_closed = True

    with g.frame("Path, clock, palette"):
        curve = g.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=path)["Geometry"]
        time = g.math("MULTIPLY_ADD", g.node("GeometryNodeInputSceneTime")["Seconds"], tscale, toffset,
                      label="Time")
        menu = g.node("GeometryNodeMenuSwitch", props={"data_type": "INT"})
        menu.b.enum_items.clear()
        for k, name in enumerate([*PALETTES, "Custom"]):
            menu.b.enum_items.new(name)
            g.connect(k, menu.i(name))
        g.connect(palette, menu.i("Menu"))
        slots = []
        for j in range(4):
            sw = g.node("GeometryNodeIndexSwitch", props={"data_type": "RGBA"}, Index=menu["Output"])
            sw.b.index_switch_items.new()
            sw.b.index_switch_items.new()
            for k, cols in enumerate([*(lin(p[j]) for p in PALETTES.values()), custom[j]]):
                g.connect(cols, sw.i(k + 1))
            slots.append(sw["Output"])
    with g.frame("Poles: NK Curve Samples on both sides; one string per left/right pair"):
        smp = g.group(curve_samples(), Curve=curve, Spacing=spacing, **{"Both Sides": True,
                      "Offset": g.math("MULTIPLY", width, 0.5), "Seed": seed})
        poles = store(g, smp["Points"], "wb_h", g.math("MULTIPLY", pole_h, rand(g, 0.93, 1.07, seed, 10)))
        n = g.math("DIVIDE", g.node("GeometryNodeAttributeDomainSize", props={"component": "POINTCLOUD"},
                                    Geometry=poles)["Point Count"], 2.0, label="pairs")
        top = g.vmath("ADD", g.node("GeometryNodeInputPosition"), g.combine(0.0, 0.0, g.math("SUBTRACT", attr(g, "wb_h"), 0.15)))
        far = g.node("GeometryNodeSampleIndex", props={"data_type": "FLOAT_VECTOR", "domain": "POINT"},
                     Geometry=poles, Value=top, Index=g.math("ADD", g.node("GeometryNodeInputIndex"), n))["Value"]
        strings = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=poles, Selection=g.math(
            "LESS_THAN", attr(g, "nk_side", "INT"), 0.0))["Geometry"]
        strings = store(g, strings, "wb_a", top, "FLOAT_VECTOR")
        strings = store(g, strings, "wb_b", far, "FLOAT_VECTOR")
        sid = g.node("GeometryNodeInputIndex")["Index"]
        strings = store(g, strings, "wb_string", sid, "INT")
        strings = store(g, strings, "wb_sag", g.math("MULTIPLY", sag, rand(g, 0.85, 1.15, seed, 1, sid)))
        strings = store(g, strings, "wb_phase", rand(g, 0.0, TAU, seed, 2, sid))
    with g.frame("Wind: a gust travelling down the path (NK Wind Gust) swings each rope (NK Pendulum Sway)"):
        gust = g.group(wind_gust(), Time=time, Position=attr(g, "nk_s"), Strength=wind, Gustiness=gusty,
                       **{"Gust Period": period, "Seed": seed, "Travel Speed": 4.0})
        sway = g.group(pendulum_sway(), Time=time, Wind=gust["Gust"], Phase=attr(g, "wb_phase"), Lean=swing,
                       Length=g.math("MULTIPLY_ADD", attr(g, "wb_sag"), 2.0, 0.6),
                       Swing=g.math("MULTIPLY", swing, 0.6), Wobble=0.25)
        strings = store(g, strings, "wb_swing", sway["Angle"])
        strings = store(g, strings, "wb_gust", gust["Gust"])

    def on_rope(geo, u):
        """NK Catenary Point at U for every element of geo (which carries wb_a, wb_b, wb_sag, wb_swing)."""
        return g.group(rp, Start=attr(g, "wb_a", "FLOAT_VECTOR"), End=attr(g, "wb_b", "FLOAT_VECTOR"), U=u,
                       Sag=attr(g, "wb_sag"), Swing=attr(g, "wb_swing"))

    with g.frame("Ropes: NK Catenary Point at 24 values of U per string, joined into curves and swept"):
        dup = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=strings,
                     Amount=ROPE_POINTS)
        u = g.math("DIVIDE", dup["Duplicate Index"], ROPE_POINTS - 1.0)
        pts = g.node("GeometryNodeSetPosition", Geometry=dup["Geometry"], Position=on_rope(dup, u)["Position"])
        crv = g.node("GeometryNodePointsToCurves", Points=pts, Weight=u,
                     **{"Curve Group ID": attr(g, "wb_string", "INT")})["Curves"]
        prof = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=6, Radius=rope_r)["Curve"]
        ropes = g.node("GeometryNodeCurveToMesh", Curve=crv, **{"Profile Curve": prof})["Mesh"]
        ropes = g.node("GeometryNodeSetMaterial", Geometry=ropes, Material=mats["rope"])["Geometry"]
    with g.frame("Pennants: floor(chord / spacing) per rope, hung along the tangent, colour cycling the palette"):
        chord = g.vmath("DISTANCE", attr(g, "wb_a", "FLOAT_VECTOR"), attr(g, "wb_b", "FLOAT_VECTOR"))["Value"]
        m = g.math("FLOOR", g.math("DIVIDE", g.math("MULTIPLY", chord, fest), p_space))
        pd = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=strings, Amount=m)
        pu = g.math("DIVIDE", g.math("ADD", pd["Duplicate Index"], 0.5), g.math("MAXIMUM", m, 1.0))
        pid = g.node("GeometryNodeInputIndex")["Index"]
        pr = on_rope(pd, pu)
        ppts = g.node("GeometryNodeSetPosition", Geometry=pd["Geometry"], Position=pr["Position"])["Geometry"]
        k = g.math("FLOORED_MODULO", g.math("ADD", pd["Duplicate Index"], attr(g, "wb_string", "INT")), 4.0)
        col = g.node("GeometryNodeIndexSwitch", props={"data_type": "RGBA"}, Index=k)
        col.b.index_switch_items.new()
        col.b.index_switch_items.new()
        for j in range(4):
            g.connect(slots[j], col.i(j + 1))
        ppts = store(g, ppts, "nk_color", col["Output"], "FLOAT_COLOR")
        ppts = store(g, ppts, "nk_rand", rand(g, 0.0, 1.0, seed, 3, pid))
    with g.frame("Pennant flutter: NK Damped Spring lagging the gust, a wave running along the rope"):
        spring = g.group(damped_spring(), Time=time, Amplitude=1.0, Damping=0.25, **{
            "Drive Frequency": 1.3, "Natural Frequency": 1.8,
            "Phase": g.math("ADD", g.math("MULTIPLY", pu, -9.0), g.math("MULTIPLY", attr(g, "nk_rand"), 1.5))})
        ang = g.math("ADD", attr(g, "wb_swing"), g.math("MULTIPLY", g.math("MULTIPLY", spring["Response"], flutter),
                                                       g.math("MULTIPLY", attr(g, "wb_gust"), 0.7)))
        prot = g.node("FunctionNodeAlignRotationToVector", props={"axis": "X", "pivot_axis": "AUTO"},
                      Vector=pr["Tangent"])["Rotation"]
        prot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=prot, **{
            "Rotate By": g.node("FunctionNodeEulerToRotation", Euler=g.combine(ang, 0.0, 0.0))["Rotation"]})
        flags = g.node("GeometryNodeInstanceOnPoints", Points=ppts, Rotation=prot["Rotation"],
                       Instance=g.group(pennant, Width=p_w, Length=p_l))["Instances"]
        flags = g.node("GeometryNodeSetMaterial", Geometry=flags, Material=mats["cloth"])["Geometry"]
    with g.frame("Lanterns: three slots per rope, each lit with Lantern Chance x Festivity"):
        ld = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=strings, Amount=3)
        lid = g.node("GeometryNodeInputIndex")["Index"]
        keep = g.math("LESS_THAN", rand(g, 0.0, 1.0, seed, 4, lid), g.math("MULTIPLY", l_chance, fest))
        lpts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=ld["Geometry"],
                      Selection=g.node("FunctionNodeBooleanMath", props={"operation": "NOT"}, Boolean=keep))
        lpts = store(g, lpts["Geometry"], "wb_u", g.math("MULTIPLY_ADD", ld["Duplicate Index"], 0.25, g.math(
            "ADD", 0.25, rand(g, -0.05, 0.05, seed, 5, lid))))
        lr = on_rope(lpts, attr(g, "wb_u"))
        lpts = g.node("GeometryNodeSetPosition", Geometry=lpts, Position=lr["Position"])["Geometry"]
        ci = g.node("GeometryNodeIndexSwitch", props={"data_type": "RGBA"},
                    Index=g.math("FLOORED_MODULO", lid, 4.0))
        ci.b.index_switch_items.new()
        ci.b.index_switch_items.new()
        for j in range(4):
            g.connect(slots[j], ci.i(j + 1))
        warm = g.mix(0.7, ci["Output"], lin("#FF6A10"), data_type="RGBA")
        lpts = store(g, lpts, "nk_color", warm["Result"], "FLOAT_COLOR")
        fl = g.group(flicker(), Time=time, Seed=lid, Rate=1.2, Amount=0.2, Strength=glow)
        lpts = store(g, lpts, "nk_glow", fl["Value"])
    with g.frame("Lantern swing: a heavier pendulum on the lagged gust, about the rope's chord"):
        lgust = g.group(wind_gust(), Time=time, Position=attr(g, "nk_s"), Strength=wind, Gustiness=gusty,
                        **{"Gust Period": period, "Seed": seed, "Travel Speed": 4.0, "Lag": 0.6})
        lsway = g.group(pendulum_sway(), Time=time, Wind=lgust["Gust"], Lean=0.1, Swing=0.07, Wobble=0.2,
                        Length=g.math("MULTIPLY", l_size, 1.6), Phase=rand(g, 0.0, TAU, seed, 6, lid))
        chord_dir = g.vmath("NORMALIZE", g.vmath("SUBTRACT", attr(g, "wb_b", "FLOAT_VECTOR"),
                                                 attr(g, "wb_a", "FLOAT_VECTOR")))
        lrot = g.node("FunctionNodeAxisAngleToRotation", Axis=chord_dir, Angle=lsway["Angle"])["Rotation"]
        lamps = g.node("GeometryNodeInstanceOnPoints", Points=lpts, Rotation=lrot,
                       Instance=g.group(lantern, **{"Paper Material": mats["paper"], "Trim Material": mats["trim"]}),
                       Scale=g.math("MULTIPLY", l_size, rand(g, 0.85, 1.15, seed, 7, lid)))["Instances"]
    with g.frame("Pole meshes: a wooden rod and a ball finial on every pole, leaning a little"):
        pole = g.group(rod(), Start=(0.0, 0.0, 0.0), End=(0.0, 0.0, 1.0), Radius=pole_r, Resolution=12)["Mesh"]
        pole = g.group(store_local_coords(), Geometry=pole)["Geometry"]       # nk_local: grain in pole space
        ball = g.node("GeometryNodeMeshUVSphere", Segments=16, Rings=8,
                      Radius=g.math("MULTIPLY", pole_r, 1.5))["Mesh"]
        pmesh = g.node("GeometryNodeInstanceOnPoints", Points=poles, Instance=pole, Scale=g.combine(1.0, 1.0, attr(g, "wb_h")),
                       Rotation=g.node("FunctionNodeEulerToRotation", Euler=g.combine(
                           rand(g, -0.02, 0.02, seed, 8), rand(g, -0.02, 0.02, seed, 9), 0.0))["Rotation"])
        tops = g.node("GeometryNodeSetPosition", Geometry=poles, Offset=g.combine(0.0, 0.0, attr(g, "wb_h")))["Geometry"]
        balls = g.node("GeometryNodeInstanceOnPoints", Points=tops, Instance=ball)["Instances"]
        wood = g.node("GeometryNodeSetMaterial", Geometry=join(g, pmesh["Instances"], balls),
                      Material=mats["wood"])["Geometry"]
    with g.frame("Lane: a cobbled NK Curve Ribbon between the poles"):
        lane = g.group(curve_ribbon(), Curve=curve, Width=g.math("SUBTRACT", width, 0.4), Height=0.01,
                       Material=mats["cobble"], **{"Segments Across": 2})["Mesh"]
        lane = g.node("GeometryNodeSwitch", props={"input_type": "GEOMETRY"}, Switch=show_lane,
                      **{"True": lane})["Output"]
    with g.frame("Join and realize (shaders read nk_color, nk_rand, nk_glow, nk_local)"):
        out = g.node("GeometryNodeRealizeInstances", Geometry=join(g, ropes, flags, lamps, wood, lane))["Geometry"]
    g.output("Geometry", "GEOMETRY", out, desc="Poles, ropes, pennants, lanterns and lane")
    tree = g.finish()
    tree.interface.items_tree["Palette"].default_value = "Festival"
    return tree


# ---- materials -----------------------------------------------------------------------------------------------
def materials():
    return {
        "cloth": make_material("Wind Bunting Cloth", attribute_tint, bsdf={"Sheen Weight": 0.4}, **{
            "Value Variation": 0.12, "Hue Variation": 0.02, "Roughness": 0.85}),
        "paper": make_material("Wind Bunting Paper", glow_glass, **{
            "Core Color": "attr:nk_color", "Flicker": "attr:nk_glow", "Strength": 1.0, "Rim": 0.6,
            "Glass Color": lin("#B07A4A"), "Roughness": 0.7}),
        "trim": make_material("Wind Bunting Trim", attribute_tint, **{
            "Base Color": lin("#2A211C"), "Attribute Weight": 0.0, "Roughness": 0.5}),
        "rope": make_material("Wind Bunting Rope", attribute_tint, **{
            "Base Color": lin("#D8CBB0"), "Attribute Weight": 0.0, "Roughness": 0.9}),
        "wood": make_material("Wind Bunting Wood", wood_grain, **{
            "Light Color": lin("#7E5C40"), "Dark Color": lin("#4A3222"), "Piece Shift": 53.0,
            "Ring Scale": 50.0, "Distortion": 1.5, "Roughness": 0.7}),
        "cobble": make_material("Wind Bunting Cobble", stone, **{"Stone Scale": 6.0, "Color": lin("#A08C76")}),
    }


# ---- scenes --------------------------------------------------------------------------------------------------
def path(sc, name, pts):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    ob = bpy.data.objects.new(name, cu)
    ob.hide_render = True
    sc.collection.objects.link(ob)
    return ob


def camera(sc, loc, target, lens):
    cam = bpy.data.objects.new(f"{sc.name} Camera", bpy.data.cameras.new(f"{sc.name} Camera"))
    cam.data.lens, cam.data.clip_end = lens, 500
    aim = bpy.data.objects.new(f"{sc.name} Camera Target", None)
    cam.location, aim.location = loc, target
    for o in (cam, aim):
        sc.collection.objects.link(o)
    c = cam.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
    sc.camera = cam
    return cam


LIGHT = {   # light_world and post arguments per look
    "dusk": (dict(sun_elev=10, sun_azim=20, strength=3.5, sun_color="#FFB27A", sky_top="#5D7EA6",
                  sky_horizon="#F2B98C", sky_strength=0.7),
             dict(haze_color="#E9B88E", haze_start=6.0, haze_depth=70.0, haze_amount=0.65, glare=0.6,
                  sky_top="#4F6F9C", sky_horizon="#F4BC8C")),
    "day": (dict(sun_elev=40, sun_azim=140, strength=4.0, sun_color="#FFE6C8", sky_top="#8FB8D8",
                 sky_horizon="#E6D8C4", sky_strength=1.0),
            dict(haze_color="#E6D8C4", haze_start=20.0, haze_depth=150.0, haze_amount=0.4, glare=0.3,
                 sky_top="#8FB8D8", sky_horizon="#E6D8C4")),
}
SCENES = {
    # a gently winding market lane at dusk, eye level under the strings
    "Bunting": dict(pts=[(0, -8, 0), (0.5, 6, 0), (-2.5, 20, 0), (1, 34, 0), (4, 48, 0)],
                    cam=((0.9, -12.5, 1.65), (-0.3, 6.0, 3.1), 24), preset={}, light="dusk"),
    # a curved promenade (three quarters of a circle) seen from above
    "Bunting Transfer": dict(pts=[(12 * math.cos(a), 12 * math.sin(a), 0)
                                  for a in [math.radians(d) for d in range(200, -80, -35)]],
                             cam=((3.0, -31.0, 19.0), (0.0, 1.5, 0.0), 30),
                             preset={"Palette": "Pastel", "Spacing": 3.0, "Seed": 2}, light="day"),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--render")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--frame", type=int, default=30)
    ap.add_argument("--scene", default="", help="render this scene instead of the first")
    ap.add_argument("--frames", default="", help="render a sequence a:b into --render (a folder) instead")
    a = ap.parse_args(argv)

    sc0 = S.reset()
    group = build_bunting(materials())
    for i, (name, cfg) in enumerate(SCENES.items()):
        sc = sc0 if i == 0 else bpy.data.scenes.new(name)
        sc.name = name
        sc.render.fps, sc.frame_start, sc.frame_end = S.FPS, 1, 96
        crv = path(sc, f"{name} Path", cfg["pts"])
        ob, mod = S.holder(f"{name} Bunting", crv, group, sc=sc)
        inspect.set_modifier_inputs(mod, {"Path": crv.name, **cfg["preset"]})
        S.ground(sc=sc, color="#7E8A50")
        light, post = LIGHT[cfg["light"]]
        S.light_world(sc=sc, **light)
        camera(sc, *cfg["cam"])
        w = a.width
        S.render_setup(sc=sc, width=w, height=int(w * 0.5625) // 2 * 2, samples=a.samples,
                       look="Medium High Contrast")
        S.post(sc=sc, **post)
        sc.frame_set(a.frame)
        st = inspect.evaluated_stats(ob, sc)
        print(f"SCENE {name}: verts {st['verts']} faces {st['faces']} warnings "
              f"{[x.message for x in mod.node_warnings]}")
    problems = inspect.check_groups()
    print("LINT", len(problems), *problems, sep="\n  ")
    out = pathlib.Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
    if a.render:
        sc = bpy.data.scenes[a.scene or next(iter(SCENES))]
        if bpy.context.window:
            bpy.context.window.scene = sc
        frames = [a.frame]
        if a.frames:
            f0, f1 = (int(x) for x in a.frames.split(":"))
            frames = range(f0, f1 + 1)
        for f in frames:
            sc.frame_set(f)
            dst = pathlib.Path(a.render).resolve()
            sc.render.filepath = str(dst / f"{f:04d}.png" if a.frames else dst)
            bpy.ops.render.render(write_still=True, scene=sc.name)
            print("RENDERED", sc.render.filepath)


main()
