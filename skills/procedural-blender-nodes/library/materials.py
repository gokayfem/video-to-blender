"""Shader node groups for procedural surfaces, used inside materials. Each group returns the terms a Principled
BSDF takes (Color, Roughness, Normal, and Emission/Sheen where they matter), so a material is one group node wired
into one BSDF: `make_material("Wall", stucco, Color=(0.8, 0.6, 0.4, 1))`.

Texture coordinates come in through a `Vector` input (object coordinates in metres by default when built with
`make_material`); per-piece variation comes from Geometry Nodes through the named attributes `nk_color`
(FLOAT_COLOR) and `nk_rand` (FLOAT 0..1), which NK Attribute Tint reads. A missing attribute reads as 0, so every
term here is written so that 0 means "no effect"."""
import math
import bpy
from nodekit.graph import Graph, layout
from nodekit.library import nodegroup

TAU = 2.0 * math.pi


def lin(hexstr, a=1.0):
    """'#RRGGBB' (sRGB, as picked from a reference) -> linear RGBA."""
    h = hexstr.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return (*[x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c], a)


def _doc(fn):
    return fn.__doc__.strip().split("\n\n")[0].replace("\n", " ")


# ---- small node idioms (python helpers, not groups) ------------------------------------------------------------
def _noise(g, vec, scale, detail=3.0, rough=0.55, distortion=0.0):
    n = g.node("ShaderNodeTexNoise", props={"noise_dimensions": "3D"}, Vector=vec, Scale=scale, Detail=detail,
               Roughness=rough, Distortion=distortion)
    return n["Factor"]


def _mixc(g, fac, a, b, blend="MIX"):
    n = g.node("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": blend, "clamp_factor": True})
    return n.set(Factor=fac, A=a, B=b)["Result"]


def _tone(g, color, fac):
    """color * fac (fac a float)."""
    return g.vmath("SCALE", color, scale=fac)["Vector"]


def _bump(g, height, strength, distance=0.02):
    return g.node("ShaderNodeBump", Strength=strength, Distance=distance, Height=height)["Normal"]


def _coords(g, vec, scale):
    return g.vmath("MULTIPLY", vec, g.combine(scale, scale, scale))["Vector"]


def _vector_input(g, scale_default=1.0):
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True,
                  desc="Texture coordinate in metres (object coordinates; make_material wires them by default)")
    scale = g.input("Scale", "FLOAT", scale_default, min=0.001, max=1000.0,
                    desc="Pattern scale: features per metre relative to the defaults")
    return vec, scale


# ---- groups ----------------------------------------------------------------------------------------------------
@nodegroup("NK Attribute Tint", kind="SHADER", tags=["material", "attribute", "variation", "tint", "color"],
           use="houses, props, scattered rocks, leaves, crowds: any instances painted per piece by Geometry Nodes")
def attribute_tint():
    """Per-piece colour from Geometry Nodes: nk_color replaces the base colour where present, nk_rand varies it.

    nk_color (FLOAT_COLOR) is mixed over Base Color by Attribute Weight wherever it is non-black (a missing
    attribute reads as black, so the base shows). nk_rand (FLOAT 0..1) darkens by up to Value Variation, shifts hue
    by up to +-Hue Variation and roughens by up to Roughness Variation; nk_rand = 0 (or missing) changes nothing.
    """
    g = Graph("NK Attribute Tint", kind="SHADER", description=_doc(attribute_tint))
    base = g.input("Base Color", "COLOR", lin("#C8A27A"), desc="Colour used where nk_color is missing")
    weight = g.input("Attribute Weight", "FLOAT", 1.0, min=0.0, max=1.0, subtype="FACTOR",
                     desc="How much nk_color replaces Base Color where it is present")
    v_var = g.input("Value Variation", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR",
                    desc="Darken by up to this much per piece (from nk_rand)")
    h_var = g.input("Hue Variation", "FLOAT", 0.02, min=0.0, max=0.5, subtype="FACTOR",
                    desc="Shift hue by up to +- this much per piece (0.02 is subtle, 0.1 is varied)")
    rough = g.input("Roughness", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", desc="Base roughness")
    r_var = g.input("Roughness Variation", "FLOAT", 0.1, min=0.0, max=1.0, subtype="FACTOR",
                    desc="Add up to this much roughness per piece (from nk_rand)")
    with g.frame("Read nk_color and nk_rand (missing attributes read as 0)"):
        ac = g.node("ShaderNodeAttribute", props={"attribute_type": "GEOMETRY", "attribute_name": "nk_color"})
        ar = g.node("ShaderNodeAttribute", props={"attribute_type": "GEOMETRY", "attribute_name": "nk_rand"})
        rnd = ar["Factor"]
    with g.frame("Colour: nk_color over the base where it is non-black"):
        present = g.math("GREATER_THAN", g.vmath("LENGTH", ac["Vector"])["Value"], 1e-5)
        col = _mixc(g, g.math("MULTIPLY", present, weight), base, ac["Color"])
    with g.frame("Variation: darken by rand, hue +- sin(2 pi rand), roughen by rand"):
        val = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", rnd, v_var))
        hue = g.math("ADD", 0.5, g.math("MULTIPLY", g.math("SINE", g.math("MULTIPLY", rnd, TAU)), h_var))
        hs = g.node("ShaderNodeHueSaturation", Hue=hue, Saturation=1.0, Value=val, Fac=1.0, Color=col)
        r = g.math("MULTIPLY_ADD", rnd, r_var, rough, clamp=True)
    g.output("Color", "COLOR", hs["Color"], desc="Tinted colour")
    g.output("Roughness", "FLOAT", r, desc="Roughness with per-piece variation")
    g.output("Random", "FLOAT", rnd, desc="nk_rand, for further variation downstream")
    g.output("Present", "FLOAT", present, desc="1 where nk_color is present")
    return g.finish()


@nodegroup("NK Stucco", kind="SHADER", tags=["material", "plaster", "wall", "grime"],
           use="plastered walls, render, adobe, painted masonry, cottages, town houses")
def stucco():
    """Soft mottled lime plaster with fine speckle, a pitted bump and grime rising from the base of the wall.

    Mottle is large soft blotches plus fine speckle; grime is a streaky darkening from Base Height up to Base
    Height + Grime Height (object Z in metres), multiplied toward Grime Color.
    """
    g = Graph("NK Stucco", kind="SHADER", description=_doc(stucco))
    vec, scale = _vector_input(g)
    color = g.input("Color", "COLOR", lin("#D9B48A"), desc="Clean plaster colour (wire NK Attribute Tint here)")
    grime_c = g.input("Grime Color", "COLOR", lin("#4A3A2A"), desc="Colour the base of the wall is dirtied toward")
    mottle = g.input("Mottle", "FLOAT", 0.15, min=0.0, max=1.0, subtype="FACTOR",
                     desc="Strength of the soft blotchy tone variation")
    base_h = g.input("Base Height", "FLOAT", 0.0, subtype="DISTANCE", desc="Height (object Z) of the ground line")
    grime_h = g.input("Grime Height", "FLOAT", 1.0, min=0.01, max=100.0, subtype="DISTANCE",
                      desc="How high the grime rises above Base Height")
    grime = g.input("Grime", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", desc="Grime amount")
    rough = g.input("Roughness", "FLOAT", 0.92, min=0.0, max=1.0, subtype="FACTOR", desc="Base roughness")
    bump = g.input("Bump", "FLOAT", 0.12, min=0.0, max=1.0, subtype="FACTOR", desc="Bump strength of the pits")
    with g.frame("Mottle: soft blotches and fine speckle"):
        p = _coords(g, vec, scale)
        blot = _noise(g, p, 0.9, 5.0, 0.6)
        fine = _noise(g, p, 14.0, 3.0, 0.5)
        lo = g.math("SUBTRACT", 1.0, mottle)
        hi = g.math("MULTIPLY_ADD", mottle, 0.6, 1.0)
        tone = g.math("ADD", g.map_range(blot, 0.3, 0.7, lo, hi)["Result"],
                      g.map_range(fine, 0.3, 0.7, -0.03, 0.03)["Result"])
        col = _tone(g, color, tone)
    with g.frame("Grime: streaky darkening rising from the base"):
        z = g.separate(vec)["Z"]
        rise = g.map_range(z, base_h, g.math("ADD", base_h, grime_h), 1.0, 0.0, interp="SMOOTHSTEP")["Result"]
        streak_p = g.vmath("MULTIPLY", p, (3.0, 3.0, 0.4))["Vector"]
        streak = g.map_range(_noise(g, streak_p, 2.0, 3.0), 0.35, 0.65, 0.5, 1.0)["Result"]
        dirty = _mixc(g, 0.85, col, grime_c, "MULTIPLY")
        amt = g.math("MULTIPLY", g.math("MULTIPLY", rise, streak), grime)
        col = _mixc(g, amt, col, dirty)
    with g.frame("Pits bump and roughness"):
        pits = _noise(g, p, 6.0, 4.0, 0.6)
        nrm = _bump(g, pits, bump, 0.02)
        r = g.math("ADD", rough, g.math("MULTIPLY", amt, 0.05), clamp=True)
    g.output("Color", "COLOR", col, desc="Plaster colour")
    g.output("Roughness", "FLOAT", r, desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Bumped normal")
    g.output("Grime", "FLOAT", amt, desc="Grime mask 0..1")
    return g.finish()


@nodegroup("NK Wood Grain", kind="SHADER", tags=["material", "wood", "grain", "timber"],
           use="beams, planks, furniture, barrels, doors, fences, log ends, handles")
def wood_grain():
    """Wood: distorted growth rings around the object Z axis (grain runs along Z) with long fibre streaks.

    Rings are a saw-profile ring wave (sharp latewood edge), distorted by noise; fibres are noise stretched along
    Z. Orient pieces so their length runs along object Z, or rotate the Vector.
    """
    g = Graph("NK Wood Grain", kind="SHADER", description=_doc(wood_grain))
    vec, scale = _vector_input(g)
    light = g.input("Light Color", "COLOR", lin("#A8784A"), desc="Earlywood colour (wire NK Attribute Tint here)")
    dark = g.input("Dark Color", "COLOR", lin("#5A3A22"), desc="Latewood (ring) colour")
    rings = g.input("Ring Scale", "FLOAT", 30.0, min=0.01, max=1000.0, desc="Growth rings per metre")
    distort = g.input("Distortion", "FLOAT", 3.0, min=0.0, max=50.0, desc="How wavy the rings are")
    fibre = g.input("Fibre", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", desc="Strength of the fibre streaks")
    rough = g.input("Roughness", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", desc="Base roughness")
    bump = g.input("Bump", "FLOAT", 0.15, min=0.0, max=1.0, subtype="FACTOR", desc="Bump strength of the grain")
    with g.frame("Rings: saw-profile ring wave around Z, distorted"):
        p = _coords(g, vec, scale)
        wave = g.node("ShaderNodeTexWave", props={"wave_type": "RINGS", "rings_direction": "Z",
                                                  "wave_profile": "SAW"},
                      Vector=p, Scale=g.math("MULTIPLY", rings, 0.159155), Distortion=distort, Detail=2.0,
                      **{"Detail Scale": 1.5, "Detail Roughness": 0.5})
        ring = g.math("POWER", wave["Factor"], 3.0)
    with g.frame("Fibres: noise stretched along Z"):
        fp = g.vmath("MULTIPLY", p, (40.0, 40.0, 1.5))["Vector"]
        fib = g.map_range(_noise(g, fp, 1.0, 4.0, 0.6), 0.3, 0.7, 0.0, 1.0)["Result"]
        blot = g.map_range(_noise(g, p, 2.0, 3.0), 0.3, 0.7, 0.9, 1.08)["Result"]
    with g.frame("Colour from rings and fibres; latewood is a touch glossier"):
        t = g.math("ADD", g.math("MULTIPLY", ring, 0.85), g.math("MULTIPLY", fib, g.math("MULTIPLY", fibre, 0.5)),
                   clamp=True)
        col = _tone(g, _mixc(g, t, light, dark), blot)
        r = g.math("SUBTRACT", rough, g.math("MULTIPLY", ring, 0.12), clamp=True)
        nrm = _bump(g, g.math("ADD", g.math("MULTIPLY", fib, 0.5), ring), bump, 0.005)
    g.output("Color", "COLOR", col, desc="Wood colour")
    g.output("Roughness", "FLOAT", r, desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Bumped normal")
    g.output("Ring", "FLOAT", ring, desc="Ring mask 0..1 (latewood = 1)")
    return g.finish()


@nodegroup("NK Stone", kind="SHADER", tags=["material", "stone", "cobble", "rock", "masonry", "cells"],
           use="cobbles, flagstones, rubble walls, dry-stone walls, plinths, paving, rocks")
def stone():
    """Irregular stones in mortar: per-cell tone and hue, rounded worn edges, grain, and a bump that domes each
    stone and sinks the joints.

    Cells are Voronoi cells (Scale x Stone Scale per metre); the distance to the cell edge gives the mortar joint,
    the rounded shoulder and the paler worn rim.
    """
    g = Graph("NK Stone", kind="SHADER", description=_doc(stone))
    vec, scale = _vector_input(g)
    color = g.input("Color", "COLOR", lin("#9A8C7A"), desc="Average stone colour (wire NK Attribute Tint here)")
    mortar_c = g.input("Mortar Color", "COLOR", lin("#7C7266"), desc="Colour of the joints")
    cells = g.input("Stone Scale", "FLOAT", 4.0, min=0.01, max=1000.0, desc="Stones per metre")
    var = g.input("Variation", "FLOAT", 0.35, min=0.0, max=1.0, subtype="FACTOR",
                  desc="Per-stone tone and hue variation")
    wear = g.input("Edge Wear", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR",
                   desc="How rounded and pale-worn the stone edges are")
    joint = g.input("Mortar Width", "FLOAT", 0.06, min=0.0, max=0.5, subtype="FACTOR",
                    desc="Joint width as a share of a stone")
    rough = g.input("Roughness", "FLOAT", 0.82, min=0.0, max=1.0, subtype="FACTOR", desc="Stone roughness")
    bump = g.input("Bump", "FLOAT", 0.4, min=0.0, max=1.0, subtype="FACTOR", desc="Bump strength")
    with g.frame("Cells: per-stone random colour and the distance to the cell edge"):
        p = _coords(g, vec, scale)
        f1 = g.node("ShaderNodeTexVoronoi", props={"voronoi_dimensions": "3D", "feature": "F1"},
                    Vector=p, Scale=cells, Randomness=0.9)
        edge = g.node("ShaderNodeTexVoronoi", props={"voronoi_dimensions": "3D", "feature": "DISTANCE_TO_EDGE"},
                      Vector=p, Scale=cells, Randomness=0.9)
        d = edge["Distance"]
        cell_v = g.separate(f1["Color"])["X"]
    with g.frame("Stone colour: per-cell tone and hue, grain"):
        tone = g.math("ADD", 1.0, g.math("MULTIPLY", g.math("SUBTRACT", cell_v, 0.5), g.math("MULTIPLY", var, 1.2)))
        grain = g.map_range(_noise(g, p, 30.0, 3.0, 0.6), 0.3, 0.7, 0.9, 1.08)["Result"]
        col = _tone(g, color, g.math("MULTIPLY", tone, grain))
        hue = _mixc(g, 1.0, col, _tone(g, f1["Color"], 2.0), "MULTIPLY")
        col = _mixc(g, g.math("MULTIPLY", var, 0.35), col, hue)
    with g.frame("Edges: joint mask, rounded shoulder, paler worn rim"):
        j = g.math("MULTIPLY", joint, 0.5)
        stone_m = g.map_range(d, j, g.math("ADD", j, 0.02), 0.0, 1.0)["Result"]
        shoulder_w = g.math("ADD", j, g.math("MULTIPLY_ADD", wear, 0.25, 0.03))
        dome = g.map_range(d, j, shoulder_w, 0.0, 1.0, interp="SMOOTHSTEP")["Result"]
        rim = g.math("MULTIPLY", g.math("SUBTRACT", 1.0, dome), stone_m)
        chips = g.map_range(_noise(g, p, 12.0, 3.0), 0.35, 0.65, 0.4, 1.0)["Result"]
        worn = _mixc(g, 0.35, col, (1.0, 0.97, 0.92, 1.0), "SCREEN")
        col = _mixc(g, g.math("MULTIPLY", g.math("MULTIPLY", rim, wear), chips), col, worn)
        mortar = _tone(g, mortar_c, g.map_range(_noise(g, p, 40.0, 2.0), 0.3, 0.7, 0.8, 1.1)["Result"])
        col = _mixc(g, stone_m, mortar, col)
    with g.frame("Bump: domed stones, sunk joints; mortar is rougher"):
        height = g.math("ADD", g.math("MULTIPLY", dome, 1.0), g.math("MULTIPLY", grain, 0.15))
        nrm = _bump(g, height, bump, 0.02)
        r = g.mix(stone_m, 1.0, g.math("ADD", rough, g.math("MULTIPLY", rim, 0.08)))
    g.output("Color", "COLOR", col, desc="Stone and mortar colour")
    g.output("Roughness", "FLOAT", r["Result"], desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Bumped normal")
    g.output("Stone", "FLOAT", stone_m, desc="1 on stone, 0 in the joints")
    g.output("Cell", "FLOAT", cell_v, desc="Random value per stone 0..1")
    return g.finish()


@nodegroup("NK Felt", kind="SHADER", tags=["material", "felt", "fabric", "wool", "sheen", "cloth"],
           use="felt toys, hats, coats, wool, plush characters, cushions, soft props")
def felt():
    """Matte felt: low mottling, a soft sheen at grazing angles, a little subsurface and a fine fibre-fuzz bump.

    Wire Sheen to the Principled BSDF's Sheen Weight and Sheen Tint to Sheen Tint (make_material does this).
    """
    g = Graph("NK Felt", kind="SHADER", description=_doc(felt))
    vec, scale = _vector_input(g)
    color = g.input("Color", "COLOR", lin("#B4473A"), desc="Felt colour (wire NK Attribute Tint here)")
    mottle = g.input("Mottle", "FLOAT", 0.08, min=0.0, max=1.0, subtype="FACTOR", desc="Tone variation")
    fuzz_s = g.input("Fuzz Scale", "FLOAT", 300.0, min=1.0, max=10000.0, desc="Fibre fuzz features per metre")
    fuzz = g.input("Fuzz", "FLOAT", 0.3, min=0.0, max=1.0, subtype="FACTOR", desc="Fibre fuzz bump strength")
    sheen = g.input("Sheen", "FLOAT", 0.6, min=0.0, max=1.0, subtype="FACTOR", desc="Sheen weight (soft rim)")
    rough = g.input("Roughness", "FLOAT", 0.95, min=0.0, max=1.0, subtype="FACTOR", desc="Roughness")
    with g.frame("Mottle: low soft variation"):
        p = _coords(g, vec, scale)
        m = _noise(g, p, 3.0, 2.0, 0.5)
        tone = g.map_range(m, 0.3, 0.7, g.math("SUBTRACT", 1.0, mottle), g.math("ADD", 1.0, mottle))["Result"]
        col = _tone(g, color, tone)
    with g.frame("Fibre fuzz bump; sheen tinted by a lighter felt colour"):
        fz = _noise(g, p, fuzz_s, 4.0, 0.75)
        nrm = _bump(g, fz, fuzz, 0.002)
        tint = _mixc(g, 0.3, col, (1.0, 1.0, 1.0, 1.0))
    g.output("Color", "COLOR", col, desc="Felt colour")
    g.output("Roughness", "FLOAT", rough, desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Fuzz-bumped normal")
    g.output("Sheen", "FLOAT", sheen, desc="Sheen weight")
    g.output("Sheen Tint", "COLOR", tint, desc="Sheen tint")
    g.output("Subsurface", "FLOAT", g.math("MULTIPLY", sheen, 0.15), desc="Subsurface weight")
    return g.finish()


@nodegroup("NK Terracotta", kind="SHADER", tags=["material", "clay", "terracotta", "pottery", "brick"],
           use="flower pots, roof tiles, bricks, amphorae, floor tiles, clay figures")
def terracotta():
    """Unglazed fired clay: warm mottling between two clay tones, chalky pale bloom, pores, per-piece darkening.

    Variation (wire nk_rand) darkens the whole piece toward Dark Color; Bloom adds the pale efflorescence that old
    pots get.
    """
    g = Graph("NK Terracotta", kind="SHADER", description=_doc(terracotta))
    vec, scale = _vector_input(g)
    color = g.input("Color", "COLOR", lin("#C97A4C"), desc="Fresh clay colour")
    dark = g.input("Dark Color", "COLOR", lin("#A35A3A"), desc="Darker, fired-harder clay colour")
    var = g.input("Variation", "FLOAT", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                  desc="Per-piece darkening toward Dark Color (wire nk_rand)")
    bloom = g.input("Bloom", "FLOAT", 0.25, min=0.0, max=1.0, subtype="FACTOR", desc="Chalky pale efflorescence")
    rough = g.input("Roughness", "FLOAT", 0.85, min=0.0, max=1.0, subtype="FACTOR", desc="Roughness")
    bump = g.input("Bump", "FLOAT", 0.15, min=0.0, max=1.0, subtype="FACTOR", desc="Pore bump strength")
    with g.frame("Clay mottling between the two tones"):
        p = _coords(g, vec, scale)
        m = _noise(g, p, 6.0, 4.0, 0.55)
        col = _mixc(g, g.map_range(m, 0.35, 0.7, 0.0, 0.7, interp="SMOOTHSTEP")["Result"], color, dark)
        col = _mixc(g, g.math("MULTIPLY", var, 0.7), col, dark)
    with g.frame("Bloom: pale chalky patches"):
        b = g.map_range(_noise(g, p, 2.5, 5.0, 0.6), 0.55, 0.72, 0.0, 1.0, interp="SMOOTHSTEP")["Result"]
        amt = g.math("MULTIPLY", b, g.math("MULTIPLY", bloom, 0.6))
        col = _mixc(g, amt, col, lin("#D8C2A6"))
    with g.frame("Pores and roughness"):
        pores = _noise(g, p, 90.0, 2.0, 0.5)
        nrm = _bump(g, pores, bump, 0.004)
        r = g.math("ADD", rough, g.math("MULTIPLY", amt, 0.1), clamp=True)
    g.output("Color", "COLOR", col, desc="Clay colour")
    g.output("Roughness", "FLOAT", r, desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Pore-bumped normal")
    return g.finish()


@nodegroup("NK Stripes", kind="SHADER", tags=["material", "fabric", "stripes", "canvas", "pattern"],
           use="awnings, deck chairs, sails, flags, bunting, shirts, rugs, barber poles, road markings")
def stripes():
    """Antialiased two-colour stripes along a coordinate, on a woven canvas with a soft sheen.

    One stripe of A and one of B repeat every 2 x Width along Coordinate (Ratio sets A's share); edges are
    smoothed over Softness of a period. Wire Coordinate from an attribute (e.g. distance along an awning) or one
    axis of the object coordinates (make_material uses object X).
    """
    g = Graph("NK Stripes", kind="SHADER", description=_doc(stripes))
    coord = g.input("Coordinate", "FLOAT", 0.0, desc="Position across the stripes (metres or any unit)")
    vec = g.input("Vector", "VECTOR", (0.0, 0.0, 0.0), hide_value=True,
                  desc="Texture coordinate for the weave (object coordinates by default)")
    a = g.input("Color A", "COLOR", lin("#2F6B6A"), desc="First stripe colour")
    b = g.input("Color B", "COLOR", lin("#EDE3CF"), desc="Second stripe colour")
    width = g.input("Width", "FLOAT", 0.1, min=0.0001, max=1000.0, subtype="DISTANCE",
                    desc="Width of one stripe at Ratio 0.5 (a full A + B repeat is 2 x Width)")
    ratio = g.input("Ratio", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR", desc="Share of each repeat in A")
    soft = g.input("Softness", "FLOAT", 0.02, min=0.0, max=0.5, subtype="FACTOR",
                   desc="Edge blur as a share of a repeat (antialiasing)")
    weave_s = g.input("Weave Scale", "FLOAT", 400.0, min=1.0, max=10000.0, desc="Threads per metre (x 1/2 pi)")
    weave = g.input("Weave", "FLOAT", 0.15, min=0.0, max=1.0, subtype="FACTOR", desc="Weave bump strength")
    rough = g.input("Roughness", "FLOAT", 0.85, min=0.0, max=1.0, subtype="FACTOR", desc="Roughness")
    with g.frame("Distance d from the centre of the nearest A stripe, in repeats"):
        cyc = g.math("DIVIDE", coord, g.math("MULTIPLY", g.math("MAXIMUM", width, 0.0001), 2.0))
        x = g.math("ADD", g.math("SUBTRACT", cyc, g.math("MULTIPLY", ratio, 0.5)), 0.5)
        d = g.math("ABSOLUTE", g.math("SUBTRACT", g.math("FRACT", x), 0.5))
    with g.frame("Mask: A inside ratio / 2 of the centre, smoothed over Softness"):
        half = g.math("MULTIPLY", ratio, 0.5)
        s = g.math("MAXIMUM", g.math("MULTIPLY", soft, 0.5), 1e-5)
        mask = g.map_range(d, g.math("SUBTRACT", half, s), g.math("ADD", half, s), 1.0, 0.0,
                           interp="SMOOTHSTEP")["Result"]
        col = _mixc(g, mask, b, a)
    with g.frame("Weave: fine crossing threads"):
        wp = g.vmath("SCALE", vec, scale=weave_s)["Vector"]
        sp = g.separate(wp)
        h = g.math("ADD", g.math("ADD", g.math("SINE", sp["X"]), g.math("SINE", sp["Y"])), g.math("SINE", sp["Z"]))
        nrm = _bump(g, h, weave, 0.0005)
    g.output("Color", "COLOR", col, desc="Stripe colour")
    g.output("Roughness", "FLOAT", rough, desc="Roughness")
    g.output("Normal", "VECTOR", nrm, desc="Weave-bumped normal")
    g.output("Sheen", "FLOAT", 0.35, desc="Sheen weight for a canvas look")
    g.output("Mask", "FLOAT", mask, desc="1 in A stripes, 0 in B stripes")
    return g.finish()


@nodegroup("NK Glow Glass", kind="SHADER", tags=["material", "glass", "emission", "lantern", "light", "glow"],
           use="lanterns, lit windows, lamps, fireflies, candles in jars, glowing orbs, signs")
def glow_glass():
    """Emissive glass with a warm bright core and a darker, redder rim, driven by a strength (e.g. NK Flicker).

    The rim comes from the facing ratio (grazing view) and, if Pane UV is wired (0..1 across a flat pane), from
    the distance to the pane edge. Emission Strength = Strength x Flicker x (1 - Rim x rim mask).
    """
    g = Graph("NK Glow Glass", kind="SHADER", description=_doc(glow_glass))
    core = g.input("Core Color", "COLOR", lin("#FF8C2E"), desc="Emission colour at the bright core")
    rim_c = g.input("Rim Color", "COLOR", lin("#B8461C"), desc="Emission colour at the rim")
    glass = g.input("Glass Color", "COLOR", lin("#3A2410"), desc="Base colour of the glass when unlit")
    strength = g.input("Strength", "FLOAT", 1.5, min=0.0, max=100000.0, desc="Emission strength at the core")
    flick = g.input("Flicker", "FLOAT", 1.0, min=0.0, max=10.0,
                    desc="Strength multiplier (wire an nk_glow attribute written by NK Flicker; 1 = steady)")
    rim = g.input("Rim", "FLOAT", 0.85, min=0.0, max=1.0, subtype="FACTOR", desc="How much darker the rim is")
    rim_w = g.input("Rim Width", "FLOAT", 0.5, min=0.0, max=1.0, subtype="FACTOR",
                    desc="Width of the rim falloff (facing blend)")
    pane = g.input("Pane UV", "VECTOR", (0.5, 0.5, 0.0), desc="0..1 across a flat pane (UV); leave at 0.5 for "
                                                              "rounded glass")
    rough = g.input("Roughness", "FLOAT", 0.2, min=0.0, max=1.0, subtype="FACTOR", desc="Glass roughness")
    with g.frame("Rim mask: grazing view and distance to the pane edge"):
        lw = g.node("ShaderNodeLayerWeight", Blend=rim_w)
        face = g.math("POWER", lw["Facing"], 0.8)
        pv = g.separate(pane)
        e = g.math("MAXIMUM", g.math("ABSOLUTE", g.math("SUBTRACT", pv["X"], 0.5)),
                   g.math("ABSOLUTE", g.math("SUBTRACT", pv["Y"], 0.5)))
        edge = g.map_range(e, 0.2, 0.5, 0.0, 1.0, interp="SMOOTHSTEP")["Result"]
        m = g.math("MAXIMUM", face, edge)
    with g.frame("Emission: core to rim colour, strength falls toward the rim"):
        em = _mixc(g, m, core, rim_c)
        k = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", rim, m))
        st = g.math("MULTIPLY", g.math("MULTIPLY", strength, flick), k)
    g.output("Color", "COLOR", glass, desc="Base colour of the glass")
    g.output("Roughness", "FLOAT", rough, desc="Roughness")
    g.output("Emission", "COLOR", em, desc="Emission colour")
    g.output("Emission Strength", "FLOAT", st, desc="Emission strength")
    g.output("Rim Mask", "FLOAT", m, desc="0 at the core, 1 at the rim")
    return g.finish()


# ---- material helper (plain function, not a group) ------------------------------------------------------------
BSDF_OUTPUTS = {"Color": "Base Color", "Roughness": "Roughness", "Normal": "Normal", "Emission": "Emission Color",
                "Emission Strength": "Emission Strength", "Sheen": "Sheen Weight", "Sheen Tint": "Sheen Tint",
                "Subsurface": "Subsurface Weight", "Metallic": "Metallic", "Specular": "Specular IOR Level",
                "Alpha": "Alpha"}
_COORDS = {"object": "Object", "generated": "Generated", "uv": "UV", "normal": "Normal", "camera": "Camera",
           "window": "Window", "reflection": "Reflection"}


def make_material(name, group, bsdf=None, **inputs):
    """Build (or rebuild) material ``name``: one ``group`` node wired into a Principled BSDF by output name
    (Color -> Base Color, Roughness, Normal, Emission -> Emission Color, Emission Strength, Sheen -> Sheen Weight,
    Sheen Tint, Subsurface -> Subsurface Weight, Metallic, Specular, Alpha).

    ``group`` is a builder (e.g. ``stucco``) or a shader node group. ``inputs`` set group inputs by name
    (``**{"Color A": ...}`` for names with spaces); a value may be a constant, a socket, or a string:
    ``"attr:nk_rand"`` (Attribute node, GEOMETRY type), ``"object"``/``"generated"``/``"uv"`` (texture coordinates)
    or ``"object.x"`` (one axis of them). Unset ``Vector`` inputs get object coordinates and an unset
    ``Coordinate`` gets object X. ``bsdf`` sets Principled inputs directly, e.g. ``{"Specular IOR Level": 0.3}``.
    """
    tree = group() if callable(group) else group
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    gn = nt.nodes.new("ShaderNodeGroup")
    gn.node_tree = tree
    gn.label = tree.name
    pb = nt.nodes.new("ShaderNodeBsdfPrincipled")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(pb.outputs["BSDF"], out.inputs["Surface"])
    cache = {}

    def coord_node():
        if "tc" not in cache:
            cache["tc"] = nt.nodes.new("ShaderNodeTexCoord")
        return cache["tc"]

    def source(spec, sock):
        if spec.startswith("attr:"):
            a = nt.nodes.new("ShaderNodeAttribute")
            a.attribute_type, a.attribute_name = "GEOMETRY", spec[5:]
            return a.outputs[{"VALUE": "Factor", "RGBA": "Color", "VECTOR": "Vector"}.get(sock.type, "Factor")]
        base, _, axis = spec.partition(".")
        if base not in _COORDS:
            raise ValueError(f"make_material: unknown source {spec!r} for {sock.name!r}")
        o = coord_node().outputs[_COORDS[base]]
        if not axis:
            return o
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(o, sep.inputs[0])
        return sep.outputs[axis.upper()]

    defaults = {"Vector": "object", "Coordinate": "object.x"}
    for sock in gn.inputs:
        v = inputs.pop(sock.name, defaults.get(sock.name))
        if v is None:
            continue
        if isinstance(v, str):
            v = source(v, sock)
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        elif isinstance(v, (list, tuple)):
            n = len(sock.default_value)
            sock.default_value = (list(v) + [1.0] * n)[:n]
        else:
            sock.default_value = v
    if inputs:
        raise KeyError(f"make_material: {tree.name} has no inputs {sorted(inputs)}")
    for o in gn.outputs:
        target = BSDF_OUTPUTS.get(o.name)
        if target and target in pb.inputs:
            nt.links.new(o, pb.inputs[target])
    for k, v in (bsdf or {}).items():
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, pb.inputs[k])
        else:
            pb.inputs[k].default_value = v
    layout(nt)
    return m
