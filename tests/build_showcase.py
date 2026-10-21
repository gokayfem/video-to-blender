"""Build the README showcase from the gallery .blend files (needs a display: Blender opens windows).

    python3 tests/build_showcase.py [--only parametric_house] [--skip-atlas]

For every template in build/gallery/<name>.blend (run tests/build_gallery.py first) and for the Storybook Street
project, writes to gallery/:
  ui/<name>_ui.png               Blender itself: viewport through the camera, shader editor, geometry nodes,
                                 modifier panel (scripts/ui_shot.py)
  nodes/<name>_<kind>.png        the main graph of each kind: geometry, shader_group, shader, world, compositor
  atlas/<name>_graphs.jpg        every node tree the scene uses, tiled (scripts/graph_shots.py ALL +
                                 scripts/graph_atlas.py)
"""
import argparse, os, pathlib, shutil, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "procedural-blender-nodes" / "scripts"
G = REPO / "gallery"
FRAMES = {"growth_sim": 100, "storybook_street": 169}

ap = argparse.ArgumentParser()
ap.add_argument("--only", default="")
ap.add_argument("--skip-atlas", action="store_true")
a = ap.parse_args()


def blender():
    for c in (os.environ.get("BLENDER"), shutil.which("blender"), "/Applications/Blender.app/Contents/MacOS/Blender"):
        if c and pathlib.Path(c).exists():
            return c
    sys.exit("Blender not found")


def run_ui(blend, script, *args):
    cmd = [blender(), str(blend), "-p", "0", "0", "1920", "1080", "--python", str(SCRIPTS / script), "--", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    shots = [l for l in r.stdout.splitlines() if l.startswith(("UI SHOT", "SHOT", "SKIP", "ALL:"))]
    print("  ", script, f"{len(shots)} lines", *(s for s in shots if s.startswith(("SKIP", "ALL:"))))
    return r.returncode


targets = {p.stem: p for p in sorted((REPO / "build" / "gallery").glob("*.blend"))}
targets["storybook_street"] = REPO / "prompts" / "storybook-street" / "street" / "storybook_street.blend"
for name, blend in targets.items():
    if a.only and name not in a.only.split(","):
        continue
    if not blend.exists():
        print("missing", blend)
        continue
    print(name)
    frame = ["--frame", str(FRAMES[name])] if name in FRAMES else []
    run_ui(blend, "ui_shot.py", "--out", str(G / "ui" / f"{name}_ui.png"), *frame)
    run_ui(blend, "graph_shots.py", "--out", str(G / "nodes"), "--prefix", f"{name}_",
           "--shots", "TOP,SGROUP:*,MAT:*,WORLD,COMP,MODIFIER")
    if not a.skip_atlas:
        shots = REPO / "build" / "atlas" / name
        shutil.rmtree(shots, ignore_errors=True)
        run_ui(blend, "graph_shots.py", "--out", str(shots), "--shots", "ALL")
        (G / "atlas").mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(SCRIPTS / "graph_atlas.py"), str(shots), "-o",
                        str(G / "atlas" / f"{name}_graphs.jpg"), "--tile", "960"], check=True)
