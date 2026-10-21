"""Track static scene points and recover their street-space position, f-independently.

For a static point and a camera moving straight ahead at V with focus of expansion (XF, YH):
  u = x - XF = f*d/Z,  w = YH - y = f*(h - hc)/Z,  Z = Z0 - V*t
so 1/u and 1/w are linear in t, with slopes -V/(f*d) and -V/(f*(h-hc)).
V/f = K = 1.29e-3 /s was measured from ground flow (V/(f*hc) = 1.44e-3 /s, hc = 0.895 H),
hence d = -K/slope_u, h = hc - K/slope_w ... (sign handled below), and size_H = size_px * d / u.
Depth Z in H needs f (Z = f*d/u); reported with f = 700 px (vertical FOV 53 deg, low confidence).

usage: track_point.py FRAME X Y [N_FRAMES] [HALF]   (template half-size, default 10)
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
XF, YH, HC, K, F = 620.0, 355.0, 0.895, 1.29e-3, 700.0

def track(f0, x, y, n=60, half=10, search=8):
    pos = np.array([x, y], float); tmpl = None; out = []
    for i, g in frames(f0, n, gray=True):
        xi, yi = int(round(pos[0])), int(round(pos[1]))
        if tmpl is None:
            tmpl = g[yi - half:yi + half + 1, xi - half:xi + half + 1].copy(); out.append((i, pos[0], pos[1])); continue
        best = None
        for dy in range(-search, search + 1):
            for dx in range(-search, search + 1):
                yy, xx = yi + dy, xi + dx
                if yy - half < 0 or xx - half < 0 or yy + half + 1 > g.shape[0] or xx + half + 1 > g.shape[1]: continue
                s = np.mean((g[yy - half:yy + half + 1, xx - half:xx + half + 1] - tmpl) ** 2)
                if best is None or s < best[0]: best = (s, xx, yy)
        if best is None: break
        pos = np.array([best[1], best[2]], float)
        tmpl = 0.7 * tmpl + 0.3 * g[best[2] - half:best[2] + half + 1, best[1] - half:best[1] + half + 1]
        out.append((i, pos[0], pos[1]))
        if pos[0] < half + 9 or pos[1] < half + 9 or pos[0] > 1270 - half or pos[1] > 694 - half: break
    return np.array(out)

def solve(tr):
    t = tr[:, 0] / 24.0; u = tr[:, 1] - XF; w = YH - tr[:, 2]
    res = {}
    su = np.polyfit(t, 1 / u, 1)[0]; sw = np.polyfit(t, 1 / w, 1)[0]
    d = -K / su; hmh = -K / sw
    res["d"] = d; res["h"] = HC + hmh
    res["Z_first"] = F * d / u[0]
    return res

if __name__ == "__main__":
    f0, x, y = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 60
    half = int(sys.argv[5]) if len(sys.argv) > 5 else 10
    tr = track(f0, x, y, n, half)
    r = solve(tr)
    print(f"[ground-plane d at first frame would be {(tr[0,1]-XF)*HC/(tr[0,2]-YH):+.2f}] ", end="")
    print(f"tracked {len(tr)} frames: ({tr[0,1]:.0f},{tr[0,2]:.0f}) -> ({tr[-1,1]:.0f},{tr[-1,2]:.0f});  d = {r['d']:+.2f} H, h = {r['h']:.2f} H, Z(first) = {r['Z_first']:.1f} H @f=700")
