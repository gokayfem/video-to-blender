"""SS Street Point: the street's coordinate frame. Every other group places things through it.

A street-space point is (s, d, h): arc length along the path curve, lateral offset (+ = left of travel), height
above the curve. The group returns world position and a rotation whose +X runs along the street, +Y points left
and +Z is up, so anything modelled in street space can be instanced with that rotation and follows any curve.
"""
from v2n.graph import Graph, once

NAME = "SS Street Point"


@once
def build():
    g = Graph(NAME, description="Street-space (s, d, h) to world position and orientation on the path curve. "
                                "s = arc length, d = lateral offset (+left), h = height above the curve")
    curve = g.input("Curve", "GEOMETRY", desc="The street's path curve")
    s = g.input("Length", "FLOAT", 0.0, subtype="DISTANCE", desc="Arc length along the curve (field)")
    d = g.input("Offset", "FLOAT", 0.0, subtype="DISTANCE", desc="Lateral offset, positive to the left of travel")
    h = g.input("Height", "FLOAT", 0.0, subtype="DISTANCE", desc="Height above the curve")
    with g.frame("Sample the path at arc length s"):
        sample = g.node("GeometryNodeSampleCurve", props={"mode": "LENGTH", "use_all_curves": True},
                        Curves=curve, Length=s)
    with g.frame("Horizontal frame: tangent, left = up x tangent"):
        flat = g.vmath("MULTIPLY", sample["Tangent"], (1.0, 1.0, 0.0))
        tangent = g.vmath("NORMALIZE", flat)
        left = g.vmath("CROSS_PRODUCT", (0.0, 0.0, 1.0), tangent)
        rot = g.node("FunctionNodeAxesToRotation", props={"primary_axis": "X", "secondary_axis": "Z"},
                     **{"Primary Axis": tangent, "Secondary Axis": (0.0, 0.0, 1.0)})
    with g.frame("Offset sideways and up"):
        side = g.vmath("SCALE", left, scale=d)
        up = g.combine(0.0, 0.0, h)
        pos = g.vmath("ADD", g.vmath("ADD", sample["Position"], side), up)
    g.output("Position", "VECTOR", pos)
    g.output("Rotation", "ROTATION", rot["Rotation"])
    g.output("Tangent", "VECTOR", tangent)
    g.output("Left", "VECTOR", left)
    return g.finish()
