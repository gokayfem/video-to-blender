"""Two-colour split (luminance threshold at the median) of a box: for striped awnings, flags, etc.
usage: two_tone.py T X0 Y0 X1 Y1 [label]  (T = second, reads reference/frames/tNN.png)"""
import os, sys, subprocess, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import srgb_hex, ROOT
t, x0, y0, x1, y1 = map(int, sys.argv[1:6])
b = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", os.path.join(ROOT, "reference", "frames", f"t{t:02d}.png"), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
A = np.frombuffer(b, np.uint8).reshape(704, 1280, 3)[y0:y1, x0:x1].reshape(-1, 3).astype(float)
L = A @ [0.3, 0.59, 0.11]; th = np.median(L)
lo, hi = A[L < np.percentile(L, 35)], A[L > np.percentile(L, 65)]
print(f"{' '.join(sys.argv[6:]) or 'box'}: dark {srgb_hex(np.median(lo,0))}  light {srgb_hex(np.median(hi,0))}")
