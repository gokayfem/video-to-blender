"""Screenshot an effect inside Blender's own UI (needs a display, not -b): the Geometry Nodes workspace with the
viewport looking through the scene camera, the effect's node graph, and its modifier panel.

    blender my_effect.blend -p 0 0 1920 1080 --python scripts/ui_shot.py -- --out shots/my_effect_ui.png \
        [--scene NAME] [--frame 100] [--shading MATERIAL|RENDERED|SOLID]

The hero object is the scene's object with a Nodes modifier whose group has the most nodes. Frames are stepped from
the start (simulation zones need it). The left area shows the most complex material's Shader Nodes. For the node
graph alone, use scripts/graph_shots.py. Quits when done.
"""
import pathlib, sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opts = dict(zip(argv[::2], argv[1::2]))
OUT = pathlib.Path(opts["--out"]).resolve()
OUT.parent.mkdir(parents=True, exist_ok=True)
SHADING = opts.get("--shading", "MATERIAL")
state = {"step": 0}


def hero(sc):
    cands = [(len(m.node_group.nodes), o) for o in sc.objects for m in o.modifiers
             if m.type == "NODES" and m.node_group]
    return max(cands, key=lambda c: c[0])[1] if cands else None


def setup():
    win = bpy.context.window_manager.windows[0]
    sc = bpy.data.scenes.get(opts.get("--scene", "")) or bpy.data.scenes[0]
    win.scene = sc
    ws = bpy.data.workspaces.get("Geometry Nodes")
    if ws:
        win.workspace = ws
    frame = int(opts.get("--frame", sc.frame_current))
    for f in range(sc.frame_start, frame + 1):             # step: simulation zones need every frame
        sc.frame_set(f)
    ob = hero(sc)
    for o in sc.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    return win, sc, ob


def arrange(win, sc, ob):
    areas = sorted(win.screen.areas, key=lambda a: a.width * a.height, reverse=True)
    for area in win.screen.areas:
        if area.type == "SPREADSHEET" or area == state.get("left"):
            # the spreadsheet becomes a Shader Editor on the most complex material (type first, tree next pass)
            state["left"] = area
            mats = [m for m in bpy.data.materials if m.node_tree and m.users]
            if not mats:
                continue
            if area.ui_type != "ShaderNodeTree":
                area.ui_type = "ShaderNodeTree"
                continue
            sp = area.spaces.active
            sp.shader_type = "OBJECT"
            sp.pin = True
            sp.node_tree = max(mats, key=lambda m: len(m.node_tree.nodes)).node_tree
            sp.show_region_ui = False
            sp.show_region_toolbar = False
            with bpy.context.temp_override(window=win, area=area,
                                           region=next(r for r in area.regions if r.type == "WINDOW")):
                bpy.ops.node.view_all()
            continue
        if area.type == "PROPERTIES":
            area.spaces.active.context = "MODIFIER"
        if area.type == "VIEW_3D":
            sp = area.spaces.active
            sp.shading.type = SHADING
            sp.overlay.show_overlays = False
            sp.show_gizmo = False
            sp.region_3d.view_perspective = "CAMERA"
            with bpy.context.temp_override(window=win, area=area,
                                           region=next(r for r in area.regions if r.type == "WINDOW")):
                bpy.ops.view3d.view_center_camera()
        if area.type == "NODE_EDITOR" and area != state.get("left"):
            area.ui_type = "GeometryNodeTree"
            sp = area.spaces.active
            sp.show_region_ui = False
            sp.show_region_toolbar = False
            with bpy.context.temp_override(window=win, area=area,
                                           region=next(r for r in area.regions if r.type == "WINDOW")):
                bpy.ops.node.select_all(action="DESELECT")
                bpy.ops.node.view_all()
    return areas


def tick():
    s = state["step"]
    state["step"] += 1
    if s == 0:
        state["ctx"] = setup()
        return 1.0
    win, sc, ob = state["ctx"]
    if s in (1, 2, 3):
        arrange(win, sc, ob)                                # thrice: editors switch type, get a tree, then frame
        return 2.5 if s == 3 else 1.0
    if s == 4:
        with bpy.context.temp_override(window=win):
            bpy.ops.screen.screenshot(filepath=str(OUT))
        print("UI SHOT", OUT)
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=2.0)
