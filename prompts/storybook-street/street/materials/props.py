"""Materials for SS Props: terracotta, barrel wood, iron, striped awning fabric, foliage, petals, sign wood and
paint, potting soil, and the emissive lantern glass.

Per-piece variation comes from attributes written in Geometry Nodes (read with Attribute nodes, type GEOMETRY):
- ``ss_color``  (FLOAT_COLOR) tint: petal colour, leaf colour, awning stripe colour, sign paint, lantern glow colour;
- ``ss_rand``   (FLOAT 0..1)  per-prop variation (terracotta and wood tint);
- ``ss_stripe`` (FLOAT) position along an awning in stripe cells (one coloured + one cream band per cell);
- ``ss_local``  (FLOAT_VECTOR) barrel-local position, for stave seams;
- ``ss_glow``   (FLOAT) lantern emission strength (already includes the flicker).
"""
import bpy
from street.materials import common
from nodekit.graph import layout


def lin(rgb):
    """sRGB (0..1) -> linear, so colours can be written as they were measured from the frames."""
    return tuple(((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in rgb)


class _Mat:
    """Tiny helper: a material with one Principled BSDF and terse node/link calls."""

    def __init__(self, name):
        self.m = common.material(name)
        self.nt = self.m.node_tree
        self.bsdf = self.add("ShaderNodeBsdfPrincipled")
        out = self.add("ShaderNodeOutputMaterial")
        self.link(self.bsdf.outputs["BSDF"], out.inputs["Surface"])

    def add(self, idname, label="", **props):
        n = self.nt.nodes.new(idname)
        n.label = label
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def put(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.link(v, sock)
        elif isinstance(v, (tuple, list)):
            sock.default_value = (*v, 1.0)[:len(sock.default_value)]
        else:
            sock.default_value = v

    def attr(self, name):
        return self.add("ShaderNodeAttribute", label=name, attribute_type="GEOMETRY", attribute_name=name)

    def mix(self, fac, a, b, label=""):
        n = self.add("ShaderNodeMix", label=label, data_type="RGBA", clamp_factor=True)
        self.put(n.inputs["Factor"], fac)
        self.put(n.inputs[6], a)
        self.put(n.inputs[7], b)
        return n.outputs[2]

    def math(self, op, a, b=None, clamp=False):
        n = self.add("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.put(n.inputs[0], a)
        if b is not None:
            self.put(n.inputs[1], b)
        return n.outputs[0]

    def noise(self, scale, vector=None, detail=2.0):
        n = self.add("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        if vector is not None:
            self.put(n.inputs["Vector"], vector)
        else:
            self.link(self.add("ShaderNodeNewGeometry").outputs["Position"], n.inputs["Vector"])
        return n.outputs["Fac"]

    def ramp(self, v, a, b, lo=0.3, hi=0.7):
        """Map v from [lo, hi] to [a, b] (clamped, smooth)."""
        n = self.add("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP", clamp=True)
        self.put(n.inputs["Value"], v)
        n.inputs["From Min"].default_value, n.inputs["From Max"].default_value = lo, hi
        n.inputs["To Min"].default_value, n.inputs["To Max"].default_value = a, b
        return n.outputs["Result"]

    def bump(self, height, strength=0.2, distance=0.01):
        n = self.add("ShaderNodeBump")
        n.inputs["Strength"].default_value = strength
        n.inputs["Distance"].default_value = distance
        self.put(n.inputs["Height"], height)
        self.link(n.outputs["Normal"], self.bsdf.inputs["Normal"])

    def set(self, **kw):
        for k, v in kw.items():
            self.put(self.bsdf.inputs[k.replace("_", " ")], v)
        return self

    def done(self):
        layout(self.nt)
        return self.m


def terracotta():
    """Unglazed clay: warm orange-brown, mottled, a little darker per prop by ss_rand."""
    M = _Mat("SS Terracotta")
    n = M.noise(9.0, detail=3.0)
    base = M.mix(M.ramp(n, 0.0, 1.0), lin((0.60, 0.31, 0.19)), lin((0.74, 0.42, 0.27)))
    col = M.mix(M.math("MULTIPLY", M.attr("ss_rand").outputs["Fac"], 0.6), base, lin((0.55, 0.27, 0.17)))
    M.set(Base_Color=col, Roughness=0.85)
    M.bump(n, 0.15)
    return M.done()


def barrel_wood():
    """Barrel staves: 16 staves around ss_local's angle with dark seams, grain along the height, darker lid."""
    M = _Mat("SS Barrel Wood")
    sep = M.add("ShaderNodeSeparateXYZ")
    M.link(M.attr("ss_local").outputs["Vector"], sep.inputs[0])
    ang = M.math("ARCTAN2", sep.outputs["Y"], sep.outputs["X"])
    stave = M.math("FRACT", M.math("MULTIPLY", ang, 16.0 / 6.283185))
    edge = M.math("ABSOLUTE", M.math("SUBTRACT", stave, 0.5))
    seam = M.ramp(edge, 1.0, 0.3, 0.40, 0.48)
    mp = M.add("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (5.0, 5.0, 45.0)
    M.link(M.attr("ss_local").outputs["Vector"], mp.inputs["Vector"])
    grain = M.noise(2.0, mp.outputs["Vector"], 4.0)
    wood = M.mix(M.ramp(grain, 0.0, 1.0), lin((0.45, 0.25, 0.12)), lin((0.62, 0.36, 0.18)))
    geo = M.add("ShaderNodeNewGeometry")
    nz = M.add("ShaderNodeSeparateXYZ")
    M.link(geo.outputs["Normal"], nz.inputs[0])
    top = M.ramp(nz.outputs["Z"], 0.0, 1.0, 0.6, 0.8)
    wood = M.mix(top, wood, lin((0.40, 0.25, 0.13)))
    wood = M.mix(M.math("MULTIPLY", M.attr("ss_rand").outputs["Fac"], 0.5), wood, lin((0.40, 0.22, 0.11)))
    shade = M.add("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
    shade.inputs["Factor"].default_value = 1.0
    M.link(wood, shade.inputs[6])
    comb = M.add("ShaderNodeCombineXYZ")
    for k in "XYZ":
        M.link(seam, comb.inputs[k])
    M.link(comb.outputs[0], shade.inputs[7])
    M.set(Base_Color=shade.outputs[2], Roughness=0.65)
    M.bump(M.math("MULTIPLY", seam, 0.5), 0.3)
    return M.done()


def iron():
    """Black wrought iron (brackets, arms, hoops, lantern frames)."""
    return _Mat("SS Iron").set(Base_Color=lin((0.07, 0.065, 0.06)), Metallic=0.6, Roughness=0.45).done()


def fabric():
    """Awning canvas: cream and ss_color stripes from ss_stripe (one cell = one coloured + one cream band)."""
    M = _Mat("SS Awning Fabric")
    st = M.math("FRACT", M.attr("ss_stripe").outputs["Fac"])
    band = M.ramp(st, 0.0, 1.0, 0.47, 0.53)
    col = M.mix(band, lin((0.93, 0.90, 0.83)), M.attr("ss_color").outputs["Color"])
    M.set(Base_Color=col, Roughness=0.9, Sheen_Weight=0.4)
    return M.done()


def foliage():
    """Leaves, leaf mounds, conifers and ivy: ss_color tint with a little dappled variation."""
    M = _Mat("SS Foliage")
    v = M.ramp(M.noise(25.0), 0.75, 1.15, 0.3, 0.7)
    mul = M.add("ShaderNodeVectorMath", operation="SCALE")
    M.link(M.attr("ss_color").outputs["Vector"], mul.inputs[0])
    M.link(v, mul.inputs["Scale"])
    M.set(Base_Color=mul.outputs[0], Roughness=0.55, Subsurface_Weight=0.08)
    return M.done()


def petals():
    """Geranium florets: ss_color (red, coral, white), soft sheen."""
    M = _Mat("SS Petals")
    M.set(Base_Color=M.attr("ss_color").outputs["Color"], Roughness=0.6, Subsurface_Weight=0.05)
    return M.done()


def glass():
    """Lantern panes: warm glass that emits ss_color at ss_glow strength (flicker baked in by Geometry Nodes)."""
    M = _Mat("SS Lantern Glass")
    M.set(Base_Color=lin((0.62, 0.42, 0.14)), Roughness=0.25,
          Emission_Color=M.attr("ss_color").outputs["Color"], Emission_Strength=M.attr("ss_glow").outputs["Fac"])
    return M.done()


def sign_wood():
    """Painted-over sign boards: dark brown wood with grain."""
    M = _Mat("SS Sign Wood")
    g = M.noise(14.0, detail=4.0)
    col = M.mix(M.ramp(g, 0.0, 1.0), lin((0.34, 0.21, 0.12)), lin((0.48, 0.30, 0.17)))
    M.set(Base_Color=col, Roughness=0.7)
    M.bump(g, 0.1)
    return M.done()


def paint():
    """Painted motifs on signs (bread loaf, teal disc, cream bowl): ss_color."""
    M = _Mat("SS Sign Paint")
    return M.set(Base_Color=M.attr("ss_color").outputs["Color"], Roughness=0.6).done()


def soil():
    return _Mat("SS Potting Soil").set(Base_Color=lin((0.20, 0.13, 0.08)), Roughness=1.0).done()


def build():
    """Build every props material once; returns {short name: material}."""
    return {"terracotta": terracotta(), "wood": barrel_wood(), "iron": iron(), "fabric": fabric(),
            "foliage": foliage(), "petals": petals(), "glass": glass(), "sign": sign_wood(), "paint": paint(),
            "soil": soil()}
