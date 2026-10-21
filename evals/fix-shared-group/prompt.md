---
description: "Repair: a shared node group is rebuilt in place by a second builder, which silently unlinks its first user."
tags: [positive, repair]
expected_outcome: "build.py builds the shared Round Profile group once and reuses it, so the rail keeps its profile link and sweeps a round tube; the interface is preserved and the script still saves scene.blend."
max_turns: 50
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

This Blender 5.2 script builds a fence on a curve with Geometry Nodes. The posts come out fine, but the rail is just a thin wire with no thickness, and the rail Radius does nothing. There are no errors and no node warnings. Can you find out why and fix it? Keep the groups and their inputs as they are. Save the fixed script as `build.py`; running it with `blender -b --python build.py` should still save `scene.blend`.

```python
import bpy


def socket(ng, name, in_out, stype, default=None, lo=None, hi=None, desc=""):
    s = ng.interface.new_socket(name, in_out=in_out, socket_type=stype)
    if default is not None:
        s.default_value = default
    if lo is not None:
        s.min_value, s.max_value = lo, hi
    s.description = desc
    return s


def fresh_group(name):
    ng = bpy.data.node_groups.get(name) or bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.nodes.clear()
    ng.interface.clear()
    return ng, ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")


def build_profile():
    """Round profile shared by the rail and the posts."""
    ng, gin, gout = fresh_group("Round Profile")
    socket(ng, "Radius", "INPUT", "NodeSocketFloat", 0.04, 0.005, 0.5, "Radius of the round profile")
    socket(ng, "Curve", "OUTPUT", "NodeSocketGeometry")
    circle = ng.nodes.new("GeometryNodeCurvePrimitiveCircle")
    circle.inputs["Resolution"].default_value = 12
    ng.links.new(gin.outputs["Radius"], circle.inputs["Radius"])
    ng.links.new(circle.outputs["Curve"], gout.inputs["Curve"])
    return ng


def build_rail():
    """Sweep the round profile along the path, lifted to the rail height."""
    profile = build_profile()
    ng, gin, gout = fresh_group("Rail")
    socket(ng, "Curve", "INPUT", "NodeSocketGeometry", desc="Path the fence follows")
    socket(ng, "Height", "INPUT", "NodeSocketFloat", 0.9, 0.1, 3.0, "Rail height above the path")
    socket(ng, "Radius", "INPUT", "NodeSocketFloat", 0.04, 0.005, 0.5, "Rail thickness (radius)")
    socket(ng, "Mesh", "OUTPUT", "NodeSocketGeometry")
    lift = ng.nodes.new("GeometryNodeSetPosition")
    up = ng.nodes.new("ShaderNodeCombineXYZ")
    prof = ng.nodes.new("GeometryNodeGroup")
    prof.node_tree = profile
    sweep = ng.nodes.new("GeometryNodeCurveToMesh")
    ng.links.new(gin.outputs["Curve"], lift.inputs["Geometry"])
    ng.links.new(gin.outputs["Height"], up.inputs["Z"])
    ng.links.new(up.outputs["Vector"], lift.inputs["Offset"])
    ng.links.new(gin.outputs["Radius"], prof.inputs["Radius"])
    ng.links.new(lift.outputs["Geometry"], sweep.inputs["Curve"])
    ng.links.new(prof.outputs["Curve"], sweep.inputs["Profile Curve"])
    ng.links.new(sweep.outputs["Mesh"], gout.inputs["Mesh"])
    return ng


def build_posts():
    """Vertical round posts at regular spacing along the path."""
    profile = build_profile()
    ng, gin, gout = fresh_group("Posts")
    socket(ng, "Curve", "INPUT", "NodeSocketGeometry", desc="Path the fence follows")
    socket(ng, "Spacing", "INPUT", "NodeSocketFloat", 1.5, 0.2, 10.0, "Distance between posts")
    socket(ng, "Height", "INPUT", "NodeSocketFloat", 1.0, 0.1, 3.0, "Post height")
    socket(ng, "Radius", "INPUT", "NodeSocketFloat", 0.05, 0.005, 0.5, "Post thickness (radius)")
    socket(ng, "Instances", "OUTPUT", "NodeSocketGeometry")
    pts = ng.nodes.new("GeometryNodeCurveToPoints")
    pts.mode = "LENGTH"
    line = ng.nodes.new("GeometryNodeCurvePrimitiveLine")
    top = ng.nodes.new("ShaderNodeCombineXYZ")
    prof = ng.nodes.new("GeometryNodeGroup")
    prof.node_tree = profile
    sweep = ng.nodes.new("GeometryNodeCurveToMesh")
    sweep.inputs["Fill Caps"].default_value = True
    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    ng.links.new(gin.outputs["Curve"], pts.inputs["Curve"])
    ng.links.new(gin.outputs["Spacing"], pts.inputs["Length"])
    ng.links.new(gin.outputs["Height"], top.inputs["Z"])
    ng.links.new(top.outputs["Vector"], line.inputs["End"])
    ng.links.new(gin.outputs["Radius"], prof.inputs["Radius"])
    ng.links.new(line.outputs["Curve"], sweep.inputs["Curve"])
    ng.links.new(prof.outputs["Curve"], sweep.inputs["Profile Curve"])
    ng.links.new(pts.outputs["Points"], inst.inputs["Points"])
    ng.links.new(sweep.outputs["Mesh"], inst.inputs["Instance"])
    ng.links.new(inst.outputs["Instances"], gout.inputs["Instances"])
    return ng


def build_fence():
    """Modifier group: posts plus one rail along the curve object it is added to."""
    rail, posts = build_rail(), build_posts()
    ng, gin, gout = fresh_group("Fence")
    ng.is_modifier = True
    socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    r = ng.nodes.new("GeometryNodeGroup"); r.node_tree = rail
    p = ng.nodes.new("GeometryNodeGroup"); p.node_tree = posts
    join = ng.nodes.new("GeometryNodeJoinGeometry")
    ng.links.new(gin.outputs["Geometry"], r.inputs["Curve"])
    ng.links.new(gin.outputs["Geometry"], p.inputs["Curve"])
    ng.links.new(r.outputs["Mesh"], join.inputs["Geometry"])
    ng.links.new(p.outputs["Instances"], join.inputs["Geometry"])
    ng.links.new(join.outputs["Geometry"], gout.inputs["Geometry"])
    return ng


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.curve.primitive_bezier_curve_add(location=(0, 0, 0))
path = bpy.context.active_object
path.scale = (4, 4, 4)
mod = path.modifiers.new("Fence", "NODES")
mod.node_group = build_fence()
bpy.ops.wm.save_as_mainfile(filepath="scene.blend")
```
