"""Worked example of the group contract (not part of the street): posts every N metres on both curbs.

Shows the pattern every group follows: Curve in, street-space points, SS Street Point for world placement,
instances rotated by the street frame, materials set by name, one Geometry out.
"""
from v2n.graph import Graph
from street.groups import frame
from street.materials import common

NAME = "SS Example Posts"


def build():
    pt = frame.build()
    g = Graph(NAME, description="Example: a post every Spacing metres on both curbs")
    curve = g.input("Curve", "GEOMETRY", desc="Street path curve")
    width = g.input("Street Width", "FLOAT", 4.0, min=1, max=20, subtype="DISTANCE", panel="Street",
                    desc="Curb-to-curb width")
    spacing = g.input("Spacing", "FLOAT", 3.0, min=0.5, max=50, subtype="DISTANCE", panel="Posts",
                      desc="Distance between posts along the street")
    with g.frame("Street-space samples: one point per Spacing along the curve, two sides"):
        length = g.node("GeometryNodeCurveLength", Curve=curve)
        count = g.math("FLOOR", g.math("DIVIDE", length, spacing))
        line = g.node("GeometryNodeMeshLine", props={"mode": "OFFSET"}, Count=g.math("MULTIPLY", count, 2.0),
                      Offset=(0, 0, 0))
        idx = g.node("GeometryNodeInputIndex")
        s = g.math("MULTIPLY", g.math("FLOOR", g.math("DIVIDE", idx, 2.0)), spacing)
        side = g.math("SUBTRACT", g.math("MULTIPLY", g.math("MODULO", idx, 2.0), 2.0), 1.0)
        d = g.math("MULTIPLY", side, g.math("MULTIPLY", width, 0.5))
    with g.frame("Place in world through the street frame"):
        sp = g.group(pt, Curve=curve, Length=s, Offset=d)
        pts = g.node("GeometryNodeSetPosition", Geometry=line["Mesh"], Position=sp["Position"])
        post = g.node("GeometryNodeMeshCube", Size=(0.15, 0.15, 1.0))
        lift = g.node("GeometryNodeTransform", Geometry=post["Mesh"], Translation=(0, 0, 0.5))
        inst = g.node("GeometryNodeInstanceOnPoints", Points=pts["Geometry"], Instance=lift["Geometry"],
                      Rotation=sp["Rotation"])
        real = g.node("GeometryNodeRealizeInstances", Geometry=inst["Instances"])
        mat = g.node("GeometryNodeSetMaterial", Geometry=real["Geometry"], Material=common.flat("SS Example Post",
                                                                                               (0.4, 0.2, 0.1)))
    g.output("Geometry", "GEOMETRY", mat["Geometry"])
    return g.finish()
