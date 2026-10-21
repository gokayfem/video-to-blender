"""Tile the numbered captures from `graph_shots.py --shots ALL` into one large poster: the whole scene's graphs.

    python3 scripts/graph_atlas.py shots/my_effect/ -o my_effect_graphs.jpg [--cols 6] [--tile 1280]

Order is the capture order: the hero group and its sub-groups depth first, then materials, shader groups, world,
compositor. Each tile keeps the editor header, which names the tree. Needs ffmpeg.
"""
import argparse, pathlib, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument("shots")
ap.add_argument("-o", "--out", required=True)
ap.add_argument("--cols", type=int, default=6)
ap.add_argument("--tile", type=int, default=1280, help="tile width in pixels")
a = ap.parse_args()

files = sorted(p for p in pathlib.Path(a.shots).glob("[0-9][0-9][0-9]_*.png"))
if not files:
    sys.exit(f"no NNN_*.png captures in {a.shots}")
n, cols = len(files), min(a.cols, len(files))
ins, chains = [], []
for i, f in enumerate(files):
    ins += ["-i", str(f)]
    chains.append(f"[{i}]scale={a.tile}:-2,setsar=1[t{i}]")
layout = "|".join(f"{'+'.join(['w0'] * (i % cols)) or '0'}_{'+'.join(['h0'] * (i // cols)) or '0'}" for i in range(n))
graph = ";".join(chains) + ";" + "".join(f"[t{i}]" for i in range(n)) + \
    f"xstack=inputs={n}:layout={layout}:fill=0x181818"
if n == 1:
    graph = chains[0].replace("[t0]", "")
cmd = ["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", graph, "-q:v", "3", a.out]
subprocess.run(cmd, check=True)
kinds = {}
for f in files:
    k = f.stem.split("_")[1]
    kinds[k] = kinds.get(k, 0) + 1
print(f"wrote {a.out}: {n} graphs ({', '.join(f'{v} {k}' for k, v in kinds.items())}), {cols} columns")
