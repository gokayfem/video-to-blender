"""SS Facades: continuous rows of half-timbered storybook houses on both sides of the street (owner: facades).

How the graph explains itself, left to right:

    SS Facades Parcels   split each side of the path into house parcels (random widths, staggered facades);
                         each parcel's two front corners are found on the curve, so the chord between them
                         gives the house's width, centre and facing: neighbours meet exactly at the facade on
                         any bend. The house's frame (+X along the wall, +Y out to the street, +Z up) and a
                         'fan' factor (how much wider/narrower the house is at its back) are stored per house.
    SS House Plan        every random decision per house: storeys, plaster colour, timber pattern, windows,
                         door, shop, roof form and material, chimney. Written as h_* attributes.
    SS House Body/Timber/Windows/Doors/Roof
                         the parts, modelled in house-local space (see facades_parts.py) from those attributes.
    SS House Cut         subtracts window and door reveals from the wall blocks (Mesh Boolean, Manifold).
    SS House Place       local -> world: fan the back of the house to close bend gaps, rotate by the house
                         frame, move to the parcel centre. Anchors go through the same transform.

Reference (reference/frames, shader-skills village-loop REFERENCE.md): 3-4 storeys, ground floor 2 H, upper
floors 1.6 H, houses 2.5-4 H wide, jettied upper floors on corbels, cream/ochre/terracotta/sage plaster, dark
timber, green shutters, clay or slate roofs, facades staggered a little.
"""
import math
from v2n.graph import Graph
from street.groups import frame
from street.groups import facades_parts as P
from street.groups.facades_parts import (add, sub, mul, div, mad, mx, mn, half, neg, vec, xyz, attr, store, rnd,
                                         chance, sw, iswitch, cmp, both)
from street.materials import facades as fm

NAME = "SS Facades"
FACADE_DEPTH = 4.5       # house depth behind the facade

# plaster albedo and share of houses (docs/REFERENCE.md 2: ~40% cream/peach, 30% ochre/orange, 20% yellow, 10% sage)
PALETTE = [("Cream", "#D9AE7C", 0.17), ("Peach", "#D79A66", 0.33), ("Ochre", "#C7864C", 0.2),
           ("Terracotta", "#BD7650", 0.12), ("Yellow", "#CE9E5E", 0.11), ("Sage", "#A09D80", 0.07)]
DOORS = [("Door Brown", "#6E4428"), ("Door Teal", "#2F6E73"), ("Door Green", "#3F6E4E")]


# ---- SS Facades Parcels --------------------------------------------------------------------------------------
def parcels():
    pt = frame.build()
    g = Graph("SS Facades Parcels", description="One point per house on both sides of the street: random parcel "
                                                "widths laid end to end along s, facades staggered in d. Each "
                                                "house's front corners are placed on the curve; the chord gives "
                                                "width (h_width), centre (position) and frame (h_rot), and the "
                                                "back corners give h_fan, how much to widen the back on bends")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    sw_ = g.input("Street Width", "FLOAT", 3.0, min=1.0, max=20.0, subtype="DISTANCE", desc="Curb-to-curb width")
    cw = g.input("Curb Width", "FLOAT", 0.25, min=0.0, max=1.0, subtype="DISTANCE", desc="Curb stone width")
    vw = g.input("Verge Width", "FLOAT", 0.8, min=0.0, max=4.0, subtype="DISTANCE",
                 desc="Paving and grass between the curb and the house fronts")
    wmin = g.input("Width Min", "FLOAT", 2.0, min=1.2, max=12.0, subtype="DISTANCE", desc="Narrowest house")
    wmax = g.input("Width Max", "FLOAT", 4.6, min=1.2, max=12.0, subtype="DISTANCE", desc="Widest house")
    stag = g.input("Stagger", "FLOAT", 0.18, min=0.0, max=1.5, subtype="DISTANCE",
                   desc="Each facade steps in or out of the facade line by up to this much")
    depth = g.input("Depth", "FLOAT", FACADE_DEPTH, min=1.0, max=12.0, subtype="DISTANCE",
                    desc="House depth behind the facade")
    with g.frame("Candidate parcels: N per side with random widths, laid end to end (accumulate)"):
        length = g.node("GeometryNodeCurveLength", Curve=curve)["Length"]
        n = add(g, g.math("CEIL", div(g, length, wmin)), 1.0)
        line = g.node("GeometryNodeMeshLine", props={"mode": "OFFSET"}, Count=mul(g, n, 2.0), Offset=(0, 0, 0))
        idx = g.node("GeometryNodeInputIndex")["Index"]
        side_k = g.math("FLOOR", div(g, idx, n))                     # 0 left, 1 right
        width = rnd(g, wmin, wmax, idx, seed)
        acc = g.node("GeometryNodeAccumulateField", props={"data_type": "FLOAT", "domain": "POINT"}, Value=width,
                     **{"Group ID": side_k})
        sign = sub(g, 1.0, mul(g, side_k, 2.0))                      # +1 left of travel, -1 right
        d = mul(g, sign, add(g, add(g, add(g, half(g, sw_), cw), vw), rnd(g, neg(g, stag), stag, idx, add(g, seed, 7))))
        pts = store(g, line["Mesh"], "h_key", idx, "INT")
        pts = store(g, pts, "h_sign", sign)
        pts = store(g, pts, "h_s0", acc["Trailing"])
        pts = store(g, pts, "h_s1", acc["Leading"])
        pts = store(g, pts, "h_d", d)
    with g.frame("Keep the parcels that end before the street does"):
        pts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=pts,
                     Selection=cmp(g, attr(g, "h_s1"), length))["Geometry"]
    with g.frame("Front corners on the facade line; the chord gives width, centre and the house frame"):
        sgn, dd = attr(g, "h_sign"), attr(g, "h_d")
        p0 = g.group(pt, Curve=curve, Length=attr(g, "h_s0"), Offset=dd)["Position"]
        p1 = g.group(pt, Curve=curve, Length=attr(g, "h_s1"), Offset=dd)["Position"]
        chord = g.vmath("MULTIPLY", g.vmath("SUBTRACT", p1, p0), (1.0, 1.0, 0.0))
        w = g.vmath("LENGTH", chord)["Value"]
        xdir = g.vmath("SCALE", g.vmath("NORMALIZE", chord), scale=neg(g, sgn))   # wall +X, so +Y faces the street
        rot = g.node("FunctionNodeAxesToRotation", props={"primary_axis": "X", "secondary_axis": "Z"},
                     **{"Primary Axis": xdir, "Secondary Axis": (0.0, 0.0, 1.0)})["Rotation"]
        centre = g.vmath("SCALE", g.vmath("ADD", p0, p1), scale=0.5)
    with g.frame("Back corners: fan = relative width change per unit depth (outside of a bend > 0)"):
        db = add(g, dd, mul(g, sgn, depth))
        b0 = g.group(pt, Curve=curve, Length=attr(g, "h_s0"), Offset=db)["Position"]
        b1 = g.group(pt, Curve=curve, Length=attr(g, "h_s1"), Offset=db)["Position"]
        wb = g.vmath("LENGTH", g.vmath("MULTIPLY", g.vmath("SUBTRACT", b1, b0), (1.0, 1.0, 0.0)))["Value"]
        fan = div(g, sub(g, div(g, wb, mx(g, w, 0.01)), 1.0), depth)
    with g.frame("Store the house frame"):
        pts = store(g, pts, "h_width", w)
        pts = store(g, pts, "h_rot", rot, "QUATERNION")
        pts = store(g, pts, "h_fan", fan)
        pts = store(g, pts, "h_depth", depth)
        pts = g.node("GeometryNodeSetPosition", Geometry=pts, Position=centre)["Geometry"]
        pts = store(g, pts, "ss_house", g.node("GeometryNodeInputIndex")["Index"], "INT")
    g.output("Houses", "GEOMETRY", pts)
    return g.finish()


# ---- SS House Plan -------------------------------------------------------------------------------------------
def plan():
    g = Graph("SS House Plan", description="Every random decision per house, written as h_* attributes: storeys "
                                           "and floor heights, plaster colour, timber pattern, window columns "
                                           "and sizes, shutters, door (side, width, arch, colour), shop or "
                                           "ground windows, roof form, roof material and chimney")
    houses = g.input("Houses", "GEOMETRY", desc="House points from SS Facades Parcels")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    ch = g.input("Curb Height", "FLOAT", 0.07, min=0.0, max=0.5, subtype="DISTANCE",
                 desc="Curb height; the verge (door thresholds) sits at 0.55 of it, as in SS Road")
    smin = g.input("Storeys Min", "INT", 2, min=1, max=6, panel="Houses", desc="Fewest storeys (incl. ground)")
    smax = g.input("Storeys Max", "INT", 4, min=1, max=6, panel="Houses", desc="Most storeys (incl. ground); the middle count is the most common")
    gh = g.input("Ground Floor Height", "FLOAT", 1.85, min=1.4, max=4.0, subtype="DISTANCE", panel="Houses",
                 desc="Ground storey height")
    fh = g.input("Floor Height", "FLOAT", 1.5, min=1.0, max=3.0, subtype="DISTANCE", panel="Houses",
                 desc="Upper storey height")
    jet = g.input("Jetty Depth", "FLOAT", 0.18, min=0.0, max=0.6, subtype="DISTANCE", panel="Houses",
                  desc="How far each upper storey overhangs the one below")
    tden = g.input("Timber Density", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", panel="Timber",
                   desc="Share of houses with half-timber frames (the rest are plain plaster)")
    tmix = g.input("Brace Mix", "FLOAT", 0.65, min=0.0, max=1.0, subtype="FACTOR", panel="Timber",
                   desc="Share of timbered houses that get braces or crosses rather than plain posts and rails")
    wden = g.input("Window Density", "FLOAT", 0.55, min=0.2, max=1.5, panel="Windows",
                   desc="Upper-floor windows per H of house width (rounded, 1-4 per storey)")
    wsize = g.input("Window Size", "FLOAT", 1.0, min=0.5, max=1.6, subtype="FACTOR", panel="Windows",
                    desc="Scale of all windows")
    shch = g.input("Shutter Chance", "FLOAT", 0.65, min=0.0, max=1.0, subtype="FACTOR", panel="Windows",
                   desc="Share of houses with shutters")
    shcol = g.input("Shutter Color", "COLOR", fm.hexc("#4F6E58"), panel="Windows", desc="Shutter paint")
    shop = g.input("Shop Chance", "FLOAT", 0.35, min=0.0, max=1.0, subtype="FACTOR", panel="Doors & Shops",
                   desc="Share of houses with a shopfront on the ground floor")
    archc = g.input("Arch Chance", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", panel="Doors & Shops",
                    desc="Share of doors with a round arch")
    dcols = [g.input(n, "COLOR", fm.hexc(hx), panel="Doors & Shops", desc=f"{n.split()[1]} door and fascia paint")
             for n, hx in DOORS]
    gmix = g.input("Gable Mix", "FLOAT", 0.25, min=0.0, max=1.0, subtype="FACTOR", panel="Roof",
                   desc="Share of houses with a gable to the street (else eaves to the street)")
    smix = g.input("Slate Mix", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR", panel="Roof",
                   desc="Share of roofs in blue slate (else clay tile)")
    tower = g.input("Tower Chance", "FLOAT", 0.06, min=0.0, max=1.0, subtype="FACTOR", panel="Roof",
                    desc="Share of houses built two storeys taller with a steep blue slate spire roof")
    chim = g.input("Chimney Chance", "FLOAT", 0.55, min=0.0, max=1.0, subtype="FACTOR", panel="Roof",
                   desc="Share of houses with a chimney")
    tile = g.input("Tile Color", "COLOR", fm.hexc("#A65A3A"), panel="Roof", desc="Clay tile colour")
    slate = g.input("Slate Color", "COLOR", fm.hexc("#4C5E78"), panel="Roof", desc="Slate colour")
    pal = [g.input(n, "COLOR", fm.hexc(hx), panel="Palette", desc=f"{n} plaster (about {round(w * 100)}% of houses)")
           for n, hx, w in PALETTE]

    key = None
    geo = houses

    def R(lo, hi, k, dt="FLOAT"):
        return rnd(g, lo, hi, key, add(g, seed, 100 + k), dt)

    def C(p, k):
        return chance(g, p, key, add(g, seed, 100 + k))

    def put(name, value, dt="FLOAT"):
        nonlocal geo
        geo = store(g, geo, name, value, dt)

    with g.frame("Storeys and floor heights (a few % per house so beams and eaves do not line up)"):
        key = attr(g, "h_key", "INT")
        lo, hi = sub(g, smin, 0.49), add(g, smax, 0.49)          # mean of two uniforms: the middle is likeliest
        put("h_storeys", g.math("ROUND", half(g, add(g, R(lo, hi, 1), R(lo, hi, 24)))), "INT")
        put("h_ground_h", mul(g, gh, R(0.97, 1.03, 2)))
        put("h_floor_h", mul(g, fh, R(0.95, 1.05, 3)))
        put("h_level", mul(g, ch, 0.55))
        put("h_plinth", C(0.3, 23), "BOOLEAN")
        put("ss_rand", R(0.0, 1.0, 4))
        put("h_tower", C(tower, 26), "BOOLEAN")
        put("h_storeys", add(g, attr(g, "h_storeys", "INT"), sw(g, attr(g, "h_tower", "BOOLEAN"), 0, 2, "INT")),
            "INT")
    with g.frame("Plaster colour: one of the palette, value jittered"):
        r, acc, pick = R(0.0, 1.0, 5), 0.0, 0.0
        for _, _, share in PALETTE[:-1]:                         # index = how many cumulative shares r exceeds
            acc += share
            pick = add(g, pick, cmp(g, r, acc))
        c = iswitch(g, pick, pal, "RGBA")
        put("h_color", g.vmath("SCALE", c, scale=R(0.9, 1.06, 6)), "FLOAT_COLOR")
    with g.frame("Timber pattern: 0 plain, 1 posts and rails, 2 corner braces, 3 crosses"):
        braced = add(g, sw(g, C(0.5, 9), 0, 1, "INT"), 2.0)
        pat = sw(g, C(tmix, 8), 1, braced, "INT")
        put("h_timber", sw(g, C(tden, 7), 0, pat, "INT"), "INT")
        put("h_jetty", mul(g, jet, cmp(g, attr(g, "h_timber", "INT"), 0.5)))     # plain houses stand flush
    with g.frame("Windows: columns per storey from the width, sizes that fit with their shutters"):
        w = attr(g, "h_width")
        cols = mn(g, mx(g, g.math("ROUND", mul(g, w, wden)), 1.0), 4.0)
        put("h_cols", cols, "INT")
        cols = attr(g, "h_cols", "INT")
        put("h_win_w", mn(g, mul(g, 0.62, wsize), sub(g, half(g, div(g, w, cols)), 0.2)))
        put("h_win_h", mn(g, mul(g, 0.82, wsize), mul(g, attr(g, "h_floor_h"), 0.62)))
        put("h_shutter", C(shch, 10), "BOOLEAN")
        put("h_shutter_color", g.vmath("SCALE", shcol, scale=R(0.85, 1.12, 11)), "FLOAT_COLOR")
    with g.frame("Door: side, width, height, arch, colour"):
        dw = R(0.7, 0.82, 12)
        side = sw(g, C(0.5, 13), -1.0, 1.0)
        put("h_door_w", dw)
        put("h_door_side", side)
        put("h_door_arch", C(archc, 14), "BOOLEAN")
        put("h_door_h", R(1.4, 1.5, 25))
        margin = R(0.32, 0.6, 15)
        put("h_door_x", mul(g, side, sub(g, sub(g, half(g, w), margin), half(g, dw))))
        put("h_door_color", iswitch(g, R(0, 2, 16, "INT"), dcols, "RGBA"), "FLOAT_COLOR")
    with g.frame("Ground floor span beside the door: a shopfront or 0-2 windows"):
        dx, dwa, sd = attr(g, "h_door_x"), attr(g, "h_door_w"), attr(g, "h_door_side")
        e_in = sub(g, dx, mul(g, sd, add(g, half(g, dwa), 0.32)))
        e_out = mul(g, neg(g, sd), sub(g, half(g, w), 0.3))
        span = g.math("ABSOLUTE", sub(g, e_in, e_out))
        put("h_span_c", half(g, add(g, e_in, e_out)))
        put("h_span_len", span)
        put("h_shop", both(g, C(shop, 17), cmp(g, span, 1.2)), "BOOLEAN")
        n = sw(g, cmp(g, span, 2.3), sw(g, cmp(g, span, 0.9), 0, 1, "INT"), 2, "INT")
        put("h_gwin", sw(g, attr(g, "h_shop", "BOOLEAN"), n, 0, "INT"), "INT")
        gw = mn(g, mul(g, 0.72, wsize), sub(g, half(g, div(g, span, mx(g, attr(g, "h_gwin", "INT"), 1.0))), 0.18))
        put("h_gwin_w", mn(g, gw, 0.75))
        put("h_gwin_h", mn(g, mul(g, 0.95, wsize), sub(g, gh, 0.8)))
    with g.frame("Roof: gable or eaves to the street, clay or slate, chimney"):
        tw = attr(g, "h_tower", "BOOLEAN")
        put("h_gable", both(g, C(gmix, 18), tw, "OR"), "BOOLEAN")
        put("h_slate", both(g, C(smix, 19), tw, "OR"), "BOOLEAN")
        rc = sw(g, attr(g, "h_slate", "BOOLEAN"), tile, slate, "RGBA")
        put("h_roof_color", g.vmath("SCALE", rc, scale=R(0.85, 1.1, 20)), "FLOAT_COLOR")
        put("h_chimney", C(chim, 21), "BOOLEAN")
        put("h_chimney_x", mul(g, sw(g, C(0.5, 22), -1.0, 1.0), sub(g, half(g, w), 0.6)))
    g.output("Houses", "GEOMETRY", geo)
    return g.finish()


# ---- SS House Cut --------------------------------------------------------------------------------------------
def cut():
    g = Graph("SS House Cut", description="Subtracts window and door reveals from the wall blocks. Houses are "
                                          "spread apart along x (house i by i * 60) so each is cut on its own; "
                                          "afterwards the house index is read back from x, so nothing depends "
                                          "on attributes surviving the boolean")
    walls = g.input("Walls", "GEOMETRY", desc="Wall blocks, house-local, with ss_house")
    cutters = g.input("Cutters", "GEOMETRY", desc="Opening volumes, house-local, with ss_house")
    houses = g.input("Houses", "GEOMETRY", desc="House points (for the plaster colour)")

    def spread(geo):
        geo = g.node("GeometryNodeRealizeInstances", Geometry=geo)["Geometry"]
        off = vec(g, mul(g, attr(g, "ss_house", "INT"), P.SPREAD), 0.0, 0.0)
        return g.node("GeometryNodeSetPosition", Geometry=geo, Offset=off)["Geometry"]

    with g.frame("Spread houses apart, so neighbours never touch while cutting"):
        a = spread(walls)
        b = spread(cutters)
    with g.frame("Walls minus openings (Manifold boolean)"):
        res = g.node("GeometryNodeMeshBoolean", props={"operation": "DIFFERENCE", "solver": "MANIFOLD"},
                     **{"Mesh 1": a, "Mesh 2": b})["Mesh"]
    with g.frame("House index from x, move each house back, restore its plaster colour"):
        x = xyz(g, g.node("GeometryNodeInputPosition")["Position"])[0]
        hid = g.math("ROUND", div(g, x, P.SPREAD))
        res = store(g, res, "ss_house", hid, "INT")
        hid = attr(g, "ss_house", "INT")
        out = g.node("GeometryNodeSetPosition", Geometry=res,
                     Offset=vec(g, mul(g, hid, -P.SPREAD), 0.0, 0.0))["Geometry"]
        col = g.node("GeometryNodeSampleIndex", props={"data_type": "FLOAT_COLOR", "domain": "POINT"},
                     Geometry=houses, Value=attr(g, "h_color", "FLOAT_COLOR"), Index=hid)["Value"]
        out = store(g, out, "ss_color", col, "FLOAT_COLOR")
    g.output("Geometry", "GEOMETRY", out)
    return g.finish()


# ---- SS House Place ------------------------------------------------------------------------------------------
def place():
    g = Graph("SS House Place", description="House-local geometry to the world: widen (or narrow) the back of "
                                            "each house by h_fan so neighbours close up on bends, rotate by the "
                                            "house frame h_rot, move to the parcel centre. Stores ss_local and "
                                            "the house frame as ss_rot")
    geo = g.input("Geometry", "GEOMETRY", desc="Realized house-local geometry or points with ss_house")
    houses = g.input("Houses", "GEOMETRY", desc="House points (position, h_rot, h_fan)")
    with g.frame("Look up the house of every vertex"):
        hid = attr(g, "ss_house", "INT")

        def look(value, dt):
            return g.node("GeometryNodeSampleIndex", props={"data_type": dt, "domain": "POINT"}, Geometry=houses,
                          Value=value, Index=hid)["Value"]
        hpos = look(g.node("GeometryNodeInputPosition")["Position"], "FLOAT_VECTOR")
        hrot = look(attr(g, "h_rot", "QUATERNION"), "QUATERNION")
        fan = look(attr(g, "h_fan"), "FLOAT")
    with g.frame("Fan the house: x scales with the distance from the facade plane (back wider on the outside "
                 "of a bend, jetties and eaves narrower), so neighbours close up at every depth"):
        pos = g.node("GeometryNodeInputPosition")["Position"]
        x, y, z = xyz(g, pos)
        sx = mx(g, sub(g, 1.0, mul(g, fan, y)), 0.25)
        local = vec(g, mul(g, x, sx), y, z)
    with g.frame("Rotate into the house frame and move to the parcel"):
        world = g.vmath("ADD", hpos, g.node("FunctionNodeRotateVector", Vector=local, Rotation=hrot)["Vector"])
        geo = store(g, geo, "ss_local", pos, "FLOAT_VECTOR")
        geo = store(g, geo, "ss_rot", hrot, "QUATERNION")
        geo = g.node("GeometryNodeSetPosition", Geometry=geo, Position=world)["Geometry"]
    g.output("Geometry", "GEOMETRY", geo)
    return g.finish()


# ---- SS Facades ----------------------------------------------------------------------------------------------
def build():
    fm.reset()
    P.reset()
    g_parcels, g_plan, g_body, g_timber = parcels(), plan(), P.body(), P.timber()
    g_windows, g_doors, g_roof, g_cut, g_place = P.windows(), P.doors(), P.roof(), cut(), place()

    g = Graph(NAME, description="Continuous rows of half-timbered storybook houses along both sides of the path "
                                "curve: jettied storeys on corbels, plaster in a pastel palette, timber frames, "
                                "deep windows with shutters, doors and shopfronts, clay or slate roofs. Outputs "
                                "the houses and the Anchors point cloud for SS Props")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    seed = g.input("Seed", "INT", 0, desc="Changes every random choice of the houses")
    swd = g.input("Street Width", "FLOAT", 3.0, min=1.0, max=20.0, subtype="DISTANCE", desc="Curb-to-curb width")
    cw = g.input("Curb Width", "FLOAT", 0.25, min=0.0, max=1.0, subtype="DISTANCE", desc="Curb stone width")
    chh = g.input("Curb Height", "FLOAT", 0.07, min=0.0, max=0.5, subtype="DISTANCE",
                  desc="Curb height (door thresholds sit on the verge at 0.55 of it)")
    vw = g.input("Verge Width", "FLOAT", 0.8, min=0.0, max=4.0, subtype="DISTANCE",
                 desc="Paving and grass between the curb and the house fronts")
    # panels: the artist's controls; each is forwarded to the sub-group that uses it
    ui = {}

    def inp(name, stype, default, panel, desc, **kw):
        ui[name] = g.input(name, stype, default, panel=panel, desc=desc, **kw)
        return ui[name]

    def copy_from(sub_tree, names, panel):
        for it in sub_tree.interface.items_tree:
            if it.item_type == "SOCKET" and it.in_out == "INPUT" and it.name in names:
                kw = {}
                for k, a in (("min", "min_value"), ("max", "max_value"), ("subtype", "subtype")):
                    if hasattr(it, a):
                        kw[k] = getattr(it, a)
                if kw.get("subtype") == "NONE":
                    kw.pop("subtype")
                dv = getattr(it, "default_value", None)
                if dv is not None and hasattr(dv, "__len__"):
                    dv = tuple(dv)
                stype = {"NodeSocketFloat": "FLOAT", "NodeSocketInt": "INT", "NodeSocketColor": "COLOR"}[
                    it.socket_type]
                inp(it.name, stype, dv, panel, it.description, **kw)

    copy_from(g_parcels, ["Width Min", "Width Max"], "Houses")
    copy_from(g_plan, ["Storeys Min", "Storeys Max", "Ground Floor Height", "Floor Height", "Jetty Depth"], "Houses")
    copy_from(g_parcels, ["Stagger", "Depth"], "Houses")
    copy_from(g_plan, ["Timber Density", "Brace Mix"], "Timber")
    copy_from(g_body, ["Beam Width", "Timber Color"], "Timber")
    copy_from(g_plan, ["Window Density", "Window Size", "Shutter Chance", "Shutter Color"], "Windows")
    copy_from(g_plan, ["Shop Chance", "Arch Chance"] + [n for n, _ in DOORS], "Doors & Shops")
    copy_from(g_roof, ["Pitch", "Overhang"], "Roof")
    copy_from(g_plan, ["Gable Mix", "Slate Mix", "Tower Chance", "Chimney Chance", "Tile Color", "Slate Color"], "Roof")
    copy_from(g_plan, [n for n, _, _ in PALETTE], "Palette")

    def wire(sub_tree, label, **fixed):
        n = g.group(sub_tree, label=label)
        for s in n.b.inputs:
            if not s.enabled:
                continue
            if s.name in fixed:
                g.connect(fixed[s.name], s)
            elif s.name in ui:
                g.connect(ui[s.name], s)
        return n

    with g.frame("Where the houses stand: parcels on both sides, then every random decision per house"):
        par = wire(g_parcels, "Parcels", Curve=curve, Seed=seed, **{"Street Width": swd, "Curb Width": cw,
                                                                    "Verge Width": vw})
        houses = wire(g_plan, "Plan", Houses=par["Houses"], Seed=seed, **{"Curb Height": chh})["Houses"]
    with g.frame("The parts, modelled in house-local space"):
        body = wire(g_body, "Body", Houses=houses)
        tim = wire(g_timber, "Timber", Houses=houses)
        win = wire(g_windows, "Windows", Houses=houses, Seed=seed)
        door = wire(g_doors, "Doors & Shops", Houses=houses, Seed=seed)
        roof = wire(g_roof, "Roof", Houses=houses)
    with g.frame("Cut the window and door reveals into the walls"):
        cutters = P.join(g, win["Cutters"], door["Cutters"])
        walls = g.group(g_cut, label="Cut", Walls=body["Walls"], Cutters=cutters, Houses=houses)["Geometry"]
    with g.frame("Everything to the world through each house's frame"):
        parts = P.join(g, walls, body["Geometry"], tim["Geometry"], win["Geometry"], door["Geometry"],
                       roof["Geometry"])
        real = g.node("GeometryNodeRealizeInstances", Geometry=parts)["Geometry"]
        placed = g.group(g_place, label="Place", Geometry=real, Houses=houses)["Geometry"]
        flat = g.node("GeometryNodeSetShadeSmooth", props={"domain": "FACE"}, Geometry=placed,
                      **{"Shade Smooth": False})["Geometry"]
        geo = g.node("GeometryNodeRemoveAttribute", **{"Pattern Mode": "Wildcard"}, Geometry=flat,
                     Name="ss_rot")["Geometry"]
    with g.frame("Anchors for SS Props: same transform, then only the interface attributes"):
        anc = P.join(g, win["Anchors"], door["Anchors"])
        anc = g.group(g_place, label="Place Anchors", Geometry=anc, Houses=houses)["Geometry"]
        for pat in ("h_*", "w_*", "t_*", "ss_local"):
            anc = g.node("GeometryNodeRemoveAttribute", **{"Pattern Mode": "Wildcard"}, Geometry=anc,
                         Name=pat)["Geometry"]
    g.output("Geometry", "GEOMETRY", geo)
    g.output("Anchors", "GEOMETRY", anc, desc="Facade anchor points: anchor (1-7), ss_rot, ss_width, ss_house, "
                                               "ss_rand (see AGENTS.md)")
    return g.finish()

