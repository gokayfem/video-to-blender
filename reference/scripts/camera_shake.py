"""Camera bob/sway: image shift of far-street patches (near the vanishing point, depth >> walker distance),
frame to frame by exhaustive SSD search with subpixel refinement, integrated over time.
Far patches move almost only with camera rotation (and slowly with the street bends), so their
high-frequency motion is the camera's angular bob/sway. Output out/camera_shake.csv.
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
PATCHES = [(440, 250, 100, 80), (780, 250, 100, 80), (560, 200, 160, 90)]  # x, y, w, h (far street)
prev = None; acc = np.zeros((len(PATCHES), 2)); rows = []
def match(a, b, x, y, w, h, R=6):
    p = a[y:y + h, x:x + w]; best = None
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            s = np.mean((b[y + dy:y + dy + h, x + dx:x + dx + w] - p) ** 2)
            if best is None or s < best[0]: best = (s, dx, dy)
    s0, dx, dy = best; sub = []
    for ax, ay in ((1, 0), (0, 1)):
        sm = np.mean((b[y + dy - ay:y + dy - ay + h, x + dx - ax:x + dx - ax + w] - p) ** 2)
        sp = np.mean((b[y + dy + ay:y + dy + ay + h, x + dx + ax:x + dx + ax + w] - p) ** 2)
        den = sm - 2 * s0 + sp; sub.append(0.5 * (sm - sp) / den if den > 1e-6 else 0)
    return dx + sub[0], dy + sub[1]
for i, g in frames(gray=True):
    if prev is not None:
        for k, P in enumerate(PATCHES):
            acc[k] += match(prev, g, *P)
    rows.append([i] + acc.flatten().tolist()); prev = g
R = np.array(rows)
np.savetxt(os.path.join(os.path.dirname(__file__), "out", "camera_shake.csv"), R, delimiter=",", fmt="%.3f",
           header="frame," + ",".join(f"p{k}_x,p{k}_y" for k in range(len(PATCHES))))
X = R[:, 1::2].mean(1); Y = R[:, 2::2].mean(1)
for name, s in (("far x", X), ("far y", Y)):
    hp = s - np.convolve(s, np.ones(25) / 25, "same"); hp = hp[20:-20]
    n = 4096; F = np.abs(np.fft.rfft(hp * np.hanning(len(hp)), n)); fq = np.fft.rfftfreq(n, 1 / 24)
    m = (fq > 0.5) & (fq < 6); i = np.argmax(F * m)
    print(f"{name}: dominant {fq[i]:.2f} Hz, hp amp(p5-p95)/2 {0.5*(np.percentile(hp,95)-np.percentile(hp,5)):.2f} px, total drift range {s.min():.1f}..{s.max():.1f} px")
