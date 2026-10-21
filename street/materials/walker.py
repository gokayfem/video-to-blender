"""Walker materials: felt (hood, flaps, tunic, mittens, legs), knit (scarf), leather (belt, satchel), rubber (boots).

Every material takes its base tint from the `ss_color` attribute the walker groups write, and its procedural
texture coordinates from `ss_local` (the part's rest-pose position, so fuzz and stitches stick to the part while
it moves). The hood dome also writes `ss_seam` = 1 so the felt draws the stitched centre seam only there, and `ss_occ`
(0..1, baked soft shadow around the teardrop pad and down the lower back; absent = 0 elsewhere).
"""
from street.materials import common

# Sizes are in H (the walker's height): fibres and stitches are a few thousandths of H.
FELT_FUZZ = 900.0       # fine fuzz frequency (bump)
FELT_MOTTLE = 14.0      # low-frequency felt mottling (colour)


class _T:
    """Tiny shader-tree helper: nodes with inputs by name, laid out left to right in creation order."""

    def __init__(self, mat):
        self.nt = mat.node_tree
        self.x = -1400

    def n(self, idname, props=None, **inputs):
        b = self.nt.nodes.new(idname)
        for k, v in (props or {}).items():
            setattr(b, k, v)
        b.location = (self.x, 0)
        self.x += 180
        for k, v in inputs.items():
            k = k.replace("_", " ")
            self.link(v, next(s for s in b.inputs if s.name == k and s.enabled))
        return b

    def link(self, v, sock):
        if v is None:
            return
        if hasattr(v, "bl_idname") and hasattr(v, "outputs"):
            v = next(s for s in v.outputs if s.enabled)
        if hasattr(v, "node"):
            self.nt.links.new(v, sock)
        else:
            sock.default_value = v

    def attr(self, name, out="Color"):
        a = self.n("ShaderNodeAttribute", props={"attribute_type": "GEOMETRY", "attribute_name": name})
        return a.outputs[out]

    def math(self, op, a, b=None):
        m = self.n("ShaderNodeMath", props={"operation": op})
        self.link(a, m.inputs[0])
        if b is not None:
            self.link(b, m.inputs[1])
        return m.outputs[0]

    def out(self, shader):
        o = self.n("ShaderNodeOutputMaterial")
        self.link(shader, o.inputs["Surface"])


def _fuzz_bump(t, local, scale, strength, distance=0.002):
    noise = t.n("ShaderNodeTexNoise", Vector=local, Scale=scale, Detail=3.0, Roughness=0.6)
    return t.n("ShaderNodeBump", Strength=strength, Distance=distance, Height=noise.outputs["Fac"])


def felt(name="SS Walker Felt"):
    """Matte felt: mottled tint, soft sheen, a little subsurface wrap, fine fibre fuzz in the normal, and a dark
    stitched seam groove where `ss_seam` is set (hood centre back, below the teardrop pad)."""
    m = common.material(name)
    t = _T(m)
    col = t.attr("ss_color")
    local = t.attr("ss_local", "Vector")
    seam_on = t.attr("ss_seam", "Fac")
    # Low-frequency mottling: felt is never perfectly even.
    mot = t.n("ShaderNodeTexNoise", Vector=local, Scale=FELT_MOTTLE, Detail=2.0)
    mot_f = t.n("ShaderNodeMapRange", Value=mot.outputs["Fac"], From_Min=0.3, From_Max=0.7, To_Min=0.9,
                To_Max=1.08)
    # Seam: a thin line down the back centre (x < 0, |y| small) below the teardrop's point.
    sep = t.n("ShaderNodeSeparateXYZ", Vector=local)
    line = t.n("ShaderNodeMapRange", Value=t.math("ABSOLUTE", sep.outputs["Y"]), From_Min=0.0025, From_Max=0.007,
               To_Min=1.0, To_Max=0.0)
    below = t.math("LESS_THAN", sep.outputs["Z"], 0.70)
    behind = t.math("LESS_THAN", sep.outputs["X"], -0.05)
    seam = t.math("MULTIPLY", t.math("MULTIPLY", line.outputs[0], below), t.math("MULTIPLY", behind, seam_on))
    occ = t.attr("ss_occ", "Fac")
    dark = t.n("ShaderNodeMapRange", Value=seam, To_Min=1.0, To_Max=0.45)
    dark = t.math("MULTIPLY", dark, t.math("SUBTRACT", 1.0, occ))
    tint = t.n("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": "MULTIPLY"}, Factor=1.0, A=col,
               B=t.n("ShaderNodeCombineColor", Red=mot_f.outputs[0], Green=mot_f.outputs[0], Blue=mot_f.outputs[0]))
    tint2 = t.n("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": "MULTIPLY"}, Factor=1.0,
                A=tint, B=t.n("ShaderNodeCombineColor", Red=dark, Green=dark, Blue=dark))
    # Normal: fibre fuzz plus the seam groove.
    fuzz = t.n("ShaderNodeTexNoise", Vector=local, Scale=FELT_FUZZ, Detail=4.0, Roughness=0.7)
    height = t.math("SUBTRACT", t.math("MULTIPLY", fuzz.outputs["Fac"], 0.6), t.math("MULTIPLY", seam, 1.5))
    bump = t.n("ShaderNodeBump", Strength=0.35, Distance=0.003, Height=height)
    b = t.n("ShaderNodeBsdfPrincipled", Base_Color=tint2, Roughness=0.95, Normal=bump)
    b.inputs["Sheen Weight"].default_value = 0.6
    b.inputs["Sheen Roughness"].default_value = 0.5
    b.inputs["Subsurface Weight"].default_value = 0.12
    b.inputs["Subsurface Radius"].default_value = (0.02, 0.012, 0.008)
    b.inputs["Specular IOR Level"].default_value = 0.2
    t.link(tint2, b.inputs["Sheen Tint"])
    t.out(b)
    return m


def knit(name="SS Walker Knit"):
    """Knitted wool: vertical ribs of V stitches (from `ss_local`), fuzzy sheen. Used for the scarf and pom-poms."""
    m = common.material(name)
    t = _T(m)
    col = t.attr("ss_color")
    local = t.attr("ss_local", "Vector")
    sep = t.n("ShaderNodeSeparateXYZ", Vector=local)
    # V stitches: columns across y, rows down z; each row is offset by the distance from the column centre.
    colx = t.math("MULTIPLY", sep.outputs["Y"], 60.0)
    v = t.math("MULTIPLY", t.math("ABSOLUTE", t.math("SUBTRACT", t.math("FRACT", colx), 0.5)), 2.0)
    row = t.math("FRACT", t.math("ADD", t.math("MULTIPLY", sep.outputs["Z"], 75.0), t.math("MULTIPLY", v, 0.5)))
    stitch = t.math("MULTIPLY", t.math("SINE", t.math("MULTIPLY", row, 3.14159)), 1.0)
    shade = t.n("ShaderNodeMapRange", Value=stitch, To_Min=0.7, To_Max=1.0)
    tint = t.n("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": "MULTIPLY"}, Factor=1.0, A=col,
               B=t.n("ShaderNodeCombineColor", Red=shade.outputs[0], Green=shade.outputs[0], Blue=shade.outputs[0]))
    fuzz = t.n("ShaderNodeTexNoise", Vector=local, Scale=700.0, Detail=3.0)
    height = t.math("ADD", stitch, t.math("MULTIPLY", fuzz.outputs["Fac"], 0.4))
    bump = t.n("ShaderNodeBump", Strength=0.5, Distance=0.004, Height=height)
    b = t.n("ShaderNodeBsdfPrincipled", Base_Color=tint, Roughness=0.9, Normal=bump)
    b.inputs["Sheen Weight"].default_value = 0.15
    b.inputs["Sheen Roughness"].default_value = 0.5
    b.inputs["Specular IOR Level"].default_value = 0.2
    t.out(b)
    return m


def leather(name="SS Walker Leather"):
    """Soft worn leather: tint with mottled wear, a little gloss, fine grain bump."""
    m = common.material(name)
    t = _T(m)
    col = t.attr("ss_color")
    local = t.attr("ss_local", "Vector")
    wear = t.n("ShaderNodeTexNoise", Vector=local, Scale=25.0, Detail=3.0)
    w = t.n("ShaderNodeMapRange", Value=wear.outputs["Fac"], From_Min=0.35, From_Max=0.7, To_Min=0.85,
            To_Max=1.15)
    tint = t.n("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": "MULTIPLY"}, Factor=1.0, A=col,
               B=t.n("ShaderNodeCombineColor", Red=w.outputs[0], Green=w.outputs[0], Blue=w.outputs[0]))
    bump = _fuzz_bump(t, local, 400.0, 0.15)
    b = t.n("ShaderNodeBsdfPrincipled", Base_Color=tint, Roughness=0.55, Normal=bump)
    t.out(b)
    return m


def rubber(name="SS Walker Rubber"):
    """Chunky rubber boots: smooth, satin, a faint clear coat."""
    m = common.material(name)
    t = _T(m)
    col = t.attr("ss_color")
    local = t.attr("ss_local", "Vector")
    bump = _fuzz_bump(t, local, 150.0, 0.05)
    b = t.n("ShaderNodeBsdfPrincipled", Base_Color=col, Roughness=0.5, Normal=bump)
    b.inputs["Coat Weight"].default_value = 0.15
    b.inputs["Coat Roughness"].default_value = 0.3
    t.out(b)
    return m
