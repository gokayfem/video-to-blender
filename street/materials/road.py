"""Road materials: cobble stone, mortar, curb stone, verge turf, grass blades and verge flowers.

Every material reads its base tint from the `ss_color` attribute written in Geometry Nodes (so the Palette
panel of SS Road drives it) and adds only small procedural variation on top: value noise, a darkened stone
shoulder where the dome turns down into the mortar (reads as the dark gap), and a light bump.
Colours were sampled from reference/frames t00, t07, t12: lit cobble tops #9C897D, cobble median #807060,
gaps #4E4A3B, curb tops #887D77, gutter grass #5D5437..#625F41.
"""
import bpy
from street.materials import common


class _M:
    """Tiny shader-node builder for one material (links by socket name, values as constants)."""

    def __init__(self, name):
        self.m = common.material(name)
        self.nt = self.m.node_tree
        self.x = 0

    def n(self, idname, props=None, **ins):
        b = self.nt.nodes.new(idname)
        for k, v in (props or {}).items():
            setattr(b, k, v)
        b.location = (self.x, 0)
        self.x += 200
        for k, v in ins.items():
            self.set(b.inputs[k], v)
        return b

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, sock)
        elif isinstance(v, bpy.types.Node):
            self.nt.links.new(v.outputs[0], sock)
        elif isinstance(v, (tuple, list)):
            n = len(sock.default_value)
            sock.default_value = (list(v) + [1.0] * n)[:n]
        else:
            sock.default_value = v

    def attr(self, name):
        return self.n("ShaderNodeAttribute", props={"attribute_type": "GEOMETRY", "attribute_name": name})

    def coords(self):
        return self.n("ShaderNodeTexCoord").outputs["Object"]

    def noise(self, scale, detail=3.0, rough=0.55, vec=None):
        return self.n("ShaderNodeTexNoise", Vector=vec or self.coords(), Scale=scale, Detail=detail,
                      Roughness=rough)

    def math(self, op, a, b=0.0, clamp=False):
        n = self.n("ShaderNodeMath", props={"operation": op, "use_clamp": clamp})
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        return n

    def mapr(self, v, a0, a1, b0, b1):
        return self.n("ShaderNodeMapRange", Value=v, **{"From Min": a0, "From Max": a1, "To Min": b0,
                                                        "To Max": b1})

    def mixc(self, fac, a, b, blend="MIX"):
        n = self.n("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": blend, "clamp_factor": True})
        self.set(n.inputs["Factor"], fac)
        self.set(next(x for x in n.inputs if x.identifier == "A_Color"), a)
        self.set(next(x for x in n.inputs if x.identifier == "B_Color"), b)
        return next(x for x in n.outputs if x.identifier == "Result_Color")

    def bsdf(self, color, rough=0.8, normal=None, spec=0.3):
        b = self.n("ShaderNodeBsdfPrincipled", **{"Base Color": color, "Roughness": rough})
        b.inputs["Specular IOR Level"].default_value = spec
        if normal is not None:
            self.set(b.inputs["Normal"], normal)
        out = self.n("ShaderNodeOutputMaterial")
        self.nt.links.new(b.outputs[0], out.inputs["Surface"])
        return self.m

    def bump(self, height, strength, dist=0.02):
        return self.n("ShaderNodeBump", Strength=strength, Distance=dist, Height=height).outputs["Normal"]

    def normal_z(self):
        geo = self.n("ShaderNodeNewGeometry")
        return self.n("ShaderNodeSeparateXYZ", Vector=geo.outputs["Normal"]).outputs["Z"]


def cobble():
    m = _M("SS Cobble")
    tint = m.attr("ss_color").outputs["Color"]
    grain = m.noise(14.0, 4.0, 0.6)
    mott = m.mapr(grain.outputs["Fac"], 0.3, 0.7, 0.8, 1.12)
    col = m.mixc(1.0, tint, mott.outputs[0], blend="MULTIPLY")
    # shoulder: where the dome turns down into the mortar the stone darkens (soft occlusion of the gap)
    shoulder = m.mapr(m.normal_z(), 0.35, 0.9, 0.0, 1.0)
    col = m.mixc(shoulder.outputs[0], m.mixc(1.0, col, (0.6, 0.5, 0.42), blend="MULTIPLY"), col)
    pores = m.noise(60.0, 2.0, 0.5)
    return m.bsdf(col, 0.72, m.bump(pores.outputs["Fac"], 0.12))


def mortar():
    m = _M("SS Mortar")
    tint = m.attr("ss_color").outputs["Color"]
    dirt = m.noise(9.0, 3.0, 0.6)
    var = m.mapr(dirt.outputs["Fac"], 0.3, 0.7, 0.75, 1.2)
    col = m.mixc(1.0, tint, var.outputs[0], blend="MULTIPLY")
    return m.bsdf(col, 0.95, m.bump(m.noise(40.0).outputs["Fac"], 0.25))


def curb():
    m = _M("SS Curb")
    tint = m.attr("ss_color").outputs["Color"]
    grain = m.noise(10.0, 5.0, 0.65)
    var = m.mapr(grain.outputs["Fac"], 0.3, 0.7, 0.85, 1.1)
    col = m.mixc(1.0, tint, var.outputs[0], blend="MULTIPLY")
    shoulder = m.mapr(m.normal_z(), 0.2, 0.9, 0.0, 1.0)
    col = m.mixc(shoulder.outputs[0], m.mixc(1.0, col, (0.7, 0.72, 0.78), blend="MULTIPLY"), col)
    return m.bsdf(col, 0.8, m.bump(m.noise(45.0, 3.0).outputs["Fac"], 0.15))


def turf():
    """Ground under the grass: olive turf with patches of bare earth."""
    m = _M("SS Verge Turf")
    tint = m.attr("ss_color").outputs["Color"]
    patches = m.noise(3.5, 3.0, 0.6)
    bare = m.mapr(patches.outputs["Fac"], 0.58, 0.72, 0.0, 0.8)
    earth = (0.12, 0.085, 0.05)
    col = m.mixc(bare.outputs[0], tint, earth)
    fine = m.mapr(m.noise(30.0).outputs["Fac"], 0.3, 0.7, 0.8, 1.15)
    col = m.mixc(1.0, col, fine.outputs[0], blend="MULTIPLY")
    return m.bsdf(col, 0.95, m.bump(m.noise(50.0).outputs["Fac"], 0.15))


def grass():
    """Blades: per-tuft tint, darker toward the root (ss_tip runs 0 at the root to 1 at the tip)."""
    m = _M("SS Verge Grass")
    tint = m.attr("ss_color").outputs["Color"]
    tip = m.attr("ss_tip").outputs["Fac"]
    shade = m.mapr(tip, 0.0, 1.0, 0.6, 1.2)
    col = m.mixc(1.0, tint, shade.outputs[0], blend="MULTIPLY")
    b = m.bsdf(col, 0.7, spec=0.4)
    for n in m.nt.nodes:
        if n.bl_idname == "ShaderNodeBsdfPrincipled":
            n.inputs["Subsurface Weight"].default_value = 0.0
    return b


def flower():
    m = _M("SS Verge Flower")
    tint = m.attr("ss_color").outputs["Color"]
    return m.bsdf(tint, 0.6)


def build():
    """All road materials by key."""
    return {"cobble": cobble(), "mortar": mortar(), "curb": curb(), "turf": turf(), "grass": grass(),
            "flower": flower()}
