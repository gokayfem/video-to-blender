"""Storybook Street: the top-level modifier group. Pick a path curve, get a street.

It reads the path through an Object input, wires the shared cross-section and Seed into every part, drives
animated parts with Scene Time (the only place that reads it), and forwards every other part input to its own
panel named "<Part> > <Panel>", so the modifier panel is the artist's control surface while each part group
stays usable on its own.
"""
import importlib
import os
from v2n.graph import Graph, SOCKET_TYPES

NAME = "Storybook Street"
# (module, label, extra outputs consumed elsewhere)
PARTS = [
    ("street.groups.road", "Road"),
    ("street.groups.facades", "Houses"),
    ("street.groups.props", "Props"),
    ("street.groups.bunting", "Bunting"),
    ("street.groups.walker", "Walker"),
]
SHARED = ["Street Width", "Curb Width", "Curb Height", "Verge Width"]
SHARED_SPEC = {
    "Street Width": (3.0, 1.0, 20.0, "Curb-to-curb width of the cobbled road"),
    "Curb Width": (0.25, 0.0, 1.0, "Width of the curb stones"),
    "Curb Height": (0.07, 0.0, 0.5, "Height of the curb above the road"),
    "Verge Width": (0.8, 0.0, 4.0, "Paved strip and grass between the curb and the house fronts"),
}
_TYPE_BY_SOCKET = {v: k for k, v in SOCKET_TYPES.items()}

# The Primary panel: a few broad controls that each drive several detailed ones (which stay available, and
# are combined with these: detailed value (op) primary value).
PRIMARY = [
    # name, type, default, min, max, description, [(part, input, op)]
    ("Extra Storeys", "INT", 0, -2, 4, "Taller or lower houses: added to Storeys Min and Max",
     [("Houses", "Storeys Min", "ADD"), ("Houses", "Storeys Max", "ADD")]),
    ("Timber Amount", "FLOAT", 1.0, 0.0, 1.7, "0 = plain plaster houses, 1 = the reference, more = busier framing",
     [("Houses", "Timber Density", "MULTIPLY")]),
    ("Prop Amount", "FLOAT", 1.0, 0.0, 2.0, "Scales every prop chance: window boxes, awnings, signs, lanterns, "
     "pots, barrels, ivy", [("Props", n, "MULTIPLY") for n in (
        "Window Box Chance", "Awning Chance", "Sign Chance", "Wall Lantern Chance", "Pot Chance",
        "Barrel Chance", "Ivy Chance")]),
    ("Flower Amount", "FLOAT", 1.0, 0.0, 3.0, "Blossoms in window boxes and flowers in the grass",
     [("Props", "Box Flower Density", "MULTIPLY"), ("Road", "Flower Density", "MULTIPLY")]),
    ("Festivity", "FLOAT", 1.0, 0.2, 3.0, "More bunting strings and paper lanterns (hide them with Show Bunting)",
     [("Bunting", "String Spacing", "DIVIDE"), ("Bunting", "Paper Lantern Chance", "MULTIPLY")]),
    ("Wind", "FLOAT", 1.0, 0.0, 8.0, "1 = the reference's light breeze; 4-6 = a windy day (bunting, signs)",
     [("Bunting", "Wind Strength", "MULTIPLY"), ("Props", "Sign Swing", "MULTIPLY")]),
]
PRIMARY_DIRECT = {"Walk Speed"}          # detailed inputs shown in the Primary panel as they are


def load_parts():
    built = []
    parts = PARTS
    if os.environ.get("V2N_PARTS"):          # e.g. "street.groups.road:Road,street.groups.walker:Walker"
        parts = [tuple(x.split(":")) for x in os.environ["V2N_PARTS"].split(",")]
    for mod, label in parts:
        try:
            m = importlib.import_module(mod)
        except ModuleNotFoundError:
            continue
        built.append((label, m.build()))
    return built


def _iface_inputs(ng):
    for it in ng.interface.items_tree:
        if it.item_type == "SOCKET" and it.in_out == "INPUT":
            yield it


def build():
    parts = load_parts()
    g = Graph(NAME, modifier=True,
              description="A storybook street generated along any path curve: cobbled road, half-timbered "
                          "houses, props, bunting and a walker. Every part group can also be used on its own")
    g.input("Geometry", "GEOMETRY", desc="Ignored; the street is generated from Path", hide_value=True)
    path = g.input("Path", "OBJECT", desc="The curve the street follows. Draw any curve and pick it here",
                   panel="Primary")
    seed = g.input("Seed", "INT", 0, desc="Changes every random choice: house widths, colours, props, stones",
                   panel="Primary")
    shared = {"Seed": seed}
    for name in SHARED:
        dv, lo, hi, desc = SHARED_SPEC[name]
        shared[name] = g.input(name, "FLOAT", dv, min=lo, max=hi, subtype="DISTANCE", desc=desc,
                               panel="Primary" if name == "Street Width" else "Street")
    macros, macro_targets = {}, {}
    for name, stype, dv, lo, hi, desc, targets in PRIMARY:
        macros[name] = g.input(name, stype, dv, min=lo, max=hi, desc=desc, panel="Primary")
        for part, inp, op in targets:
            macro_targets[(part, inp)] = (name, op)
    tscale = g.input("Time Scale", "FLOAT", 1.0, min=0.0, max=4.0, panel="Street",
                     desc="Speed of all animation (walk, wind); 0 freezes the street")
    toffset = g.input("Time Offset", "FLOAT", 0.0, subtype="TIME_ABSOLUTE", panel="Street",
                      desc="Seconds added to scene time, to choose a different moment")
    shows = {label: g.input(f"Show {label}", "BOOL", True, panel="Visibility", desc=f"Generate the {label.lower()}")
             for label, _ in parts}

    with g.frame("Path curve and animation clock"):
        info = g.node("GeometryNodeObjectInfo", props={"transform_space": "RELATIVE"}, Object=path)
        clock = g.node("GeometryNodeInputSceneTime")
        time = g.math("MULTIPLY_ADD", clock["Seconds"], tscale, toffset, label="Time")

    # Forward each part's own inputs to "<Part> > <Panel>" panels on the modifier
    nodes = {}
    used = {"Path", "Seed", "Time Scale", "Time Offset", *SHARED, *(f"Show {l}" for l, _ in parts),
            *(p[0] for p in PRIMARY)}
    for label, ng in parts:
        with g.frame(f"{label}: its own inputs, Primary macros applied"):
            node = g.group(ng, label=label)
            nodes[label] = node
            for it in _iface_inputs(ng):
                sock = next(s for s in node.b.inputs if s.identifier == it.identifier)
                if it.name == "Curve":
                    g.connect(info["Geometry"], sock)
                elif it.name == "Time":
                    g.connect(time, sock)
                elif it.name in shared:
                    g.connect(shared[it.name], sock)
                elif it.socket_type == "NodeSocketGeometry":
                    continue                                        # wired below (Anchors)
                else:
                    panel = f"{label} > {it.parent.name}" if it.parent and it.parent.name else label
                    if it.name in PRIMARY_DIRECT:
                        panel = "Primary"
                    kw = {}
                    for k, attr in (("min", "min_value"), ("max", "max_value"), ("subtype", "subtype")):
                        if hasattr(it, attr):
                            kw[k] = getattr(it, attr)
                    if kw.get("subtype") == "NONE":
                        kw.pop("subtype")
                    default = getattr(it, "default_value", None)
                    if default is not None and hasattr(default, "__len__") and not isinstance(default, str):
                        default = tuple(default)
                    stype = _TYPE_BY_SOCKET.get(it.socket_type, None)
                    if stype is None:
                        continue
                    name = it.name if it.name not in used else f"{label} {it.name}"
                    used.add(name)
                    src = g.input(name, stype, default, desc=it.description, panel=panel, **kw)
                    if (label, it.name) in macro_targets:
                        mname, op = macro_targets[(label, it.name)]
                        src = g.math(op, src, macros[mname], label=f"{it.name} {op.lower()} {mname}")
                    g.connect(src, sock)

    if "Houses" in nodes and "Props" in nodes:
        anchors = [s for s in nodes["Houses"].b.outputs if s.name == "Anchors"]
        if anchors:
            g.connect(anchors[0], nodes["Props"].i("Anchors"))

    with g.frame("Join visible parts, realize once for materials"):
        join = g.node("GeometryNodeJoinGeometry")
        for label, node in nodes.items():
            sw = g.node("GeometryNodeSwitch", props={"input_type": "GEOMETRY"}, Switch=shows[label],
                        **{"True": node["Geometry"]})
            g.connect(sw["Output"], join.i("Geometry"))
        real = g.node("GeometryNodeRealizeInstances", Geometry=join["Geometry"])
    g.output("Geometry", "GEOMETRY", real["Geometry"])
    return g.finish()
