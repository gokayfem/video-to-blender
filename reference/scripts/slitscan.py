"""Slit-scan 'unrolled facade' strips. A fixed image column x samples each facade at a fixed depth
ahead of the camera; stacking that column from every frame gives the facade unrolled along the street,
1 frame = Walk Speed/24 H of street (0.0375 H at 0.9 H/s). s increases to the right in every strip (true elevation for the left side, mirrored for the right side).
Writes reference/sheets/slit_<side>_x<col>.png (raw RGB via ffmpeg).
"""
import os, sys, subprocess, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames, ROOT, N
COLS = [int(c) for c in (sys.argv[1:] or ["183", "328", "912", "1057"])]
SW = 2  # columns averaged per frame
strips = {c: np.zeros((704, N * SW, 3), np.uint8) for c in COLS}
for i, a in frames():
    for c in COLS:
        strips[c][:, i * SW:(i + 1) * SW] = a[:, c - 1:c + 1]
out = os.path.join(ROOT, "reference", "sheets"); os.makedirs(out, exist_ok=True)
for c, s in strips.items():
    side = "left" if c < 620 else "right"
    name = os.path.join(out, f"slit_{side}_x{c}.jpg")
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                          f"{s.shape[1]}x{s.shape[0]}", "-i", "-", "-q:v", "4", name], stdin=subprocess.PIPE)
    p.communicate(np.ascontiguousarray(s).tobytes()); print(name)
