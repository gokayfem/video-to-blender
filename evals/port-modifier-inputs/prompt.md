---
description: "Repair: port a Blender 4.x script that sets Geometry Nodes modifier inputs through ID properties to 5.2."
tags: [positive, repair]
expected_outcome: "build.py sets the modifier inputs through the 5.2 API (mod.properties.inputs or a helper that uses it), including Size from the pebble_size attribute and the Material, keeps the group interface, and saves scene.blend."
max_turns: 50
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

This script worked in Blender 4.2 but fails in 5.2 with `TypeError: bpy_struct[key] = val: id properties not supported for this type` on the line `mod["Socket_1"] = 35.0`. Please port it to 5.2 so it does the same thing: density 35, pebble size read from the `pebble_size` attribute, seed 7 and the Stone material. Don't change the node group's inputs. Save the ported script as `build.py`; `blender -b --python build.py` should save `scene.blend`.

```python
import bpy


def new_input(ng, name, stype, default=None, lo=None, hi=None, desc=""):
    s = ng.interface.new_socket(name, in_out="INPUT", socket_type=stype)
    if default is not None:
        s.default_value = default
    if lo is not None:
        s.min_value, s.max_value = lo, hi
    s.description = desc
    return s


def build_pebbles():
    ng = bpy.data.node_groups.new("Pebbles", "GeometryNodeTree")
    ng.is_modifier = True
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    new_input(ng, "Density", "NodeSocketFloat", 20.0, 0.0, 500.0, "Pebbles per square metre")
    new_input(ng, "Size", "NodeSocketFloat", 0.08, 0.01, 1.0, "Pebble radius; can be driven by an attribute")
    new_input(ng, "Seed", "NodeSocketInt", 0, 0, 10000, "Random layout seed")
    new_input(ng, "Material", "NodeSocketMaterial", desc="Pebble material")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    gin, gout = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
    dist = ng.nodes.new("GeometryNodeDistributePointsOnFaces")
    rock = ng.nodes.new("GeometryNodeMeshIcoSphere")
    rock.inputs["Subdivisions"].default_value = 1
    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    setmat = ng.nodes.new("GeometryNodeSetMaterial")
    realize = ng.nodes.new("GeometryNodeRealizeInstances")
    join = ng.nodes.new("GeometryNodeJoinGeometry")
    L = ng.links.new
    L(gin.outputs["Geometry"], dist.inputs["Mesh"])
    L(gin.outputs["Density"], dist.inputs["Density"])
    L(gin.outputs["Seed"], dist.inputs["Seed"])
    L(dist.outputs["Points"], inst.inputs["Points"])
    L(rock.outputs["Mesh"], inst.inputs["Instance"])
    L(gin.outputs["Size"], inst.inputs["Scale"])
    L(inst.outputs["Instances"], realize.inputs["Geometry"])
    L(realize.outputs["Geometry"], setmat.inputs["Geometry"])
    L(gin.outputs["Material"], setmat.inputs["Material"])
    L(gin.outputs["Geometry"], join.inputs["Geometry"])
    L(setmat.outputs["Geometry"], join.inputs["Geometry"])
    L(join.outputs["Geometry"], gout.inputs["Geometry"])
    return ng


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_grid_add(x_subdivisions=40, y_subdivisions=40, size=6)
ground = bpy.context.active_object
ground.name = "Ground"

# per-vertex pebble size: bigger toward the middle
size = ground.data.attributes.new("pebble_size", "FLOAT", "POINT")
for i, v in enumerate(ground.data.vertices):
    size.data[i].value = max(0.02, 0.12 - 0.03 * v.co.length)

stone = bpy.data.materials.new("Stone")
stone.diffuse_color = (0.42, 0.40, 0.37, 1.0)

mod = ground.modifiers.new("Pebbles", "NODES")
mod.node_group = build_pebbles()
mod["Socket_1"] = 35.0                       # Density
mod["Socket_2_use_attribute"] = True         # Size from the pebble_size attribute
mod["Socket_2_attribute_name"] = "pebble_size"
mod["Socket_3"] = 7                          # Seed
mod["Socket_4"] = stone                      # Material
ground.data.update()

bpy.ops.wm.save_as_mainfile(filepath="scene.blend")
```
