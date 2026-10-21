"""Placement along a path curve. Model things in curve space (s along, d to the left, h up), then place them
through these groups; the same graph then follows any curve: bends, hills, spirals."""
from nodekit.graph import Graph
from nodekit.library import nodegroup


@nodegroup("NK Curve Frame", tags=["curve", "path", "placement", "orientation"],
           use="streets, fences, rails, rivers, cables, anything placed along a path")
def curve_frame():
    """Curve-space (s, d, h) to world position and a level orientation on a path curve."""
    g = Graph("NK Curve Frame", description="Curve-space (s, d, h) to world position and orientation on a path "
                                            "curve. s = arc length, d = lateral offset (+left), h = height above "
                                            "the curve. Rotation: +X along the curve, +Y left, +Z up")
    curve = g.input("Curve", "GEOMETRY", desc="The path curve")
    s = g.input("Length", "FLOAT", 0.0, subtype="DISTANCE", desc="Arc length along the curve (field)")
    d = g.input("Offset", "FLOAT", 0.0, subtype="DISTANCE", desc="Lateral offset, positive to the left of travel")
    h = g.input("Height", "FLOAT", 0.0, subtype="DISTANCE", desc="Height above the curve")
    with g.frame("Sample the path at arc length s"):
        sample = g.node("GeometryNodeSampleCurve", props={"mode": "LENGTH", "use_all_curves": True},
                        Curves=curve, Length=s)
    with g.frame("Level frame: tangent flattened, left = up x tangent"):
        tangent = g.vmath("NORMALIZE", g.vmath("MULTIPLY", sample["Tangent"], (1.0, 1.0, 0.0)))
        left = g.vmath("CROSS_PRODUCT", (0.0, 0.0, 1.0), tangent)
        rot = g.node("FunctionNodeAxesToRotation", props={"primary_axis": "X", "secondary_axis": "Z"},
                     **{"Primary Axis": tangent, "Secondary Axis": (0.0, 0.0, 1.0)})
    with g.frame("Offset sideways and up"):
        pos = g.vmath("ADD", g.vmath("ADD", sample["Position"], g.vmath("SCALE", left, scale=d)),
                      g.combine(0.0, 0.0, h))
    g.output("Position", "VECTOR", pos)
    g.output("Rotation", "ROTATION", rot["Rotation"])
    g.output("Tangent", "VECTOR", tangent)
    g.output("Left", "VECTOR", left)
    return g.finish()
