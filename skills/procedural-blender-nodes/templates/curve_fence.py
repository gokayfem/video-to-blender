"""A rustic post-and-rail fence that follows any curve over any ground, with gate gaps, leaning posts and grass.

    blender -b --factory-startup --python templates/curve_fence.py -- --out out/fence.blend [--render f.png]
        [--width 960] [--samples 16] [--frame 1] [--scene "Fence Transfer"]

Technique: curve-space placement. NK Curve Samples puts a post every Post Spacing along the Path curve; each post
is dropped onto the Ground object by a ray, leans a little and gets its own height. Rails are spans between
consecutive posts (Sample Index i+1, wrapping on closed curves), one chamfered box per span and rail level, so
they follow the leaning posts instead of being bent copies of the curve. Everything solid is NK Chamfer Boxes;
the wood is NK Wood Grain read in each piece's own frame (attribute nk_grain), tinted and silvered per piece
(nk_color / nk_dark). Grass tufts (a template-local blade fan) are clumped around each post base with NK Clumps.

Scenes (one shared "Curve Fence" group):
  Fence            an S-curve across a rolling hillside, three-quarter view (rendered for the gallery)
  Fence Transfer   the same group on a closed circle: a paddock seen from above
Adapt: draw your own curve and pick it as Path; pick your terrain mesh as Ground (or leave it empty for a flat
fence on the curve). Swap the post/rail boxes for other shapes in "Curve Fence Rails" / the posts frame.
"""
import argparse, math, pathlib, sys

SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import bpy
from nodekit import inspect
from nodekit import scene as S
from nodekit.graph import Graph, once
from library.curve import curve_samples
from library.shapes import chamfer_boxes, leaf, blossom
from library.scatter import clumps, scatter_on_surface
from library.materials import make_material, wood_grain, attribute_tint, lin

NAME = "Curve Fence"
TAU = 2 * math.pi


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


def sample(g, geo, value, index, dtype="FLOAT_VECTOR"):
    return g.node("GeometryNodeSampleIndex", props={"data_type": dtype, "domain": "POINT"}, Geometry=geo,
                  Value=value, Index=index)["Value"]


def rot_vec(g, v, rot):
    return g.node("FunctionNodeRotateVector", Vector=v, Rotation=rot)["Vector"]


def grain(g, mesh, swap):
    """nk_grain: each vertex in its piece's own frame (stored as fc_c / fc_q), long axis on Z for NK Wood Grain,
    shifted per piece so no two boards share a pattern. Then drop the working attributes."""
    local = rot_vec(g, g.vmath("SUBTRACT", g.node("GeometryNodeInputPosition"), attr(g, "fc_c", "FLOAT_VECTOR")),
                    g.node("FunctionNodeInvertRotation", Rotation=attr(g, "fc_q", "QUATERNION")))
    if swap:                                               # rails: long axis X -> Z
        p = g.separate(local)
        local = g.combine(p["Y"], p["Z"], p["X"])
    shift = g.vmath("SCALE", (3.1, 1.7, 5.3), scale=g.math("MULTIPLY", attr(g, "nk_rand"), 10.0))
    mesh = store(g, mesh, "nk_grain", g.vmath("ADD", local, shift), "FLOAT_VECTOR")
    return g.node("GeometryNodeRemoveAttribute", Geometry=mesh, Name="fc_*", **{"Pattern Mode": "Wildcard"})["Geometry"]


# ---- template-local groups -----------------------------------------------------------------------------------
@once
def build_tuft():
    """A grass tuft: a fan of NK Leaf blades rising from the origin and arching outwards."""
    g = Graph("Curve Fence Tuft", description="A grass tuft: Blades NK Leaf blades stood up from the origin, each "
                                              "tilted outwards by up to Spread and spun around Z, arching under "
                                              "their own curl")
    n = g.input("Blades", "INT", 26, min=1, max=64, desc="Blades per tuft")
    h = g.input("Height", "FLOAT", 0.35, min=0.01, max=5.0, subtype="DISTANCE", desc="Tallest blade length")
    spread = g.input("Spread", "FLOAT", 0.35, min=0.0, max=1.5, subtype="ANGLE", desc="Largest outward tilt")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    with g.frame("One point per blade; stand the blade up, tilt it out, spin it round"):
        pts = g.node("GeometryNodePoints", Count=n)["Points"]
        idx = g.node("GeometryNodeInputIndex")["Index"]
        tilt = g.math("MULTIPLY", rand(g, 0.25, 1.0, seed, 1, idx), spread)
        spin = g.math("MULTIPLY_ADD", idx, 2.39996, rand(g, -0.4, 0.4, seed, 2, idx), label="golden angle")
        rot = g.node("FunctionNodeEulerToRotation", Euler=g.combine(0.0, g.math("SUBTRACT", tilt, math.pi / 2), spin))
        blade = g.group(leaf(), Length=1.0, Width=0.045, **{"Widest At": 0.2, "Fold": 0.5, "Curl": 0.5,
                                                           "Resolution": 4})
        out = g.node("GeometryNodeInstanceOnPoints", Points=pts, Instance=blade, Rotation=rot["Rotation"],
                     Scale=g.math("MULTIPLY", h, rand(g, 0.55, 1.0, seed, 3, idx)))["Instances"]
    g.output("Tuft", "GEOMETRY", out, desc="Blade instances (realize before reading attributes in shaders)")
    return g.finish()


@once
def build_ground():
    """Rolling meadow: a grid raised into a ridge, rolled by noise, tinted and dotted with tufts and flowers."""
    g = Graph("Curve Fence Ground", modifier=True,
              description="A rolling hillside for the fence to stand on: a grid raised into a ridge along X (a "
                          "raised-cosine crest at Crest Y), rolled by noise, its meadow colour stored as nk_color, "
                          "with grass tufts and small flowers scattered near Meadow Centre. Scene dressing: the "
                          "fence follows any mesh picked as its Ground")
    g.input("Geometry", "GEOMETRY", desc="Ignored; the ground is generated", hide_value=True)
    size = g.input("Size", "FLOAT", 140.0, min=1.0, max=1000.0, subtype="DISTANCE", panel="Shape",
                   desc="Side length of the square of ground")
    res = g.input("Resolution", "INT", 240, min=2, max=1000, panel="Shape", desc="Grid vertices per side")
    hill = g.input("Hill Height", "FLOAT", 5.0, min=-50.0, max=50.0, subtype="DISTANCE", panel="Shape",
                   desc="Height of the ridge crest above the valley (0 = flat ground)")
    crest = g.input("Crest Y", "FLOAT", 30.0, min=-500.0, max=500.0, subtype="DISTANCE", panel="Shape",
                    desc="Where the crest runs (Y coordinate)")
    width = g.input("Hill Width", "FLOAT", 40.0, min=1.0, max=1000.0, subtype="DISTANCE", panel="Shape",
                    desc="Distance from the crest to the foot of the hill")
    roll = g.input("Roll Height", "FLOAT", 0.9, min=0.0, max=20.0, subtype="DISTANCE", panel="Shape",
                   desc="Height of the rolling bumps")
    scale = g.input("Roll Scale", "FLOAT", 0.05, min=0.001, max=10.0, panel="Shape", desc="Bumps per metre")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, panel="Shape", desc="Random seed")
    centre = g.input("Meadow Centre", "VECTOR", (0.0, 0.0, 0.0), subtype="TRANSLATION", panel="Meadow",
                     desc="Tufts and flowers grow around this point (put it where the camera looks)")
    radius = g.input("Meadow Radius", "FLOAT", 30.0, min=0.0, max=1000.0, subtype="DISTANCE", panel="Meadow",
                     desc="Tufts and flowers thin out to nothing at this distance from the centre")
    tufts = g.input("Tuft Density", "FLOAT", 0.6, min=0.0, max=100.0, panel="Meadow", desc="Grass tufts per m^2")
    flowers = g.input("Flower Density", "FLOAT", 3.0, min=0.0, max=100.0, panel="Meadow",
                      desc="Flowers per m^2")
    grass_c = g.input("Grass Color", "COLOR", lin("#64813A"), panel="Meadow", desc="Main meadow colour")
    dry_c = g.input("Dry Color", "COLOR", lin("#A9A452"), panel="Meadow", desc="Sun-dried patches")
    gmat = g.input("Grass Material", "MATERIAL", panel="Meadow", desc="Material of ground and tufts")
    fmat = g.input("Flower Material", "MATERIAL", panel="Meadow", desc="Material of the flowers")
    with g.frame("Grid raised into a ridge (raised cosine across Y) and rolled by noise"):
        grid = g.node("GeometryNodeMeshGrid", **{"Size X": size, "Size Y": size, "Vertices X": res,
                                                "Vertices Y": res})["Mesh"]
        pos = g.node("GeometryNodeInputPosition")["Position"]
        noise = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "3D"}, Scale=scale, Detail=3.0,
                       Roughness=0.45)
        noise.set(Vector=g.vmath("ADD", pos, g.combine(0.0, 0.0, g.math("MULTIPLY", seed, 13.7))))  # seed shifts it
        u = g.math("DIVIDE", g.math("SUBTRACT", g.separate(pos)["Y"], crest), width)
        u = g.math("MINIMUM", g.math("MAXIMUM", u, -1.0), 1.0)
        ridge = g.math("MULTIPLY", hill, g.math("MULTIPLY_ADD", g.math("COSINE", g.math("MULTIPLY", u, math.pi)), 0.5,
                                                 0.5))
        z = g.math("ADD", ridge,
                   g.math("MULTIPLY", g.math("SUBTRACT", noise["Factor"], 0.5), g.math("MULTIPLY", roll, 2.0)))
        ground = g.node("GeometryNodeSetPosition", Geometry=grid, Offset=g.combine(0.0, 0.0, z))["Geometry"]
    with g.frame("Meadow colour: large patches of dry grass, stored as nk_color"):
        patch = g.node("ShaderNodeTexNoise", Vector=pos, Scale=0.12, Detail=4.0, Roughness=0.6)["Factor"]
        col = g.mix(g.map_range(patch, 0.45, 0.7, 0.0, 1.0, interp="SMOOTHSTEP"), grass_c, dry_c,
                    data_type="RGBA")["Result"]
        ground = store(g, g.node("GeometryNodeSetShadeSmooth", Geometry=ground)["Geometry"], "nk_color", col,
                       "FLOAT_COLOR")
    with g.frame("Meadow mask: 1 at the centre, fading to 0 at Meadow Radius (fc_meadow)"):
        dist = g.vmath("DISTANCE", g.vmath("MULTIPLY", pos, (1.0, 1.0, 0.0)),
                       g.vmath("MULTIPLY", centre, (1.0, 1.0, 0.0)))["Value"]
        ground = store(g, ground, "fc_meadow", g.map_range(dist, g.math("MULTIPLY", radius, 0.5), radius, 1.0, 0.0,
                                                           interp="SMOOTHSTEP"))
        ground = g.node("GeometryNodeSetMaterial", Geometry=ground, Material=gmat)["Geometry"]
    with g.frame("Tufts and flowers scattered over the meadow"):
        tuft = g.group(build_tuft(), Seed=seed)
        tf = g.group(scatter_on_surface(), Surface=ground, Instance=tuft, Density=tufts, Seed=seed,
                     **{"Scale Min": 0.4, "Scale Max": 1.3, "Align": 0.3, "Mask Attribute": "fc_meadow"})
        tf_m = g.node("GeometryNodeSetMaterial", Geometry=tf["Instances"], Material=gmat)["Geometry"]
        bloom = g.group(blossom(), Petals=6, Size=0.11)
        fl = g.group(scatter_on_surface(), Surface=ground, Instance=bloom, Density=flowers,
                     Seed=g.math("ADD", seed, 7.0), **{"Scale Min": 0.6, "Scale Max": 1.2, "Align": 0.0,
                                                       "Mask Attribute": "fc_meadow"})
        fl_up = g.node("GeometryNodeTranslateInstances", Instances=fl["Instances"], Translation=(0.0, 0.0, 0.05))
        fl_m = g.node("GeometryNodeSetMaterial", Geometry=fl_up, Material=fmat)["Geometry"]
        join = g.node("GeometryNodeJoinGeometry")
        for x in (fl_m, tf_m, ground):
            g.connect(x, join.i("Geometry"))
        out = g.node("GeometryNodeRealizeInstances", Geometry=join)["Geometry"]
        out = g.node("GeometryNodeRemoveAttribute", Geometry=out, Name="fc_meadow")["Geometry"]
    g.output("Geometry", "GEOMETRY", out, desc="The meadow mesh with tufts and flowers")
    return g.finish()


def build_fence(wood, grass):
    """The top modifier group: posts, rails and grass along the Path, standing on the Ground."""
    tuft = build_tuft()
    g = Graph(NAME, modifier=True,
              description="A rustic split-rail fence along any curve: posts every Post Spacing dropped onto the "
                          "Ground object, leaning a little, joined by Rails rails per span, with gate gaps, "
                          "broken rails, weathered wood and grass tufts at the post bases")
    g.input("Geometry", "GEOMETRY", desc="Ignored; the fence is generated from Path", hide_value=True)
    # Primary: the macro controls an artist reaches for first
    path = g.input("Path", "OBJECT", panel="Primary", desc="The curve the fence follows (open or closed)")
    ground = g.input("Ground", "OBJECT", panel="Primary",
                     desc="Terrain the posts stand on (rays straight down); empty = posts on the curve itself")
    spacing = g.input("Post Spacing", "FLOAT", 2.4, min=0.4, max=20.0, subtype="DISTANCE", panel="Primary",
                      desc="Distance between posts along the curve")
    height = g.input("Height", "FLOAT", 1.3, min=0.3, max=5.0, subtype="DISTANCE", panel="Primary",
                     desc="Post height above the ground")
    rails = g.input("Rails", "INT", 3, min=1, max=6, panel="Primary", desc="Rails per span")
    lean = g.input("Lean", "FLOAT", 1.0, min=0.0, max=4.0, panel="Primary",
                   desc="0 = plumb posts, 1 = gently settled, 3+ = a fence about to fall over")
    weather = g.input("Weathering", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR", panel="Primary",
                      desc="0 = fresh brown timber, 1 = silver-grey old wood with more broken rails")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, panel="Primary", desc="Changes every random choice")
    # Detailed panels
    post_w = g.input("Post Width", "FLOAT", 0.17, min=0.02, max=1.0, subtype="DISTANCE", panel="Posts",
                     desc="Post thickness")
    h_jit = g.input("Height Jitter", "FLOAT", 0.08, min=0.0, max=1.0, subtype="DISTANCE", panel="Posts",
                    desc="Random post height change, either way")
    s_jit = g.input("Spacing Jitter", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR", panel="Posts",
                    desc="Random shift along the curve, as a share of Post Spacing")
    lean_a = g.input("Lean Angle", "FLOAT", 0.05, min=0.0, max=0.5, subtype="ANGLE", panel="Posts",
                     desc="Largest lean at Lean 1 (mostly across the fence)")
    sink = g.input("Sink", "FLOAT", 0.3, min=0.0, max=2.0, subtype="DISTANCE", panel="Posts",
                   desc="Post length buried below the ground (hides the foot on slopes)")
    rail_h = g.input("Rail Height", "FLOAT", 0.12, min=0.01, max=1.0, subtype="DISTANCE", panel="Rails",
                     desc="Vertical size of a rail")
    rail_t = g.input("Rail Thickness", "FLOAT", 0.05, min=0.01, max=0.5, subtype="DISTANCE", panel="Rails",
                     desc="Rail thickness across the fence")
    lo = g.input("Bottom Rail", "FLOAT", 0.3, min=0.0, max=1.0, subtype="FACTOR", panel="Rails",
                 desc="Lowest rail as a share of Height")
    hi = g.input("Top Rail", "FLOAT", 0.85, min=0.0, max=1.0, subtype="FACTOR", panel="Rails",
                 desc="Highest rail as a share of Height (the only rail when Rails = 1)")
    over = g.input("Overhang", "FLOAT", 0.1, min=0.0, max=1.0, subtype="DISTANCE", panel="Rails",
                   desc="How far rails run past the posts")
    droop = g.input("Droop", "FLOAT", 0.04, min=0.0, max=0.5, subtype="DISTANCE", panel="Rails",
                    desc="Random height change at each rail end")
    gap = g.input("Gap Chance", "FLOAT", 0.08, min=0.0, max=1.0, subtype="FACTOR", panel="Rails",
                  desc="Chance that a span has no rails (a gate gap)")
    broken = g.input("Broken Chance", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR", panel="Rails",
                     desc="Chance (x Weathering) that a rail has dropped one end to the ground")
    show_grass = g.input("Show Grass", "BOOL", True, panel="Grass", desc="Grass tufts around the post bases")
    tufts = g.input("Tufts Per Post", "FLOAT", 12.0, min=0.0, max=100.0, panel="Grass",
                    desc="Average grass tufts around each post")
    tuft_h = g.input("Tuft Height", "FLOAT", 0.6, min=0.01, max=3.0, subtype="DISTANCE", panel="Grass",
                     desc="Tallest grass blade")
    grass_c = g.input("Grass Color", "COLOR", lin("#5F8432"), panel="Grass", desc="Colour of the tufts (nk_color)")
    wood_c = g.input("Wood Color", "COLOR", lin("#85593A"), panel="Wood", desc="Fresh timber colour")
    grey_c = g.input("Weathered Color", "COLOR", lin("#ABA79C"), panel="Wood", desc="Silvered old timber colour")
    for p in ("Posts", "Rails", "Grass", "Wood"):
        g._panels[p].default_closed = True

    with g.frame("Path curve and terrain"):
        curve = g.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=path)["Geometry"]
        terrain = g.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=ground)["Geometry"]
        length = g.node("GeometryNodeCurveLength", Curve=curve)["Length"]
        cyclic = g.node("GeometryNodeSampleIndex", props={"data_type": "BOOLEAN", "domain": "CURVE"},
                        Geometry=curve, Value=g.node("GeometryNodeInputSplineCyclic"), Index=0)["Value"]
    with g.frame("Posts: NK Curve Samples; on a closed curve drop the last post if it crowds the first"):
        smp = g.group(curve_samples(), Curve=curve, Spacing=spacing, Jitter=s_jit, Seed=seed)
        n = g.node("GeometryNodeAttributeDomainSize", props={"component": "POINTCLOUD"},
                   Geometry=smp["Points"])["Point Count"]
        last = g.node("FunctionNodeCompare", props={"data_type": "INT", "operation": "EQUAL"},
                      A=g.node("GeometryNodeInputIndex"), B=g.math("SUBTRACT", n, 1.0))["Result"]
        tail = g.math("SUBTRACT", length, g.math("MULTIPLY", g.math("SUBTRACT", n, 1.0), spacing))
        crowd = g.node("FunctionNodeBooleanMath", props={"operation": "AND"}, Boolean=cyclic,
                       **{"Boolean_001": g.math("LESS_THAN", tail, g.math("MULTIPLY", spacing, 0.5))})["Boolean"]
        drop = g.node("FunctionNodeBooleanMath", props={"operation": "AND"}, Boolean=last, Boolean_001=crowd)
        posts = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=smp["Points"],
                       Selection=drop)["Geometry"]
    with g.frame("Drop each post onto the Ground (a ray straight down; misses keep the curve height)"):
        pos = g.node("GeometryNodeInputPosition")["Position"]
        ray = g.node("GeometryNodeRaycast", **{"Target Geometry": terrain, "Ray Direction": (0.0, 0.0, -1.0),
                                               "Ray Length": 1000.0})
        g.connect(g.vmath("ADD", pos, (0.0, 0.0, 500.0)), ray.i("Source Position"))
        hit = g.node("GeometryNodeSwitch", props={"input_type": "VECTOR"}, Switch=ray["Is Hit"], **{
            "False": pos, "True": ray["Hit Position"]})["Output"]
        posts = g.node("GeometryNodeSetPosition", Geometry=posts, Position=hit)["Geometry"]
    with g.frame("Per post: height, lean (mostly across the fence), weathered colour"):
        pid = g.node("GeometryNodeInputIndex")["Index"]
        hp = g.math("ADD", height, g.math("MULTIPLY", rand(g, -1.0, 1.0, seed, 11, pid), h_jit))
        amp = g.math("MULTIPLY", lean_a, lean)
        tilt = g.node("FunctionNodeEulerToRotation", Euler=g.combine(
            g.math("MULTIPLY", rand(g, -1.0, 1.0, seed, 12, pid), amp),
            g.math("MULTIPLY", rand(g, -0.4, 0.4, seed, 13, pid), amp), rand(g, -0.15, 0.15, seed, 14, pid)))
        q = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"},
                   Rotation=attr(g, "nk_rot", "QUATERNION"), **{"Rotate By": tilt["Rotation"]})["Rotation"]
        posts = store(g, posts, "fc_q", q, "QUATERNION")
        posts = store(g, posts, "fc_h", hp)
        posts = store(g, posts, "fc_base", g.node("GeometryNodeInputPosition"), "FLOAT_VECTOR")
    painted = paint(g, weather, wood_c, grey_c, seed)(posts, 21)
    with g.frame("Post boxes from Sink below the ground to the post height, along the leaning axis"):
        up = rot_vec(g, (0.0, 0.0, 1.0), attr(g, "fc_q", "QUATERNION"))
        mid = g.math("MULTIPLY", g.math("SUBTRACT", attr(g, "fc_h"), sink), 0.5)
        ctr = g.node("GeometryNodeSetPosition", Geometry=painted,
                     Offset=g.vmath("SCALE", up, scale=mid))["Geometry"]
        ctr = store(g, ctr, "fc_c", g.node("GeometryNodeInputPosition"), "FLOAT_VECTOR")
        wv = g.math("MULTIPLY", post_w, rand(g, 0.9, 1.15, seed, 22))
        boxes = g.group(chamfer_boxes(), Points=ctr, Rotation=attr(g, "fc_q", "QUATERNION"), Chamfer=0.015,
                        Size=g.combine(wv, post_w, g.math("ADD", attr(g, "fc_h"), sink)))["Mesh"]
        post_mesh = grain(g, boxes, swap=False)
    rails_mesh = g.group(build_rails(), Posts=posts, Cyclic=cyclic, Rails=rails, Height=height, Seed=seed,
                         Weathering=weather, **{"Post Width": post_w, "Rail Height": rail_h,
                                                "Rail Thickness": rail_t, "Bottom Rail": lo, "Top Rail": hi,
                                                "Overhang": over, "Droop": droop, "Gap Chance": gap,
                                                "Broken Chance": broken, "Wood Color": wood_c,
                                                "Weathered Color": grey_c})["Rails"]
    with g.frame("Wood: posts and rails, one material"):
        wood_geo = g.node("GeometryNodeJoinGeometry")
        g.connect(rails_mesh, wood_geo.i("Geometry"))
        g.connect(post_mesh, wood_geo.i("Geometry"))
        wood_geo = g.node("GeometryNodeSetMaterial", Geometry=wood_geo, Material=wood)["Geometry"]
    with g.frame("Grass: a disc on the ground at each post, NK Clumps of tufts on it"):
        disc = g.node("GeometryNodeMeshCircle", props={"fill_type": "TRIANGLE_FAN"}, Vertices=10, Radius=0.4)
        discs = g.node("GeometryNodeRealizeInstances", Geometry=g.node(
            "GeometryNodeInstanceOnPoints", Points=posts, Instance=disc["Mesh"])["Instances"])["Geometry"]
        discs = store(g, discs, "nk_color", grass_c, "FLOAT_COLOR")
        area = math.pi * 0.4 ** 2 * math.cos(math.pi / 10)          # area of the 10-gon
        tf = g.group(clumps(), Surface=discs, Instance=g.group(tuft, Height=tuft_h, Seed=seed), Seed=seed,
                     **{"Clump Density": g.math("DIVIDE", tufts, area * 4.5), "Clump Radius": 0.35,
                        "Members Min": 3, "Members Max": 6, "Scale Min": 0.6, "Scale Max": 1.0, "Falloff": 0.5})
        grass_geo = g.node("GeometryNodeSetMaterial", Geometry=tf["Instances"], Material=grass)["Geometry"]
        grass_geo = g.node("GeometryNodeSwitch", props={"input_type": "GEOMETRY"}, Switch=show_grass,
                           **{"True": grass_geo})["Output"]
    with g.frame("Join and realize (so shaders read nk_color, nk_rand, nk_grain)"):
        join = g.node("GeometryNodeJoinGeometry")
        g.connect(grass_geo, join.i("Geometry"))
        g.connect(wood_geo, join.i("Geometry"))
        out = g.node("GeometryNodeRealizeInstances", Geometry=join)["Geometry"]
    g.output("Geometry", "GEOMETRY", out, desc="Posts, rails and grass")
    return g.finish()


def paint(g, weather, wood_c, grey_c, seed):
    """Returns tint(geo, k): store nk_rand, nk_color (wood silvered by Weathering, varied per piece) and nk_dark."""
    def tint(geo, k):
        with g.frame("Per piece: nk_rand, wood colour silvered by Weathering (nk_color) and its latewood (nk_dark)"):
            r = rand(g, 0.0, 1.0, seed, k)
            geo = store(g, geo, "nk_rand", r)
            w = g.math("MULTIPLY", weather, g.math("MULTIPLY_ADD", attr(g, "nk_rand"), 0.8, 0.6), clamp=True)
            light = g.mix(w, wood_c, grey_c, data_type="RGBA")["Result"]
            light = g.vmath("SCALE", light, scale=g.math("MULTIPLY_ADD", attr(g, "nk_rand"), 0.35, 0.8))
            geo = store(g, geo, "nk_color", light, "FLOAT_COLOR")
            dark = g.vmath("SCALE", light, scale=g.math("MULTIPLY_ADD", w, 0.2, 0.42))
            return store(g, geo, "nk_dark", dark, "FLOAT_COLOR")
    return tint


@once
def build_rails():
    """Rails between consecutive posts: one chamfered box per (span, rail level), from post i to post i+1."""
    g = Graph("Curve Fence Rails",
              description="Rails between consecutive posts. Each post point (fc_base, fc_q, fc_h) starts a span "
                          "to the next post (wrapping on a closed curve); a span is duplicated Rails times, each "
                          "copy a rail level between Bottom and Top Rail, both ends fixed to the leaning posts' "
                          "faces. Gap Chance leaves a span empty; Broken Chance drops one rail end to the ground")
    posts = g.input("Posts", "GEOMETRY", desc="Post points in order along the curve, with fc_base, fc_q, fc_h")
    cyclic = g.input("Cyclic", "BOOL", False, desc="Close the fence: a span from the last post to the first")
    rails = g.input("Rails", "INT", 3, min=1, max=6, desc="Rails per span")
    height = g.input("Height", "FLOAT", 1.2, min=0.1, max=10.0, subtype="DISTANCE", desc="Nominal post height")
    post_w = g.input("Post Width", "FLOAT", 0.15, min=0.0, max=1.0, subtype="DISTANCE", desc="Post thickness")
    rail_h = g.input("Rail Height", "FLOAT", 0.12, min=0.01, max=1.0, subtype="DISTANCE", desc="Rail height")
    rail_t = g.input("Rail Thickness", "FLOAT", 0.05, min=0.01, max=0.5, subtype="DISTANCE", desc="Rail thickness")
    lo = g.input("Bottom Rail", "FLOAT", 0.3, min=0.0, max=1.0, subtype="FACTOR", desc="Lowest rail / Height")
    hi = g.input("Top Rail", "FLOAT", 0.85, min=0.0, max=1.0, subtype="FACTOR", desc="Highest rail / Height")
    over = g.input("Overhang", "FLOAT", 0.1, min=0.0, max=1.0, subtype="DISTANCE", desc="Rail run past the posts")
    droop = g.input("Droop", "FLOAT", 0.04, min=0.0, max=0.5, subtype="DISTANCE", desc="Rail end height jitter")
    gap = g.input("Gap Chance", "FLOAT", 0.08, min=0.0, max=1.0, subtype="FACTOR", desc="Chance of an empty span")
    broken = g.input("Broken Chance", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR",
                     desc="Chance (x Weathering) of a rail with one end on the ground")
    weather = g.input("Weathering", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR", desc="Wood age 0..1")
    wood_c = g.input("Wood Color", "COLOR", lin("#8A5E3A"), desc="Fresh timber colour")
    grey_c = g.input("Weathered Color", "COLOR", lin("#9A958A"), desc="Silvered timber colour")
    seed = g.input("Seed", "INT", 0, min=0, max=100000, desc="Random seed")
    with g.frame("Spans: post i to post i+1 (wrapping when Cyclic); gaps removed"):
        n = g.node("GeometryNodeAttributeDomainSize", props={"component": "POINTCLOUD"}, Geometry=posts)
        n = n["Point Count"]
        idx = g.node("GeometryNodeInputIndex")["Index"]
        nxt = g.math("FLOORED_MODULO", g.math("ADD", idx, 1.0), g.math("MAXIMUM", n, 1.0))
        spans = store(g, posts, "fc_next", nxt, "INT")
        is_last = g.node("FunctionNodeCompare", props={"data_type": "FLOAT", "operation": "GREATER_EQUAL"},
                         A=idx, B=g.math("SUBTRACT", n, 1.0))["Result"]
        open_end = g.node("FunctionNodeBooleanMath", props={"operation": "NIMPLY"}, Boolean=is_last,
                          Boolean_001=cyclic)["Boolean"]
        is_gap = g.math("LESS_THAN", rand(g, 0.0, 1.0, seed, 31, idx), gap)
        no_span = g.node("FunctionNodeBooleanMath", props={"operation": "OR"}, Boolean=open_end, Boolean_001=is_gap)
        spans = g.node("GeometryNodeDeleteGeometry", props={"domain": "POINT"}, Geometry=spans,
                       Selection=no_span)["Geometry"]
    with g.frame("Rail levels: duplicate each span Rails times, top rail first"):
        dup = g.node("GeometryNodeDuplicateElements", props={"domain": "POINT"}, Geometry=spans, Amount=rails)
        lv = store(g, dup["Geometry"], "fc_level", dup["Duplicate Index"], "INT")
    with g.frame("Rail ends on the two posts' faces, with droop; a broken rail drops its far end"):
        rid = g.node("GeometryNodeInputIndex")["Index"]
        k = attr(g, "fc_level", "INT")
        frac = g.math("DIVIDE", k, g.math("MAXIMUM", g.math("SUBTRACT", rails, 1.0), 1.0))
        hr = g.math("MULTIPLY", height, g.math("SUBTRACT", hi, g.math("MULTIPLY", frac, g.math("SUBTRACT", hi, lo))))
        face = g.math("MULTIPLY_ADD", post_w, 0.5, g.math("MULTIPLY", rail_t, 0.5))
        nxt = attr(g, "fc_next", "INT")

        def end(base, q, h):
            return g.vmath("ADD", base, rot_vec(g, g.combine(0.0, face, h), q))
        ha = g.math("ADD", hr, g.math("MULTIPLY", rand(g, -1.0, 1.0, seed, 32, rid), droop))
        hb = g.math("ADD", hr, g.math("MULTIPLY", rand(g, -1.0, 1.0, seed, 33, rid), droop))
        bk = g.math("LESS_THAN", rand(g, 0.0, 1.0, seed, 34, rid), g.math("MULTIPLY", broken, weather))
        hb = g.node("GeometryNodeSwitch", props={"input_type": "FLOAT"}, Switch=bk,
                    **{"False": hb, "True": g.math("MULTIPLY", rail_h, 0.6)})["Output"]
        a = end(attr(g, "fc_base", "FLOAT_VECTOR"), attr(g, "fc_q", "QUATERNION"), ha)
        b = end(sample(g, posts, attr(g, "fc_base", "FLOAT_VECTOR"), nxt),
                sample(g, posts, attr(g, "fc_q", "QUATERNION"), nxt, "QUATERNION"), hb)
        d = g.vmath("SUBTRACT", b, a)
        rot = g.node("FunctionNodeAlignRotationToVector", props={"axis": "X", "pivot_axis": "AUTO"},
                     Rotation=attr(g, "nk_rot", "QUATERNION"), Vector=d)["Rotation"]
        size = g.combine(g.math("ADD", g.vmath("LENGTH", d)["Value"], g.math("MULTIPLY", over, 2.0)), rail_t, rail_h)
        ctr = g.vmath("SCALE", g.vmath("ADD", a, b), scale=0.5)
        pts = g.node("GeometryNodeSetPosition", Geometry=lv, Position=ctr)["Geometry"]
        pts = store(g, pts, "fc_q", rot, "QUATERNION")
        pts = store(g, pts, "fc_c", ctr, "FLOAT_VECTOR")
        pts = store(g, pts, "fc_size", size, "FLOAT_VECTOR")
    pts = paint(g, weather, wood_c, grey_c, seed)(pts, 35)
    with g.frame("One chamfered box per rail; grain along the rail"):
        boxes = g.group(chamfer_boxes(), Points=pts, Rotation=attr(g, "fc_q", "QUATERNION"),
                        Size=attr(g, "fc_size", "FLOAT_VECTOR"), Chamfer=0.01)["Mesh"]
        out = grain(g, boxes, swap=True)
    g.output("Rails", "GEOMETRY", out, desc="All rails as one mesh, with nk_color, nk_dark, nk_rand, nk_grain")
    return g.finish()


# ---- materials -----------------------------------------------------------------------------------------------
@once
def build_meadow_shader():
    """Meadow ground: per-vertex colour from Geometry Nodes, mottled at two scales, with a fine grassy bump."""
    g = Graph("Curve Fence Meadow", kind="SHADER",
              description="Meadow ground seen from a few metres: the Geometry Nodes colour (nk_color) mottled by "
                          "a broad and a fine noise, slightly yellower where it is brighter, with a fine bump of "
                          "short grass")
    col = g.input("Color", "COLOR", lin("#5F8432"), desc="Ground colour (wire attribute nk_color here)")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True, desc="Texture coordinate in metres")
    mottle = g.input("Mottle", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR", desc="Strength of the mottling")
    bump = g.input("Bump", "FLOAT", 0.4, min=0.0, max=1.0, subtype="FACTOR", desc="Strength of the grass bump")
    with g.frame("Mottle: broad and fine noise, brighter patches turn yellower"):
        broad = g.node("ShaderNodeTexNoise", Vector=vec, Scale=0.6, Detail=3.0)["Factor"]
        fine = g.node("ShaderNodeTexNoise", Vector=vec, Scale=7.0, Detail=2.0)["Factor"]
        k = g.math("ADD", g.math("MULTIPLY", broad, 0.6), g.math("MULTIPLY", fine, 0.4))
        k = g.math("MULTIPLY_ADD", g.math("SUBTRACT", k, 0.5), g.math("MULTIPLY", mottle, 1.6), 1.0)
        warm = g.mix(g.math("SUBTRACT", k, 1.0, clamp=True), col, lin("#C8B860"), data_type="RGBA")["Result"]
        out = g.vmath("SCALE", warm, scale=k)
    with g.frame("Bump: fine noise stretched upright, like short grass"):
        grass = g.node("ShaderNodeTexNoise", Vector=g.vmath("MULTIPLY", vec, (60.0, 60.0, 10.0)), Scale=1.0,
                       Detail=1.0)["Factor"]
        nrm = g.node("ShaderNodeBump", Strength=bump, Distance=0.02, Height=grass)["Normal"]
    g.output("Color", "COLOR", out, desc="Ground colour")
    g.output("Roughness", "FLOAT", 0.9, desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Bumped normal")
    return g.finish(split_inputs=False)


def materials():
    wood = make_material("Curve Fence Wood", wood_grain, **{
        "Vector": "attr:nk_grain", "Light Color": "attr:nk_color", "Dark Color": "attr:nk_dark",
        "Ring Scale": 60.0, "Distortion": 1.2, "Fibre": 1.0, "Roughness": 0.85, "Bump": 0.5})
    grass = make_material("Curve Fence Grass", build_meadow_shader(), **{"Color": "attr:nk_color", "Mottle": 0.5})
    flower = make_material("Curve Fence Flower", attribute_tint, **{
        "Base Color": lin("#F2E9C8"), "Attribute Weight": 0.0, "Value Variation": 0.2, "Hue Variation": 0.15,
        "Roughness": 0.6})
    return wood, grass, flower


# ---- scenes --------------------------------------------------------------------------------------------------
def path(sc, name, pts, cyclic=False):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    sp.use_cyclic_u = cyclic
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


SCENES = {
    # an S across a hillside, seen three-quarter from below the slope
    "Fence": dict(pts=[(3, -16, 0), (-1, -6, 0), (1, 4, 0), (-3, 14, 0), (-1, 24, 0), (4, 34, 0), (8, 44, 0)],
                  cyclic=False, cam=((-1.5, -22.5, 1.7), (2.0, 0.0, 1.2), 28),
                  ground={"Meadow Centre": (1.0, -12.0, 0.0)}, preset={}),
    # a closed circle paddock seen from above
    "Fence Transfer": dict(pts=[(9 * math.cos(a), 9 * math.sin(a), 0) for a in [i * TAU / 8 for i in range(8)]],
                           cyclic=True, cam=((0.0, -21.0, 11.0), (0.0, 0.5, 0.0), 35),
                           ground={"Hill Height": 0.0, "Roll Height": 0.6}, preset={"Post Spacing": 2.0, "Seed": 3}),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--render")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--frame", type=int, default=1)
    ap.add_argument("--scene", default="", help="render this scene instead of the first")
    a = ap.parse_args(argv)

    sc0 = S.reset()
    wood, grass, flower = materials()
    fence_g, ground_g = build_fence(wood, grass), build_ground()
    for i, (name, cfg) in enumerate(SCENES.items()):
        sc = sc0 if i == 0 else bpy.data.scenes.new(name)
        sc.name = name
        sc.render.fps, sc.frame_start, sc.frame_end = S.FPS, 1, 48
        crv = path(sc, f"{name} Path", cfg["pts"], cfg["cyclic"])
        land, lmod = S.holder(f"{name} Ground", crv, ground_g, sc=sc)
        inspect.set_modifier_inputs(lmod, {"Grass Material": grass, "Flower Material": flower, **cfg["ground"]})
        fence, mod = S.holder(f"{name} Fence", crv, fence_g, sc=sc)
        inspect.set_modifier_inputs(mod, {"Path": crv.name, "Ground": land.name, **cfg["preset"]})
        S.light_world(sc=sc, sun_elev=11, sun_azim=215, strength=5.0, sun_color="#FFC98C",
                      sky_top="#7FA6CC", sky_horizon="#EED8B8", sky_strength=0.8)
        camera(sc, *cfg["cam"])
        w = a.width
        S.render_setup(sc=sc, width=w, height=int(w * 0.5625) // 2 * 2, samples=a.samples,
                       look="Medium High Contrast")
        S.post(sc=sc, haze_color="#EED3AE", haze_start=10.0, haze_depth=100.0, haze_amount=0.6, glare=0.0,
               sky_top="#6A92C0", sky_horizon="#F2D6B0")
        sc.frame_set(a.frame)
        st = inspect.evaluated_stats(fence, sc)
        print(f"SCENE {name}: fence verts {st['verts']} faces {st['faces']} warnings "
              f"{[x.message for x in mod.node_warnings] + [x.message for x in lmod.node_warnings]}")
    problems = inspect.check_groups()
    print("LINT", len(problems), *problems, sep="\n  ")
    out = pathlib.Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
    if a.render:
        sc = bpy.data.scenes[a.scene or next(iter(SCENES))]
        if bpy.context.window:
            bpy.context.window.scene = sc
        sc.frame_set(a.frame)
        sc.render.filepath = str(pathlib.Path(a.render).resolve())
        bpy.ops.render.render(write_still=True, scene=sc.name)
        print("RENDERED", sc.render.filepath)


main()
