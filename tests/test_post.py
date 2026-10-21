import math, os, tempfile
import numpy as np
import bpy
from nodekit.graph import Graph
from library.post import haze_over_sky, soft_glow

W, H = 64, 48
HAZE, HORIZON, TOP = (0.9, 0.7, 0.5), (0.8, 0.6, 0.4), (0.2, 0.4, 0.9)


# ---- local helpers: a tiny scene rendered through a compositor tree, read back as linear float pixels ----------
def _scene():
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
    sc.eevee.taa_render_samples = 4
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    sc.view_layers[0].use_pass_mist = True
    w = bpy.data.worlds.new("NKT World")
    w.color = (0.2, 0.2, 0.2)
    w.mist_settings.start, w.mist_settings.depth, w.mist_settings.falloff = 2.0, 20.0, "LINEAR"
    sc.world = w
    sun = bpy.data.objects.new("NKT Sun", bpy.data.lights.new("NKT Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(-30))
    sc.collection.objects.link(sun)
    for loc, r in (((-0.8, 3.0, 0.0), 0.7), ((1.2, 12.0, 0.6), 1.5)):     # one near, one deep in the mist
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc)
    cam = bpy.data.objects.new("NKT Cam", bpy.data.cameras.new("NKT Cam"))
    cam.location, cam.rotation_euler = (0, -2.0, 0.0), (math.radians(90), 0, 0)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return sc


def _composite(sc, build):
    """Render once through a compositor tree whose Group Output 'Image' is build(graph, render_layers)."""
    g = Graph(f"NKT Comp {len(bpy.data.node_groups)}", kind="COMPOSITOR", description="test compositor")
    rl = g.node("CompositorNodeRLayers")
    rl.b.scene = sc
    g.output("Image", "COLOR", build(g, rl))
    g.finish()
    sc.compositing_node_group = g.nt
    path = os.path.join(tempfile.mkdtemp(prefix="nkt_post_"), "frame.exr")
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float64).reshape(H, W, 4)[::-1]       # row 0 = top
    bpy.data.images.remove(img)
    return px


def _group(g, tree, **inputs):
    gn = g.node("CompositorNodeGroup")
    gn.b.node_tree = tree
    for k, v in inputs.items():
        g.connect(v, gn.i(k))
    return gn


def _haze(g, rl):
    return _group(g, haze_over_sky(), Image=rl["Image"], Mist=rl["Mist"], **{
        "Haze Color": HAZE, "Haze Amount": 0.8, "Sky Horizon": HORIZON, "Sky Top": TOP, "Horizon": 0.4,
        "Top": 0.9})["Image"]


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


# ---- tests -----------------------------------------------------------------------------------------------------
def test_haze_over_sky_matches_premultiplied_formula():
    """Sky pixels follow the screen-height gradient; every pixel (edges included) equals
    sky (1 - a) + (1 - f) C + f Haze a with f = 0.8 mist: premultiplied haze, alpha restored, no halo."""
    sc = _scene()
    raw = _composite(sc, lambda g, rl: rl["Image"])
    mist = _composite(sc, lambda g, rl: rl["Mist"])[..., 0]
    out = _composite(sc, _haze)
    a = raw[..., 3:4]
    assert (a < 1e-4).sum() > 500 and (a > 0.999).sum() > 300
    edge = (a[..., 0] > 0.05) & (a[..., 0] < 0.95)
    assert edge.sum() > 10, edge.sum()
    y = 1.0 - (np.arange(H) + 0.5) / H                               # normalised height of each row centre
    t = _smooth((y - 0.4) / (0.9 - 0.4))[:, None, None]
    sky = np.array(HORIZON) * (1 - t) + np.array(TOP) * t
    sky = np.broadcast_to(sky, (H, W, 3))
    f = np.clip(mist * 0.8, 0, 1)[..., None]
    want = sky * (1 - a) + (1 - f) * raw[..., :3] + f * np.array(HAZE) * a
    bg = a[..., 0] < 1e-4
    assert np.max(np.abs(out[..., :3][bg] - sky[bg])) < 0.02, np.max(np.abs(out[..., :3][bg] - sky[bg]))
    err = np.abs(out[..., :3] - want)
    assert err.max() < 0.02, (err.max(), np.unravel_index(err.argmax(), err.shape))
    assert err[edge].max() < 0.02
    assert np.all(out[..., 3] > 0.999)                                # the sky makes the frame opaque
    # the far sphere is hazed more than the near one
    far, near = mist[H // 2, int(W * 0.62)], mist[H // 2, int(W * 0.25)]
    assert far > near + 0.2, (far, near)


def test_soft_glow_spreads_only_from_bright_pixels():
    """Bloom adds light around a bright emitter but leaves an image with nothing above Threshold unchanged."""
    sc = _scene()
    for ob in list(bpy.data.objects):
        if ob.type == "MESH":
            bpy.data.objects.remove(ob)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(0, 3.0, 0))
    m = bpy.data.materials.new("NKT Hot")
    m.use_nodes = True
    em = m.node_tree.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 30.0
    m.node_tree.links.new(em.outputs[0], m.node_tree.nodes["Material Output"].inputs["Surface"])
    bpy.context.object.data.materials.append(m)
    raw = _composite(sc, lambda g, rl: rl["Image"])
    glow = _composite(sc, lambda g, rl: _group(g, soft_glow(), Image=rl["Image"], Threshold=1.0,
                                               Strength=1.0)["Image"])
    ring = raw[..., 3] < 1e-4
    near = np.zeros_like(ring)
    near[H // 2 - 8:H // 2 + 8, W // 2 - 8:W // 2 + 8] = True
    gain = (glow[..., :3] - raw[..., :3]).sum(-1)
    assert np.all(np.isfinite(glow)) and gain[ring & near].mean() > 0.01, gain[ring & near].mean()
    dim = _composite(sc, lambda g, rl: _group(g, soft_glow(), Image=rl["Image"], Threshold=100.0,
                                              Strength=1.0)["Image"])
    assert np.max(np.abs(dim[..., :3] - raw[..., :3])) < 1e-3
