"""Build storybook_street.blend from nothing.

    blender -b --factory-startup --python street/build.py -- [--out street/storybook_street.blend] [--preset reference]

One .blend, several scenes sharing the SAME node groups:
  Reference          the reference-like street and follow camera (the clip's shot)
  Transfer S-Bend    the same graph on a strongly winding path
  Transfer Hill      ... on a climbing path
  Transfer Spiral    ... on an inward spiral (seen from above)
Each scene has its own path curve object; the street object carries one 'Storybook Street' modifier whose Path
input points at it. A camera rig follows the walker along the same curve (Follow Path with a driver that reads
the modifier's Walk Start / Walk Speed / Time Scale / Time Offset), so retiming the walk in the modifier retimes
the camera too.
"""
import argparse, json, math, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT.parents[1] / "skills" / "procedural-blender-nodes"
sys.path[:0] = [str(ROOT), str(SKILL)]
import bpy
from nodekit import inspect
from nodekit import scene as S
from street.groups import assembly

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(ROOT / "street" / "storybook_street.blend"))
ap.add_argument("--preset", default="1_reference")
ap.add_argument("--scenes", default="Reference,Transfer S-Bend,Transfer Hill,Transfer Spiral")
a = ap.parse_args(argv)

SCENES = {
    "Reference": dict(path="reference", cam="follow"),
    "Transfer S-Bend": dict(path="s_bend", cam="high"),
    "Transfer Hill": dict(path="hill", cam="follow"),
    "Transfer Spiral": dict(path="spiral", cam="top"),
}
CAM = json.loads((ROOT / "street" / "camera.json").read_text()) if (ROOT / "street" / "camera.json").exists() else {
    "follow": {"lens": 20.0, "back": 2.05, "side": -0.15, "height": 0.925, "ahead": 8.0, "target_h": 0.925},
    "high": {"lens": 32.0, "static": [52, -14, 34], "look_at": [0, 24, 0], "ground": True,
             "haze": {"haze_start": 12.0, "haze_depth": 220.0}},
    "top": {"lens": 35.0, "static": [0, -105, 90], "look_at": [0, 2, 0], "ground": True,
            "haze": {"haze_start": 120.0, "haze_depth": 400.0, "haze_amount": 0.35}},
}


def load_preset(name):
    p = ROOT / "street" / "presets" / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def curve_length(ob):
    """Arc length of the path as Geometry Nodes sees it (Bezier splines at their resolution)."""
    return sum(sp.calc_length() for sp in ob.data.splines)


def driver_var(drv, name, target_id, path, id_type="OBJECT"):
    v = drv.variables.new()
    v.name, v.type = name, "SINGLE_PROP"
    v.targets[0].id_type = id_type
    v.targets[0].id = target_id
    v.targets[0].data_path = path


def camera_rig(sc, curve, street, mod, kind, name=None):
    spec = CAM[kind]
    name = name or f"{sc.name} Camera"
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens, cam_data.clip_start, cam_data.clip_end = spec["lens"], 0.05, 500
    cam = bpy.data.objects.new(name, cam_data)
    target = bpy.data.objects.new(f"{name} Target", None)
    for o in (cam, target):
        sc.collection.objects.link(o)
    sc.camera = cam
    if "static" in spec:
        cam.location = spec["static"]
        target.location = spec["look_at"]
    else:
        # Camera and aim point both ride the path itself (behind and ahead of the walker), so on any curve the
        # camera stays over the street, never inside a house, however tight the bend.
        ids = inspect.modifier_inputs(mod)
        curve["street_length"] = curve_length(curve)      # before the drivers exist, so they never divide by 0
        print(f"PATH {curve.name}: length {curve['street_length']:.2f}")
        names = {"ws": "Walk Start", "sp": "Walk Speed", "ts": "Time Scale", "to": "Time Offset"}
        consts = {"ws": 4.0, "sp": 0.9, "ts": 1.0, "to": 0.0}
        for obj, along, side, up in ((cam, -spec["back"], -spec.get("side", 0.0), spec["height"]),
                                     (target, spec["ahead"], -spec.get("side", 0.0), spec["target_h"])):
            rig = bpy.data.objects.new(f"{obj.name} Rig", None)
            sc.collection.objects.link(rig)
            c = rig.constraints.new("FOLLOW_PATH")
            c.target, c.use_fixed_location, c.use_curve_follow = curve, True, True
            c.forward_axis, c.up_axis = "FORWARD_Y", "UP_Z"
            obj.parent = rig
            obj.location = (side, 0.0, up)
            drv = c.driver_add("offset_factor").driver
            drv.type = "SCRIPTED"
            driver_var(drv, "L", curve, '["street_length"]')
            expr = {}
            for k, nm in names.items():
                if nm in ids:
                    driver_var(drv, k, street, f'modifiers["{mod.name}"].properties.inputs.{ids[nm]}.value')
                    expr[k] = k
                else:
                    expr[k] = repr(consts[k])
            drv.expression = (f"min(max(({expr['ws']} + {expr['sp']} * (frame / {S.FPS} * {expr['ts']} + "
                              f"{expr['to']}) + {along}) / L, 0.0), 1.0)")
    tc = cam.constraints.new("TRACK_TO")
    tc.target, tc.track_axis, tc.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    return cam


def main():
    sc0 = S.reset()
    group = assembly.build()
    preset = load_preset(a.preset)
    names = [n for n in a.scenes.split(",") if n]
    for i, name in enumerate(names):
        cfg = SCENES[name]
        sc = sc0 if i == 0 else bpy.data.scenes.new(name)
        sc.name = name
        sc.render.fps, sc.frame_start, sc.frame_end = S.FPS, 1, 481
        curve = S.path_curve(cfg["path"], name=f"{name} Path", sc=sc)
        curve.data.use_path = True
        curve.hide_render = True
        street, mod = S.holder(f"{name} Street", curve, group, sc=sc)
        inspect.set_modifier_inputs(mod, {"Path": curve.name, **preset})
        light = json.loads((ROOT / "street" / "light.json").read_text())
        render_opts, post_opts = light.pop("render", {}), light.pop("post", None)
        S.light_world(sc=sc, **light)
        follow = camera_rig(sc, curve, street, mod, "follow")
        if cfg["cam"] != "follow":                      # overview shot is the scene camera; follow stays available
            camera_rig(sc, curve, street, mod, cfg["cam"], name=f"{name} Overview")
        if CAM[cfg["cam"]].get("ground"):
            S.ground(sc=sc)
        S.render_setup(sc=sc, **render_opts)
        if post_opts is not None:
            S.post(sc=sc, **{**post_opts, **CAM[cfg["cam"]].get("haze", {})})
        sc.frame_set(1)
        st = inspect.evaluated_stats(street, sc)
        print(f"SCENE {name}: verts {st['verts']} faces {st['faces']} materials {len(st['materials'])} "
              f"warnings {[w.message for w in mod.node_warnings]}")
    problems = inspect.check_groups("SS ") + inspect.check_groups(assembly.NAME)
    print("LINT", len(problems))
    for p in problems:
        print("  ", p)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    inspect.dump_groups(str(out.with_suffix(".graph.json")))
    bpy.ops.wm.save_as_mainfile(filepath=str(out.resolve()), compress=True)
    print("SAVED", out)


main()
