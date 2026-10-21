import math, os, tempfile
import numpy as np
import bpy
import nkt
from nodekit.graph import Graph
from library import materials as M

GROUPS = [M.attribute_tint, M.stucco, M.wood_grain, M.stone, M.felt, M.terracotta, M.stripes, M.glow_glass,
          M.ground, M.root_tip_gradient]


# ---- local render helpers (tiny EEVEE frames read back as linear float pixels) --------------------------------
def _render(w=64, h=64, samples=1):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
    sc.eevee.taa_render_samples = samples
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    path = os.path.join(tempfile.mkdtemp(prefix="nkt_mat_"), "frame.exr")
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)[::-1]       # row 0 = top
    bpy.data.images.remove(img)
    return px


def _camera(loc=(0, -4, 0), ortho=2.2):
    cam = bpy.data.objects.new("NKT Cam", bpy.data.cameras.new("NKT Cam"))
    cam.location = loc
    cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.type, cam.data.ortho_scale = "ORTHO", ortho
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def _lights():
    sun = bpy.data.objects.new("NKT Sun", bpy.data.lights.new("NKT Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(60), 0, math.radians(-30))
    bpy.context.scene.collection.objects.link(sun)
    w = bpy.data.worlds.new("NKT World")
    w.color = (0.3, 0.3, 0.3)
    bpy.context.scene.world = w


def _plane(size=2.0, mat=None):
    """A plane facing the camera (normal -Y), object coordinates x in [-size/2, size/2]."""
    bpy.ops.mesh.primitive_plane_add(size=size, rotation=(math.radians(90), 0, 0))
    ob = bpy.context.object
    if mat:
        ob.data.materials.append(mat)
    return ob


def _emission_material(name, group_tree, out="Color", strength_out=None, **inputs):
    """make_material, then route a group output straight into an Emission shader (exact colours on screen)."""
    m = M.make_material(name, group_tree, **inputs)
    nt = m.node_tree
    gn = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeGroup")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(gn.outputs[out], em.inputs["Color"])
    if strength_out:
        nt.links.new(gn.outputs[strength_out], em.inputs["Strength"])
    outn = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], outn.inputs["Surface"])
    return m


# ---- tests -----------------------------------------------------------------------------------------------------
def test_every_material_renders_lit_and_varied():
    """Each group builds into a material that compiles in EEVEE and renders a lit, finite, non-flat sphere."""
    _lights()
    _camera(ortho=1.1)
    bpy.context.scene.render.film_transparent = True
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5)
    ob = bpy.context.object
    bpy.ops.object.shade_smooth()
    rnd = ob.data.attributes.new("nk_rand", "FLOAT", "FACE")
    rnd.data.foreach_set("value", np.random.default_rng(0).random(len(ob.data.polygons)))
    for build in GROUPS:
        tree = build()
        ob.data.materials.clear()
        ob.data.materials.append(M.make_material(f"NKT {tree.name}", tree))
        px = _render(64, 64)
        disc = px[16:48, 16:48, :3]
        assert np.all(np.isfinite(px)), tree.name
        lum = disc @ np.array([0.2126, 0.7152, 0.0722])
        assert lum.mean() > 0.03, (tree.name, lum.mean())
        assert not np.any((disc[..., 0] > 0.8) & (disc[..., 1] < 0.05) & (disc[..., 2] > 0.8)), \
            f"{tree.name}: magenta (shader failed to compile)"
        assert lum.std() > 0.01, (tree.name, lum.std())
        assert px[0, 0, 3] < 1e-3 and px[32, 32, 3] > 0.999        # background empty, sphere opaque


def test_stripes_two_colours_along_coordinate():
    """Stripes of Width 0.25 along object X on a 2 m plane: every pixel is A or B except at edges, and they
    alternate exactly where the analytic pattern says."""
    a, b = (0.8, 0.1, 0.05, 1.0), (0.05, 0.2, 0.7, 1.0)
    m = _emission_material("NKT Stripes", M.stripes(), **{"Color A": a, "Color B": b, "Width": 0.25,
                                                          "Softness": 0.01, "Ratio": 0.5})
    _plane(2.0, m)
    _camera(ortho=2.0)
    px = _render(64, 16)
    row = px[8, :, :3]
    da = np.linalg.norm(row - np.array(a[:3]), axis=1)
    db = np.linalg.norm(row - np.array(b[:3]), axis=1)
    pure = np.minimum(da, db) < 1e-3
    assert pure.sum() >= 56, pure.sum()
    x = (np.arange(64) + 0.5) / 64 * 2.0 - 1.0                      # pixel centres in object X
    d = np.abs(np.mod(x / 0.5 - 0.25 + 0.5, 1.0) - 0.5)             # distance from the nearest A centre
    want_a = d < 0.25
    got_a = da < db
    clear = np.abs(d - 0.25) > 0.02
    assert np.array_equal(got_a[clear], want_a[clear])
    assert got_a.sum() > 20 and (~got_a).sum() > 20


def test_attribute_tint_reads_nk_color_and_rand():
    """Where nk_color is present it replaces the base; where missing the base shows; nk_rand darkens by Value
    Variation (and its hue term is 0 at rand 0 and 1)."""
    base = (0.5, 0.4, 0.3, 1.0)
    m = _emission_material("NKT Tint", M.attribute_tint(), **{"Base Color": base, "Value Variation": 0.5,
                                                               "Hue Variation": 0.1})
    me = bpy.data.meshes.new("NKT Quads")
    me.from_pydata([(-1, 0, -0.5), (0, 0, -0.5), (0, 0, 0.5), (-1, 0, 0.5), (1, 0, -0.5), (1, 0, 0.5)], [],
                   [(0, 1, 2, 3), (1, 4, 5, 2)])
    col = me.attributes.new("nk_color", "FLOAT_COLOR", "FACE")
    col.data[0].color, col.data[1].color = (0.1, 0.6, 0.2, 1.0), (0.0, 0.0, 0.0, 0.0)
    rnd = me.attributes.new("nk_rand", "FLOAT", "FACE")
    rnd.data[0].value, rnd.data[1].value = 0.0, 1.0
    me.materials.append(m)
    ob = bpy.data.objects.new("NKT Quads", me)
    bpy.context.scene.collection.objects.link(ob)
    _camera(ortho=2.0)
    px = _render(32, 16)
    left, right = px[8, 8, :3], px[8, 24, :3]
    assert nkt.close(left, (0.1, 0.6, 0.2), 2e-3), left
    assert nkt.close(right, np.array(base[:3]) * 0.5, 2e-3), right


def test_glow_glass_core_brighter_than_rim():
    """Emission strength is Strength at the facing core and falls toward the grazing rim."""
    m = _emission_material("NKT Glow", M.glow_glass(), out="Emission", strength_out="Emission Strength",
                           Strength=2.0, Flicker=0.5)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=0.5)
    bpy.ops.object.shade_smooth()
    bpy.context.object.data.materials.append(m)
    _camera(ortho=1.1)
    px = _render(64, 64)
    lum = px[..., :3] @ np.array([0.2126, 0.7152, 0.0722])
    core, rim = lum[32, 32], lum[32, 5]
    assert np.all(np.isfinite(px)) and core > 3 * rim > 0, (core, rim)
    core_rgb = px[32, 32, :3]
    assert core_rgb[0] > core_rgb[1] > core_rgb[2]                  # warm


def _two_pieces(store_local, mat, rand=(0.0, 0.0)):
    """Two identical 0.9 m squares facing the camera, instanced at x = -0.5 and +0.5 and realized. The square is
    modelled in XY; with store_local, NK Store Local Coords writes nk_local on the prototype first. Each instance
    carries nk_rand from ``rand``; the pieces get material ``mat``."""
    w = Graph(nkt._name("NKT Pieces"), description="two realized pieces", modifier=True)
    w.input("Geometry", "GEOMETRY", desc="ignored")
    sq = w.node("GeometryNodeMeshGrid", **{"Size X": 0.9, "Size Y": 0.9, "Vertices X": 2, "Vertices Y": 2})["Mesh"]
    if store_local:
        sq = w.group(M.store_local_coords(), Geometry=sq)["Geometry"]
    sq = w.node("GeometryNodeTransform", Geometry=sq, Rotation=(math.radians(90), 0.0, 0.0))["Geometry"]
    pts = w.node("GeometryNodePoints", Count=2, Position=w.combine(w.math(
        "SUBTRACT", w.node("GeometryNodeInputIndex")["Index"], 0.5), 0.0, 0.0))["Points"]
    sw = w.node("GeometryNodeSwitch", props={"input_type": "FLOAT"}, Switch=w.math(
        "GREATER_THAN", w.node("GeometryNodeInputIndex")["Index"], 0.5), **{"False": rand[0], "True": rand[1]})
    pts = w.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"}, Geometry=pts,
                 Name="nk_rand", Value=sw["Output"])["Geometry"]
    sq = w.node("GeometryNodeSetMaterial", Geometry=sq, Material=mat)["Geometry"]
    ins = w.node("GeometryNodeInstanceOnPoints", Points=pts, Instance=sq)["Instances"]
    w.output("Geometry", "GEOMETRY", w.node("GeometryNodeRealizeInstances", Geometry=ins)["Geometry"])
    w.finish()
    ob = bpy.data.objects.new(w.nt.name, bpy.data.meshes.new(w.nt.name))
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("nkt", "NODES").node_group = w.nt
    return ob


def _halves(store_local, mat, rand=(0.0, 0.0)):
    ob = _two_pieces(store_local, mat, rand)
    px = _render(64, 32)[4:28, :, :3]
    bpy.data.objects.remove(ob)
    return px[:, 4:28], px[:, 36:60]                     # the middle of each square (32 px = 1 m apart)


def test_local_coords_give_each_piece_its_own_pattern():
    """With nk_local (NK Store Local Coords before instancing) both realized pieces show the same wood rings and
    stone cells; with Use Local 0 (object coordinates) they differ; Piece Shift with different nk_rand separates
    them again. NK Store Local Coords' Grain Axis is a cyclic swap and Centre/Rotation invert the frame."""
    _camera(ortho=2.0)
    for build, out in ((M.wood_grain, "Ring"), (M.stone, "Cell")):
        left, right = _halves(True, _emission_material(f"NKT L {out}", build(), out=out))
        assert np.abs(left - right).max() < 2e-3 and left.std() > 0.02, (out, np.abs(left - right).max(), left.std())
        left, right = _halves(True, _emission_material(f"NKT O {out}", build(), out=out, **{"Use Local": 0.0}))
        assert np.abs(left - right).mean() > 0.02, (out, np.abs(left - right).mean())
        left, right = _halves(False, _emission_material(f"NKT F {out}", build(), out=out))   # no nk_local: Vector
        assert np.abs(left - right).mean() > 0.02, (out, np.abs(left - right).mean())
    left, right = _halves(True, _emission_material("NKT S", M.wood_grain(), out="Ring", **{"Piece Shift": 1.0}),
                          rand=(0.2, 0.7))
    assert np.abs(left - right).mean() > 0.02
    pts = [(0.3, -0.2, 0.5), (1.0, 2.0, -1.0)]
    me = bpy.data.meshes.new("NKT Verts")
    me.from_pydata(pts, [], [])
    vob = bpy.data.objects.new("NKT Verts", me)
    bpy.context.scene.collection.objects.link(vob)
    for axis, perm in ((0, [1, 2, 0]), (1, [2, 0, 1]), (2, [0, 1, 2])):
        got = nkt.attrs(nkt.evaluate(M.store_local_coords(), {"Geometry": vob, "Grain Axis": axis,
                                                               "Centre": (1.0, 0.0, 0.0)}), ["nk_local"])["nk_local"]
        assert nkt.close(got, (np.array(pts) - (1.0, 0.0, 0.0))[:, perm]), (axis, got)


def test_root_tip_gradient_and_ground():
    """Root Tip Gradient: Factor 0 gives Root Color, 1 Tip Color, 0.5 the Power-shaped mix; Random 0 changes
    nothing. NK Ground with Mottle 0, Patch 0 returns its Color exactly; Patch 1 brings Patch Color in."""
    _camera(ortho=2.0)
    root, tip = (0.1, 0.3, 0.05, 1.0), (0.7, 0.8, 0.2, 1.0)
    for fac, want in ((0.0, root[:3]), (1.0, tip[:3]),
                      (0.5, np.array(root[:3]) + (np.array(tip[:3]) - root[:3]) * 0.5 ** 2.0)):
        m = _emission_material(f"NKT RTG {fac}", M.root_tip_gradient(), **{
            "Factor": fac, "Root Color": root, "Tip Color": tip, "Power": 2.0})
        ob = _plane(2.0, m)
        px = _render(16, 16)[8, 8, :3]
        assert nkt.close(px, want, 2e-3), (fac, px, want)
        bpy.data.objects.remove(ob)
    col, patch = (0.2, 0.4, 0.1, 1.0), (0.6, 0.5, 0.2, 1.0)
    m = _emission_material("NKT Ground 0", M.ground(), Color=col, Mottle=0.0, **{"Patch Amount": 0.0})
    ob = _plane(2.0, m)
    px = _render(16, 16)[2:14, 2:14, :3]
    assert nkt.close(px, col[:3], 2e-3), px.reshape(-1, 3)[0]
    ob.data.materials.clear()
    ob.data.materials.append(_emission_material("NKT Ground 1", M.ground(), Color=col, Mottle=0.0, **{
        "Patch Amount": 1.0, "Patch Color": patch}))
    px = _render(16, 16)[2:14, 2:14, :3]
    assert np.mean(np.linalg.norm(px - np.array(patch[:3]), axis=2) < 1e-2) > 0.5
