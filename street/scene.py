"""Scene scaffolding shared by the build and by per-group tests: path curves, light, world, camera, render setup.

Owned by the integrator. Groups never import this; only build scripts and tools do.
"""
import math
import bpy

FPS = 24


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 1, 481
    return sc


def path_curve(kind="reference", name="Street Path"):
    """A path curve in the XY plane. 'reference' is the gentle S-bend of the reference street; the others are
    transfer inputs used to show the graph working on new paths."""
    pts = {
        # ~60 m gently winding street, travel along +Y (bend amplitude from the vanishing-point drift)
        "reference": [(0, -10, 0), (0.6, 5, 0), (-0.8, 20, 0), (0.5, 35, 0), (-0.4, 50, 0)],
        "straight": [(0, -10, 0), (0, 50, 0)],
        "s_bend": [(0, -10, 0), (6, 8, 0), (-6, 26, 0), (4, 44, 0), (0, 60, 0)],
        "hill": [(0, -10, 0), (0, 10, 1.5), (2, 30, 4.0), (-1, 50, 4.5)],
        "spiral": [(12 * math.cos(a) * (1 - a / 30), 12 * math.sin(a) * (1 - a / 30), 0)
                   for a in [i * 0.35 for i in range(28)]],
    }[kind]
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def holder(name, curve_obj, group):
    """A mesh-less object carrying the Geometry Nodes modifier, with the path curve fed in through an Object
    Info node inside the top-level group (input socket 'Path')."""
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new(group.name, "NODES")
    mod.node_group = group
    return ob, mod


def light_world(sun_elev=42.0, sun_azim=-35.0, strength=4.0):
    sc = bpy.context.scene
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy = strength
    sun.angle = math.radians(2.0)
    sun.color = (1.0, 0.86, 0.68)
    ob = bpy.data.objects.new("Sun", sun)
    ob.rotation_euler = (math.radians(90 - sun_elev), 0, math.radians(sun_azim))
    sc.collection.objects.link(ob)
    w = bpy.data.worlds.new("Sky")
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    grad = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(grad.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], ramp.inputs[0])
    ramp.color_ramp.elements[0].position = 0.5
    ramp.color_ramp.elements[0].color = (0.62, 0.72, 0.74, 1)      # horizon haze
    ramp.color_ramp.elements[1].color = (0.30, 0.55, 0.68, 1)      # sky top
    nt.links.new(ramp.outputs[0], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.0
    sc.world = w
    return ob


def camera(name="Camera", lens=24.0, loc=(0, -8, 1.6), target=(0, 10, 1.2)):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    cam.clip_end = 400
    ob = bpy.data.objects.new(name, cam)
    ob.location = loc
    bpy.context.scene.collection.objects.link(ob)
    t = bpy.data.objects.new(name + " Target", None)
    t.location = target
    bpy.context.scene.collection.objects.link(t)
    c = ob.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = t, "TRACK_NEGATIVE_Z", "UP_Y"
    bpy.context.scene.camera = ob
    return ob, t


def render_setup(width=1280, height=704, samples=16, engine="BLENDER_EEVEE"):
    sc = bpy.context.scene
    sc.render.engine = engine
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = 100
    if hasattr(sc, "eevee"):
        sc.eevee.taa_render_samples = samples
    sc.view_settings.view_transform = "AgX"
    sc.render.image_settings.file_format = "PNG"
    return sc
