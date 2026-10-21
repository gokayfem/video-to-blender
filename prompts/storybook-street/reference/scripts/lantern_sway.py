"""Lantern sway: track a lantern blob centroid, fit the static-point model (1/u and 1/w linear in t),
and analyse the residual (sway) in pixels and in H (px * d / u). Also flags.
usage: lantern_sway.py FRAME X Y [N]
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
XF, YH, HC, K = 620.0, 355.0, 0.895, 1.29e-3
def run(f0, x, y, n=96):
    pos = np.array([x, y], float); tr = []; R = 40; sizes = []
    for i, a in frames(f0, n):
        x0, y0 = int(max(pos[0] - R, 0)), int(max(pos[1] - R, 0))
        c = a[y0:int(pos[1] + R), x0:int(pos[0] + R)].astype(np.int16)
        m = (c[..., 0] > 190) & (c[..., 1] > 150) & (c[..., 2] < 180) & (c[..., 0] - c[..., 2] > 50)
        ys, xs = np.nonzero(m)
        if len(xs) < 40: break
        d = np.hypot(xs + x0 - pos[0], ys + y0 - pos[1]); k = d < max(8, np.percentile(d, 70))
        xs, ys = xs[k] + x0, ys[k] + y0
        pos = np.array([xs.mean(), ys.mean()]); tr.append((i, *pos)); sizes.append((np.ptp(xs) + 1, np.ptp(ys) + 1))
        R = max(25, 0.9 * max(sizes[-1]))
        if pos[0] < 30 or pos[1] < 30 or pos[0] > 1250: break
    tr = np.array(tr); t = tr[:, 0] / 24; u = tr[:, 1] - XF; w = YH - tr[:, 2]
    pu = np.polyfit(t, 1 / u, 1); pw = np.polyfit(t, 1 / w, 1)
    ru = u - 1 / np.polyval(pu, t); rw = w - 1 / np.polyval(pw, t)
    d = -K / pu[0]; h = HC - K / pw[0]
    scale = d / u  # H per px at each frame
    sx = ru * scale; sy = rw * scale
    def per(s):
        s = s - s.mean(); r = np.correlate(s, s, "full")[len(s) - 1:]; r /= r[0] + 1e-9
        lo = 6; k = lo + np.argmax(r[lo:len(s) // 2]) if len(s) > 2 * lo + 2 else 0
        return k / 24, r[k] if k else 0
    sz = np.array(sizes)
    print(f"lantern from ({x},{y})@{f0}: {len(tr)} frames  |d|={abs(d):.2f} side={'right' if d>0 else 'left'}  h={h:.2f}  "
          f"size {np.median(sz[:,0]*scale):.2f}x{np.median(sz[:,1]*scale):.2f} H")
    print(f"   sway x: rms {sx.std():.3f} H, peak-to-peak {np.ptp(sx):.3f} H, ACF period {per(sx)[0]:.2f}s (r={per(sx)[1]:.2f});"
          f"  sway y: rms {sy.std():.3f} H, period {per(sy)[0]:.2f}s")
    return tr
if __name__ == "__main__":
    a = sys.argv[1:]
    run(int(a[0]), float(a[1]), float(a[2]), int(a[3]) if len(a) > 3 else 96)
