"""A storybook house generated from a footprint and a few controls.

    blender -b --factory-startup --python templates/parametric_house.py -- --out out/parametric_house.blend \
        [--render out/parametric_house.png] [--width 960] [--samples 16] [--frame 1] [--scene "House Row"]

One modifier group, "Parametric House", builds a whole half-timbered house from Width, Depth and Storeys. Every
part is modelled in FACADE space and placed through one shared frame, so the parts read as short formulas:

    Parametric House Facades   NK Facade Frame on one box per storey: a point per wall face (front, right, back,
                               left, ordered 4 x storey + side): face centre f_centre,
                               turn f_rot (local X along the wall, Y out of it, Z up), length, floor heights, the
                               number of window slots, window size and height, the door slot
    Parametric House Openings  window points (one per slot, the door slot left out, plus a gable window) and the
                               door point, in facade space (w_u along the wall, w_z up)
    Parametric House Walls     plaster storey blocks (NK Chamfer Boxes; each upper storey jettied forward) and the
                               gables, with window and door reveals cut by a Manifold boolean; stone plinth;
                               bressummer beams and braced corbels under the jetties
    Parametric House Timber    half-timbering on the upper storeys: plates, rails, posts, crosses under windows and
                               a collar truss in the gables; Timber Amount adds pieces one at a time
    Parametric House Windows   glass (NK Glow Glass), frames, sills, louvred shutters, window boxes planted with
                               NK Foliage Mound and NK Blossom
    Parametric House Door      plank door in a timber frame, strap hinges, step, a wall lantern
    Parametric House Roof      roof slabs, staggered clay tiles (NK Terracotta) one by one, ridge, barge boards,
                               chimney with an NK Profile Revolve pot

Coordinates: x across the front (-Width/2..Width/2), y out of the front (ground-floor front at y = 0, the house
runs back to y = -Depth), z up from the ground. Upper storey k has its front at y = k * Jetty.

Scenes: "House" (the hero 3/4 view) and "House Row" (Parametric House Row: NK Curve Parcels along a curve, one
house per parcel with its own width, storeys, timbering, pitch and seed, built by the same group in a For Each zone).
"""
import argparse, math, pathlib, sys

SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import bpy
from nodekit import inspect
from nodekit import scene as S
from nodekit.graph import Graph, once
from library.curve import curve_parcels, curve_ribbon
from library.scatter import facade_frame
from library.shapes import chamfer_boxes, foliage_mound, profile_revolve
from library.materials import (make_material, attribute_tint, stucco, wood_grain, stone, terracotta, glow_glass,
                               lin)
from library.post import haze_over_sky, soft_glow

NAME = "Parametric House"
BEAM = 0.16              # timber width on the wall face
BEAM_D = 0.08            # timber depth; timbers sit 2 cm into the plaster
TIMBER_V = 0.02          # facade-space v of the timber centre


# ---- node idioms (python helpers, not groups) -----------------------------------------------------------------
def add(g, a, b): return g.math("ADD", a, b)
def sub(g, a, b): return g.math("SUBTRACT", a, b)
def mul(g, a, b): return g.math("MULTIPLY", a, b)
def div(g, a, b): return g.math("DIVIDE", a, b)
def mn(g, a, b): return g.math("MINIMUM", a, b)
def mx(g, a, b): return g.math("MAXIMUM", a, b)
def half(g, a): return g.math("MULTIPLY", a, 0.5)


def attr(g, name, dtype="FLOAT"):
    return g.node("GeometryNodeInputNamedAttribute", props={"data_type": dtype}, Name=name)["Attribute"]


def store(g, geo, name, value, dtype="FLOAT", domain="POINT"):
    return g.node("GeometryNodeStoreNamedAttribute", props={"data_type": dtype, "domain": domain},
                  Geometry=geo, Name=name, Value=value)["Geometry"]


def rand(g, lo, hi, seed, k, ident=None, dtype="FLOAT"):
    n = g.node("FunctionNodeRandomValue", props={"data_type": dtype}, Min=lo, Max=hi,
               Seed=g.math("ADD", seed, float(k)))
    if ident is None:                   # per element
        ident = g.node("GeometryNodeInputIndex")["Index"]
    elif isinstance(ident, (int, float)):  # one value for the whole house (the ID socket ignores constants)
        ident = g.value(float(ident))
    g.connect(ident, n.i("ID"))
    return n["Value"]


def cmp(g, a, b, op="GREATER_THAN"):
    return g.node("FunctionNodeCompare", props={"data_type": "FLOAT", "operation": op}, A=a, B=b)["Result"]


def both(g, a, b, op="AND"):
    n = g.node("FunctionNodeBooleanMath", props={"operation": op})
    g.connect(a, n.i(0))
    g.connect(b, n.i(1))
    return n["Boolean"]


def switch(g, typ, cond, false=None, true=None):
    n = g.node("GeometryNodeSwitch", props={"input_type": typ}, Switch=cond)
    g.connect(false, n.i("False"))
    g.connect(true, n.i("True"))
    return n["Output"]


def pick(g, idx, items, dtype="FLOAT"):
    """Index Switch: items[idx]."""
    n = g.node("GeometryNodeIndexSwitch", props={"data_type": dtype})
    while len([s for s in n.b.inputs if s.enabled and s.name not in ("Index", "")]) < len(items):
        n.b.index_switch_items.new()
    g.connect(idx, n.i("Index"))
    for k, v in enumerate(items):
        g.connect(v, n.i(str(k)))
    return n["Output"]


def join(g, *geos):
    j = g.node("GeometryNodeJoinGeometry")
    for x in reversed(geos):            # the multi-input socket stacks the newest link first
        g.connect(x, j.i("Geometry"))
    return j["Geometry"]


def dup(g, geo, amount):
    """Duplicate each point `amount` times; returns the copies and the copy index (0..amount-1)."""
    n = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=geo, Amount=amount)
    return n["Geometry"], n["Duplicate Index"]


def keep(g, geo, sel):
    """Only the points where sel is true."""
    return g.node("GeometryNodeSeparateGeometry", props={"domain": "POINT"}, Geometry=geo, Selection=sel)["Selection"]


def euler(g, x=0.0, y=0.0, z=0.0):
    return g.node("FunctionNodeEulerToRotation", Euler=g.combine(x, y, z))["Rotation"]


def strut(g, ua, za, ub, zb):
    """A beam in the wall plane from (ua, za) to (ub, zb): centre u, centre z, length, local rotation (X along it)."""
    du, dz = sub(g, ub, ua), sub(g, zb, za)
    length = g.vmath("LENGTH", g.combine(du, dz, 0.0))["Value"]
    ang = g.math("ARCTAN2", dz, du)
    return half(g, add(g, ua, ub)), half(g, add(g, za, zb)), length, euler(g, 0.0, mul(g, ang, -1.0), 0.0)


def on_facade(g, pts, u, v, z):
    """Move points to facade space: u along the wall, v out of it, z up (through f_centre and f_rot)."""
    off = g.node("FunctionNodeRotateVector", Vector=g.combine(u, v, 0.0),
                 Rotation=attr(g, "f_rot", "QUATERNION"))["Vector"]
    pos = g.vmath("ADD", g.vmath("ADD", attr(g, "f_centre", "FLOAT_VECTOR"), off), g.combine(0.0, 0.0, z))
    return g.node("GeometryNodeSetPosition", Geometry=pts, Position=pos)["Geometry"]


def boxes(g, pts, u, v, z, size, mat, color, local_rot=None, sel=True, chamfer=0.012, seed=0):
    """NK Chamfer Boxes on facade points: centre (u, v, z) in facade space, Size along the facade axes (or along
    local_rot's axes), painted nk_color, nk_rand per box, material set."""
    pts = on_facade(g, pts, u, v, z)
    pts = store(g, pts, "nk_color", color, "FLOAT_COLOR")
    pts = store(g, pts, "nk_rand", rand(g, 0.0, 1.0, seed, 97))
    rot = attr(g, "f_rot", "QUATERNION")
    if local_rot is not None:
        rot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"}, Rotation=rot,
                     **{"Rotate By": local_rot})["Rotation"]
    mesh = g.group(chamfer_boxes(), Points=pts, Selection=sel, Size=size, Rotation=rot, Chamfer=chamfer)["Mesh"]
    return g.node("GeometryNodeSetMaterial", Geometry=mesh, Material=mat)["Geometry"]


def scale_color(g, c, k):
    return g.vmath("SCALE", c, scale=k)["Vector"]


# ---- materials ----------------------------------------------------------------------------------------------------
@once
def plaster_paint():
    g = Graph("Parametric House Plaster Paint", kind="SHADER",
              description="Lime plaster: NK Stucco in the house colour (nk_color through NK Attribute Tint), "
                          "grime rising from the ground")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True, desc="Texture coordinate in metres")
    with g.frame("House colour, then plaster"):
        tint = g.group(attribute_tint(), **{"Base Color": lin("#E4C9A0"), "Value Variation": 0.0,
                                            "Hue Variation": 0.0})
        st = g.group(stucco(), Vector=vec, Color=tint["Color"],
                     **{"Grime Height": 0.9, "Grime": 0.45, "Mottle": 0.18, "Bump": 0.15})
    g.output("Color", "COLOR", st["Color"], desc="Plaster colour")
    g.output("Roughness", "FLOAT", st["Roughness"], desc="Roughness")
    g.output("Normal", "VECTOR", st["Normal"], desc="Bumped normal")
    return g.finish()


@once
def timber_paint():
    g = Graph("Parametric House Timber Paint", kind="SHADER",
              description="Oak beams: NK Wood Grain with its light colour from nk_color and dark rings below it")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True, desc="Texture coordinate in metres")
    with g.frame("Timber colour, then grain"):
        tint = g.group(attribute_tint(), **{"Base Color": lin("#5A3A24"), "Value Variation": 0.25})
        wd = g.group(wood_grain(), Vector=vec, **{"Light Color": tint["Color"],
                                                  "Dark Color": scale_color(g, tint["Color"], 0.55),
                                                  "Ring Scale": 14.0, "Roughness": 0.7, "Bump": 0.25})
    g.output("Color", "COLOR", wd["Color"], desc="Wood colour")
    g.output("Roughness", "FLOAT", wd["Roughness"], desc="Roughness")
    g.output("Normal", "VECTOR", wd["Normal"], desc="Bumped normal")
    return g.finish()


@once
def tile_paint():
    g = Graph("Parametric House Tile Paint", kind="SHADER",
              description="Clay tiles: NK Terracotta between the roof colour (nk_color) and a darker firing, "
                          "each tile a little different (nk_rand)")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True, desc="Texture coordinate in metres")
    with g.frame("Roof colour, then clay"):
        tint = g.group(attribute_tint(), **{"Base Color": lin("#B0603C"), "Value Variation": 0.3,
                                            "Hue Variation": 0.012})
        tc = g.group(terracotta(), Vector=vec, Color=tint["Color"],
                     **{"Dark Color": scale_color(g, tint["Color"], 0.72), "Variation": 0.35, "Bloom": 0.25})
    g.output("Color", "COLOR", tc["Color"], desc="Tile colour")
    g.output("Roughness", "FLOAT", tc["Roughness"], desc="Roughness")
    g.output("Normal", "VECTOR", tc["Normal"], desc="Bumped normal")
    return g.finish()


@once
def stone_paint():
    g = Graph("Parametric House Stone Paint", kind="SHADER",
              description="Rubble stone (plinth, step, chimney): NK Stone in nk_color")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True, desc="Texture coordinate in metres")
    with g.frame("Stone colour, then stones"):
        tint = g.group(attribute_tint(), **{"Base Color": lin("#9A8C7A"), "Value Variation": 0.0})
        st = g.group(stone(), Vector=vec, Color=tint["Color"], **{"Stone Scale": 5.0, "Bump": 0.5})
    g.output("Color", "COLOR", st["Color"], desc="Stone colour")
    g.output("Roughness", "FLOAT", st["Roughness"], desc="Roughness")
    g.output("Normal", "VECTOR", st["Normal"], desc="Bumped normal")
    return g.finish()


@once
def petal_paint():
    g = Graph("Parametric House Petal Paint", kind="SHADER",
              description="Leaves and blossoms painted by nk_color (NK Attribute Tint), blossom centres "
                          "(nk_part = 1) in Centre Color")
    part = g.input("Part", "FLOAT", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                   desc="1 on blossom centres (wire the nk_part attribute here)")
    centre = g.input("Centre Color", "COLOR", lin("#E8B520"), desc="Colour of the flower centres")
    with g.frame("nk_color per instance, then centres"):
        tint = g.group(attribute_tint(), **{"Base Color": lin("#4F7A2A"), "Value Variation": 0.15,
                                            "Roughness": 0.5})
        col = g.mix(part, tint["Color"], centre, data_type="RGBA")["Result"]
    g.output("Color", "COLOR", col, desc="Leaf or petal colour")
    g.output("Roughness", "FLOAT", tint["Roughness"], desc="Roughness")
    g.output("Subsurface", "FLOAT", 0.2, desc="Soft light through leaves and petals")
    return g.finish()


def materials():
    """Every material the house uses, keyed by part. Colours come per piece through nk_color."""
    return {
        "plaster": make_material("Parametric House Plaster", plaster_paint()),
        "timber": make_material("Parametric House Timber", timber_paint()),
        "tile": make_material("Parametric House Tile", tile_paint()),
        "stone": make_material("Parametric House Stone", stone_paint()),
        "paint": make_material("Parametric House Paint", attribute_tint(),
                               **{"Value Variation": 0.08, "Roughness": 0.5}),
        "glass": make_material("Parametric House Glass", glow_glass(), Strength="attr:hp_glow",
                               **{"Glass Color": lin("#1C2630"), "Roughness": 0.08}),
        "plant": make_material("Parametric House Plant", petal_paint(), Part="attr:nk_part"),
    }


# ---- shared scalar inputs ---------------------------------------------------------------------------------------
# Every part group declares the scalars it needs with these specs, so the top group wires them all by name.
SPEC = {
    "Width": ("FLOAT", 6.4, 3.0, 16.0, "DISTANCE", "Frontage, across the front (x)"),
    "Depth": ("FLOAT", 5.2, 3.0, 14.0, "DISTANCE", "Ground-floor depth, front to back (y)"),
    "Storeys": ("INT", 3, 1, 6, None, "Storeys including the ground floor"),
    "Ground Floor Height": ("FLOAT", 2.7, 2.0, 5.0, "DISTANCE", "Height of the ground storey"),
    "Floor Height": ("FLOAT", 2.35, 1.8, 4.0, "DISTANCE", "Height of each upper storey"),
    "Jetty": ("FLOAT", 0.35, 0.0, 1.2, "DISTANCE", "How far each upper storey steps out over the one below"),
    "Roof Pitch": ("FLOAT", math.radians(52), math.radians(20), math.radians(68), "ANGLE",
                   "Roof slope; the gables get taller with it"),
    "Overhang": ("FLOAT", 0.45, 0.0, 1.5, "DISTANCE", "Roof overhang past the walls at eaves and gables"),
    "Timber Amount": ("FLOAT", 0.75, 0.0, 1.0, "FACTOR",
                      "0 plain plaster; up to 1 adds posts, rails, crosses and gable trusses one by one"),
    "Window Width": ("FLOAT", 0.85, 0.3, 2.5, "DISTANCE", "Window width (narrowed to fit its slot)"),
    "Window Height": ("FLOAT", 1.15, 0.3, 2.5, "DISTANCE", "Window height (lowered to fit its storey)"),
    "Window Spacing": ("FLOAT", 1.75, 0.8, 6.0, "DISTANCE", "Wall length per window slot"),
    "Reveal": ("FLOAT", 0.16, 0.02, 0.5, "DISTANCE", "How deep windows and the door sit in the wall"),
    "Gable Window": ("BOOL", True, None, None, None, "A small window in each gable when it is tall enough"),
    "Door Width": ("FLOAT", 1.0, 0.6, 2.5, "DISTANCE", "Door width (narrowed to fit its slot)"),
    "Door Height": ("FLOAT", 2.05, 1.6, 3.5, "DISTANCE", "Door height (lowered to fit the ground storey)"),
    "Plinth Height": ("FLOAT", 0.45, 0.0, 1.5, "DISTANCE", "Height of the stone plinth around the ground floor"),
    "Shutter Chance": ("FLOAT", 0.75, 0.0, 1.0, "FACTOR", "Share of windows with shutters"),
    "Window Box Chance": ("FLOAT", 0.55, 0.0, 1.0, "FACTOR", "Share of windows with a planted window box"),
    "Lit Windows": ("FLOAT", 0.3, 0.0, 1.0, "FACTOR", "Share of windows lit from inside (and the lantern)"),
    "Glow": ("FLOAT", 2.5, 0.0, 50.0, None, "Emission strength of lit windows and the lantern"),
    "Lantern": ("BOOL", True, None, None, None, "A lantern on the wall beside the door"),
    "Tile Size": ("FLOAT", 0.3, 0.12, 1.0, "DISTANCE", "Width of one roof tile (courses are 0.8 of it)"),
    "Chimney": ("BOOL", True, None, None, None, "A stone chimney through the roof"),
    "Seed": ("INT", 0, 0, 100000, None, "Changes the colours and every random choice"),
}


def inputs(g, *names, panel=None):
    out = {}
    for n in names:
        stype, dv, lo, hi, sub_, desc = SPEC[n]
        out[n] = g.input(n, stype, dv, min=lo, max=hi, subtype=sub_, desc=desc, panel=panel)
    return out


def eave(g, i):
    """Wall top: Ground Floor Height + (Storeys - 1) x Floor Height."""
    return g.math("MULTIPLY_ADD", sub(g, i["Storeys"], 1.0), i["Floor Height"], i["Ground Floor Height"])


def rise(g, i):
    """Gable height above the eaves: half the width x tan(pitch)."""
    return mul(g, half(g, i["Width"]), g.math("TANGENT", i["Roof Pitch"]))


# ---- Parametric House Facades --------------------------------------------------------------------------------------
@once
def facades():
    g = Graph("Parametric House Facades", description="One point per wall face and storey (NK Facade Frame on "
                                                       "one box per storey, sorted so index = 4 x storey + "
                                                       "side; side 0 front +Y, 1 right +X, 2 back, 3 left). Stores "
                                                       "the facade frame (f_centre, f_rot: X along the wall, Y out), "
                                                       "f_len, floor heights f_zb/f_z1, window slots f_n/f_slot, "
                                                       "window size and centre height, and the door slot")
    i = inputs(g, "Width", "Depth", "Storeys", "Ground Floor Height", "Floor Height", "Jetty", "Window Width",
               "Window Height", "Window Spacing", "Door Width", "Door Height", "Seed")
    W, D = i["Width"], i["Depth"]
    with g.frame("Storey boxes: storey k spans x +-W/2, y from -D to its jettied front k x Jetty, zb..z1"):
        boxes = g.node("GeometryNodePoints", Count=i["Storeys"])["Points"]
        k = g.node("GeometryNodeInputIndex")["Index"]
        front = mul(g, k, i["Jetty"])
        zb = mul(g, g.math("MULTIPLY_ADD", sub(g, k, 1.0), i["Floor Height"], i["Ground Floor Height"]),
                 cmp(g, k, 0.5))
        z1 = g.math("MULTIPLY_ADD", k, i["Floor Height"], i["Ground Floor Height"])
        boxes = g.node("GeometryNodeSetPosition", Geometry=boxes, Position=g.combine(
            0.0, half(g, sub(g, front, D)), half(g, add(g, zb, z1))))["Geometry"]
        boxes = store(g, boxes, "f_storey", k, "INT")
        size = g.combine(W, add(g, D, front), sub(g, z1, zb))
        boxes = g.node("GeometryNodeInstanceOnPoints", Points=boxes, Scale=size,
                       Instance=g.node("GeometryNodeMeshCube", Size=(1.0, 1.0, 1.0))["Mesh"])["Instances"]
        boxes = g.node("GeometryNodeRealizeInstances", Geometry=boxes)["Geometry"]
    with g.frame("NK Facade Frame: a point per wall; side s from its outward axis; order by 4 k + s"):
        pts = g.group(facade_frame(), Mesh=boxes)["Points"]
        out_y = g.node("FunctionNodeRotateVector", Vector=(0.0, 1.0, 0.0),
                       Rotation=attr(g, "nk_rot", "QUATERNION"))["Vector"]
        oy = g.separate(out_y)
        theta = g.math("ARCTAN2", mul(g, oy["X"], -1.0), oy["Y"])
        s = g.math("FLOORED_MODULO", g.math("ROUND", div(g, theta, -math.pi / 2)), 4.0)
        k = attr(g, "f_storey", "INT")
        pts = store(g, pts, "f_side", s, "INT")
        pts = g.node("GeometryNodeSortElements", props={"domain": "POINT"}, Geometry=pts, **{
            "Sort Weight": g.math("MULTIPLY_ADD", k, 4.0, attr(g, "f_side", "INT"))})["Geometry"]
        p = g.separate(g.node("GeometryNodeInputPosition"))
        length = g.separate(attr(g, "nk_size", "FLOAT_VECTOR"))["X"]
        cx, cy = p["X"], p["Y"]
    with g.frame("Floor heights: base f_zb (0 on the ground) and top f_z1"):
        zb = mul(g, g.math("MULTIPLY_ADD", sub(g, k, 1.0), i["Floor Height"], i["Ground Floor Height"]),
                 cmp(g, k, 0.5))
        z1 = g.math("MULTIPLY_ADD", k, i["Floor Height"], i["Ground Floor Height"])
    with g.frame("Window slots along the wall; window size fitted to slot and storey; door slot"):
        n = mx(g, g.math("FLOOR", div(g, length, i["Window Spacing"])), 1.0)
        slot = div(g, length, n)
        ww = mx(g, mn(g, i["Window Width"], sub(g, slot, 0.5)), 0.3)
        wh = mx(g, mn(g, i["Window Height"], sub(g, sub(g, z1, zb), 1.1)), 0.3)
        wz = add(g, zb, mul(g, sub(g, z1, zb), 0.55))
        r = rand(g, 0.0, 0.999, i["Seed"], 3, ident=0)
        dslot = switch(g, "FLOAT", cmp(g, n, 2.5), g.math("FLOOR", mul(g, r, n)),
                       add(g, 1.0, g.math("FLOOR", mul(g, r, sub(g, n, 2.0)))))
        du = sub(g, mul(g, add(g, dslot, 0.5), slot), half(g, length))
    with g.frame("Store the facade frame and its numbers"):
        for name, value, dt in (("f_len", length, "FLOAT"),
                                ("f_zb", zb, "FLOAT"), ("f_z1", z1, "FLOAT"), ("f_n", n, "INT"),
                                ("f_slot", slot, "FLOAT"), ("f_ww", ww, "FLOAT"), ("f_wh", wh, "FLOAT"),
                                ("f_wz", wz, "FLOAT"), ("f_dslot", dslot, "INT"), ("f_du", du, "FLOAT"),
                                ("f_dw", mn(g, i["Door Width"], sub(g, slot, 0.35)), "FLOAT"),
                                ("f_dh", mn(g, i["Door Height"], sub(g, i["Ground Floor Height"], 0.4)), "FLOAT"),
                                ("f_centre", g.combine(cx, cy, 0.0), "FLOAT_VECTOR"),
                                ("f_rot", attr(g, "nk_rot", "QUATERNION"), "QUATERNION")):
            pts = store(g, pts, name, value, dt)
        pts = g.node("GeometryNodeRemoveAttribute", Geometry=pts, Name="nk_*",
                     **{"Pattern Mode": "Wildcard"})["Geometry"]
    g.output("Facades", "GEOMETRY", pts, desc="One point per wall face and storey with the f_* attributes")
    return g.finish()


def side(g):
    return attr(g, "f_side", "INT")


def storey(g):
    return attr(g, "f_storey", "INT")


def is_side(g, s):
    return cmp(g, side(g), float(s), "EQUAL")


# ---- Parametric House Openings ---------------------------------------------------------------------------------------
@once
def openings():
    g = Graph("Parametric House Openings", description="Window points, one per slot on every facade except the "
                                                       "door slot, plus a small window in each gable; and the door "
                                                       "point. Each carries its facade's frame and w_u (along the "
                                                       "wall), w_z (centre height), w_w, w_h, w_kind (0 wall, 1 "
                                                       "gable) and w_rand")
    fac = g.input("Facades", "GEOMETRY", desc="Facade points (Parametric House Facades)")
    i = inputs(g, "Width", "Storeys", "Ground Floor Height", "Floor Height", "Roof Pitch", "Gable Window", "Seed")
    with g.frame("A window in every slot; the door takes one slot of the ground-floor front"):
        win, j = dup(g, fac, attr(g, "f_n", "INT"))
        u = sub(g, mul(g, add(g, j, 0.5), attr(g, "f_slot")), half(g, attr(g, "f_len")))
        win = store(g, win, "w_u", u)
        door_slot = both(g, both(g, is_side(g, 0), cmp(g, storey(g), 0.0, "EQUAL")),
                         cmp(g, j, attr(g, "f_dslot", "INT"), "EQUAL"))
        win = store(g, win, "w_door", door_slot, "BOOLEAN")
        win = keep(g, win, g.node("FunctionNodeBooleanMath", props={"operation": "NOT"},
                                  Boolean=attr(g, "w_door", "BOOLEAN"))["Boolean"])
        for name, src in (("w_z", "f_wz"), ("w_w", "f_ww"), ("w_h", "f_wh")):
            win = store(g, win, name, attr(g, src))
    with g.frame("Gable windows: front and back of the top storey, a third of the way up the gable"):
        top = cmp(g, storey(g), sub(g, i["Storeys"], 1.0), "EQUAL")
        ends = both(g, is_side(g, 0), is_side(g, 2), "OR")
        r = rise(g, i)
        gab = keep(g, fac, both(g, both(g, top, ends), both(g, i["Gable Window"], cmp(g, r, 1.6))))
        gab = store(g, gab, "w_u", 0.0)
        gab = store(g, gab, "w_z", add(g, eave(g, i), mul(g, r, 0.34)))
        gab = store(g, gab, "w_w", mn(g, 0.7, mul(g, i["Width"], 0.14)))
        gab = store(g, gab, "w_h", mn(g, 0.85, mul(g, r, 0.32)))
        gab = store(g, gab, "w_kind", 1, "INT")
    with g.frame("All windows get a random number; the door point"):
        allw = join(g, win, gab)
        allw = store(g, allw, "w_rand", rand(g, 0.0, 1.0, i["Seed"], 11))
        door = keep(g, fac, both(g, is_side(g, 0), cmp(g, storey(g), 0.0, "EQUAL")))
    g.output("Windows", "GEOMETRY", allw, desc="Window points with the facade frame and w_*")
    g.output("Door", "GEOMETRY", door, desc="The front ground-floor facade point (door at f_du, f_dw x f_dh)")
    return g.finish()


# ---- Parametric House Walls ------------------------------------------------------------------------------------------
@once
def walls(mats):
    g = Graph("Parametric House Walls", description="Plaster storey blocks (each upper storey jettied forward) and "
                                                    "the two gables, with window and door reveals cut by a Manifold "
                                                    "boolean; a stone plinth around the ground floor (open at the "
                                                    "door); a bressummer beam and braced corbels under each jetty")
    fac = g.input("Facades", "GEOMETRY", desc="Facade points (Parametric House Facades)")
    win = g.input("Windows", "GEOMETRY", desc="Window points (Parametric House Openings)")
    door = g.input("Door", "GEOMETRY", desc="Door point (Parametric House Openings)")
    i = inputs(g, "Width", "Depth", "Storeys", "Ground Floor Height", "Floor Height", "Jetty", "Roof Pitch",
               "Reveal", "Plinth Height")
    plaster_c = g.input("Plaster Color", "COLOR", lin("#E4C9A0"), desc="Wall colour")
    timber_c = g.input("Timber Color", "COLOR", lin("#5A3A24"), desc="Beam colour")
    stone_c = g.input("Stone Color", "COLOR", lin("#9A8C7A"), desc="Plinth colour")
    W, D, J = i["Width"], i["Depth"], i["Jetty"]
    with g.frame("Storey blocks: x across, y from the back to k x Jetty, a 4 mm gap between storeys"):
        fronts = keep(g, fac, is_side(g, 0))
        k = storey(g)
        front = mul(g, k, J)
        zlo = switch(g, "FLOAT", cmp(g, k, 0.5), -0.3, add(g, attr(g, "f_zb"), 0.002))
        zhi = sub(g, attr(g, "f_z1"), 0.002)
        centre = g.combine(0.0, half(g, sub(g, front, D)), half(g, add(g, zlo, zhi)))
        blocks = g.node("GeometryNodeSetPosition", Geometry=fronts, Position=centre)["Geometry"]
        blocks = g.group(chamfer_boxes(), Points=blocks, Size=g.combine(W, add(g, D, front), sub(g, zhi, zlo)),
                         Chamfer=0.02)["Mesh"]
    with g.frame("Gables: a prism over the top storey, apex rise = Width/2 x tan(pitch)"):
        r = rise(g, i)
        top_front = mul(g, sub(g, i["Storeys"], 1.0), J)
        cube = g.node("GeometryNodeMeshCube", Size=g.combine(W, add(g, D, top_front), r))["Mesh"]
        p = g.separate(g.node("GeometryNodeInputPosition")["Position"])
        ridge = g.node("GeometryNodeSetPosition", Geometry=cube, Selection=cmp(g, p["Z"], 0.0),
                       Position=g.combine(0.0, p["Y"], p["Z"]))["Geometry"]
        prism = g.node("GeometryNodeMergeByDistance", Geometry=ridge, Distance=0.001)["Geometry"]
        prism = g.node("GeometryNodeTransform", Geometry=prism, Translation=g.combine(
            0.0, half(g, sub(g, top_front, D)), add(g, add(g, eave(g, i), half(g, r)), 0.002)))["Geometry"]
    with g.frame("Cutters: a box Reveal deep behind every window and the door"):
        reveal2 = mul(g, i["Reveal"], 2.0)
        wcut = boxes(g, win, attr(g, "w_u"), 0.0, attr(g, "w_z"),
                     g.combine(attr(g, "w_w"), reveal2, attr(g, "w_h")), mats["plaster"], plaster_c, chamfer=0.0)
        dh = attr(g, "f_dh")
        dcut = boxes(g, door, attr(g, "f_du"), 0.0, half(g, dh),
                     g.combine(attr(g, "f_dw"), reveal2, dh), mats["plaster"], plaster_c, chamfer=0.0)
    with g.frame("Walls minus openings (Manifold boolean), then plaster in the house colour"):
        cut = g.node("GeometryNodeMeshBoolean", props={"operation": "DIFFERENCE", "solver": "MANIFOLD"},
                     **{"Mesh 1": join(g, blocks, prism), "Mesh 2": join(g, wcut, dcut)})["Mesh"]
        cut = store(g, cut, "nk_color", plaster_c, "FLOAT_COLOR")
        cut = g.node("GeometryNodeSetShadeSmooth", props={"domain": "FACE"}, Geometry=cut,
                     **{"Shade Smooth": False})["Geometry"]
        cut = g.node("GeometryNodeSetMaterial", Geometry=cut, Material=mats["plaster"])["Geometry"]
    with g.frame("Plinth: a stone band round the ground floor, in two pieces either side of the door"):
        ground = keep(g, fac, cmp(g, storey(g), 0.0, "EQUAL"))
        is_front = is_side(g, 0)
        pl, q = dup(g, ground, switch(g, "INT", is_front, 1, 2))
        half_l = add(g, half(g, attr(g, "f_len")), 0.09)
        door_l = sub(g, attr(g, "f_du"), add(g, half(g, attr(g, "f_dw")), 0.14))
        door_r = add(g, attr(g, "f_du"), add(g, half(g, attr(g, "f_dw")), 0.14))
        a = switch(g, "FLOAT", both(g, is_front, cmp(g, q, 0.5)), mul(g, half_l, -1.0), door_r)
        b = switch(g, "FLOAT", both(g, is_front, cmp(g, q, 0.5, "LESS_THAN")), half_l, door_l)
        ph = add(g, i["Plinth Height"], 0.3)
        plinth = boxes(g, pl, half(g, add(g, a, b)), 0.03, sub(g, half(g, ph), 0.3),
                       g.combine(sub(g, b, a), 0.12, ph), mats["stone"], stone_c,
                       sel=cmp(g, i["Plinth Height"], 0.01), chamfer=0.02)
    with g.frame("Jetties: a bressummer along each overhanging front, braced corbels under it at the slots"):
        upper = keep(g, fac, both(g, both(g, is_side(g, 0), cmp(g, storey(g), 0.5)), cmp(g, J, 0.05)))
        bress = boxes(g, upper, 0.0, 0.0, add(g, attr(g, "f_zb"), 0.1),
                      g.combine(add(g, attr(g, "f_len"), 0.12), 0.22, 0.24), mats["timber"], timber_c,
                      chamfer=0.02)
        cb, j = dup(g, upper, add(g, attr(g, "f_n", "INT"), 1.0))
        hl = sub(g, half(g, attr(g, "f_len")), BEAM / 2)
        cu = mn(g, mx(g, sub(g, mul(g, j, attr(g, "f_slot")), half(g, attr(g, "f_len"))), mul(g, hl, -1.0)), hl)
        zb = attr(g, "f_zb")
        # each corbel climbs from the wall below (v = -Jetty, 0.6 m down) to the underside of the jetty (v = 0)
        ang = g.math("ARCTAN2", 0.6, J)
        length = g.vmath("LENGTH", g.combine(J, 0.6, 0.0))["Value"]
        corbels = boxes(g, cb, cu, mul(g, J, -0.5), sub(g, zb, 0.3),
                        g.combine(BEAM, length, BEAM * 0.9), mats["timber"], timber_c,
                        local_rot=euler(g, ang, 0.0, 0.0), chamfer=0.015)
    g.output("Geometry", "GEOMETRY", join(g, cut, plinth, bress, corbels), desc="Walls, plinth and jetty timbers")
    return g.finish()


# ---- Parametric House Timber ------------------------------------------------------------------------------------------
@once
def timber(mats):
    g = Graph("Parametric House Timber", description="Half-timbering on the upper storeys of every facade: sole "
                                                     "and top plates, sill and head rails, posts at the slot "
                                                     "edges, St Andrew's crosses under the windows, and a collar "
                                                     "truss in each gable. Timber Amount adds pieces in a fixed "
                                                     "random order (each compares its own random number)")
    fac = g.input("Facades", "GEOMETRY", desc="Facade points (Parametric House Facades)")
    i = inputs(g, "Width", "Storeys", "Ground Floor Height", "Floor Height", "Roof Pitch", "Timber Amount", "Seed")
    tc = g.input("Timber Color", "COLOR", lin("#5A3A24"), desc="Beam colour")
    amt = i["Timber Amount"]
    with g.frame("Upper storeys only (the ground floor stays plaster and stone)"):
        upper = keep(g, fac, cmp(g, storey(g), 0.5))
        zb, z1 = attr(g, "f_zb"), attr(g, "f_z1")
        sill = sub(g, sub(g, attr(g, "f_wz"), half(g, attr(g, "f_wh"))), 0.1)
        head = add(g, add(g, attr(g, "f_wz"), half(g, attr(g, "f_wh"))), BEAM / 2)
    with g.frame("Rails: sole plate, sill rail, head rail, top plate (rails need Timber Amount > 0, 0.1, 0.5, 0)"):
        rl, q = dup(g, upper, 4)
        z = pick(g, q, [add(g, zb, BEAM / 2), sub(g, sill, BEAM / 2), head, sub(g, z1, BEAM / 2)])
        need = pick(g, q, [0.0, 0.1, 0.5, 0.0])
        rails = boxes(g, rl, 0.0, TIMBER_V, z, g.combine(add(g, attr(g, "f_len"), 0.1), BEAM_D, BEAM * 0.9),
                      mats["timber"], tc, sel=cmp(g, amt, need), seed=i["Seed"])
    with g.frame("Posts at the slot edges: corners always, the rest by chance"):
        ps, j = dup(g, upper, add(g, attr(g, "f_n", "INT"), 1.0))
        hl = sub(g, half(g, attr(g, "f_len")), BEAM / 2)
        u = mn(g, mx(g, sub(g, mul(g, j, attr(g, "f_slot")), half(g, attr(g, "f_len"))), mul(g, hl, -1.0)), hl)
        corner = both(g, cmp(g, j, 0.5, "LESS_THAN"), cmp(g, j, sub(g, attr(g, "f_n", "INT"), 0.5)), "OR")
        chance = cmp(g, mul(g, amt, 1.6), rand(g, 0.0, 1.0, i["Seed"], 21))
        posts = boxes(g, ps, u, TIMBER_V, half(g, add(g, zb, z1)), g.combine(BEAM, BEAM_D, sub(g, z1, zb)),
                      mats["timber"], tc, sel=both(g, cmp(g, amt, 0.0), both(g, corner, chance, "OR")),
                      seed=i["Seed"])
    with g.frame("Crosses under the windows: two St Andrew's crosses per slot, sole plate to sill rail"):
        cr, q = dup(g, upper, mul(g, attr(g, "f_n", "INT"), 4.0))
        jj = g.math("FLOOR", div(g, q, 4.0))                        # slot
        hs = g.math("FLOORED_MODULO", g.math("FLOOR", div(g, q, 2.0)), 2.0)   # left or right half of the slot
        flip = sub(g, 1.0, mul(g, g.math("FLOORED_MODULO", q, 2.0), 2.0))   # / or \
        slot = attr(g, "f_slot")
        uc = sub(g, mul(g, add(g, jj, mul(g, add(g, hs, 0.5), 0.5)), slot), half(g, attr(g, "f_len")))
        hw = mul(g, sub(g, mul(g, slot, 0.25), BEAM * 0.55), flip)
        cu, cz, cl, crot = strut(g, sub(g, uc, hw), add(g, zb, BEAM), add(g, uc, hw), sub(g, sill, BEAM))
        ident = add(g, mul(g, add(g, mul(g, storey(g), 4.0), side(g)), 64.0), jj)
        crosses = boxes(g, cr, cu, TIMBER_V - 0.005, cz, g.combine(cl, BEAM_D * 0.9, BEAM * 0.75), mats["timber"],
                        tc, local_rot=crot, seed=i["Seed"],
                        sel=cmp(g, amt, add(g, 0.2, rand(g, 0.0, 0.8, i["Seed"], 31, ident))))
    with g.frame("Gable truss (front and back): collar beam, king post and two raking struts"):
        top = cmp(g, storey(g), sub(g, i["Storeys"], 1.0), "EQUAL")
        gab = keep(g, fac, both(g, top, both(g, is_side(g, 0), is_side(g, 2), "OR")))
        r = rise(g, i)
        ez = eave(g, i)
        cz_ = add(g, ez, mul(g, r, 0.68))
        chw = sub(g, mul(g, half(g, i["Width"]), 0.32), 0.12)
        tr, q = dup(g, gab, 4)
        su, sz, sl, srot = strut(g, mul(g, i["Width"], -0.3), add(g, ez, BEAM), -0.45, sub(g, cz_, BEAM / 2))
        ku = pick(g, q, [0.0, 0.0, su, mul(g, su, -1.0)])
        kz = pick(g, q, [cz_, half(g, add(g, cz_, add(g, ez, mul(g, r, 0.93)))), sz, sz])
        size = pick(g, q, [g.combine(mul(g, chw, 2.0), BEAM_D, BEAM),
                           g.combine(BEAM, BEAM_D, mul(g, r, 0.25)),
                           g.combine(sl, BEAM_D, BEAM * 0.85), g.combine(sl, BEAM_D, BEAM * 0.85)], "VECTOR")
        level = euler(g)
        rot = pick(g, q, [level, level, srot,
                          g.node("FunctionNodeInvertRotation", Rotation=srot)["Rotation"]], "ROTATION")
        truss = boxes(g, tr, ku, TIMBER_V, kz, size, mats["timber"], tc, local_rot=rot, seed=i["Seed"],
                      sel=cmp(g, amt, 0.15))
    g.output("Geometry", "GEOMETRY", join(g, rails, posts, crosses, truss), desc="Timber frame pieces")
    return g.finish()


# ---- Parametric House Windows -----------------------------------------------------------------------------------------
@once
def windows(mats):
    fm = foliage_mound()
    g = Graph("Parametric House Windows", description="For every window point: glass set back in the reveal "
                                                      "(lit by chance), a painted frame with a cross bar, a sill "
                                                      "board, louvred shutters (by chance), and a window box "
                                                      "planted with NK Foliage Mound blossoms (by chance)")
    win = g.input("Windows", "GEOMETRY", desc="Window points (Parametric House Openings)")
    i = inputs(g, "Reveal", "Window Width", "Shutter Chance", "Window Box Chance", "Lit Windows", "Glow", "Seed")
    frame_c = g.input("Frame Color", "COLOR", lin("#EFE6D2"), desc="Window frame paint")
    paint_c = g.input("Paint Color", "COLOR", lin("#3F6E5A"), desc="Shutter paint")
    tc = g.input("Timber Color", "COLOR", lin("#5A3A24"), desc="Sill timber")
    flower_c = g.input("Flower Color", "COLOR", lin("#D8323A"), desc="Window-box blossom colour")
    rv = i["Reveal"]
    u, z, ww, wh = attr(g, "w_u"), attr(g, "w_z"), attr(g, "w_w"), attr(g, "w_h")
    wall = cmp(g, attr(g, "w_kind", "INT"), 0.5, "LESS_THAN")
    with g.frame("Glass deep in the reveal; hp_glow = Glow on lit windows"):
        lit = cmp(g, i["Lit Windows"], attr(g, "w_rand"))
        gpts = store(g, win, "hp_glow", mul(g, lit, i["Glow"]))
        glass = boxes(g, gpts, u, add(g, mul(g, rv, -1.0), 0.03), z, g.combine(ww, 0.02, wh), mats["glass"],
                      (1.0, 1.0, 1.0, 1.0), chamfer=0.0)
    with g.frame("Frame: four bars in the reveal, a mullion and a transom"):
        fr, q = dup(g, win, 6)
        ft = 0.06
        hw, hh = half(g, ww), half(g, wh)
        fu = pick(g, q, [sub(g, add(g, u, ft / 2), hw), add(g, sub(g, u, ft / 2), hw), u, u, u, u])
        fz = pick(g, q, [z, z, sub(g, add(g, z, hh), ft / 2), add(g, sub(g, z, hh), ft / 2), z,
                         add(g, z, mul(g, wh, 0.12))])
        fs = pick(g, q, [g.combine(ft, 0.07, wh), g.combine(ft, 0.07, wh), g.combine(ww, 0.07, ft),
                         g.combine(ww, 0.07, ft), g.combine(0.045, 0.05, wh), g.combine(ww, 0.05, 0.045)], "VECTOR")
        frames = boxes(g, fr, fu, add(g, mul(g, rv, -1.0), 0.07), fz, fs, mats["paint"], frame_c, chamfer=0.008)
    with g.frame("Sill board under each window"):
        sills = boxes(g, win, u, 0.04, sub(g, sub(g, z, hh), 0.03), g.combine(add(g, ww, 0.2), 0.16, 0.06),
                      mats["timber"], tc, chamfer=0.01)
    with g.frame("Shutters: two leaves folded back beside the window, three battens each"):
        has = both(g, wall, cmp(g, i["Shutter Chance"], rand(g, 0.0, 1.0, i["Seed"], 41)))
        sh_pts = keep(g, win, has)
        sp, q = dup(g, sh_pts, 8)
        leaf = cmp(g, q, 1.5, "LESS_THAN")                      # q 0, 1 leaves; 2..7 battens
        sgn = sub(g, mul(g, g.math("FLOORED_MODULO", q, 2.0), 2.0), 1.0)
        lw = add(g, half(g, ww), 0.03)
        su = add(g, u, mul(g, sgn, add(g, add(g, hw, half(g, lw)), 0.03)))
        bz = add(g, z, mul(g, mul(g, sub(g, g.math("FLOOR", div(g, sub(g, q, 2.0), 2.0)), 1.0), wh), 0.34))
        sz_ = switch(g, "FLOAT", leaf, bz, z)
        size = switch(g, "VECTOR", leaf, g.combine(sub(g, lw, 0.05), 0.025, 0.05),
                      g.combine(lw, 0.04, add(g, wh, 0.04)))
        sv = switch(g, "FLOAT", leaf, 0.115, 0.09)
        col = switch(g, "RGBA", leaf, scale_color(g, paint_c, 0.75), paint_c)
        shutters = boxes(g, sp, su, sv, sz_, size, mats["paint"], col, chamfer=0.008)
    with g.frame("Window boxes: a planter under the sill, by chance"):
        wb = keep(g, win, both(g, wall, cmp(g, i["Window Box Chance"], rand(g, 0.0, 1.0, i["Seed"], 51))))
        bz0 = sub(g, sub(g, z, hh), 0.2)
        planters = boxes(g, wb, u, 0.17, bz0, g.combine(add(g, ww, 0.12), 0.22, 0.2), mats["tile"],
                         lin("#B36A45"), chamfer=0.02)
    with g.frame("Planting: one NK Foliage Mound with blossoms, stretched to each window box"):
        ref_w = add(g, i["Window Width"], 0.1)
        mound = g.node("GeometryNodeMeshIcoSphere", Radius=0.5, Subdivisions=3)["Mesh"]
        mound = g.node("GeometryNodeTransform", Geometry=mound,
                       Scale=g.combine(ref_w, 0.26, 0.34))["Geometry"]
        plants = g.group(fm, Mound=mound, Seed=i["Seed"],
                         **{"Leaf Density": 650.0, "Leaf Size": 0.09, "Leaf Color": lin("#3F6A24"),
                            "Leaf Material": mats["plant"], "Blossom Density": 160.0, "Blossom Size": 0.065,
                            "Blossom Color A": flower_c, "Blossom Color B": lin("#F2EEE8"), "Color B Share": 0.25,
                            "Blossom Material": mats["plant"], "Underside": -0.2})["Geometry"]
        at = on_facade(g, wb, u, 0.17, add(g, bz0, 0.1))
        inst = g.node("GeometryNodeInstanceOnPoints", Points=at, Instance=plants,
                      Rotation=attr(g, "f_rot", "QUATERNION"),
                      Scale=g.combine(div(g, add(g, ww, 0.1), ref_w), 1.0, 1.0))["Instances"]
        inst = g.node("GeometryNodeRealizeInstances", Geometry=inst)["Geometry"]
    g.output("Geometry", "GEOMETRY", join(g, glass, frames, sills, shutters, planters, inst), desc="Window parts")
    return g.finish()


# ---- Parametric House Door ---------------------------------------------------------------------------------------------
@once
def door(mats):
    g = Graph("Parametric House Door", description="The front door: four painted planks set back in the reveal, "
                                                   "two iron strap hinges, a timber frame and lintel, a stone step, "
                                                   "and an optional lantern beside it")
    dp = g.input("Door", "GEOMETRY", desc="Door point (Parametric House Openings)")
    i = inputs(g, "Reveal", "Lantern", "Lit Windows", "Glow", "Seed")
    paint_c = g.input("Paint Color", "COLOR", lin("#3F6E5A"), desc="Door paint")
    tc = g.input("Timber Color", "COLOR", lin("#5A3A24"), desc="Frame timber")
    stone_c = g.input("Stone Color", "COLOR", lin("#9A8C7A"), desc="Step stone")
    u, w, h = attr(g, "f_du"), attr(g, "f_dw"), attr(g, "f_dh")
    rv = i["Reveal"]
    with g.frame("Planks, with a dark strap hinge across them at a quarter and three quarters of the height"):
        pk, q = dup(g, dp, 6)
        plank = cmp(g, q, 3.5, "LESS_THAN")
        pu = add(g, sub(g, u, half(g, w)), mul(g, add(g, q, 0.5), div(g, w, 4.0)))
        pz = switch(g, "FLOAT", plank, mul(g, h, add(g, 0.25, mul(g, sub(g, q, 4.0), 0.5))), half(g, h))
        size = switch(g, "VECTOR", plank, g.combine(sub(g, w, 0.08), 0.02, 0.06),
                      g.combine(sub(g, div(g, w, 4.0), 0.012), 0.05, sub(g, h, 0.01)))
        col = switch(g, "RGBA", plank, (0.02, 0.02, 0.02, 1.0), paint_c)
        planks = boxes(g, pk, switch(g, "FLOAT", plank, u, pu), add(g, mul(g, rv, -1.0),
                                                                      switch(g, "FLOAT", plank, 0.07, 0.04)),
                       pz, size, mats["paint"], col, chamfer=0.006)
    with g.frame("Frame: two posts and a lintel on the wall face"):
        fr, q = dup(g, dp, 3)
        fu = pick(g, q, [sub(g, u, add(g, half(g, w), 0.07)), add(g, u, add(g, half(g, w), 0.07)), u])
        fz = pick(g, q, [half(g, h), half(g, h), add(g, h, 0.08)])
        fs = pick(g, q, [g.combine(0.14, 0.1, h), g.combine(0.14, 0.1, h), g.combine(add(g, w, 0.4), 0.12, 0.18)],
                  "VECTOR")
        frame_ = boxes(g, fr, fu, 0.04, fz, fs, mats["timber"], tc, chamfer=0.015)
    with g.frame("Stone step in front"):
        step = boxes(g, dp, u, 0.28, 0.02, g.combine(add(g, w, 0.5), 0.5, 0.18), mats["stone"], stone_c,
                     chamfer=0.03)
    with g.frame("Lantern: glass box with a cap on an iron bracket, right of the door"):
        lp, q = dup(g, dp, 3)
        lu = add(g, u, add(g, half(g, w), 0.45))
        lz = h
        lglow = mul(g, cmp(g, i["Lit Windows"], 0.0), i["Glow"])
        lpts = store(g, lp, "hp_glow", mul(g, lglow, 1.6))
        lv = pick(g, q, [0.2, 0.2, 0.1])
        lzz = pick(g, q, [lz, add(g, lz, 0.15), add(g, lz, 0.2)])
        ls = pick(g, q, [g.combine(0.15, 0.15, 0.22), g.combine(0.21, 0.21, 0.06), g.combine(0.03, 0.2, 0.03)],
                  "VECTOR")
        is_glass = cmp(g, q, 0.5, "LESS_THAN")
        glass = boxes(g, lpts, lu, lv, lzz, ls, mats["glass"], (1.0, 1.0, 1.0, 1.0),
                      sel=both(g, i["Lantern"], is_glass), chamfer=0.01)
        iron = boxes(g, lpts, lu, lv, lzz, ls, mats["paint"], (0.03, 0.03, 0.03, 1.0),
                     sel=both(g, i["Lantern"], g.node("FunctionNodeBooleanMath", props={"operation": "NOT"},
                                                      Boolean=is_glass)["Boolean"]), chamfer=0.008)
    g.output("Geometry", "GEOMETRY", join(g, planks, frame_, step, glass, iron), desc="Door parts")
    return g.finish()


# ---- Parametric House Roof -------------------------------------------------------------------------------------------
@once
def roof(mats):
    pot = profile_revolve()
    g = Graph("Parametric House Roof", description="A pitched roof over the top storey, ridge front to back: two "
                                                   "slabs on the wall tops, clay tiles laid course by course "
                                                   "(staggered, each tilted and tinted a little), a ridge, barge "
                                                   "boards on the gables, and a stone chimney with a clay pot")
    i = inputs(g, "Width", "Depth", "Storeys", "Ground Floor Height", "Floor Height", "Jetty", "Roof Pitch",
               "Overhang", "Tile Size", "Chimney", "Seed")
    roof_c = g.input("Roof Color", "COLOR", lin("#B0603C"), desc="Clay tile colour")
    tc = g.input("Timber Color", "COLOR", lin("#5A3A24"), desc="Barge board colour")
    stone_c = g.input("Stone Color", "COLOR", lin("#9A8C7A"), desc="Chimney stone")
    W, O, phi = i["Width"], i["Overhang"], i["Roof Pitch"]
    T = 0.16                                                  # slab thickness
    with g.frame("Roof geometry: eave line, slope length, extent along y"):
        ez = eave(g, i)
        cphi, sphi = g.math("COSINE", phi), g.math("SINE", phi)
        tphi = g.math("TANGENT", phi)
        xe = add(g, half(g, W), O)                            # eave edge, |x|
        ls = div(g, xe, cphi)                                  # slope length eave edge to ridge
        z0 = add(g, sub(g, ez, mul(g, O, tphi)), div(g, T, cphi))   # top of slab at the eave edge
        top_front = mul(g, sub(g, i["Storeys"], 1.0), i["Jetty"])
        y0 = sub(g, mul(g, i["Depth"], -1.0), O)
        ly = add(g, add(g, i["Depth"], top_front), mul(g, O, 2.0))
        yc = add(g, y0, half(g, ly))
    with g.frame("Two slabs: index 0 the +x slope, 1 the -x slope (sigma = +1, -1)"):
        sl = g.node("GeometryNodePoints", Count=2)["Points"]
        sig = sub(g, 1.0, mul(g, g.node("GeometryNodeInputIndex")["Index"], 2.0))
        sl = store(g, sl, "r_sig", sig)
        sig = attr(g, "r_sig")
        # roof frame per side: local X up the slope, Y along the ridge, Z the roof normal
        beta = switch(g, "FLOAT", cmp(g, sig, 0.0), mul(g, phi, -1.0), add(g, phi, math.pi))
        sl = store(g, sl, "r_rot", euler(g, 0.0, beta, 0.0), "QUATERNION")

        def on_roof(pts, a, y, lift):
            """Point a metres up the slope from the eave edge, at y, lifted along the roof normal."""
            x = mul(g, sig, sub(g, xe, mul(g, a, cphi)))
            zz = add(g, z0, mul(g, a, sphi))
            nrm = g.combine(mul(g, sig, mul(g, sphi, lift)), 0.0, mul(g, cphi, lift))
            return g.node("GeometryNodeSetPosition", Geometry=pts,
                          Position=g.vmath("ADD", g.combine(x, y, zz), nrm))["Geometry"]

        slab_pts = on_roof(sl, half(g, ls), yc, -T / 2)
        slabs = g.group(chamfer_boxes(), Points=slab_pts, Size=g.combine(ls, ly, T),
                        Rotation=attr(g, "r_rot", "QUATERNION"), Chamfer=0.02)["Mesh"]
        slabs = store(g, slabs, "nk_color", scale_color(g, roof_c, 0.6), "FLOAT_COLOR")
        slabs = g.node("GeometryNodeSetMaterial", Geometry=slabs, Material=mats["tile"])["Geometry"]
    with g.frame("Tiles: courses up the slope (0.8 x Tile Size apart), tiles along y, odd courses staggered"):
        tw = i["Tile Size"]
        expo = mul(g, tw, 0.8)
        nc = g.math("CEIL", div(g, ls, expo))
        nt = g.math("CEIL", div(g, ly, tw))
        per = mul(g, nc, nt)
        tl, q = dup(g, sl, per)
        c = g.math("FLOOR", div(g, q, nt))
        t = g.math("FLOORED_MODULO", q, nt)
        a = mn(g, mul(g, add(g, c, 0.5), expo), sub(g, ls, mul(g, expo, 0.55)))
        stagger = mul(g, g.math("FLOORED_MODULO", c, 2.0), 0.5)
        y = mn(g, add(g, y0, mul(g, add(g, add(g, t, 0.5), stagger), tw)), sub(g, add(g, y0, ly), half(g, tw)))
        tl = on_roof(tl, a, y, 0.03)
        # each tile tips its lower edge out (less steep than the roof) and twists a little at random
        tip = euler(g, rand(g, -0.02, 0.02, i["Seed"], 61), add(g, -0.1, rand(g, -0.02, 0.02, i["Seed"], 62)),
                    rand(g, -0.025, 0.025, i["Seed"], 63))
        trot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"},
                      Rotation=attr(g, "r_rot", "QUATERNION"), **{"Rotate By": tip})["Rotation"]
        tl = store(g, tl, "nk_color", roof_c, "FLOAT_COLOR")
        tl = store(g, tl, "nk_rand", rand(g, 0.0, 1.0, i["Seed"], 64))
        tiles = g.group(chamfer_boxes(), Points=tl, Size=g.combine(mul(g, expo, 1.45), mul(g, tw, 0.96), 0.035),
                        Rotation=trot, Chamfer=0.008)["Mesh"]
        tiles = g.node("GeometryNodeSetMaterial", Geometry=tiles, Material=mats["tile"])["Geometry"]
    with g.frame("Ridge: a square bar turned 45 degrees along the top"):
        rz = add(g, add(g, ez, mul(g, half(g, W), tphi)), div(g, T, cphi))
        rp = g.node("GeometryNodePoints", Count=1, Position=g.combine(0.0, yc, add(g, rz, 0.02)))["Points"]
        rp = store(g, rp, "nk_color", scale_color(g, roof_c, 0.8), "FLOAT_COLOR")
        ridge = g.group(chamfer_boxes(), Points=rp, Size=g.combine(0.24, add(g, ly, 0.06), 0.24),
                        Rotation=euler(g, 0.0, math.pi / 4, 0.0), Chamfer=0.015)["Mesh"]
        ridge = g.node("GeometryNodeSetMaterial", Geometry=ridge, Material=mats["tile"])["Geometry"]
    with g.frame("Barge boards: under the tile edge at both gables, both slopes"):
        bb, q = dup(g, sl, 2)
        by = switch(g, "FLOAT", cmp(g, q, 0.5), add(g, y0, 0.03), sub(g, add(g, y0, ly), 0.03))
        bb = on_roof(bb, half(g, ls), by, -0.1)
        bb = store(g, bb, "nk_color", tc, "FLOAT_COLOR")
        barge = g.group(chamfer_boxes(), Points=bb, Size=g.combine(ls, 0.06, 0.26),
                        Rotation=attr(g, "r_rot", "QUATERNION"), Chamfer=0.01)["Mesh"]
        barge = g.node("GeometryNodeSetMaterial", Geometry=barge, Material=mats["timber"])["Geometry"]
    with g.frame("Chimney: a stone stack through the +x slope, a cap and a clay pot (NK Profile Revolve)"):
        side_k = switch(g, "FLOAT", cmp(g, rand(g, 0.0, 1.0, i["Seed"], 71, ident=0), 0.5), -1.0, 1.0)
        cx = mul(g, side_k, mul(g, W, 0.24))
        cy = sub(g, yc, mul(g, ly, 0.2))
        ctop = add(g, rz, 0.55)
        cbot = sub(g, ez, 0.5)
        cp, q = dup(g, g.node("GeometryNodePoints", Count=1)["Points"], 2)
        cz = switch(g, "FLOAT", cmp(g, q, 0.5), half(g, add(g, ctop, cbot)), add(g, ctop, 0.06))
        cp = g.node("GeometryNodeSetPosition", Geometry=cp, Position=g.combine(cx, cy, cz))["Geometry"]
        cp = store(g, cp, "nk_color", stone_c, "FLOAT_COLOR")
        stack = g.group(chamfer_boxes(), Points=cp, Rotation=euler(g),
                        Size=switch(g, "VECTOR", cmp(g, q, 0.5), g.combine(0.62, 0.62, sub(g, ctop, cbot)),
                                    g.combine(0.78, 0.78, 0.12)), Chamfer=0.03)["Mesh"]
        stack = g.node("GeometryNodeSetMaterial", Geometry=stack, Material=mats["stone"])["Geometry"]
        clay = g.group(pot, Height=0.38, Segments=16, **{"Radius Bottom": 0.14, "Radius Lower": 0.12,
                                                        "Radius Middle": 0.1, "Radius Upper": 0.1,
                                                        "Radius Top": 0.12, "Wall Thickness": 0.025})["Mesh"]
        clay = g.node("GeometryNodeTransform", Geometry=clay,
                      Translation=g.combine(cx, cy, add(g, ctop, 0.12)))["Geometry"]
        clay = store(g, clay, "nk_color", roof_c, "FLOAT_COLOR")
        clay = g.node("GeometryNodeSetMaterial", Geometry=clay, Material=mats["tile"])["Geometry"]
        chimney = switch(g, "GEOMETRY", i["Chimney"], None, join(g, stack, clay))
    g.output("Geometry", "GEOMETRY", join(g, slabs, tiles, ridge, barge, chimney), desc="Roof parts")
    return g.finish()


# ---- Parametric House (the modifier) ------------------------------------------------------------------------------
PALETTE = {  # name: (default sRGB hex, description)
    "Plaster A": ("#EAD7B4", "Cream plaster"), "Plaster B": ("#E3B98A", "Peach plaster"),
    "Plaster C": ("#D9A766", "Ochre plaster"), "Plaster D": ("#B9C2A6", "Sage plaster"),
    "Paint A": ("#3F6E5A", "Green shutters and door"), "Paint B": ("#2F5E7A", "Blue shutters and door"),
    "Paint C": ("#8C3B2E", "Oxblood shutters and door"),
    "Frame Color": ("#F0E8D8", "Window frames"), "Timber Color": ("#4E3220", "Oak timbers"),
    "Roof Color": ("#B3603A", "Clay tiles"), "Stone Color": ("#A39686", "Plinth, step and chimney"),
    "Flower Color": ("#D8323A", "Window-box geraniums"),
}


@once
def house():
    mats = materials()
    parts = {"facades": facades(), "openings": openings(), "walls": walls(mats), "timber": timber(mats),
             "windows": windows(mats), "door": door(mats), "roof": roof(mats)}
    g = Graph(NAME, modifier=True,
              description="A half-timbered storybook house from a footprint (Width x Depth) and Storeys: jettied "
                          "upper floors, timber frame, windows with reveals, shutters and window boxes, a door, a "
                          "tiled roof with a chimney. Origin at the middle of the ground-floor front, front +Y")
    prim = inputs(g, "Width", "Depth", "Storeys", "Timber Amount", "Roof Pitch", "Seed", panel="Primary")
    panels = [("Body", ["Ground Floor Height", "Floor Height", "Jetty", "Plinth Height"]),
              ("Windows", ["Window Width", "Window Height", "Window Spacing", "Reveal", "Gable Window",
                           "Shutter Chance", "Window Box Chance", "Lit Windows", "Glow"]),
              ("Door", ["Door Width", "Door Height", "Lantern"]),
              ("Roof", ["Overhang", "Tile Size", "Chimney"])]
    ui = dict(prim)
    for panel, names in panels:
        ui.update(inputs(g, *names, panel=panel))
    for name, (hx, desc) in PALETTE.items():
        ui[name] = g.input(name, "COLOR", lin(hx), panel="Palette", desc=desc)
    for p in ("Body", "Windows", "Door", "Roof", "Palette"):
        g._panels[p].default_closed = True

    def wire(tree, label, **fixed):
        n = g.group(tree, label=label)
        for s in n.b.inputs:
            if s.enabled and s.name in fixed:
                g.connect(fixed[s.name], s)
            elif s.enabled and s.name in ui:
                g.connect(ui[s.name], s)
        return n

    with g.frame("This house's colours: one plaster and one paint from the palette, by Seed"):
        seed = ui["Seed"]
        plaster = pick(g, rand(g, 0, 3, seed, 1, ident=0, dtype="INT"),
                       [ui[f"Plaster {c}"] for c in "ABCD"], "RGBA")
        plaster = scale_color(g, plaster, rand(g, 0.92, 1.05, seed, 2, ident=0))
        paint = pick(g, rand(g, 0, 2, seed, 3, ident=0, dtype="INT"), [ui[f"Paint {c}"] for c in "ABC"], "RGBA")
    colours = {"Plaster Color": plaster, "Paint Color": paint}
    with g.frame("Facades and openings: the frame every part is modelled in"):
        fac = wire(parts["facades"], "Facades")["Facades"]
        op = wire(parts["openings"], "Openings", Facades=fac)
    with g.frame("The parts"):
        geos = [wire(parts["walls"], "Walls", Facades=fac, Windows=op["Windows"], Door=op["Door"], **colours),
                wire(parts["timber"], "Timber", Facades=fac, **colours),
                wire(parts["windows"], "Windows", Windows=op["Windows"], **colours),
                wire(parts["door"], "Door", Door=op["Door"], **colours),
                wire(parts["roof"], "Roof", **colours)]
    with g.frame("Join and realize (materials read nk_color, nk_rand, nk_part, hp_glow)"):
        geo = g.node("GeometryNodeRealizeInstances", Geometry=join(g, *[n["Geometry"] for n in geos]))["Geometry"]
    g.output("Geometry", "GEOMETRY", geo, desc="The house")
    return g.finish()


# ---- Parametric House Row ---------------------------------------------------------------------------------------------
@once
def house_row():
    one, parcels, ribbon = house(), curve_parcels(), curve_ribbon()
    street_mat = make_material("Parametric House Cobbles", stone(),
                               **{"Color": lin("#9C9184"), "Stone Scale": 7.0, "Bump": 0.6})
    g = Graph(f"{NAME} Row", modifier=True,
              description="A street of Parametric Houses along a path curve: NK Curve Parcels splits each side into "
                          "plots; a For Each zone builds one house per plot with its own width (the plot minus a "
                          "gap), storeys, timbering, pitch and seed, and turns it to face the street. A cobbled "
                          "NK Curve Ribbon runs between the rows")
    path = g.input("Path", "OBJECT", desc="Curve object the street follows")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, panel="Primary", desc="Changes every plot and house")
    wmin = g.input("Width Min", "FLOAT", 5.0, min=3.0, max=16.0, subtype="DISTANCE", panel="Primary",
                   desc="Narrowest plot")
    wmax = g.input("Width Max", "FLOAT", 7.5, min=3.0, max=16.0, subtype="DISTANCE", panel="Primary",
                   desc="Widest plot")
    smin = g.input("Storeys Min", "INT", 2, min=1, max=6, panel="Primary", desc="Fewest storeys")
    smax = g.input("Storeys Max", "INT", 3, min=1, max=6, panel="Primary", desc="Most storeys")
    depth = g.input("Depth", "FLOAT", 5.5, min=3.0, max=14.0, subtype="DISTANCE", panel="Street",
                    desc="House depth")
    gap = g.input("Gap", "FLOAT", 0.7, min=0.0, max=5.0, subtype="DISTANCE", panel="Street",
                  desc="Space between neighbouring houses")
    off = g.input("Offset", "FLOAT", 4.5, min=0.0, max=50.0, subtype="DISTANCE", panel="Street",
                  desc="Distance from the curve to the house fronts")
    both_s = g.input("Both Sides", "BOOL", True, panel="Street", desc="Houses on both sides of the street")
    with g.frame("Path curve and plots along it"):
        curve = g.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=path)["Geometry"]
        pc = g.group(parcels, Curve=curve, Seed=seed, Offset=off, Depth=depth,
                     **{"Width Min": wmin, "Width Max": wmax, "Both Sides": both_s})
        plots = pc["Points"]
        r = attr(g, "nk_rand")
    with g.frame("One house per plot (For Each zone): its own numbers from the plot"):
        zin, zout = g.zone("FOREACH")
        for stype, name in (("FLOAT", "Width"), ("INT", "Storeys"), ("FLOAT", "Timber"), ("FLOAT", "Pitch"),
                            ("INT", "House Seed"), ("VECTOR", "Position"), ("ROTATION", "Rotation")):
            zout.b.input_items.new(stype, name)
        g.connect(plots, zin.i("Geometry"))
        idx = g.node("GeometryNodeInputIndex")["Index"]
        g.connect(sub(g, attr(g, "nk_chord"), gap), zin.i("Width"))
        g.connect(g.math("ROUND", rand(g, sub(g, smin, 0.49), add(g, smax, 0.49), seed, 1, idx)), zin.i("Storeys"))
        g.connect(rand(g, 0.0, 1.0, seed, 2, idx), zin.i("Timber"))
        g.connect(rand(g, math.radians(44), math.radians(58), seed, 3, idx), zin.i("Pitch"))
        g.connect(g.math("MULTIPLY_ADD", r, 9973.0, seed), zin.i("House Seed"))
        g.connect(g.node("GeometryNodeInputPosition")["Position"], zin.i("Position"))
        g.connect(pc["Rotation"], zin.i("Rotation"))
        h = g.group(one, Width=zin["Width"], Depth=depth, Storeys=zin["Storeys"], Seed=zin["House Seed"],
                    **{"Timber Amount": zin["Timber"], "Roof Pitch": zin["Pitch"]})
        placed = g.node("GeometryNodeTransform", Geometry=h["Geometry"], Translation=zin["Position"],
                        Rotation=zin["Rotation"])["Geometry"]
        g.connect(placed, zout.i("Geometry"))
        houses = zout["Geometry#1"]
    with g.frame("Cobbled street between the rows"):
        road = g.group(ribbon, Curve=curve, Width=mul(g, off, 2.0), Height=0.0, Material=street_mat,
                       **{"Segments Across": 4})["Mesh"]
    g.output("Geometry", "GEOMETRY", join(g, houses, road), desc="Houses and street")
    return g.finish()


# ---- scene ------------------------------------------------------------------------------------------------------------
def post(sc, haze_color, haze_start, haze_depth, haze_amount, sky_top, sky_horizon, horizon=0.5, top=0.9, glow=0.2):
    """Compositor: distance haze by the Mist pass over a screen-space sky (NK Haze Over Sky), then NK Soft Glow."""
    sc.render.film_transparent = True
    sc.view_layers[0].use_pass_mist = True
    ms = sc.world.mist_settings
    ms.start, ms.depth, ms.falloff = haze_start, haze_depth, "QUADRATIC"
    g = Graph(f"{NAME} Post {sc.name}", kind="COMPOSITOR",
              description="Haze by mist depth over a sky gradient, then a soft glow on lit windows and highlights")
    with g.frame("Render layers, haze over the sky, soft glow"):
        rl = g.node("CompositorNodeRLayers")
        rl.b.scene = sc
        hz = g.group(haze_over_sky(), Image=rl["Image"], Mist=rl["Mist"],
                     **{"Haze Color": lin(haze_color), "Haze Amount": haze_amount, "Sky Top": lin(sky_top),
                        "Sky Horizon": lin(sky_horizon), "Horizon": horizon, "Top": top})
        gl = g.group(soft_glow(), Image=hz["Image"], Threshold=1.2, Strength=glow, Size=0.5)
    g.output("Image", "COLOR", gl["Image"])
    sc.compositing_node_group = g.finish()


def street_path(sc):
    """A gently winding 45 m street for the House Row scene (hidden in renders)."""
    cu = bpy.data.curves.new("Street Path", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("BEZIER")
    pts = [(0.0, -8.0, 0.0), (2.5, 6.0, 0.0), (0.0, 20.0, 0.0), (-3.5, 36.0, 0.0)]
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    ob = bpy.data.objects.new("Street Path", cu)
    sc.collection.objects.link(ob)
    ob.hide_render = True
    return ob


def plaza(sc, size=16.0):
    """A cobbled forecourt round the hero house (the cobble material of the House Row street), on the meadow."""
    h = size / 2
    me = bpy.data.meshes.new("Plaza")
    me.from_pydata([(-h, -h + 1.0, 0.0), (h, -h + 1.0, 0.0), (h, h + 1.0, 0.0), (-h, h + 1.0, 0.0)], [],
                   [(0, 1, 2, 3)])
    me.materials.append(bpy.data.materials["Parametric House Cobbles"])
    ob = bpy.data.objects.new("Plaza", me)
    sc.collection.objects.link(ob)
    return ob


def camera(sc, name, loc, target, lens):
    """A camera at loc aimed at target (Track To an empty, so the aim can be moved in the viewport)."""
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    cam.data.lens, cam.data.clip_end = lens, 500.0
    cam.location = loc
    tgt = bpy.data.objects.new(f"{name} Target", None)
    tgt.location = target
    for o in (cam, tgt):
        sc.collection.objects.link(o)
    c = cam.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = tgt, "TRACK_NEGATIVE_Z", "UP_Y"
    sc.camera = cam
    return cam


LIGHT = dict(sun_elev=32.0, sun_azim=200.0, strength=6.0, sun_color="#FFD7A6", sky_top="#8DB4D6",
             sky_horizon="#EAD8C0", sky_strength=0.45)
POST = dict(haze_color="#E6D6C2", sky_top="#7FA9D2", sky_horizon="#F0DEC6")
SCENES = {
    # the hero uses Seed 3 (peach plaster, green paint); every other input is the group default
    "House": dict(inputs={"Seed": 3}, cam=((10.5, 18.0, 1.6), (-0.6, -2.0, 6.3), 32.0), haze=(18.0, 90.0, 0.75)),
    "House Row": dict(inputs={}, cam=((0.5, -15.0, 6.0), (0.0, 12.0, 2.5), 26.0), haze=(12.0, 90.0, 0.5)),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/parametric_house.blend")
    ap.add_argument("--render", default="")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--frame", type=int, default=1)
    ap.add_argument("--scene", default="", help="render this scene instead of the first")
    a = ap.parse_args(argv)

    sc0 = S.reset()
    one, row = house(), house_row()
    for i_, (name, cfg) in enumerate(SCENES.items()):
        sc = sc0 if i_ == 0 else bpy.data.scenes.new(name)
        sc.name = name
        S.light_world(sc=sc, **LIGHT)
        if name == "House":
            ob, mod = S.holder("House", None, one, sc=sc)
            plaza(sc)
        else:
            curve = street_path(sc)
            ob, mod = S.holder("House Row", None, row, sc=sc)
            inspect.set_modifier_inputs(mod, {"Path": curve.name})
        inspect.set_modifier_inputs(mod, cfg["inputs"])
        S.ground(sc=sc, color="#6F8A45")
        loc, target, lens = cfg["cam"]
        camera(sc, f"{name} Camera", loc, target, lens)
        S.render_setup(sc=sc, width=a.width, height=round(a.width * 0.55 / 2) * 2, samples=a.samples,
                       look="Medium High Contrast")
        hs, hd, ha = cfg["haze"]
        post(sc, haze_start=hs, haze_depth=hd, haze_amount=ha, **POST)
        sc.frame_set(a.frame)
        st = inspect.evaluated_stats(ob, sc)
        print(f"SCENE {name}: verts {st['verts']} faces {st['faces']} warnings "
              f"{[w.message for w in mod.node_warnings]}")
    lint = inspect.check_groups(NAME) + inspect.check_groups("NK ")
    print("LINT", len(lint))
    for p in lint:
        print("  ", p)
    out = pathlib.Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
    print("SAVED", out)
    if a.render:
        sc = bpy.data.scenes[a.scene] if a.scene else sc0
        if bpy.context.window:
            bpy.context.window.scene = sc
        sc.render.filepath = str(pathlib.Path(a.render).resolve())
        bpy.ops.render.render(write_still=True, scene=sc.name)
        print("RENDERED", sc.render.filepath)


main()
