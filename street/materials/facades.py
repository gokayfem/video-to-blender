"""Facade materials (owner: facades). All procedural; per-piece tint and variation come from Geometry Nodes:

    ss_color  FLOAT_COLOR  the piece's base tint (plaster colour of its house, timber colour, shutter colour ...)
    ss_rand   FLOAT        0..1 per piece
    ss_unit   FLOAT_VECTOR the vertex position in its unit shape (0..1 per axis); ss_unit * ss_size = metric
    ss_size   FLOAT_VECTOR the piece's size in H: local coordinates for tiles, planks, louvres and stone courses
    ss_local  FLOAT_VECTOR the vertex position in its house's frame (x along the wall, y out, z up from the street)

Reference palette (docs/REFERENCE.md, shader-skills village-loop REFERENCE.md section 7): sunlit plaster #CB945D,
timber #5A3A24, shutters #4F6A55, clay roof #A65A3A, slate blue #4C5E78.
"""
import bpy
from street.materials import common

_CACHE = {}


def lin(c):
    """sRGB 0..1 -> linear."""
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def hexc(h, a=1.0):
    h = h.lstrip("#")
    return (*lin(tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))), a)


# ---- a tiny shader-tree builder ------------------------------------------------------------------------------
class _T:
    def __init__(self, mat):
        self.nt = mat.node_tree
        self.k = 0

    def n(self, idname, props=None, **inputs):
        b = self.nt.nodes.new(idname)
        for k, v in (props or {}).items():
            setattr(b, k, v)
        b.location = (-200 * (self.k % 8), -220 * (self.k // 8))
        self.k += 1
        for k, v in inputs.items():
            self.set(b, k, v)
        return b

    def sock(self, b, key, out=False):
        socks = [s for s in (b.outputs if out else b.inputs) if s.enabled]
        if isinstance(key, int):
            return socks[key]
        name, _, idx = key.partition("#")
        hits = [s for s in socks if s.name == name]
        return hits[int(idx) if idx else 0]

    def set(self, b, key, v):
        s = self.sock(b, key)
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, s)
        elif isinstance(v, bpy.types.Node):
            self.nt.links.new([o for o in v.outputs if o.enabled][0], s)
        elif isinstance(v, (tuple, list)):
            dv = s.default_value
            vals = list(v) + [1.0] * (len(dv) - len(v))
            s.default_value = vals[:len(dv)]
        else:
            s.default_value = v

    def o(self, b, key=0):
        return self.sock(b, key, out=True)

    # shorthands
    def attr(self, name):
        return self.n("ShaderNodeAttribute", props={"attribute_type": "GEOMETRY", "attribute_name": name})

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.n("ShaderNodeMath", props={"operation": op, "use_clamp": clamp})
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.set(n, i, v)
        return self.o(n)

    def vmath(self, op, a, b=None, scale=None):
        n = self.n("ShaderNodeVectorMath", props={"operation": op})
        self.set(n, 0, a)
        if b is not None:
            self.set(n, 1, b)
        if scale is not None:
            self.set(n, "Scale", scale)
        return self.o(n)

    def maprange(self, v, a0, a1, b0, b1, interp="LINEAR"):
        n = self.n("ShaderNodeMapRange", props={"interpolation_type": interp, "clamp": True})
        for k, x in (("Value", v), ("From Min", a0), ("From Max", a1), ("To Min", b0), ("To Max", b1)):
            self.set(n, k, x)
        return self.o(n, "Result")

    def sep(self, v):
        return self.n("ShaderNodeSeparateXYZ", Vector=v)

    def comb(self, x, y, z=0.0):
        return self.o(self.n("ShaderNodeCombineXYZ", X=x, Y=y, Z=z))

    def mixc(self, fac, a, b, blend="MIX"):
        n = self.n("ShaderNodeMix", props={"data_type": "RGBA", "blend_type": blend, "clamp_result": True})
        self.set(n, "Factor", fac)
        self.set(n, "A", a)
        self.set(n, "B", b)
        return self.o(n, "Result")

    def tint(self, color, fac):
        """color * fac (fac a float socket)."""
        return self.vmath("SCALE", color, scale=fac)

    def noise(self, vec, scale, detail=4.0, rough=0.55, distortion=0.0, out="Factor"):
        n = self.n("ShaderNodeTexNoise", props={"noise_dimensions": "3D"}, Vector=vec, Scale=scale, Detail=detail,
                   Roughness=rough, Distortion=distortion)
        return self.o(n, out)

    def local_coords(self):
        """ss_unit * ss_size: metric coordinates inside the piece (x, y, z in H)."""
        return self.vmath("MULTIPLY", self.o(self.attr("ss_unit"), "Vector"), self.o(self.attr("ss_size"), "Vector"))

    def bsdf(self, color, rough, bump=None, spec=0.5, emission=None, emit_strength=0.0, normal=None):
        b = self.n("ShaderNodeBsdfPrincipled", **{"Base Color": color, "Roughness": rough,
                                                 "Specular IOR Level": spec})
        if normal is not None:
            self.set(b, "Normal", normal)
        if emission is not None:
            self.set(b, "Emission Color", emission)
            self.set(b, "Emission Strength", emit_strength)
        out = self.n("ShaderNodeOutputMaterial")
        out.location = (400, 0)
        self.nt.links.new(b.outputs[0], out.inputs["Surface"])
        return b

    def bump(self, height, strength, distance=0.02):
        return self.o(self.n("ShaderNodeBump", Strength=strength, Distance=distance, Height=height))


def _base(t):
    return t.o(t.attr("ss_color"), "Color")


def _world(t):
    return t.o(t.n("ShaderNodeNewGeometry"), "Position")


# ---- materials -----------------------------------------------------------------------------------------------
def plaster():
    """Lime plaster: per-house ss_color, soft blotchy mottling, fine speckle, darker grime at the base."""
    m = common.material("SS Plaster")
    t = _T(m)
    col = _base(t)
    p = _world(t)
    blot = t.noise(p, 0.9, 5.0, 0.6)
    fine = t.noise(p, 14.0, 3.0, 0.5)
    tone = t.math("ADD", t.maprange(blot, 0.3, 0.7, 0.86, 1.08), t.maprange(fine, 0.3, 0.7, -0.03, 0.03))
    col = t.tint(col, tone)
    z = t.o(t.sep(t.o(t.attr("ss_local"), "Vector")), "Z")
    grime = t.maprange(z, 0.05, 1.1, 1.0, 0.0, "SMOOTHSTEP")
    streak = t.maprange(t.noise(t.vmath("MULTIPLY", p, (3.0, 3.0, 0.4)), 2.0, 3.0), 0.35, 0.65, 0.6, 1.0)
    dirty = t.mixc(0.55, col, hexc("#4A3A2A"), "MULTIPLY")
    col = t.mixc(t.math("MULTIPLY", grime, streak), col, dirty)
    t.bsdf(col, 0.93, spec=0.3, normal=t.bump(t.noise(p, 6.0, 4.0), 0.12))
    return m


def timber():
    """Dark oak beams: ss_color with stretched grain-ish noise and per-beam tint."""
    m = common.material("SS Timber")
    t = _T(m)
    col = _base(t)
    q = t.local_coords()
    grain = t.n("ShaderNodeTexWave", props={"wave_type": "BANDS", "bands_direction": "Z"}, Vector=q, Scale=3.0,
                Distortion=7.0, Detail=3.0, **{"Detail Scale": 2.0})
    g = t.maprange(t.o(grain, "Factor"), 0.0, 1.0, 0.92, 1.05)
    r = t.maprange(t.o(t.attr("ss_rand"), "Factor"), 0.0, 1.0, 0.85, 1.12)
    blot = t.maprange(t.noise(_world(t), 3.0, 4.0), 0.3, 0.7, 0.85, 1.1)
    col = t.tint(col, t.math("MULTIPLY", t.math("MULTIPLY", g, r), blot))
    t.bsdf(col, 0.78, spec=0.35, normal=t.bump(t.o(grain, "Factor"), 0.12))
    return m


def glass():
    """Window glass: dark and glossy, reflecting the sky, with a dim warm interior behind some panes."""
    m = common.material("SS Window Glass")
    t = _T(m)
    r = t.o(t.attr("ss_rand"), "Factor")
    warm = t.math("MULTIPLY", t.maprange(r, 0.45, 0.9, 0.0, 1.0), 0.7)
    interior = t.mixc(warm, hexc("#0C0F12"), hexc("#3A2414"))
    t.bsdf(interior, 0.18, spec=0.22, emission=hexc("#FFA050"), emit_strength=t.math("MULTIPLY", warm, 0.15))
    return m


def painted_wood():
    """Painted planked wood for doors and shop fascias: ss_color, vertical plank seams, worn paint."""
    m = common.material("SS Painted Wood")
    t = _T(m)
    col = _base(t)
    q = t.sep(t.local_coords())
    plank = t.math("FRACT", t.math("DIVIDE", t.o(q, "X"), 0.16))
    seam = t.maprange(t.math("ABSOLUTE", t.math("SUBTRACT", plank, 0.5)), 0.42, 0.5, 1.0, 0.45)
    wear = t.maprange(t.noise(_world(t), 9.0, 5.0), 0.35, 0.7, 0.9, 1.08)
    col = t.tint(col, t.math("MULTIPLY", seam, wear))
    t.bsdf(col, 0.55, spec=0.45, normal=t.bump(seam, 0.3))
    return m


def window_frame():
    """Painted window frames and mullions: plain, slightly glossy ss_color."""
    m = common.material("SS Window Frame")
    t = _T(m)
    col = t.tint(_base(t), t.maprange(t.noise(_world(t), 12.0, 3.0), 0.3, 0.7, 0.9, 1.05))
    t.bsdf(col, 0.45, spec=0.45)
    return m


def shutter():
    """Louvred painted shutters: ss_color, horizontal slats shaded top to bottom, a darker frame band."""
    m = common.material("SS Shutter")
    t = _T(m)
    col = _base(t)
    q = t.sep(t.local_coords())
    sz = t.sep(t.o(t.attr("ss_size"), "Vector"))
    slat = t.math("FRACT", t.math("DIVIDE", t.o(q, "Z"), 0.075))
    # frame band: within 0.05 of the shutter's left/right/top/bottom edges
    ex = t.math("MINIMUM", t.o(q, "X"), t.math("SUBTRACT", t.o(sz, "X"), t.o(q, "X")))
    ez = t.math("MINIMUM", t.o(q, "Z"), t.math("SUBTRACT", t.o(sz, "Z"), t.o(q, "Z")))
    band = t.math("LESS_THAN", t.math("MINIMUM", ex, ez), 0.05)
    lou = t.maprange(slat, 0.0, 1.0, 0.62, 1.08)
    f = t.math("MAXIMUM", t.math("MULTIPLY", lou, t.math("SUBTRACT", 1.0, band)), t.math("MULTIPLY", band, 0.9))
    wear = t.maprange(t.noise(_world(t), 8.0, 4.0), 0.3, 0.7, 0.88, 1.06)
    col = t.tint(col, t.math("MULTIPLY", f, wear))
    t.bsdf(col, 0.6, spec=0.4, normal=t.bump(t.math("MULTIPLY", slat, t.math("SUBTRACT", 1.0, band)), 0.35))
    return m


def _roof(name, tile_w, tile_h, rough, var):
    m = common.material(name)
    t = _T(m)
    col = _base(t)
    q = t.sep(t.local_coords())
    rv = t.math("DIVIDE", t.o(q, "Y"), tile_h)
    row = t.math("FLOOR", rv)
    fr = t.math("FRACT", rv)
    cu = t.math("ADD", t.math("DIVIDE", t.o(q, "X"), tile_w), t.math("MULTIPLY", t.math("MODULO", row, 2.0), 0.5))
    col_i = t.math("FLOOR", cu)
    fu = t.math("FRACT", cu)
    cell = t.comb(col_i, row, t.math("MULTIPLY", t.o(t.attr("ss_rand"), "Factor"), 37.0))
    wn = t.n("ShaderNodeTexWhiteNoise", props={"noise_dimensions": "3D"}, Vector=cell)
    rnd = t.o(wn, "Value")
    rcol = t.o(wn, "Color")
    tone = t.maprange(rnd, 0.0, 1.0, 1.0 - var, 1.0 + var)
    overlap = t.maprange(fr, 0.0, 0.55, 0.5, 1.0, "SMOOTHSTEP")
    gap = t.maprange(t.math("ABSOLUTE", t.math("SUBTRACT", fu, 0.5)), 0.44, 0.5, 1.0, 0.6)
    col = t.tint(col, t.math("MULTIPLY", t.math("MULTIPLY", tone, overlap), gap))
    col = t.mixc(0.12, col, rcol, "OVERLAY")
    moss = t.maprange(t.noise(_world(t), 1.5, 4.0), 0.55, 0.75, 0.0, 0.35)
    col = t.mixc(moss, col, hexc("#5C5A3A"))
    height = t.math("MULTIPLY", fr, gap)
    t.bsdf(col, rough, spec=0.4, normal=t.bump(height, 0.5, 0.03))
    return m


def roof_tile():
    """Clay tiles: rows along the slope with overlap shadow, staggered joints, per-tile tone, a little moss."""
    return _roof("SS Roof Tile", 0.26, 0.2, 0.72, 0.22)


def roof_slate():
    """Blue slate: smaller, flatter, glossier tiles than clay, per-slate tone."""
    return _roof("SS Roof Slate", 0.2, 0.15, 0.45, 0.18)


def stone():
    """Rubble-stone plinths, door arches and chimneys: courses of blocks with mortar, ss_color tinted."""
    m = common.material("SS Stone")
    t = _T(m)
    col = _base(t)
    q = t.sep(t.local_coords())
    uv = t.comb(t.math("ADD", t.o(q, "X"), t.o(q, "Y")), t.o(q, "Z"), 0.0)
    br = t.n("ShaderNodeTexBrick", Vector=uv, Scale=1.0, Color1=(1, 1, 1, 1), Color2=(0.7, 0.66, 0.6, 1),
             Mortar=(0.42, 0.4, 0.36, 1), **{"Mortar Size": 0.022, "Mortar Smooth": 0.6, "Bias": 0.0,
                                           "Brick Width": 0.36, "Row Height": 0.17})
    br.offset, br.squash, br.squash_frequency = 0.45, 1.3, 3
    shade = t.o(br, "Color")
    col = t.mixc(1.0, col, shade, "MULTIPLY")
    col = t.tint(col, t.maprange(t.noise(_world(t), 5.0, 5.0), 0.3, 0.7, 0.85, 1.1))
    t.bsdf(col, 0.88, spec=0.3, normal=t.bump(t.math("SUBTRACT", 1.0, t.o(br, "Factor")), 0.5))
    return m


_BUILDERS = {"plaster": plaster, "timber": timber, "glass": glass, "painted": painted_wood, "frame": window_frame,
             "shutter": shutter, "tile": roof_tile, "slate": roof_slate, "stone": stone}


def reset():
    _CACHE.clear()


def get(key):
    """Build each facade material once per build and return it."""
    if key not in _CACHE:
        _CACHE[key] = _BUILDERS[key]()
    return _CACHE[key]
