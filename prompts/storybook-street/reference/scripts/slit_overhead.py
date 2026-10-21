"""Overhead slit: image column(s) near the street centre, rows 0-360, stacked over time (3 px per frame).
Bunting strings and lanterns crossing over the street show as tracks rising out of the top; counting
how many leave the top edge over the 20 s gives the string spacing along the street.
Writes reference/sheets/slit_overhead_x<col>.jpg
"""
import os, sys, subprocess, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames, ROOT, N
for col in [int(c) for c in (sys.argv[1:] or ["560", "700"])]:
    S = np.zeros((360, N * 2, 3), np.uint8)
    for i, a in frames():
        S[:, 2 * i:2 * i + 2] = a[:360, col - 1:col + 1]
    name = os.path.join(ROOT, "reference", "sheets", f"slit_overhead_x{col}.jpg")
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{S.shape[1]}x{S.shape[0]}",
                          "-i", "-", "-q:v", "4", name], stdin=subprocess.PIPE)
    p.communicate(S.tobytes()); print(name)
