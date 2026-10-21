"""SS Road: the street surface along the path curve.

Cross-section, from the centre line outward on each side (reference frames t00, t07, t12):

    | cobbled carriageway | grass gutter | curb | cobbled paving | grass verge | facade line
    0             W/2 - Gutter          W/2   W/2+CW        +Paving      W/2+CW+Verge Width

Method: everything hard (ground bands, cobbles, curb blocks) is modelled flat in street space, x = s (arc length),
y = d (lateral offset), z = height, and then bent onto the path vertex by vertex (SS Road Bend). Stones and
blocks therefore follow any path, including hills and tight spirals: on the inside of a bend they are squeezed
along the street (never overlapping), on the outside slightly stretched. Cobbles are instances of one domed stone
laid in loose courses across the street; each stone is sized, shifted, turned and tinted on its own, and the
realized stones get a low-frequency wobble so no two outlines are alike. Grass is scattered on the bent ground.
"""
from v2n.graph import Graph
from street.groups import frame
from street.materials import road as mats

NAME = "SS Road"
GROUND_STEP = 0.5          # ground bands: one vertex row every GROUND_STEP along the street
CURB_FOOT = 0.08           # curb blocks reach this far below the road surface


# ---- small helpers -------------------------------------------------------------------------------------------
def rand(g, lo, hi, ident, seed, k, label=None, dtype="FLOAT"):
    """Random value in [lo, hi] for a stable ID; k decorrelates the different random properties."""
    return g.node("FunctionNodeRandomValue", label, props={"data_type": dtype}, Min=lo, Max=hi, ID=ident,
                  Seed=g.math("ADD", seed, float(k)))


# ---- sub-groups ----------------------------------------------------------------------------------------------
def build_bend(pt):
    g = Graph("SS Road Bend", description="Bend geometry modelled in flat street space (x = arc length, "
                                          "y = lateral offset, z = height) onto the path curve, vertex by vertex")
    geo = g.input("Geometry", "GEOMETRY", desc="Geometry in street space")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    base = g.input("Height", "FLOAT", 0.0, subtype="DISTANCE", desc="Extra height added to every vertex")
    with g.frame("Each vertex: (s, d, h) -> world through SS Street Point"):
        p = g.separate(g.node("GeometryNodeInputPosition"))
        sp = g.group(pt, Curve=curve, Length=p["X"], Offset=p["Y"], Height=g.math("ADD", p["Z"], base))
        out = g.node("GeometryNodeSetPosition", Geometry=geo, Position=sp["Position"])
    g.output("Geometry", "GEOMETRY", out)
    return g.finish()


def build_strip(bend):
    g = Graph("SS Road Strip", description="A flat ground band between two lateral offsets, the full length of "
                                           "the street, tinted with ss_color")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    d0 = g.input("Inner", "FLOAT", 0.0, subtype="DISTANCE", desc="Lateral offset of one edge")
    d1 = g.input("Outer", "FLOAT", 1.0, subtype="DISTANCE", desc="Lateral offset of the other edge")
    h = g.input("Height", "FLOAT", 0.0, subtype="DISTANCE", desc="Height of the band above the curve")
    color = g.input("Color", "COLOR", (0.5, 0.5, 0.5, 1.0), desc="Tint written to ss_color")
    mat = g.input("Material", "MATERIAL", desc="Surface material")
    with g.frame("A grid in (s, d): rows every half unit along the street, two columns across"):
        length = g.node("GeometryNodeCurveLength", Curve=curve)
        rows = g.math("ADD", g.math("CEIL", g.math("DIVIDE", length, GROUND_STEP)), 1.0)
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": length, "Size Y": g.math("SUBTRACT", d1, d0),
                                                 "Vertices X": rows, "Vertices Y": 2})
        move = g.node("GeometryNodeTransform", Geometry=grid["Mesh"],
                      Translation=g.combine(g.math("MULTIPLY", length, 0.5),
                                            g.math("MULTIPLY", g.math("ADD", d0, d1), 0.5), h))
    with g.frame("Bend it onto the street, tint, material"):
        bent = g.group(bend, Geometry=move, Curve=curve)
        tinted = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "POINT"},
                        Geometry=bent, Name="ss_color", Value=color)
        out = g.node("GeometryNodeSetMaterial", Geometry=tinted, Material=mat)
    g.output("Geometry", "GEOMETRY", out)
    return g.finish()


def build_stone_shape():
    g = Graph("SS Road Stone Shape", description="One domed cobble of unit footprint (diameter 1) and unit "
                                                 "height; its rim sinks below 0 into the mortar")
    detail = g.input("Detail", "INT", 7, min=3, max=16, desc="Vertices across the stone (mesh budget per stone)")
    roundness = g.input("Roundness", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR",
                        desc="0 flat top with steep shoulders, 1 a round pebble dome")
    sink = 0.25
    with g.frame("A square grid mapped onto a disc, rings packed toward the rim"):
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": 2.0, "Size Y": 2.0, "Vertices X": detail,
                                                 "Vertices Y": detail})
        p = g.separate(g.node("GeometryNodeInputPosition"))

        def toward_rim(c):          # t -> sign(t) (1 - (1 - |t|)^2): more vertex rings near the shoulder
            inv = g.math("SUBTRACT", 1.0, g.math("ABSOLUTE", c))
            return g.math("MULTIPLY", g.math("SIGN", c), g.math("SUBTRACT", 1.0, g.math("MULTIPLY", inv, inv)))
        px, py = toward_rim(p["X"]), toward_rim(p["Y"])
        x2, y2 = g.math("MULTIPLY", px, px), g.math("MULTIPLY", py, py)
        u = g.math("MULTIPLY", px, g.math("SQRT", g.math("SUBTRACT", 1.0, g.math("MULTIPLY", y2, 0.5))))
        v = g.math("MULTIPLY", py, g.math("SQRT", g.math("SUBTRACT", 1.0, g.math("MULTIPLY", x2, 0.5))))
        r = g.math("MINIMUM", g.vmath("LENGTH", g.combine(u, v))["Value"], 1.0)
    with g.frame("Superellipse dome: z = (1 - r^p)^(1/p), p from Roundness"):
        pw = g.map_range(roundness, 0.0, 1.0, 5.0, 2.0)
        top = g.math("POWER", g.math("MAXIMUM", g.math("SUBTRACT", 1.0, g.math("POWER", r, pw)), 0.0),
                     g.math("DIVIDE", 1.0, pw))
        z = g.math("MULTIPLY_ADD", top, 1.0 + sink, -sink)
        pos = g.combine(g.math("MULTIPLY", u, 0.5), g.math("MULTIPLY", v, 0.5), z)
        shaped = g.node("GeometryNodeSetPosition", Geometry=grid["Mesh"], Position=pos)
        smooth = g.node("GeometryNodeSetShadeSmooth", Mesh=shaped, **{"Shade Smooth": True})
    g.output("Geometry", "GEOMETRY", smooth)
    return g.finish()


def build_cobbles(bend, shape):
    g = Graph("SS Road Cobbles", description="Cobbles between two lateral offsets: loose courses across the "
                                            "street, each stone sized, shifted, turned, wobbled and tinted on "
                                            "its own, then bent onto the path")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    d0 = g.input("Inner", "FLOAT", -1.5, subtype="DISTANCE", desc="Lateral offset of one edge of the field")
    d1 = g.input("Outer", "FLOAT", 1.5, subtype="DISTANCE", desc="Lateral offset of the other edge")
    base = g.input("Height", "FLOAT", 0.0, subtype="DISTANCE", desc="Height of the mortar bed")
    size = g.input("Stone Size", "FLOAT", 0.24, min=0.05, max=1.0, subtype="DISTANCE",
                   desc="Typical stone width across the street")
    elong = g.input("Elongation", "FLOAT", 0.95, min=0.5, max=2.5, desc="Stone width across / length along")
    var = g.input("Size Variation", "FLOAT", 0.25, min=0, max=0.6, subtype="FACTOR", desc="Random size spread")
    gap = g.input("Gap", "FLOAT", 0.03, min=0, max=0.2, subtype="DISTANCE", desc="Mortar gap between stones")
    jit = g.input("Jitter", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR",
                  desc="How loosely stones sit in their courses (offset and turn)")
    wobble = g.input("Irregularity", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR",
                     desc="Lumpiness of each stone's outline")
    dome = g.input("Dome Height", "FLOAT", 0.05, min=0, max=0.3, subtype="DISTANCE",
                   desc="Height of a stone's crown above the mortar")
    roundness = g.input("Roundness", "FLOAT", 0.45, min=0, max=1, subtype="FACTOR", desc="Flat top (0) to pebble (1)")
    detail = g.input("Detail", "INT", 7, min=3, max=16, desc="Vertices across each stone")
    color = g.input("Stone Color", "COLOR", (0.4, 0.33, 0.27, 1), desc="Base stone tint")
    tintvar = g.input("Tint Variation", "FLOAT", 0.25, min=0, max=1, subtype="FACTOR",
                      desc="Per-stone brightness and warmth spread")
    mat = g.input("Material", "MATERIAL", desc="Stone material")

    with g.frame("Course layout: one grid point per stone slot in (row, column)"):
        cell_a = g.math("ADD", size, gap, label="cell across")
        cell_l = g.math("ADD", g.math("DIVIDE", size, elong), gap, label="cell along")
        length = g.node("GeometryNodeCurveLength", Curve=curve)
        rows = g.math("MAXIMUM", g.math("FLOOR", g.math("DIVIDE", length, cell_l)), 1.0)
        width = g.math("ABSOLUTE", g.math("SUBTRACT", d1, d0))
        cols = g.math("ADD", g.math("CEIL", g.math("DIVIDE", width, cell_a)), 2.0)
        sx = g.math("MULTIPLY", g.math("SUBTRACT", rows, 1.0), cell_l)
        sy = g.math("MULTIPLY", g.math("SUBTRACT", cols, 1.0), cell_a)
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": sx, "Size Y": sy, "Vertices X": rows,
                                                 "Vertices Y": cols})
    with g.frame("Street-space position of each stone (course shift + jitter); stable IDs from (row, column)"):
        p = g.separate(g.node("GeometryNodeInputPosition"))
        row = g.math("ROUND", g.math("DIVIDE", g.math("MULTIPLY_ADD", sx, 0.5, p["X"]), cell_l), label="row")
        col = g.math("ROUND", g.math("DIVIDE", g.math("MULTIPLY_ADD", sy, 0.5, p["Y"]), cell_a), label="column")
        ident = g.math("MULTIPLY_ADD", row, 1024.0, col, label="stone id")
        lo = g.math("MINIMUM", d0, d1)
        hi = g.math("MAXIMUM", d0, d1)
        shift = g.math("MULTIPLY", rand(g, 0.0, 1.0, row, seed, 1, "course shift"), cell_a)
        jit_a = g.math("MULTIPLY", g.math("MULTIPLY", jit, cell_a), 0.18)
        jit_l = g.math("MULTIPLY", g.math("MULTIPLY", jit, cell_l), 0.18)
        s = g.math("ADD", g.math("MULTIPLY_ADD", row, cell_l, g.math("MULTIPLY", cell_l, 0.5)),
                   g.math("MULTIPLY", rand(g, -1.0, 1.0, ident, seed, 2), jit_l), label="s")
        d = g.math("ADD", g.math("ADD", g.math("MULTIPLY_ADD", g.math("SUBTRACT", col, 1.0), cell_a, lo), shift),
                   g.math("MULTIPLY", rand(g, -1.0, 1.0, ident, seed, 3), jit_a), label="d")
    with g.frame("Stone size: random spread and aspect, squeezed to fit the field edges"):
        k = rand(g, -0.7, 1.0, ident, seed, 4)
        across = g.math("MULTIPLY", g.math("MULTIPLY", size, 1.08), g.math("MULTIPLY_ADD", k, var, 1.0))
        room = g.math("MULTIPLY", g.math("MINIMUM", g.math("SUBTRACT", d, lo), g.math("SUBTRACT", hi, d)), 2.0)
        across_fit = g.math("MINIMUM", across, room, label="across (fit)")
        k2 = rand(g, -0.6, 0.9, ident, seed, 5)
        along = g.math("MULTIPLY", g.math("DIVIDE", across, elong), g.math("MULTIPLY_ADD", k2, var, 1.0),
                       label="along (slightly over the cell: neighbours touch)")
        height = g.math("MULTIPLY", dome, rand(g, 0.7, 1.3, ident, seed, 6))
        too_small = g.node("FunctionNodeCompare", props={"data_type": "FLOAT", "operation": "LESS_THAN"},
                           A=across_fit, B=g.math("MULTIPLY", across, 0.45))
        pts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=grid["Mesh"],
                     Selection=too_small["Result"])
    with g.frame("Instance the domed stone in flat street space, turned a little"):
        stone = g.group(shape, Detail=detail, Roundness=roundness)
        stone_m = g.node("GeometryNodeSetMaterial", Geometry=stone, Material=mat)
        yaw = g.math("MULTIPLY", rand(g, -0.35, 0.35, ident, seed, 7), jit)
        inst = g.node("GeometryNodeInstanceOnPoints", Points=pts, Instance=stone_m,
                      Rotation=g.combine(0.0, 0.0, yaw), Scale=g.combine(along, across_fit, height))
    with g.frame("Per-stone tint: brightness and a warm/cool shift"):
        r1 = rand(g, 0.0, 1.0, ident, seed, 8, "ss_rand")
        bright = g.math("MULTIPLY_ADD", g.math("SUBTRACT", r1, 0.5), tintvar, 1.0)
        warm = g.mix(rand(g, 0.0, 1.0, ident, seed, 9), (0.92, 0.98, 1.06, 1), (1.08, 1.0, 0.9, 1),
                     data_type="RGBA")
        tint = g.node("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": "MULTIPLY", "clamp_factor": True},
                      Factor=tintvar, A=color, B=warm)
        shade = g.vmath("SCALE", tint, scale=bright)
        c1 = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "INSTANCE"},
                    Geometry=inst, Name="ss_color", Value=shade)
        c2 = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "INSTANCE"},
                    Geometry=c1, Name="ss_rand", Value=r1)
        slot = g.node("GeometryNodeSetPosition", Geometry=c2, Position=g.combine(s, d, 0.0))
    with g.frame("Realize, wobble the outlines with low-frequency noise, bend onto the street"):
        real = g.node("GeometryNodeRealizeInstances", Geometry=slot)
        pos = g.node("GeometryNodeInputPosition")
        noise = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "3D"}, Vector=pos,
                       Scale=g.math("DIVIDE", 1.6, size), Detail=1.0)
        n = g.vmath("SUBTRACT", noise["Color"], (0.5, 0.5, 0.5))
        amp = g.math("MULTIPLY", g.math("MULTIPLY", wobble, size), 0.35)
        off = g.vmath("MULTIPLY", n, g.combine(amp, amp, 0.0))
        wob = g.node("GeometryNodeSetPosition", Geometry=real, Offset=off)
        bent = g.group(bend, Geometry=wob, Curve=curve, Height=base)
    g.output("Geometry", "GEOMETRY", bent)
    return g.finish()


def build_curb_block():
    g = Graph("SS Road Curb Block", description="One curb stone: a box with rounded edges, base at z = 0, "
                                                "centred on x and y")
    length = g.input("Length", "FLOAT", 0.7, min=0.05, subtype="DISTANCE", desc="Block length along the street")
    width = g.input("Width", "FLOAT", 0.2, min=0.02, subtype="DISTANCE", desc="Block width across the street")
    height = g.input("Height", "FLOAT", 0.2, min=0.02, subtype="DISTANCE", desc="Block height")
    radius = g.input("Radius", "FLOAT", 0.03, min=0.0, subtype="DISTANCE", desc="Edge rounding radius")
    with g.frame("Rounded box = a cube-sphere of the edge radius, its octants pushed out to the box size"):
        cube = g.node("GeometryNodeMeshCube", Size=(2.0, 2.0, 2.0), **{"Vertices X": 6, "Vertices Y": 6,
                                                                       "Vertices Z": 6})
        pos = g.node("GeometryNodeInputPosition")
        half = g.vmath("SCALE", g.combine(length, width, height), scale=0.5)
        r = g.math("MINIMUM", radius, g.math("MULTIPLY", g.math("MINIMUM", width, height), 0.45))
        inner = g.vmath("MAXIMUM", g.vmath("SUBTRACT", half, g.combine(r, r, r)), (0.0, 0.0, 0.0))
        sphere = g.vmath("SCALE", g.vmath("NORMALIZE", pos), scale=r)
        p = g.vmath("ADD", sphere, g.vmath("MULTIPLY", g.vmath("SIGN", pos), inner))
        p = g.vmath("ADD", p, g.combine(0.0, 0.0, g.math("MULTIPLY", height, 0.5)))
        box = g.node("GeometryNodeSetPosition", Geometry=cube["Mesh"], Position=p)
        smooth = g.node("GeometryNodeSetShadeSmooth", Mesh=box, **{"Shade Smooth": True})
    g.output("Geometry", "GEOMETRY", smooth)
    return g.finish()

def build_curbs(bend, block, mat):
    g = Graph("SS Road Curbs", description="Curbs of long stone blocks on both sides of the carriageway, each "
                                          "block slightly set, tilted and tinted on its own")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    sw = g.input("Street Width", "FLOAT", 4.0, min=1, max=20, subtype="DISTANCE", desc="Curb-to-curb width")
    cw = g.input("Curb Width", "FLOAT", 0.2, min=0.02, max=1, subtype="DISTANCE", desc="Curb stone width")
    ch = g.input("Curb Height", "FLOAT", 0.12, min=0, max=0.5, subtype="DISTANCE", desc="Curb top above the road")
    bl = g.input("Block Length", "FLOAT", 0.7, min=0.1, max=3, subtype="DISTANCE", desc="Curb block length")
    gap = g.input("Joint", "FLOAT", 0.02, min=0, max=0.2, subtype="DISTANCE", desc="Gap between blocks")
    var = g.input("Variation", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR",
                  desc="How unevenly the blocks are set (length, height, tilt, tint)")
    color = g.input("Curb Color", "COLOR", (0.3, 0.29, 0.27, 1), desc="Curb stone tint")
    with g.frame("One slot per block length, two sides (grid row = block, column = side)"):
        length = g.node("GeometryNodeCurveLength", Curve=curve)
        n = g.math("MAXIMUM", g.math("FLOOR", g.math("DIVIDE", length, bl)), 1.0)
        sx = g.math("MULTIPLY", g.math("SUBTRACT", n, 1.0), bl)
        sy = g.math("ADD", sw, cw)
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": sx, "Size Y": sy, "Vertices X": n, "Vertices Y": 2})
        p = g.separate(g.node("GeometryNodeInputPosition"))
        row = g.math("ROUND", g.math("DIVIDE", g.math("MULTIPLY_ADD", sx, 0.5, p["X"]), bl))
        side = g.math("SIGN", p["Y"])
        ident = g.math("MULTIPLY_ADD", row, 2.0, g.math("ADD", side, 1.0), label="block id")
        s = g.math("MULTIPLY_ADD", row, bl, g.math("MULTIPLY", bl, 0.5), label="s")
        d = p["Y"]
    with g.frame("Block shape, set a little unevenly: length, height, tilt"):
        hgt = g.math("ADD", ch, CURB_FOOT)
        shape = g.group(block, Length=g.math("SUBTRACT", bl, gap), Width=cw, Height=hgt, Radius=0.03)
        shape_m = g.node("GeometryNodeSetMaterial", Geometry=shape, Material=mat)
        lift = g.math("MULTIPLY", rand(g, -0.025, 0.025, ident, seed, 11), var)
        up = g.math("DIVIDE", g.math("ADD", hgt, lift), hgt)
        shorter = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", rand(g, 0.0, 0.08, ident, seed, 10), var))
        euler = g.combine(g.math("MULTIPLY", rand(g, -0.06, 0.06, ident, seed, 12), var),
                          g.math("MULTIPLY", rand(g, -0.02, 0.02, ident, seed, 13), var),
                          g.math("MULTIPLY", rand(g, -0.03, 0.03, ident, seed, 14), var))
        inst = g.node("GeometryNodeInstanceOnPoints", Points=grid["Mesh"], Instance=shape_m, Rotation=euler,
                      Scale=g.combine(shorter, 1.0, up))
    with g.frame("Per-block tint"):
        r1 = rand(g, 0.0, 1.0, ident, seed, 15, "ss_rand")
        bright = g.math("MULTIPLY_ADD", g.math("SUBTRACT", r1, 0.5), g.math("MULTIPLY", var, 0.35), 1.0)
        tint = g.vmath("SCALE", color, scale=bright)
        c1 = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "INSTANCE"},
                    Geometry=inst, Name="ss_color", Value=tint)
        c2 = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "INSTANCE"},
                    Geometry=c1, Name="ss_rand", Value=r1)
        slot = g.node("GeometryNodeSetPosition", Geometry=c2, Position=g.combine(s, d, -CURB_FOOT))
    with g.frame("Realize and bend onto the street (feet below the road surface)"):
        real = g.node("GeometryNodeRealizeInstances", Geometry=slot)
        bent = g.group(bend, Geometry=real, Curve=curve)
    g.output("Geometry", "GEOMETRY", bent)
    return g.finish()


def build_tuft():
    g = Graph("SS Road Tuft", description="One grass tuft of unit height: a few bent, tapering blades fanned "
                                          "around a point. ss_tip runs from 0 at the root to 1 at the tip")
    blades = g.input("Blades", "INT", 7, min=1, max=40, desc="Blades per tuft")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    with g.frame("One blade: a tapered strip bending over as it rises"):
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": 1.0, "Size Y": 1.0, "Vertices X": 2, "Vertices Y": 3})
        p = g.separate(g.node("GeometryNodeInputPosition"))
        t = g.math("ADD", p["Y"], 0.5, label="t (root to tip)")
        x = g.math("MULTIPLY", p["X"], g.math("MULTIPLY", g.math("SUBTRACT", 1.0, g.math("MULTIPLY", t, 0.9)),
                                               0.2))
        y = g.math("MULTIPLY", g.math("MULTIPLY", t, t), 0.3)
        blade = g.node("GeometryNodeSetPosition", Geometry=grid["Mesh"], Position=g.combine(x, y, t))
        tip = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                     Geometry=blade, Name="ss_tip", Value=t)
    with g.frame("Fan the blades: random spot, lean, turn and length"):
        idx = g.node("GeometryNodeInputIndex")
        spot = g.node("FunctionNodeRandomValue", props={"data_type": "FLOAT_VECTOR"}, Min=(-0.22, -0.22, 0.0),
                      Max=(0.22, 0.22, 0.0), ID=idx, Seed=seed)
        pts = g.node("GeometryNodePoints", Count=blades, Position=spot)
        euler = g.combine(rand(g, -0.45, 0.45, idx, seed, 1), rand(g, -0.45, 0.45, idx, seed, 2),
                          rand(g, 0.0, 6.283, idx, seed, 3))
        inst = g.node("GeometryNodeInstanceOnPoints", Points=pts, Instance=tip, Rotation=euler,
                      Scale=rand(g, 0.5, 1.0, idx, seed, 4))
        real = g.node("GeometryNodeRealizeInstances", Geometry=inst)
    g.output("Geometry", "GEOMETRY", real)
    return g.finish()


def build_grass(tuft, grass_mat, flower_mat):
    g = Graph("SS Road Grass", description="Grass tufts and small white flowers scattered over a ground mesh")
    ground = g.input("Mesh", "GEOMETRY", desc="Ground to grow on (world space)")
    seed = g.input("Seed", "INT", 0, desc="Random seed")
    density = g.input("Density", "FLOAT", 30.0, min=0, max=500, desc="Tufts per square unit")
    height = g.input("Height", "FLOAT", 0.2, min=0, max=1, subtype="DISTANCE", desc="Typical tuft height")
    fdensity = g.input("Flower Density", "FLOAT", 3.0, min=0, max=100, desc="Flowers per square unit")
    color = g.input("Grass Color", "COLOR", (0.12, 0.13, 0.04, 1), desc="Grass tint")
    fcolor = g.input("Flower Color", "COLOR", (0.85, 0.85, 0.8, 1), desc="Flower tint")
    with g.frame("Tufts: scattered, leaned, turned and sized at random"):
        pts = g.node("GeometryNodeDistributePointsOnFaces", props={"distribute_method": "RANDOM"}, Mesh=ground,
                     Density=density, Seed=seed)
        idx = g.node("GeometryNodeInputIndex")
        euler = g.combine(rand(g, -0.15, 0.15, idx, seed, 21), rand(g, -0.15, 0.15, idx, seed, 22),
                          rand(g, 0.0, 6.283, idx, seed, 23))
        sz = g.math("MULTIPLY", height, rand(g, 0.55, 1.35, idx, seed, 24))
        shape = g.group(tuft, Blades=7, Seed=seed)
        shape_m = g.node("GeometryNodeSetMaterial", Geometry=shape, Material=grass_mat)
        inst = g.node("GeometryNodeInstanceOnPoints", Points=pts["Points"], Instance=shape_m, Rotation=euler,
                      Scale=sz)
        r1 = rand(g, 0.0, 1.0, idx, seed, 25, "ss_rand")
        yellow = g.mix(rand(g, 0.0, 1.0, idx, seed, 26), color, g.vmath("MULTIPLY", color, (1.5, 1.25, 0.8)),
                       data_type="RGBA")
        tint = g.vmath("SCALE", yellow, scale=g.map_range(r1, 0.0, 1.0, 0.75, 1.2))
        tufts = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "INSTANCE"},
                       Geometry=inst, Name="ss_color", Value=tint)
    with g.frame("Flowers: tiny five-petal discs held up among the blades"):
        fp = g.node("GeometryNodeDistributePointsOnFaces", props={"distribute_method": "RANDOM"}, Mesh=ground,
                    Density=fdensity, Seed=g.math("ADD", seed, 77.0))
        fidx = g.node("GeometryNodeInputIndex")
        lift = g.node("GeometryNodeSetPosition", Geometry=fp["Points"],
                      Offset=g.combine(0.0, 0.0, g.math("MULTIPLY", height, rand(g, 0.25, 0.7, fidx, seed, 31))))
        disc = g.node("GeometryNodeMeshCircle", props={"fill_type": "NGON"}, Vertices=5, Radius=0.022)
        disc_m = g.node("GeometryNodeSetMaterial", Geometry=disc, Material=flower_mat)
        flowers = g.node("GeometryNodeInstanceOnPoints", Points=lift, Instance=disc_m,
                         Rotation=g.combine(rand(g, -0.4, 0.4, fidx, seed, 32), rand(g, -0.4, 0.4, fidx, seed, 33),
                                            rand(g, 0.0, 6.283, fidx, seed, 34)),
                         Scale=rand(g, 0.7, 1.3, fidx, seed, 35))
        fl = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "INSTANCE"},
                    Geometry=flowers, Name="ss_color", Value=fcolor)
        join = g.node("GeometryNodeJoinGeometry")
        g.connect(tufts, join.i("Geometry"))
        g.connect(fl, join.i("Geometry"))
    g.output("Geometry", "GEOMETRY", join)
    return g.finish()


def build():
    m = mats.build()
    bend = build_bend(frame.build())
    strip = build_strip(bend)
    cobbles = build_cobbles(bend, build_stone_shape())
    curbs = build_curbs(bend, build_curb_block(), m["curb"])
    grass = build_grass(build_tuft(), m["grass"], m["flower"])

    g = Graph(NAME, description="The street surface along the path: a cobbled carriageway, grassy gutters, "
                                "curbs of long stone blocks, a cobbled paving strip and a grass verge with "
                                "tufts and small white flowers up to the house fronts")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    seed = g.input("Seed", "INT", 0, desc="Changes every stone, block and tuft")
    sw = g.input("Street Width", "FLOAT", 4.0, min=1, max=20, subtype="DISTANCE", panel="Street",
                 desc="Curb-to-curb width")
    cw = g.input("Curb Width", "FLOAT", 0.2, min=0.02, max=1, subtype="DISTANCE", panel="Street",
                 desc="Width of the curb stones")
    ch = g.input("Curb Height", "FLOAT", 0.12, min=0, max=0.5, subtype="DISTANCE", panel="Street",
                 desc="Height of the curb above the road")
    vw = g.input("Verge Width", "FLOAT", 0.8, min=0, max=4, subtype="DISTANCE", panel="Street",
                 desc="Paved strip and grass between the curb and the house fronts")
    size = g.input("Stone Size", "FLOAT", 0.28, min=0.05, max=1, subtype="DISTANCE", panel="Cobbles",
                   desc="Typical cobble width across the street. Smaller stones = more instances")
    elong = g.input("Elongation", "FLOAT", 1.3, min=0.5, max=2.5, panel="Cobbles",
                    desc="Cobble width across the street divided by its length along it")
    var = g.input("Size Variation", "FLOAT", 0.25, min=0, max=0.6, subtype="FACTOR", panel="Cobbles",
                  desc="Random spread of cobble sizes")
    gap = g.input("Gap", "FLOAT", 0.02, min=0, max=0.2, subtype="DISTANCE", panel="Cobbles",
                  desc="Dark mortar gap between cobbles")
    jit = g.input("Jitter", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR", panel="Cobbles",
                  desc="How loosely cobbles sit in their courses")
    wobble = g.input("Irregularity", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR", panel="Cobbles",
                     desc="Lumpiness of each cobble's outline")
    dome = g.input("Dome Height", "FLOAT", 0.045, min=0, max=0.3, subtype="DISTANCE", panel="Cobbles",
                   desc="Height of a cobble's crown above the mortar")
    roundness = g.input("Roundness", "FLOAT", 0.35, min=0, max=1, subtype="FACTOR", panel="Cobbles",
                        desc="Flat-topped setts (0) to round pebbles (1)")
    detail = g.input("Detail", "INT", 7, min=3, max=16, panel="Cobbles",
                     desc="Mesh vertices across each cobble (the main mesh budget)")
    bl = g.input("Block Length", "FLOAT", 0.7, min=0.1, max=3, subtype="DISTANCE", panel="Curb",
                 desc="Length of one curb stone")
    cvar = g.input("Block Variation", "FLOAT", 0.5, min=0, max=1, subtype="FACTOR", panel="Curb",
                   desc="How unevenly curb stones are set and tinted")
    gutter = g.input("Gutter Width", "FLOAT", 0.35, min=0, max=2, subtype="DISTANCE", panel="Verge",
                     desc="Grass strip on the road side of each curb")
    paving = g.input("Paving Width", "FLOAT", 0.55, min=0, max=4, subtype="DISTANCE", panel="Verge",
                     desc="Cobbled strip behind each curb; the rest of the verge is grass")
    gdens = g.input("Grass Density", "FLOAT", 70.0, min=0, max=400, panel="Verge",
                    desc="Grass tufts per square unit on the gutters and verges")
    gheight = g.input("Grass Height", "FLOAT", 0.15, min=0, max=1, subtype="DISTANCE", panel="Verge",
                      desc="Typical tuft height")
    fdens = g.input("Flower Density", "FLOAT", 3.0, min=0, max=100, panel="Verge",
                    desc="Small white flowers per square unit in the grass")
    weeds = g.input("Weed Density", "FLOAT", 0.4, min=0, max=20, panel="Verge",
                    desc="Small tufts per square unit growing between the road cobbles")
    stone_c = g.input("Stone Color", "COLOR", (0.26, 0.205, 0.17, 1), panel="Palette", desc="Cobble tint")
    tintvar = g.input("Tint Variation", "FLOAT", 0.3, min=0, max=1, subtype="FACTOR", panel="Palette",
                      desc="Per-stone brightness and warmth spread")
    mortar_c = g.input("Mortar Color", "COLOR", (0.075, 0.06, 0.042, 1), panel="Palette",
                       desc="Mortar and dirt between the cobbles")
    curb_c = g.input("Curb Color", "COLOR", (0.3, 0.285, 0.265, 1), panel="Palette", desc="Curb stone tint")
    grass_c = g.input("Grass Color", "COLOR", (0.2, 0.2, 0.06, 1), panel="Palette", desc="Grass and turf tint")
    flower_c = g.input("Flower Color", "COLOR", (0.85, 0.85, 0.8, 1), panel="Palette", desc="Verge flower tint")

    with g.frame("Cross-section: lateral offsets of every band (left side; the right side mirrors it)"):
        half = g.math("MULTIPLY", sw, 0.5, label="curb face")
        road = g.math("MAXIMUM", g.math("SUBTRACT", half, gutter), 0.0, label="cobble edge")
        curb_out = g.math("ADD", half, cw, label="curb back")
        facade = g.math("ADD", curb_out, vw, label="facade line")
        pave_out = g.math("MINIMUM", g.math("ADD", curb_out, paving), facade, label="paving edge")
        under = g.math("ADD", facade, 0.4, label="ground under facades")
        pave_h = g.math("MULTIPLY", ch, 0.55, label="paving level")
        neg = lambda v: g.math("MULTIPLY", v, -1.0)
        turf_c = g.vmath("SCALE", grass_c, scale=0.9)

    def band(d0, d1, h, color, mat):
        return g.group(strip, Curve=curve, Inner=d0, Outer=d1, Height=h, Color=color, Material=mat)

    with g.frame("Ground bands: mortar under the cobbles, turf in the gutters and verges (and on under the houses)"):
        mortar = band(neg(road), road, 0.0, mortar_c, m["mortar"])
        gut_l = band(road, curb_out, 0.0, turf_c, m["turf"])
        gut_r = band(neg(curb_out), neg(road), 0.0, turf_c, m["turf"])
        pav_l = band(curb_out, pave_out, pave_h, mortar_c, m["mortar"])
        pav_r = band(neg(pave_out), neg(curb_out), pave_h, mortar_c, m["mortar"])
        ver_l = band(pave_out, facade, pave_h, turf_c, m["turf"])
        ver_r = band(neg(facade), neg(pave_out), pave_h, turf_c, m["turf"])
        hid_l = band(facade, under, pave_h, turf_c, m["turf"])
        hid_r = band(neg(under), neg(facade), pave_h, turf_c, m["turf"])

    stone_args = dict(Curve=curve, Seed=seed, **{"Stone Size": size, "Elongation": elong, "Size Variation": var,
                                                  "Gap": gap, "Jitter": jit, "Irregularity": wobble, "Dome Height": dome,
                                                  "Roundness": roundness, "Detail": detail,
                                                  "Stone Color": stone_c, "Tint Variation": tintvar,
                                                  "Material": m["cobble"]})
    with g.frame("Cobbles: the carriageway and the two paving strips"):
        c_road = g.group(cobbles, Inner=neg(road), Outer=road, Height=0.0, **stone_args)
        small = g.math("MULTIPLY", size, 0.75, label="paving stone size")
        c_pl = g.group(cobbles, Inner=curb_out, Outer=pave_out, Height=pave_h, **stone_args)
        g.connect(small, c_pl.i("Stone Size"))
        g.connect(g.math("ADD", seed, 101.0), c_pl.i("Seed"))
        c_pr = g.group(cobbles, Inner=neg(pave_out), Outer=neg(curb_out), Height=pave_h, **stone_args)
        g.connect(g.math("ADD", seed, 202.0), c_pr.i("Seed"))
        g.connect(small, c_pr.i("Stone Size"))

    with g.frame("Curbs"):
        c_curb = g.group(curbs, Curve=curve, Seed=seed, **{"Street Width": sw, "Curb Width": cw,
                                                           "Curb Height": ch, "Block Length": bl,
                                                           "Variation": cvar, "Curb Color": curb_c})

    with g.frame("Grass: thick in the gutters and verges, a few weeds between the cobbles"):
        verge = g.node("GeometryNodeJoinGeometry")
        for b in (gut_l, gut_r, ver_l, ver_r):
            g.connect(b, verge.i("Geometry"))
        green = g.group(grass, Mesh=verge, Seed=seed, Density=gdens, Height=gheight,
                        **{"Flower Density": fdens, "Grass Color": grass_c, "Flower Color": flower_c})
        weed = g.group(grass, Mesh=mortar, Seed=g.math("ADD", seed, 303.0), Density=weeds,
                       Height=g.math("MULTIPLY", gheight, 0.55),
                       **{"Flower Density": 0.0, "Grass Color": grass_c, "Flower Color": flower_c})

    with g.frame("Everything together"):
        join = g.node("GeometryNodeJoinGeometry")
        for part in (mortar, pav_l, pav_r, verge, hid_l, hid_r, c_road, c_pl, c_pr, c_curb, green, weed):
            g.connect(part, join.i("Geometry"))
    g.output("Geometry", "GEOMETRY", join)
    return g.finish()
