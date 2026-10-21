"""Render the demonstration from a built .blend: reconstruction sequence, reference comparison, variations and
transfers. Each step is a separate Blender process, so steps can be rerun alone.

    python3 tools/demo.py --blend street/storybook_street.blend --steps seq,compare,variations,transfer
    python3 tools/demo.py --steps variations --width 960 --samples 16

Outputs (out/demo/):
  seq/f_####.png, reconstruction.mp4        the Reference scene, frames 1..481
  side_by_side.mp4, sheet.png               reference | reconstruction, synchronized by time (tools/video.py)
  compare/                                  metrics over time (tools/compare.py)
  variations/<preset>_####.png, variations.png, variations.mp4   street/presets/*.json, same frame and clip
  transfer/<scene>_####.png, transfer.png, transfer_<scene>.mp4  the same graph on other path curves
"""
import argparse, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--blend", default=str(ROOT / "street" / "storybook_street.blend"))
ap.add_argument("--steps", default="seq,compare,variations,transfer")
ap.add_argument("--out", default=str(ROOT / "out" / "demo"))
ap.add_argument("--width", type=int, default=1280)
ap.add_argument("--samples", type=int, default=16)
ap.add_argument("--step", type=int, default=1, help="frame step for sequences (2 = half the frames)")
ap.add_argument("--still", type=int, default=169, help="frame used for variation/transfer stills")
ap.add_argument("--presets", default="")
a = ap.parse_args()
OUT = pathlib.Path(a.out)
steps = set(a.steps.split(","))


def blender_render(scene, out, frames=None, rng=None, preset=None, sets=(), width=None):
    cmd = ["blender", "-b", a.blend, "--python", str(ROOT / "tools" / "render.py"), "--", "--scene", scene,
           "--width", str(width or a.width), "--samples", str(a.samples), "--out", str(out)]
    if frames:
        cmd += ["--frames", ",".join(map(str, frames))]
    if rng:
        cmd += ["--range", rng]
    if preset:
        cmd += ["--preset", preset]
    for s in sets:
        cmd += ["--set", s]
    print(">>", " ".join(cmd[:8]), "...", scene, preset or "", rng or frames)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(r.returncode)


def video(*args):
    subprocess.run([sys.executable, str(ROOT / "tools" / "video.py"), *map(str, args)], check=True)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def grid(images, out, cols):
    ins = []
    for im in images:
        ins += ["-i", str(im)]
    n = len(images)
    # xstack layout with explicit offsets (all tiles have the same size)
    layout = "|".join(f"{'+'.join(['w0'] * (i % cols)) or '0'}_{'+'.join(['h0'] * (i // cols)) or '0'}"
                      for i in range(n))
    ffmpeg(*ins, "-filter_complex", f"xstack=inputs={n}:layout={layout}:fill=black", str(out))


if "seq" in steps:
    blender_render("Reference", OUT / "seq" / "f_", rng=f"1:481:{a.step}")
    ffmpeg("-framerate", 24 // a.step, "-i", OUT / "seq" / "f_%04d.png", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", 17, OUT / "reconstruction.mp4")

if "compare" in steps:
    ref = ROOT / "reference" / "source" / "village_source.mp4"
    video("sbs", "--ref", ref, "--render", OUT / "reconstruction.mp4", "--out", OUT / "side_by_side.mp4")
    video("sheet", "--ref", ref, "--render", OUT / "reconstruction.mp4", "--times", "0:20:4",
          "--out", OUT / "sheet.png")
    subprocess.run([sys.executable, str(ROOT / "tools" / "compare.py"), "--ref", ref, "--render",
                    OUT / "reconstruction.mp4", "--times", "0:20:0.5", "--out", OUT / "compare"], check=True)

if "variations" in steps:
    presets = a.presets.split(",") if a.presets else sorted(p.stem for p in (ROOT / "street" / "presets").glob("*.json"))
    vdir = OUT / "variations"
    stills = []
    for p in presets:
        blender_render("Reference", vdir / f"{p}_", frames=[a.still], preset=p, width=a.width // 2)
        stills.append(vdir / f"{p}_{a.still:04d}.png")
    grid(stills, OUT / "variations.png", cols=2 if len(stills) <= 4 else 3)
    (OUT / "variations.json").write_text(json.dumps(presets))

if "transfer" in steps:
    tdir = OUT / "transfer"
    stills = []
    for scene in ["Reference", "Transfer S-Bend", "Transfer Hill", "Transfer Spiral"]:
        tag = scene.replace(" ", "_")
        blender_render(scene, tdir / f"{tag}_", frames=[a.still], width=a.width // 2)
        stills.append(tdir / f"{tag}_{a.still:04d}.png")
    grid(stills, OUT / "transfer.png", cols=2)
