"""Materials for SS Bunting: rope, cloth pennants, glowing paper lanterns and their dark caps.

Per-piece values come from Geometry Nodes attributes (read with Attribute nodes of type GEOMETRY):
  ss_color  rope tint / flag colour / lantern glow colour
  ss_rand   0..1 per piece (small brightness variation)
  ss_glow   lantern glow strength (lanterns only)
  ss_lz     lantern paper height, -1 bottom .. +1 top (ribs and the brighter lower half)
"""
from street.materials import common


def _attr(nt, name, x=-700, y=0):
    a = nt.nodes.new("ShaderNodeAttribute")
    a.attribute_type = "GEOMETRY"
    a.attribute_name = name
    a.location = (x, y)
    return a


def _out(nt, shader, x=400):
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    o.location = (x, 0)
    nt.links.new(shader, o.inputs["Surface"])


def rope():
    m = common.material("SS Bunting Rope")
    nt = m.node_tree
    col = _attr(nt, "ss_color")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Roughness"].default_value = 0.9
    nt.links.new(col.outputs["Color"], b.inputs["Base Color"])
    _out(nt, b.outputs[0])
    return m


def flag():
    """Thin cotton: diffuse front plus some light through the cloth (the reference flags glow against the sky)."""
    m = common.material("SS Bunting Flag")
    nt = m.node_tree
    col = _attr(nt, "ss_color", y=100)
    rnd = _attr(nt, "ss_rand", y=-150)
    # +-6 % brightness per flag so neighbours of the same colour do not read as one strip
    jit = nt.nodes.new("ShaderNodeMapRange")
    jit.inputs["To Min"].default_value, jit.inputs["To Max"].default_value = 0.94, 1.06
    nt.links.new(rnd.outputs["Fac"], jit.inputs["Value"])
    tint = nt.nodes.new("ShaderNodeMix")
    tint.data_type, tint.blend_type = "RGBA", "MULTIPLY"
    tint.inputs["Factor"].default_value = 1.0
    nt.links.new(col.outputs["Color"], tint.inputs["A"])
    nt.links.new(jit.outputs["Result"], tint.inputs["B"])
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Roughness"].default_value = 0.92
    nt.links.new(tint.outputs["Result"], b.inputs["Base Color"])
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
    nt.links.new(tint.outputs["Result"], tr.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.35
    nt.links.new(b.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    _out(nt, mix.outputs[0])
    return m


def lantern():
    """Warm paper lit from inside: emission = glow colour x strength x (ribs) x (brighter lower half)."""
    m = common.material("SS Bunting Lantern")
    nt = m.node_tree
    glow = _attr(nt, "ss_color", y=200)
    k = _attr(nt, "ss_glow", y=0)
    lz = _attr(nt, "ss_lz", y=-250)
    # ribs: six bands of darker paper folds along the height
    rib = nt.nodes.new("ShaderNodeMath")
    rib.operation = "COSINE"
    sc = nt.nodes.new("ShaderNodeMath")
    sc.operation = "MULTIPLY"
    sc.inputs[1].default_value = 3.14159 * 6.0
    nt.links.new(lz.outputs["Fac"], sc.inputs[0])
    nt.links.new(sc.outputs[0], rib.inputs[0])
    ribs = nt.nodes.new("ShaderNodeMapRange")
    ribs.inputs["From Min"].default_value, ribs.inputs["From Max"].default_value = -1.0, 1.0
    ribs.inputs["To Min"].default_value, ribs.inputs["To Max"].default_value = 1.0, 0.7
    nt.links.new(rib.outputs[0], ribs.inputs["Value"])
    low = nt.nodes.new("ShaderNodeMapRange")       # lower half brighter: the flame sits low
    low.inputs["From Min"].default_value, low.inputs["From Max"].default_value = -1.0, 1.0
    low.inputs["To Min"].default_value, low.inputs["To Max"].default_value = 1.3, 0.75
    nt.links.new(lz.outputs["Fac"], low.inputs["Value"])
    f1 = nt.nodes.new("ShaderNodeMath")
    f1.operation = "MULTIPLY"
    nt.links.new(ribs.outputs["Result"], f1.inputs[0])
    nt.links.new(low.outputs["Result"], f1.inputs[1])
    f2 = nt.nodes.new("ShaderNodeMath")
    f2.operation = "MULTIPLY"
    nt.links.new(f1.outputs[0], f2.inputs[0])
    nt.links.new(k.outputs["Fac"], f2.inputs[1])
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (0.55, 0.30, 0.05, 1)      # warm paper (kept low: AgX bleaches bright albedo)
    b.inputs["Roughness"].default_value = 0.85
    b.inputs["Specular IOR Level"].default_value = 0.1     # matte paper: no bluish sky sheen
    nt.links.new(glow.outputs["Color"], b.inputs["Emission Color"])
    nt.links.new(f2.outputs[0], b.inputs["Emission Strength"])
    _out(nt, b.outputs[0])
    return m


def cap():
    return common.flat("SS Bunting Lantern Cap", (0.022, 0.012, 0.007), roughness=0.5)
