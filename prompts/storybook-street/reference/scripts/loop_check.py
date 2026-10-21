"""Loop seam and frame-to-frame change: mean abs difference (0-255) of frame 0 vs each frame,
and of consecutive frames."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
f0 = None; prev = None; d0 = []; dd = []
for i, g in frames(gray=True):
    if f0 is None: f0 = g
    d0.append(np.abs(g - f0).mean())
    if prev is not None: dd.append(np.abs(g - prev).mean())
    prev = g
d0 = np.array(d0); dd = np.array(dd)
print("consecutive diff: median %.2f  max %.2f at %d" % (np.median(dd), dd.max(), dd.argmax()))
for k in (1, 2, 12, 24, 48, 120, 240, 400, 460, 470, 476, 478, 479, 480):
    print(f"diff(frame0, frame{k}) = {d0[k]:.2f}")
