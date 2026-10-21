"""Rocks, grass clumps and flowers scattered over any terrain by slope and height.

    blender -b --factory-startup --python templates/surface_scatter.py -- --out out/surface_scatter.blend \
        [--render out/surface_scatter.png] [--width 960] [--samples 16] [--frame 1]

One modifier group, "Surface Scatter", dresses whatever mesh it sits on (or a terrain it generates itself):

    Surface Scatter Ground    the surface: the object's mesh, or a generated grid that rises into a hill; relief
                              noise along "up" (world Z, or radial for planets); stores scatter_up
    Surface Scatter Masks     slope and height per vertex -> scatter_slope, scatter_height, and two 0..1 weights:
                              scatter_meadow (gentle, low ground) and scatter_rock (steep or high ground)
    Surface Scatter Rocks     boulders and pebbles (displaced icospheres, NK Stone) by NK Scatter On Surface,
                              weighted by scatter_rock
    Surface Scatter Grass     NK Clumps of upright NK Leaf blades on the meadow faces
    Surface Scatter Flowers   NK Clumps of stemmed NK Blossom flowers on the meadow, one colour per clump
    Surface Scatter Bushes    NK Foliage Mound bushes, Poisson-spaced over the meadow

Everything is realized at the end so materials can read nk_color, nk_rand, nk_part and scatter_* attributes.

Scenes: "Meadow" (the generated terrain, the gallery shot) and "Scatter Transfer" (the same group on a lumpy
icosphere planet, Radial Up on). To dress your own mesh: add the modifier to it, switch Generate Terrain off, and
set Terrain > Relief to 0 if the mesh already has its shape.
"""
import argparse, math, pathlib, sys

SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import bpy
from nodekit import inspect
from nodekit import scene as S
from nodekit.graph import Graph, once
from library.shapes import leaf, blossom, foliage_mound, rod
from library.scatter import scatter_on_surface, clumps
from library.materials import make_material, attribute_tint, stone, lin
from library.post import haze_over_sky, soft_glow

NAME = "Surface Scatter"
TAU = 2.0 * math.pi


# ---- node idioms (python helpers, not groups) -----------------------------------------------------------------
def store(g, geo, name, value, dtype="FLOAT", domain="POINT"):
    return g.node("GeometryNodeStoreNamedAttribute", props={"data_type": dtype, "domain": domain},
                  Geometry=geo, Name=name, Value=value)["Geometry"]


def attr(g, name, dtype="FLOAT"):
    return g.node("GeometryNodeInputNamedAttribute", props={"data_type": dtype}, Name=name)["Attribute"]


def rand(g, lo, hi, seed, k, ident=None, dtype="FLOAT"):
    n = g.node("FunctionNodeRandomValue", props={"data_type": dtype}, Min=lo, Max=hi,
               Seed=g.math("ADD", seed, float(k)))
    if ident is not None:
        g.connect(ident, n.i("ID"))
    return n["Value"]


def switch(g, typ, cond, false=None, true=None):
    n = g.node("GeometryNodeSwitch", props={"input_type": typ}, Switch=cond)
    g.connect(false, n.i("False"))
    g.connect(true, n.i("True"))
    return n["Output"]


def join(g, *geos):
    j = g.node("GeometryNodeJoinGeometry")
    for x in reversed(geos):            # the multi-input socket stacks the newest link first
        g.connect(x, j.i("Geometry"))
    return j["Geometry"]


def smoothstep(g, v, a, b, label=None):
    return g.map_range(v, a, b, 0.0, 1.0, interp="SMOOTHSTEP", label=label)


def position(g):
    return g.node("GeometryNodeInputPosition")["Position"]


# ---- materials --------------------------------------------------------------------------------------------------
# Shader groups take their texture coordinate through a Vector input (make_material wires object coordinates) and
# per-piece variation through attributes, which make_material reads with "attr:<name>".
@once
def ground_paint():
    g = Graph("Surface Scatter Ground Paint", kind="SHADER",
              description="Ground colour by slope: mottled grass and dry patches on the flat, bare earth on banks, "
                          "NK Stone rock on the steepest faces (slope from the scatter_slope attribute)")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True, desc="Texture coordinate in metres")
    slope = g.input("Slope", "FLOAT", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                    desc="0 flat, 1 vertical (wire the scatter_slope attribute here)")
    grass = g.input("Grass Color", "COLOR", lin("#435F20"), desc="Ground colour under the grass")
    dry = g.input("Dry Color", "COLOR", lin("#9A934A"), desc="Sun-dried patches mixed into the grass")
    earth = g.input("Earth Color", "COLOR", lin("#7F6446"), desc="Bare earth on banks")
    rockc = g.input("Rock Color", "COLOR", lin("#8E877C"), desc="Rock on the steepest faces")
    with g.frame("Flat ground: grass mottled with dry patches"):
        n = g.node("ShaderNodeTexNoise", Vector=vec, Scale=0.12, Detail=4.0, Roughness=0.6)["Factor"]
        fine = g.node("ShaderNodeTexNoise", Vector=vec, Scale=3.0, Detail=2.0)["Factor"]
        patch = g.map_range(g.math("ADD", n, g.math("MULTIPLY", fine, 0.25)), 0.55, 0.8, 0.0, 1.0)
        flat = g.mix(patch, grass, dry, data_type="RGBA")["Result"]
        flat = g.vmath("SCALE", flat, scale=g.math("ADD", 0.8, g.math("MULTIPLY", fine, 0.4)))["Vector"]
    with g.frame("Banks: earth from a noisy slope threshold; cliffs: stone"):
        wobble = g.math("MULTIPLY", g.math("SUBTRACT", fine, 0.5), 0.2)
        s = g.math("ADD", slope, wobble)
        bank = g.map_range(s, 0.36, 0.5, 0.0, 1.0, interp="SMOOTHSTEP")
        cliff = g.map_range(s, 0.55, 0.7, 0.0, 1.0, interp="SMOOTHSTEP")
        rock = g.group(stone(), Vector=vec, Color=rockc, **{"Stone Scale": 1.2, "Mortar Width": 0.03, "Bump": 0.6})
        col = g.mix(bank, flat, earth, data_type="RGBA")["Result"]
        col = g.mix(cliff, col, rock["Color"], data_type="RGBA")["Result"]
        clumpy = g.node("ShaderNodeBump", Strength=0.35, Distance=0.05, Height=fine)["Normal"]
        nrm = g.mix(cliff, clumpy, rock["Normal"], data_type="VECTOR")["Result"]
        rough = g.map_range(cliff, 0.0, 1.0, 0.95, 0.8)
    g.output("Color", "COLOR", col, desc="Ground colour")
    g.output("Roughness", "FLOAT", rough, desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Normal (stone bump on cliffs)")
    return g.finish()


@once
def rock_paint():
    g = Graph("Surface Scatter Rock Paint", kind="SHADER",
              description="Weathered rock: NK Stone cells as cracks and facets, tinted per rock by NK Attribute "
                          "Tint (nk_rand), with moss on the faces that look up")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True, desc="Texture coordinate in metres")
    base = g.input("Rock Color", "COLOR", lin("#7C766C"), desc="Average rock colour")
    moss_c = g.input("Moss Color", "COLOR", lin("#4E6524"), desc="Moss on the tops of rocks")
    moss = g.input("Moss", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR", desc="How much of the tops is mossy")
    with g.frame("Per-rock tint, then stone cells (wide cells, thin joints read as cracks)"):
        tint = g.group(attribute_tint(), **{"Base Color": base, "Value Variation": 0.35, "Hue Variation": 0.03})
        st = g.group(stone(), Vector=vec, Color=tint["Color"],
                     **{"Stone Scale": 2.2, "Mortar Width": 0.025, "Variation": 0.25, "Edge Wear": 0.7, "Bump": 0.7})
    with g.frame("Moss where the normal points up, broken by noise"):
        nz = g.separate(g.node("ShaderNodeNewGeometry")["Normal"])["Z"]
        nn = g.node("ShaderNodeTexNoise", Vector=vec, Scale=4.0, Detail=3.0)["Factor"]
        m = g.map_range(g.math("ADD", nz, g.math("MULTIPLY", nn, 0.6)), 1.25, 1.45, 0.0, 1.0, interp="SMOOTHSTEP")
        m = g.math("MULTIPLY", m, moss)
        col = g.mix(m, st["Color"], moss_c, data_type="RGBA")["Result"]
        rough = g.mix(m, st["Roughness"], 0.95)["Result"]
    g.output("Color", "COLOR", col, desc="Rock colour")
    g.output("Roughness", "FLOAT", rough, desc="Roughness")
    g.output("Normal", "VECTOR", st["Normal"], desc="Bumped normal")
    return g.finish()


@once
def blade_paint():
    g = Graph("Surface Scatter Blade Paint", kind="SHADER",
              description="Grass blade: dark at the root, light at the tip (scatter_tip), varied per blade by NK "
                          "Attribute Tint (nk_rand), with a little translucency")
    tip = g.input("Tip", "FLOAT", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                  desc="0 at the root, 1 at the tip (wire the scatter_tip attribute here)")
    root_c = g.input("Root Color", "COLOR", lin("#36521C"), desc="Blade colour at the root")
    tip_c = g.input("Tip Color", "COLOR", lin("#A4B04A"), desc="Blade colour at the tip")
    with g.frame("Root-to-tip gradient, then per-blade value and hue variation"):
        c = g.mix(g.math("POWER", tip, 1.4), root_c, tip_c, data_type="RGBA")["Result"]
        # Attribute Weight 0: blades and stems ignore nk_color (flower stems carry their patch's colour)
        tint = g.group(attribute_tint(), **{"Base Color": c, "Attribute Weight": 0.0, "Value Variation": 0.35,
                                            "Hue Variation": 0.04, "Roughness": 0.55})
    g.output("Color", "COLOR", tint["Color"], desc="Blade colour")
    g.output("Roughness", "FLOAT", tint["Roughness"], desc="Roughness")
    g.output("Subsurface", "FLOAT", 0.15, desc="A little light through the blades")
    return g.finish()


@once
def petal_paint():
    g = Graph("Surface Scatter Petal Paint", kind="SHADER",
              description="Petals and leaves painted by nk_color (NK Attribute Tint), with the flower centres "
                          "(nk_part = 1) in Centre Color")
    part = g.input("Part", "FLOAT", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                   desc="1 on blossom centres (wire the nk_part attribute here)")
    base = g.input("Base Color", "COLOR", lin("#E8E0D0"), desc="Colour where nk_color is missing")
    centre = g.input("Centre Color", "COLOR", lin("#E8B520"), desc="Colour of the flower centres")
    with g.frame("nk_color per instance, then centres"):
        tint = g.group(attribute_tint(), **{"Base Color": base, "Value Variation": 0.15, "Roughness": 0.5})
        col = g.mix(part, tint["Color"], centre, data_type="RGBA")["Result"]
    g.output("Color", "COLOR", col, desc="Petal or leaf colour")
    g.output("Roughness", "FLOAT", tint["Roughness"], desc="Roughness")
    g.output("Subsurface", "FLOAT", 0.2, desc="Soft light through petals and leaves")
    return g.finish()


def materials():
    """Every material the scatter uses, keyed by part."""
    return {
        "ground": make_material("Surface Scatter Ground", ground_paint(), Slope="attr:scatter_slope"),
        "rock": make_material("Surface Scatter Rock", rock_paint()),
        "blade": make_material("Surface Scatter Blade", blade_paint(), Tip="attr:scatter_tip"),
        "petal": make_material("Surface Scatter Petal", petal_paint(), Part="attr:nk_part"),
    }


# ---- Surface Scatter Ground -------------------------------------------------------------------------------------
@once
def ground(mats):
    g = Graph("Surface Scatter Ground", description="The surface to dress: the input mesh, or a generated grid "
                                                    "that rises into a hill at the back (+Y). Relief noise moves it "
                                                    "along 'up' (world Z, or radial from the centre for planets); "
                                                    "up is stored as scatter_up for the masks")
    surf = g.input("Surface", "GEOMETRY", desc="Mesh to dress (used when Generate Terrain is off)")
    gen = g.input("Generate Terrain", "BOOL", True, desc="Build a terrain grid instead of using the input mesh")
    size = g.input("Terrain Size", "FLOAT", 56.0, min=2.0, max=1000.0, subtype="DISTANCE",
                   desc="Side of the generated terrain square")
    res = g.input("Resolution", "INT", 220, min=8, max=1000, desc="Generated grid vertices along each side")
    hill = g.input("Hill Height", "FLOAT", 13.0, min=0.0, max=200.0, subtype="DISTANCE",
                   desc="How high the generated terrain rises toward the back (+Y)")
    relief = g.input("Relief", "FLOAT", 1.4, min=0.0, max=50.0, subtype="DISTANCE",
                     desc="Noise displacement along up, either way (0 keeps the input shape)")
    feat = g.input("Feature Size", "FLOAT", 8.0, min=0.1, max=500.0, subtype="DISTANCE",
                   desc="Size of the bumps and hollows")
    radial = g.input("Radial Up", "BOOL", False,
                     desc="Up points away from the mesh centre (planets, rocks, heads) instead of world Z")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed of the relief")
    with g.frame("Generated terrain: a grid rising into a lumpy hill toward +Y"):
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": size, "Size Y": size, "Vertices X": res,
                                                  "Vertices Y": res})["Mesh"]
        y = g.separate(position(g))["Y"]
        rise = smoothstep(g, y, g.math("MULTIPLY", size, -0.1), g.math("MULTIPLY", size, 0.45), label="rise")
        lumps = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Vector=position(g),
                       W=g.math("ADD", seed, 7.0), Scale=g.math("DIVIDE", 0.5, feat), Detail=2.0)["Factor"]
        z = g.math("MULTIPLY", g.math("MULTIPLY", hill, g.math("POWER", rise, 1.6)),
                   g.math("ADD", 0.2, g.math("MULTIPLY", lumps, 1.6)))
        grid = g.node("GeometryNodeSetPosition", Geometry=grid, Offset=g.combine(0.0, 0.0, z))["Geometry"]
        grid = g.node("GeometryNodeSetShadeSmooth", Mesh=grid)["Mesh"]
        grid = g.node("GeometryNodeSetMaterial", Geometry=grid, Material=mats["ground"])["Geometry"]
        mesh = switch(g, "GEOMETRY", gen, surf, grid)
    with g.frame("Up: world Z, or away from the bounding-box centre"):
        bb = g.node("GeometryNodeBoundBox", Geometry=mesh)
        centre = g.vmath("SCALE", g.vmath("ADD", bb["Min"], bb["Max"]), scale=0.5)
        out = g.vmath("NORMALIZE", g.vmath("SUBTRACT", position(g), centre))
        up = switch(g, "VECTOR", radial, (0.0, 0.0, 1.0), out)
        mesh = store(g, mesh, "scatter_up", up, "FLOAT_VECTOR")
    with g.frame("Relief: fractal noise moves every vertex along up"):
        n = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Vector=position(g),
                   W=g.math("MULTIPLY", seed, 1.37), Scale=g.math("DIVIDE", 1.0, feat), Detail=4.0,
                   Roughness=0.55)["Factor"]
        d = g.math("MULTIPLY", g.math("SUBTRACT", n, 0.5), g.math("MULTIPLY", relief, 2.0))
        off = g.vmath("SCALE", attr(g, "scatter_up", "FLOAT_VECTOR"), scale=d)
        mesh = g.node("GeometryNodeSetPosition", Geometry=mesh, Offset=off)["Geometry"]
    g.output("Surface", "GEOMETRY", mesh, desc="The surface with scatter_up")
    return g.finish()


# ---- Surface Scatter Masks --------------------------------------------------------------------------------------
@once
def masks():
    g = Graph("Surface Scatter Masks", description="Slope (angle between the normal and scatter_up) and height "
                                                   "(along up, 0 lowest to 1 highest) per vertex, and two weights: "
                                                   "scatter_meadow (flatter than Slope Limit and below Meadow "
                                                   "Height) and scatter_rock (steeper than the limit, above Rock "
                                                   "Height, plus Rock Base everywhere)")
    surf = g.input("Surface", "GEOMETRY", desc="Surface with scatter_up (Surface Scatter Ground)")
    limit = g.input("Slope Limit", "FLOAT", math.radians(24), min=0.0, max=math.pi / 2, subtype="ANGLE",
                    desc="Steeper than this, grass and flowers give way to earth and rocks")
    soft = g.input("Mask Softness", "FLOAT", math.radians(6), min=0.001, max=math.pi / 4, subtype="ANGLE",
                   desc="Blend width around Slope Limit")
    meadow_h = g.input("Meadow Height", "FLOAT", 0.75, min=0.0, max=1.0, subtype="FACTOR",
                       desc="Meadow plants grow below this share of the height range")
    rock_h = g.input("Rock Height", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR",
                     desc="Rocks gather above this share of the height range")
    rock_base = g.input("Rock Base", "FLOAT", 0.05, min=0.0, max=1.0, subtype="FACTOR",
                        desc="Rock weight everywhere, so a few stones lie in the meadow too")
    with g.frame("Slope: angle between the vertex normal and up"):
        up = attr(g, "scatter_up", "FLOAT_VECTOR")
        cosang = g.vmath("DOT_PRODUCT", g.node("GeometryNodeInputNormal")["Normal"], up)["Value"]
        ang = g.math("ARCCOSINE", g.math("MINIMUM", g.math("MAXIMUM", cosang, -1.0), 1.0))
        surf = store(g, surf, "scatter_slope", g.math("DIVIDE", ang, math.pi / 2))
    with g.frame("Height: distance along up from the centre, normalised to 0..1 over the surface"):
        bb = g.node("GeometryNodeBoundBox", Geometry=surf)
        centre = g.vmath("SCALE", g.vmath("ADD", bb["Min"], bb["Max"]), scale=0.5)
        hraw = g.vmath("DOT_PRODUCT", g.vmath("SUBTRACT", position(g), centre), up)["Value"]
        surf = store(g, surf, "scatter_hraw", hraw)
        stat = g.node("GeometryNodeAttributeStatistic", props={"data_type": "FLOAT", "domain": "POINT"},
                      Geometry=surf, Attribute=attr(g, "scatter_hraw"))
        span = g.math("MAXIMUM", g.math("SUBTRACT", stat["Max"], stat["Min"]), 1e-4)
        h = g.math("DIVIDE", g.math("SUBTRACT", attr(g, "scatter_hraw"), stat["Min"]), span)
        surf = store(g, surf, "scatter_height", h)
    with g.frame("Weights: meadow where gentle and low, rock where steep or high"):
        a = g.math("MULTIPLY", attr(g, "scatter_slope"), math.pi / 2)
        gentle = g.math("SUBTRACT", 1.0, smoothstep(g, a, g.math("SUBTRACT", limit, soft),
                                                    g.math("ADD", limit, soft), label="steep"))
        hh = attr(g, "scatter_height")
        low = g.math("SUBTRACT", 1.0, smoothstep(g, hh, g.math("SUBTRACT", meadow_h, 0.1),
                                                 g.math("ADD", meadow_h, 0.1), label="high"))
        surf = store(g, surf, "scatter_meadow", g.math("MULTIPLY", gentle, low))
        high = smoothstep(g, hh, g.math("SUBTRACT", rock_h, 0.1), g.math("ADD", rock_h, 0.25), label="rocky top")
        rock = g.math("ADD", g.math("ADD", rock_base, g.math("SUBTRACT", 1.0, gentle)), high, clamp=True)
        surf = store(g, surf, "scatter_rock", rock)
        surf = g.node("GeometryNodeRemoveAttribute", Geometry=surf, Name="scatter_hraw")["Geometry"]
    g.output("Surface", "GEOMETRY", surf, desc="Surface with scatter_slope, scatter_height, scatter_meadow, "
                                               "scatter_rock")
    return g.finish()


# ---- Surface Scatter Rock (one rock mesh) ------------------------------------------------------------------------
@once
def rock(mats):
    g = Graph("Surface Scatter Rock", description="One rock of about 1 m: an icosphere displaced by two octaves of "
                                                  "noise along its normals, squashed, sunk a third into the ground "
                                                  "(origin at ground level), NK Stone material")
    lump = g.input("Lumpiness", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR",
                   desc="How far the noise pushes the surface in and out")
    flat = g.input("Flatness", "FLOAT", 0.5, min=0.2, max=1.0, subtype="FACTOR", desc="Height / width of the rock")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Shape seed")
    with g.frame("Icosphere pushed in and out along its normals by coarse and fine noise"):
        ico = g.node("GeometryNodeMeshIcoSphere", Radius=0.5, Subdivisions=4)["Mesh"]
        p = position(g)
        big = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Vector=p, W=seed, Scale=1.6,
                     Detail=1.0)["Factor"]
        small = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "4D"}, Vector=p, W=seed, Scale=5.0,
                       Detail=3.0)["Factor"]
        d = g.math("ADD", g.math("SUBTRACT", big, 0.5), g.math("MULTIPLY", g.math("SUBTRACT", small, 0.5), 0.35))
        off = g.vmath("SCALE", g.node("GeometryNodeInputNormal")["Normal"], scale=g.math("MULTIPLY", d, lump))
        rk = g.node("GeometryNodeSetPosition", Geometry=ico, Offset=off)["Geometry"]
    with g.frame("Squash, sink a third below the origin, shade smooth, stone material"):
        rk = g.node("GeometryNodeTransform", Geometry=rk, Translation=g.combine(0.0, 0.0, g.math("MULTIPLY", flat, 0.18)),
                    Scale=g.combine(1.0, 0.85, flat))["Geometry"]
        rk = g.node("GeometryNodeSetShadeSmooth", Mesh=rk)["Mesh"]
        rk = g.node("GeometryNodeSetMaterial", Geometry=rk, Material=mats["rock"])["Geometry"]
    g.output("Mesh", "GEOMETRY", rk, desc="The rock")
    return g.finish()


# ---- Surface Scatter Rocks --------------------------------------------------------------------------------------
@once
def rocks(mats):
    rk, sc = rock(mats), scatter_on_surface()
    g = Graph("Surface Scatter Rocks", description="Boulders (Poisson-spaced) and pebbles scattered by NK Scatter "
                                                   "On Surface where scatter_rock allows; each rock is spun, tilted "
                                                   "and stretched at random so one shape reads as many")
    surf = g.input("Surface", "GEOMETRY", desc="Surface with scatter_rock (Surface Scatter Masks)")
    dens = g.input("Rock Density", "FLOAT", 0.09, min=0.0, max=100.0, desc="Boulders per square metre at full weight")
    pdens = g.input("Pebble Density", "FLOAT", 0.6, min=0.0, max=1000.0, desc="Pebbles per square metre at full weight")
    smin = g.input("Rock Size Min", "FLOAT", 0.4, min=0.01, max=50.0, subtype="DISTANCE", desc="Smallest boulder")
    smax = g.input("Rock Size Max", "FLOAT", 1.4, min=0.01, max=50.0, subtype="DISTANCE", desc="Largest boulder")
    lump = g.input("Lumpiness", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR", desc="Rock surface noise")
    align = g.input("Align", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR",
                    desc="0 rocks stand on world Z, 1 they lie along the surface")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    with g.frame("The rock shape"):
        shape = g.group(rk, Lumpiness=lump, Seed=seed)["Mesh"]
    with g.frame("Boulders: Poisson-spaced so they never overlap"):
        b = g.group(sc, Surface=surf, Instance=shape, Density=dens, Seed=seed, Align=align,
                    **{"Min Distance": g.math("MULTIPLY", smax, 0.9), "Mask Attribute": "scatter_rock",
                       "Random Tilt": 0.25, "Scale Min": smin, "Scale Max": smax})["Instances"]
    with g.frame("Pebbles: many small stones, random spacing"):
        p = g.group(sc, Surface=surf, Instance=shape, Density=pdens, Seed=g.math("ADD", seed, 17.0), Align=1.0,
                    **{"Mask Attribute": "scatter_rock", "Random Tilt": 0.5, "Scale Min": 0.06,
                       "Scale Max": 0.18})["Instances"]
    with g.frame("Stretch each rock differently along its own axes"):
        both = join(g, b, p)
        idx = g.node("GeometryNodeInputIndex")["Index"]
        stretch = g.combine(rand(g, 0.75, 1.3, seed, 31, idx), rand(g, 0.75, 1.3, seed, 32, idx),
                            rand(g, 0.7, 1.2, seed, 33, idx))
        both = g.node("GeometryNodeScaleInstances", Instances=both, Scale=stretch)["Instances"]
    g.output("Instances", "GEOMETRY", both, desc="Rock instances with nk_rand")
    return g.finish()


# ---- Surface Scatter Grass ---------------------------------------------------------------------------------------
@once
def grass(mats):
    lf, cl = leaf(), clumps()
    g = Graph("Surface Scatter Grass", description="Tufts of grass: NK Clumps of single blades (an NK Leaf stood "
                                                   "upright, curling over) splayed out from each tuft's centre. "
                                                   "Blades store scatter_tip (0 root, 1 tip) for the gradient")
    surf = g.input("Surface", "GEOMETRY", desc="Faces to grow on (the meadow part of the surface)")
    dens = g.input("Tuft Density", "FLOAT", 10.0, min=0.0, max=1000.0, desc="Tufts per square metre")
    bmin = g.input("Blades Min", "INT", 18, min=1, max=500, desc="Fewest blades per tuft")
    bmax = g.input("Blades Max", "INT", 36, min=1, max=500, desc="Most blades per tuft")
    rad = g.input("Tuft Radius", "FLOAT", 0.12, min=0.0, max=10.0, subtype="DISTANCE", desc="Spread of a tuft")
    height = g.input("Blade Height", "FLOAT", 0.32, min=0.01, max=5.0, subtype="DISTANCE", desc="Blade length")
    align = g.input("Align", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR",
                    desc="0 blades grow up world Z, 1 along the surface normal")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    with g.frame("One blade: a narrow NK Leaf, stood up (tip to +Z), curling over; scatter_tip along it"):
        blade = g.group(lf, Length=height, Width=0.1, Curl=0.35, Fold=0.4, Resolution=5,
                        **{"Widest At": 0.15})["Mesh"]
        blade = g.node("GeometryNodeTransform", Geometry=blade, Rotation=(0.0, -math.pi / 2, 0.0))["Geometry"]
        tip = g.math("DIVIDE", g.separate(position(g))["Z"], height, clamp=True)
        blade = store(g, blade, "scatter_tip", tip)
        blade = g.node("GeometryNodeSetMaterial", Geometry=blade, Material=mats["blade"])["Geometry"]
    with g.frame("Tufts: clumps of blades leaning out from the centre"):
        tufts = g.group(cl, Surface=surf, Instance=blade, Seed=seed, Align=align,
                        **{"Clump Density": dens, "Clump Radius": rad, "Members Min": bmin, "Members Max": bmax,
                           "Concentration": 0.8, "Random Tilt": 0.45, "Scale Min": 0.55, "Scale Max": 1.25,
                           "Falloff": 0.5})["Instances"]
    g.output("Instances", "GEOMETRY", tufts, desc="Blade instances with nk_rand")
    return g.finish()


# ---- Surface Scatter Flower (one stemmed flower) -------------------------------------------------------------------
@once
def flower(mats):
    rd, bl, lf = rod(), blossom(), leaf()
    g = Graph("Surface Scatter Flower", description="One meadow flower: an NK Rod stem with an NK Leaf at its foot "
                                                    "and an NK Blossom on top, nodding a little toward +X")
    stem_h = g.input("Stem Height", "FLOAT", 0.35, min=0.01, max=5.0, subtype="DISTANCE", desc="Stem length")
    size = g.input("Flower Size", "FLOAT", 0.07, min=0.005, max=1.0, subtype="DISTANCE", desc="Blossom diameter")
    petals = g.input("Petals", "INT", 6, min=1, max=64, desc="Petals per blossom")
    with g.frame("Stem and a leaf (blade material)"):
        top = g.combine(g.math("MULTIPLY", stem_h, 0.12), 0.0, stem_h)
        stem = g.group(rd, End=top, Radius=0.0035, Resolution=5)["Mesh"]
        lv = g.group(lf, Length=g.math("MULTIPLY", stem_h, 0.4), Width=0.25, Curl=0.3, Resolution=4)["Mesh"]
        lv = g.node("GeometryNodeTransform", Geometry=lv, Rotation=(0.0, -0.9, 2.0))["Geometry"]
        green = g.node("GeometryNodeSetMaterial", Geometry=join(g, stem, lv), Material=mats["blade"])["Geometry"]
        green = store(g, green, "scatter_tip", g.math("DIVIDE", g.separate(position(g))["Z"], stem_h, clamp=True))
    with g.frame("Blossom on top, facing up and a little forward (petal material)"):
        head = g.group(bl, Size=size, Petals=petals, Cup=0.25, **{"Petal Width": 0.55, "Centre Size": 0.32})["Mesh"]
        head = g.node("GeometryNodeTransform", Geometry=head, Translation=top, Rotation=(0.0, 0.35, 0.0))["Geometry"]
        head = g.node("GeometryNodeSetMaterial", Geometry=head, Material=mats["petal"])["Geometry"]
    g.output("Mesh", "GEOMETRY", join(g, green, head), desc="The flower")
    return g.finish()


# ---- Surface Scatter Flowers ---------------------------------------------------------------------------------------
@once
def flowers(mats):
    fl, cl = flower(mats), clumps()
    g = Graph("Surface Scatter Flowers", description="Patches of flowers: NK Clumps of stemmed blossoms, every "
                                                     "flower in a clump the same colour (one of three, chosen per "
                                                     "clump), stored as nk_color")
    surf = g.input("Surface", "GEOMETRY", desc="Faces to grow on (the meadow part of the surface)")
    dens = g.input("Patch Density", "FLOAT", 0.5, min=0.0, max=100.0, desc="Flower patches per square metre")
    rad = g.input("Patch Radius", "FLOAT", 0.6, min=0.0, max=20.0, subtype="DISTANCE", desc="Spread of a patch")
    nmin = g.input("Flowers Min", "INT", 6, min=1, max=500, desc="Fewest flowers per patch")
    nmax = g.input("Flowers Max", "INT", 28, min=1, max=500, desc="Most flowers per patch")
    size = g.input("Flower Size", "FLOAT", 0.12, min=0.005, max=1.0, subtype="DISTANCE", desc="Blossom diameter")
    stem_h = g.input("Stem Height", "FLOAT", 0.45, min=0.01, max=5.0, subtype="DISTANCE", desc="Stem length")
    cols = [g.input(n, "COLOR", lin(h), desc=d) for n, h, d in (
        ("Flower Color A", "#F2EFE6", "White daisies"), ("Flower Color B", "#E4B92A", "Yellow buttercups"),
        ("Flower Color C", "#C2436A", "Pink campion"))]
    share = g.input("Color Shares", "VECTOR", (0.45, 0.35, 0.2), subtype="XYZ",
                    desc="Relative share of patches in colours A, B and C")
    align = g.input("Align", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR",
                    desc="0 flowers grow up world Z, 1 along the surface normal")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    with g.frame("The flower"):
        one = g.group(fl, **{"Stem Height": stem_h, "Flower Size": size})["Mesh"]
    with g.frame("Patches of flowers"):
        cl_n = g.group(cl, Surface=surf, Instance=one, Seed=seed, Align=align,
                       **{"Clump Density": dens, "Clump Radius": rad, "Members Min": nmin, "Members Max": nmax,
                          "Concentration": 0.7, "Random Tilt": 0.2, "Scale Min": 0.7, "Scale Max": 1.2,
                          "Falloff": 0.3})
        inst = cl_n["Instances"]
    with g.frame("One colour per patch: pick A, B or C by the shares, from a random value per clump"):
        sh = g.separate(share)
        total = g.math("MAXIMUM", g.math("ADD", g.math("ADD", sh["X"], sh["Y"]), sh["Z"]), 1e-4)
        r = g.math("MULTIPLY", rand(g, 0.0, 1.0, seed, 41, attr(g, "nk_clump", "INT")), total)
        pick = g.math("ADD", g.math("GREATER_THAN", r, sh["X"]),
                      g.math("GREATER_THAN", r, g.math("ADD", sh["X"], sh["Y"])))
        sw = g.node("GeometryNodeIndexSwitch", props={"data_type": "RGBA"})
        sw.b.index_switch_items.new()
        g.connect(pick, sw.i("Index"))
        for k, c in enumerate(cols):
            g.connect(c, sw.i(str(k)))
        tone = g.vmath("SCALE", sw["Output"], scale=rand(g, 0.85, 1.1, seed, 42, attr(g, "nk_clump", "INT")))
        inst = store(g, inst, "nk_color", tone, "FLOAT_COLOR", "INSTANCE")
    g.output("Instances", "GEOMETRY", inst, desc="Flower instances with nk_color and nk_rand")
    return g.finish()


# ---- Surface Scatter Bushes ----------------------------------------------------------------------------------------
@once
def bushes(mats):
    fm, sc = foliage_mound(), scatter_on_surface()
    g = Graph("Surface Scatter Bushes", description="Round bushes: one NK Foliage Mound (a squashed icosphere "
                                                    "clothed in leaves and a few blossoms) scattered Poisson-spaced "
                                                    "by NK Scatter On Surface where scatter_meadow allows")
    surf = g.input("Surface", "GEOMETRY", desc="Surface with scatter_meadow")
    dens = g.input("Bush Density", "FLOAT", 0.006, min=0.0, max=100.0, desc="Bushes per square metre at full weight")
    size = g.input("Bush Size", "FLOAT", 0.8, min=0.05, max=20.0, subtype="DISTANCE", desc="Bush radius")
    bd = g.input("Bush Blossoms", "FLOAT", 14.0, min=0.0, max=1000.0, desc="Blossoms per square metre of bush")
    leaf_c = g.input("Leaf Color", "COLOR", lin("#557A2C"), desc="Bush leaf colour")
    bloom_c = g.input("Bush Blossom Color", "COLOR", lin("#F0E6EE"), desc="Bush blossom colour")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    with g.frame("One bush: a squashed icosphere sitting on the ground, clothed in leaves and blossoms"):
        mound = g.node("GeometryNodeMeshIcoSphere", Radius=size, Subdivisions=3)["Mesh"]
        mound = g.node("GeometryNodeTransform", Geometry=mound, Scale=(1.0, 1.0, 0.75),
                       Translation=g.combine(0.0, 0.0, g.math("MULTIPLY", size, 0.45)))["Geometry"]
        bush = g.group(fm, Mound=mound, Seed=seed,
                       **{"Leaf Density": 180.0, "Leaf Size": g.math("MULTIPLY", size, 0.16), "Leaf Color": leaf_c,
                          "Leaf Material": mats["petal"], "Blossom Density": bd,
                          "Blossom Size": g.math("MULTIPLY", size, 0.07), "Blossom Color A": bloom_c,
                          "Blossom Color B": lin("#F4D35E"), "Color B Share": 0.15,
                          "Blossom Material": mats["petal"], "Underside": -0.3})["Geometry"]
    with g.frame("Bushes on the meadow, never closer than three radii"):
        out = g.group(sc, Surface=surf, Instance=bush, Density=dens, Seed=g.math("ADD", seed, 5.0), Align=0.0,
                      **{"Min Distance": g.math("MULTIPLY", size, 3.0), "Mask Attribute": "scatter_meadow",
                         "Scale Min": 0.6, "Scale Max": 1.3})["Instances"]
    g.output("Instances", "GEOMETRY", out, desc="Bush instances (nested leaf and blossom instances)")
    return g.finish()


# ---- Surface Scatter (the modifier) ----------------------------------------------------------------------------------
def build():
    mats = materials()
    parts = {"ground": ground(mats), "masks": masks(), "rocks": rocks(mats), "grass": grass(mats),
             "flowers": flowers(mats), "bushes": bushes(mats)}
    g = Graph(NAME, modifier=True,
              description="Dress any mesh (or a generated terrain) with rocks, grass tufts, flower patches and "
                          "bushes, placed by slope and height: plants on gentle low ground, rocks on steep or high "
                          "ground. Everything is realized so materials read the scatter attributes")
    surf = g.input("Surface", "GEOMETRY", desc="The object's mesh (ignored while Generate Terrain is on)")
    # Primary: macro controls, each scaling several detailed ones (neutral values reproduce the defaults)
    dens = g.input("Density", "FLOAT", 1.0, min=0.0, max=3.0, panel="Primary",
                   desc="Scales every density: grass, flowers, bushes and rocks")
    rock_amt = g.input("Rock Amount", "FLOAT", 1.0, min=0.0, max=4.0, panel="Primary",
                       desc="Scales boulder and pebble density (0 no rocks)")
    flower_amt = g.input("Flower Amount", "FLOAT", 1.0, min=0.0, max=4.0, panel="Primary",
                         desc="Scales flower patch density and bush blossoms (0 no flowers)")
    limit = g.input("Slope Limit", "FLOAT", math.radians(24), min=0.0, max=math.pi / 2, subtype="ANGLE",
                    panel="Primary", desc="Steeper than this, plants give way to earth and rocks")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, panel="Primary", desc="Changes every random choice")

    # Detailed panels: every other input of the parts, forwarded with its own name, range and description
    ui = {"Seed": seed, "Slope Limit": limit}
    skip = {"Surface", "Seed", "Slope Limit", "Align"}
    for label, key in (("Terrain", "ground"), ("Masks", "masks"), ("Rocks", "rocks"), ("Grass", "grass"),
                       ("Flowers", "flowers"), ("Bushes", "bushes")):
        for it in parts[key].interface.items_tree:
            if it.item_type != "SOCKET" or it.in_out != "INPUT" or it.name in skip or it.name in ui:
                continue
            stype = {"NodeSocketFloat": "FLOAT", "NodeSocketInt": "INT", "NodeSocketBool": "BOOL",
                     "NodeSocketColor": "COLOR", "NodeSocketVector": "VECTOR"}[it.socket_type]
            dv = it.default_value
            dv = tuple(dv) if hasattr(dv, "__len__") else dv
            kw = {k: getattr(it, a) for k, a in (("min", "min_value"), ("max", "max_value")) if hasattr(it, a)}
            if getattr(it, "subtype", "NONE") != "NONE":
                kw["subtype"] = it.subtype
            ui[it.name] = g.input(it.name, stype, dv, panel=label, desc=it.description, **kw)
    for p in ("Terrain", "Masks", "Rocks", "Grass", "Flowers", "Bushes"):
        g._panels[p].default_closed = True

    def wire(tree, label, **fixed):
        n = g.group(tree, label=label)
        for s in n.b.inputs:
            if s.enabled and s.name in fixed:
                g.connect(fixed[s.name], s)
            elif s.enabled and s.name in ui:
                g.connect(ui[s.name], s)
        return n

    with g.frame("Surface: the input mesh or a generated terrain, relief along up; slope and height masks"):
        ground_n = wire(parts["ground"], "Ground", Surface=surf)
        masked = wire(parts["masks"], "Masks", Surface=ground_n["Surface"])["Surface"]
    with g.frame("Meadow faces: where scatter_meadow is over one half (grass and flowers grow only here)"):
        meadow = g.node("GeometryNodeSeparateGeometry", props={"domain": "FACE"}, Geometry=masked,
                        Selection=g.math("GREATER_THAN", attr(g, "scatter_meadow"), 0.5))["Selection"]
        # plants stand on world Z on terrain, along the surface on planets (Radial Up)
        plant_align = switch(g, "FLOAT", ui["Radial Up"], 0.15, 0.9)
    with g.frame("Macros: Density, Rock Amount and Flower Amount scale the detailed densities"):
        def scaled(name, *macros):
            v = ui[name]
            for m in macros:
                v = g.math("MULTIPLY", v, m, label=f"{name} x macro")
            return v
        layers = [
            wire(parts["rocks"], "Rocks", Surface=masked, Align=switch(g, "FLOAT", ui["Radial Up"], 0.6, 1.0),
                 **{"Rock Density": scaled("Rock Density", dens, rock_amt),
                    "Pebble Density": scaled("Pebble Density", dens, rock_amt)})["Instances"],
            wire(parts["grass"], "Grass", Surface=meadow, Align=plant_align,
                 **{"Tuft Density": scaled("Tuft Density", dens)})["Instances"],
            wire(parts["flowers"], "Flowers", Surface=meadow, Align=plant_align,
                 **{"Patch Density": scaled("Patch Density", dens, flower_amt)})["Instances"],
            wire(parts["bushes"], "Bushes", Surface=masked,
                 **{"Bush Density": scaled("Bush Density", dens),
                    "Bush Blossoms": scaled("Bush Blossoms", flower_amt)})["Instances"],
        ]
    with g.frame("Surface plus every layer, realized so materials read nk_* and scatter_* attributes"):
        geo = g.node("GeometryNodeRealizeInstances", Geometry=join(g, masked, *layers))["Geometry"]
        geo = g.node("GeometryNodeRemoveAttribute", Geometry=geo, Name="nk_rot",
                     **{"Pattern Mode": "Exact"})["Geometry"]
    g.output("Geometry", "GEOMETRY", geo)
    return g.finish()


# ---- scene ------------------------------------------------------------------------------------------------------------
def post(sc, haze_color, haze_start, haze_depth, haze_amount, sky_top, sky_horizon, horizon=0.5, top=0.9, glow=0.15):
    """Compositor: distance haze by the Mist pass over a screen-space sky (NK Haze Over Sky), then NK Soft Glow."""
    sc.render.film_transparent = True
    sc.view_layers[0].use_pass_mist = True
    ms = sc.world.mist_settings
    ms.start, ms.depth, ms.falloff = haze_start, haze_depth, "QUADRATIC"
    g = Graph(f"{NAME} Post {sc.name}", kind="COMPOSITOR",
              description="Haze by mist depth over a sky gradient, then a soft glow on the brightest highlights")
    with g.frame("Render layers, haze over the sky, soft glow"):
        rl = g.node("CompositorNodeRLayers")
        rl.b.scene = sc
        hz = g.group(haze_over_sky(), Image=rl["Image"], Mist=rl["Mist"],
                     **{"Haze Color": lin(haze_color), "Haze Amount": haze_amount, "Sky Top": lin(sky_top),
                        "Sky Horizon": lin(sky_horizon), "Horizon": horizon, "Top": top})
        gl = g.group(soft_glow(), Image=hz["Image"], Threshold=1.0, Strength=glow, Size=0.6)
    g.output("Image", "COLOR", gl["Image"])
    sc.compositing_node_group = g.finish()


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


def ground_z(ob, sc, x, y):
    """Height of the evaluated surface under (x, y): cameras on generated terrain sit relative to it."""
    from mathutils import Vector
    ev = ob.evaluated_get(sc.view_layers[0].depsgraph)
    ok, loc, *_ = ev.ray_cast(Vector((x, y, 500.0)), Vector((0.0, 0.0, -1.0)))
    return loc.z if ok else 0.0


def planet(sc):
    """The transfer input: an icosphere 'planet' of radius 5 (plain mesh; the relief comes from the modifier)."""
    me = bpy.data.meshes.new("Planet")
    ob = bpy.data.objects.new("Planet", me)
    sc.collection.objects.link(ob)
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=6, radius=5.0)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ob.data.materials.append(bpy.data.materials["Surface Scatter Ground"])
    return ob


SCENES = {
    # name: modifier inputs, camera (location, target, lens), light, post
    "Meadow": dict(
        inputs={},
        cam=((1.5, -24.0, 1.5), (-2.0, 4.0, 0.6), 32.0), cam_on_ground=True,
        light=dict(sun_elev=24.0, sun_azim=118.0, strength=4.2, sun_color="#FFE3BF", sky_top="#8DB7D9",
                   sky_horizon="#E6D9C6", sky_strength=1.1),
        post=dict(haze_color="#D9DCD6", haze_start=6.0, haze_depth=90.0, haze_amount=0.55, sky_top="#7FAED6",
                  sky_horizon="#EADFCB", horizon=0.45, top=0.95)),
    "Scatter Transfer": dict(
        inputs={"Generate Terrain": False, "Radial Up": True, "Relief": 1.0, "Feature Size": 2.6,
                "Meadow Height": 0.7, "Rock Height": 0.55, "Rock Amount": 2.5, "Bush Size": 0.55, "Rock Size Max": 0.9},
        cam=((13.0, -21.0, 8.0), (0.0, 0.0, -0.3), 42.0),
        light=dict(sun_elev=30.0, sun_azim=70.0, strength=3.4, sun_color="#FFE3BF", sky_top="#6E98C8",
                   sky_horizon="#E8D8C8", sky_strength=1.0),
        post=dict(haze_color="#D8DCE0", haze_start=30.0, haze_depth=60.0, haze_amount=0.0, sky_top="#5F8DC4",
                  sky_horizon="#F0DCC4", horizon=0.2, top=1.0)),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/surface_scatter.blend")
    ap.add_argument("--render", default="")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--frame", type=int, default=1)
    ap.add_argument("--scene", default="", help="render this scene instead of the first")
    a = ap.parse_args(argv)

    sc0 = S.reset()
    group = build()
    for i, (name, cfg) in enumerate(SCENES.items()):
        sc = sc0 if i == 0 else bpy.data.scenes.new(name)
        sc.name = name
        S.light_world(sc=sc, **cfg["light"])
        if name == "Meadow":
            ob, mod = S.holder("Meadow", None, group, sc=sc)
        else:
            ob = planet(sc)
            mod = ob.modifiers.new(group.name, "NODES")
            mod.node_group = group
        inspect.set_modifier_inputs(mod, cfg["inputs"])
        loc, target, lens = cfg["cam"]
        if cfg.get("cam_on_ground"):              # z values are heights above the generated terrain
            sc.frame_set(a.frame)
            loc = (loc[0], loc[1], loc[2] + ground_z(ob, sc, loc[0], loc[1]))
            target = (target[0], target[1], target[2] + ground_z(ob, sc, target[0], target[1]))
        camera(sc, f"{name} Camera", loc, target, lens)
        S.render_setup(sc=sc, width=a.width, height=round(a.width * 0.55 / 2) * 2, samples=a.samples,
                       look="Medium High Contrast")
        post(sc, **cfg["post"])
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
