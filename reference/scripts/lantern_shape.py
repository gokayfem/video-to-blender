"""Track single paper lanterns from near the vanishing point to the frame edge and record blob shape
(second moments). Perspective stretches an object at off-axis angle theta by 1/cos(theta) along the radial
direction (tan(theta) = r/f), so the aspect change from centre to edge constrains the focal length f.
Also records lantern size (px) and position for the bunting/lantern section.
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
CX, CY = 640.0, 352.0
starts = [tuple(map(int, s.split(","))) for s in (sys.argv[1:] or ["0,440,105", "0,768,150"])]
for (f0, x, y) in starts:
    pos = np.array([x, y], float); out = []
    for i, a in frames(f0, 120):
        R = 70
        x0, y0 = int(max(pos[0] - R, 0)), int(max(pos[1] - R, 0))
        c = a[y0:int(pos[1] + R), x0:int(pos[0] + R)].astype(np.int16)
        m = (c[..., 0] > 190) & (c[..., 1] > 140) & (c[..., 2] < 175) & (c[..., 0] - c[..., 2] > 55)
        # keep the component nearest the previous position (crude: within growing radius)
        ys, xs = np.nonzero(m)
        if len(xs) < 30: break
        d = np.hypot(xs + x0 - pos[0], ys + y0 - pos[1])
        k = d < np.percentile(d, 60) * 1.8
        xs, ys = xs[k] + x0, ys[k] + y0
        mx, my = xs.mean(), ys.mean()
        C = np.cov(np.vstack([xs, ys]))
        w, v = np.linalg.eigh(C)
        out.append((i, mx, my, 4 * np.sqrt(w[1]), 4 * np.sqrt(w[0]), np.degrees(np.arctan2(v[1, 1], v[0, 1])),
                    xs.max() - xs.min() + 1, ys.max() - ys.min() + 1, len(xs)))
        pos = np.array([mx, my])
        if mx < 25 or my < 25 or mx > 1255: break
    print(f"lantern from frame {f0} at ({x},{y}):")
    for r in out[::4]:
        print("  fr %3d  c=(%.0f,%.0f)  r=%.0f  major %.1f minor %.1f ang %.0f  bbox %dx%d  n=%d" % (r[0], r[1], r[2], np.hypot(r[1]-CX, r[2]-CY), *r[3:]))
