"""Screenshot node groups in a real Blender UI (the 'reveal the graph' shots). Needs a display, not -b:

    blender street/storybook_street.blend --python tools/graph_shots.py -- --out out/graphs \
        --groups "Storybook Street,SS Facades" [--modifier]

For each group: turns the largest area into a Geometry Node Editor showing that group, frames all nodes, and
saves a PNG of that area. --modifier also saves the Properties editor's modifier panel. Quits when done.
"""
import pathlib, sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opts = dict(zip(argv[::2], argv[1::2]))
OUT = pathlib.Path(opts.get("--out", "out/graphs")).resolve()
OUT.mkdir(parents=True, exist_ok=True)
GROUPS = [g for g in opts.get("--groups", "Storybook Street").split(",") if g]
QUEUE = list(GROUPS)


def big_area():
    win = bpy.context.window_manager.windows[0]
    area = max(win.screen.areas, key=lambda a: a.width * a.height)
    return win, area


def shoot():
    if not QUEUE:
        bpy.ops.wm.quit_blender()
        return None
    name = QUEUE.pop(0)
    win, area = big_area()
    ng = bpy.data.node_groups[name]
    shader = ng.bl_idname == "ShaderNodeTree"
    area.ui_type = "ShaderNodeTree" if shader else "GeometryNodeTree"
    space = area.spaces.active
    if not shader:
        space.pin = True
        space.node_tree = ng
    space.show_region_ui = False
    space.show_region_toolbar = False
    region = next(r for r in area.regions if r.type == "WINDOW")

    def frame_all():
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.node.select_all(action="DESELECT")
            bpy.ops.node.view_all()
        return None

    def capture():
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=str(OUT / (name.replace(" ", "_") + ".png")))
        print("SHOT", name)
        return None
    bpy.app.timers.register(frame_all, first_interval=0.6)
    bpy.app.timers.register(frame_all, first_interval=1.2)
    bpy.app.timers.register(capture, first_interval=2.0)
    return 3.0


bpy.app.timers.register(shoot, first_interval=2.0)
