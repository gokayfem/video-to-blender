"""Screenshot node graphs of every kind in a real Blender UI (needs a display, not -b):

    blender my_effect.blend --python scripts/graph_shots.py -- --out shots/ \
        --shots "TOP,MAT:*,WORLD,COMP,MODIFIER"   [--prefix my_effect_]

Shot specs (comma separated):
  TOP            the Geometry Nodes group on the scene's hero object (the Nodes modifier with the most nodes)
  <group name>   any node group by name: Geometry, Shader or Compositor group
  MAT:<name>     a material's Shader Nodes; MAT:* = the material with the most nodes
  SGROUP:*       the shader node group (e.g. an NK material group) with the most nodes, opened
  WORLD          the scene's world shader
  COMP           the scene's compositor graph
  MODIFIER       the Properties editor on the hero object's modifier tab
  ALL            every node tree the scene uses, in order: the hero group and its sub-groups depth first, then
                 materials, shader groups, world, compositor; files are numbered NNN_<kind>_<name>.png for
                 scripts/graph_atlas.py
Each shot turns the largest area into the right editor, frames all nodes and saves <prefix><kind>.png
(geometry, shader, world, compositor, modifier, or the slugged group name). Specs that do not exist in the
file are skipped with a message. Quits when done.
"""
import pathlib, re, sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opts = dict(zip(argv[::2], argv[1::2]))
OUT = pathlib.Path(opts.get("--out", "out/graphs")).resolve()
OUT.mkdir(parents=True, exist_ok=True)
PREFIX = opts.get("--prefix", "")
SPECS = [s.strip() for s in opts.get("--shots", opts.get("--groups", "TOP")).split(",") if s.strip()]
QUEUE = []


def expand_all():
    """Every tree the scene uses, hierarchy first: [(spec, stem)]."""
    _, ob, mod = hero()
    out, seen = [], set()

    def walk(ng):
        if ng is None or ng.name in seen:
            return
        seen.add(ng.name)
        out.append((ng.name, "geo_" + slug(ng.name)))
        for n in ng.nodes:
            if getattr(n, "node_tree", None) is not None and n.node_tree.bl_idname == "GeometryNodeTree":
                walk(n.node_tree)
    walk(mod.node_group if mod else None)
    for m in sorted((m for m in bpy.data.materials if m.node_tree and m.users), key=lambda m: m.name):
        out.append(("MAT:" + m.name, "mat_" + slug(m.name)))
    for g in sorted((g for g in bpy.data.node_groups if g.bl_idname == "ShaderNodeTree" and g.users),
                    key=lambda g: g.name):
        out.append((g.name, "sgroup_" + slug(g.name)))
    out += [("WORLD", "world"), ("COMP", "compositor")]
    return [(spec, f"{i:03d}_{stem}") for i, (spec, stem) in enumerate(out)]


STEMS = {}
for s in SPECS:
    if s == "ALL":
        QUEUE.append("__ALL__")
    else:
        QUEUE.append(s)


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def hero():
    sc = bpy.context.window_manager.windows[0].scene
    cands = [(len(m.node_group.nodes), o, m) for o in sc.objects for m in o.modifiers
             if m.type == "NODES" and m.node_group]
    return max(cands, key=lambda c: c[0]) if cands else (0, None, None)


def resolve(spec):
    """-> (ui_type, shader_type or None, node_tree or None, file stem) or None when absent."""
    sc = bpy.context.window_manager.windows[0].scene
    if spec == "TOP":
        _, ob, mod = hero()
        return ("GeometryNodeTree", None, mod.node_group, "geometry") if mod else None
    if spec.startswith("MAT:"):
        name = spec[4:]
        mats = [m for m in bpy.data.materials if m.node_tree and m.users]
        mat = max(mats, key=lambda m: len(m.node_tree.nodes)) if name == "*" and mats else bpy.data.materials.get(name)
        return ("ShaderNodeTree", "OBJECT", mat.node_tree, "shader" if name == "*" else "shader_" + slug(name)) \
            if mat and mat.node_tree else None
    if spec == "SGROUP:*":
        groups = [g for g in bpy.data.node_groups if g.bl_idname == "ShaderNodeTree" and g.users]
        g = max(groups, key=lambda g: len(g.nodes)) if groups else None
        return ("ShaderNodeTree", "OBJECT", g, "shader_group") if g else None
    if spec == "WORLD":
        return ("ShaderNodeTree", "WORLD", sc.world.node_tree, "world") if sc.world and sc.world.node_tree else None
    if spec == "COMP":
        ng = getattr(sc, "compositing_node_group", None)
        return ("CompositorNodeTree", None, ng, "compositor") if ng else None
    ng = bpy.data.node_groups.get(spec)
    if ng is None:
        return None
    ui = {"GeometryNodeTree": "GeometryNodeTree", "ShaderNodeTree": "ShaderNodeTree",
          "CompositorNodeTree": "CompositorNodeTree"}[ng.bl_idname]
    return (ui, "OBJECT" if ui == "ShaderNodeTree" else None, ng, slug(spec))


def big_area():
    win = bpy.context.window_manager.windows[0]
    return win, max(win.screen.areas, key=lambda a: a.width * a.height)


def shoot():
    if not QUEUE:
        bpy.ops.wm.quit_blender()
        return None
    spec = QUEUE.pop(0)
    if spec == "__ALL__":
        items = expand_all()
        for sp, stem in reversed(items):
            QUEUE.insert(0, sp)
            STEMS.setdefault(sp, stem)
        print("ALL:", len(items), "trees")
        return 0.1
    win, area = big_area()
    if spec == "MODIFIER":
        return shoot_modifier(win, area)
    target = resolve(spec)
    if target is None:
        print("SKIP", spec, "(not in this file)")
        return 0.2
    ui, shader_type, tree, stem = target
    stem = STEMS.get(spec, stem)
    area.ui_type = ui

    def set_tree():                                        # the space only exists after the type switch redraws
        space = area.spaces.active
        if shader_type and hasattr(space, "shader_type"):
            space.shader_type = shader_type
        try:
            space.pin = True
            space.node_tree = tree
        except (AttributeError, TypeError, RuntimeError):
            pass                                           # editor shows the scene's own tree (compositor)
        space.show_region_ui = False
        space.show_region_toolbar = False
        return None

    def frame_all():
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.node.select_all(action="DESELECT")
            bpy.ops.node.view_all()
        return None

    def capture():
        region = next(r for r in area.regions if r.type == "WINDOW")
        path = OUT / f"{PREFIX}{stem}.png"
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=str(path))
        print("SHOT", spec, "->", path.name)
        return None

    bpy.app.timers.register(set_tree, first_interval=0.4)
    bpy.app.timers.register(frame_all, first_interval=1.0)
    bpy.app.timers.register(frame_all, first_interval=1.6)
    bpy.app.timers.register(capture, first_interval=2.4)
    return 3.2


def shoot_modifier(win, area):
    """The Properties editor on the hero object's modifier tab: the artist's control surface."""
    _, ob, _ = hero()
    sc = win.scene
    for o in sc.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    area.ui_type = "PROPERTIES"

    def tab():
        area.spaces.active.context = "MODIFIER"
        return None

    def capture():
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=str(OUT / f"{PREFIX}modifier.png"))
        print("SHOT MODIFIER")
        return None
    bpy.app.timers.register(tab, first_interval=0.4)
    bpy.app.timers.register(capture, first_interval=1.6)
    return 2.4


bpy.app.timers.register(shoot, first_interval=2.0)
