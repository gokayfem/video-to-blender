"""Build every template, validate it, and render its gallery image.

    python3 tests/build_gallery.py                 build + validate + render gallery/<name>.png (and .blend)
    python3 tests/build_gallery.py --check         build + validate only (CI)
    python3 tests/build_gallery.py --only growth-sim --width 960 --samples 16

Template contract: skills/procedural-blender-nodes/templates/<name>.py is a Blender script run as
`blender -b --factory-startup --python <name>.py -- --out <file.blend> [--render <file.png>] [--width W]
[--samples N] [--frame F]`. It builds its node groups from the library, creates its scene (input object, light,
camera), saves the .blend, and renders the still if asked. Its docstring's first line is its gallery caption.
"""
import argparse, ast, os, pathlib, shutil, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "procedural-blender-nodes"
TEMPLATES = SKILL / "templates"
GALLERY = REPO / "gallery"

ap = argparse.ArgumentParser()
ap.add_argument("--check", action="store_true")
ap.add_argument("--only", default="")
ap.add_argument("--width", type=int, default=960)
ap.add_argument("--samples", type=int, default=16)
a = ap.parse_args()


def blender():
    for c in (os.environ.get("BLENDER"), shutil.which("blender"), "/Applications/Blender.app/Contents/MacOS/Blender"):
        if c and pathlib.Path(c).exists():
            return c
    sys.exit("Blender not found")


failures = []
GALLERY.mkdir(exist_ok=True)
build = REPO / "build" / "gallery"
build.mkdir(parents=True, exist_ok=True)
for tpl in sorted(TEMPLATES.glob("*.py")):
    name = tpl.stem
    if a.only and name not in a.only.split(","):
        continue
    blend = build / f"{name}.blend"
    blend.unlink(missing_ok=True)                 # never validate a stale file from an earlier run
    cmd = [blender(), "-b", "--factory-startup", "--python", str(tpl), "--", "--out", str(blend)]
    if not a.check:
        cmd += ["--render", str(GALLERY / f"{name}.png"), "--width", str(a.width), "--samples", str(a.samples)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode or not blend.exists():
        failures.append(f"{name}: build failed\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
        print("FAIL build", name)
        continue
    v = subprocess.run([blender(), "-b", str(blend), "--python", str(SKILL / "scripts" / "validate.py"), "--",
                        "--no-cameras", "--out", str(build / f"{name}_validate")], capture_output=True, text=True)
    summary = [l for l in v.stdout.splitlines() if l.startswith(("SCENE", "FAILURES", "   "))]
    print(("PASS " if v.returncode == 0 else "FAIL ") + name)
    for l in summary:
        print("   ", l[:180])
    if v.returncode:
        failures.append(f"{name}: validation failed")
    if not a.check and (GALLERY / f"{name}.png").exists():
        doc = ast.get_docstring(ast.parse(tpl.read_text())) or ""
        print("    gallery:", f"gallery/{name}.png", "-", doc.strip().splitlines()[0] if doc.strip() else "")

print(f"{len(failures)} failure(s)")
for f in failures:
    print(f)
sys.exit(1 if failures else 0)
