"""Ground-plane optical flow by block matching (frame i -> i+STEP).
For a level camera at height hc moving forward at V along its axis, a ground point at row offset
v = y - y_h (below the horizon) moves down by dv/dt = V/(f*hc) * v^2. Fitting dy = k*(y - y_h)^2 over
many ground patches gives the horizon row y_h and k = V/(f*hc) (per frame step).
Output: out/ground_flow.csv (frame, x, y, dx, dy, score), prints the fit.
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames, N

STEP = 2
PW, PH = 40, 20
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
prev = {}
recs = []
buf = []
for i, g in frames(gray=True):
    buf.append(g)
    if len(buf) > STEP + 1:
        buf.pop(0)
    if len(buf) < STEP + 1 or i % 2:
        continue
    a, b = buf[0], buf[-1]
    f0 = i - STEP
    for y in range(470, 680 - PH, 16):
        for x in list(range(60, 470, 40)) + list(range(860, 1220, 40)):
            p = a[y:y + PH, x:x + PW]
            if p.std() < 6:
                continue
            best = None
            for dy in range(-3, 32):
                yy = y + dy
                if yy + PH > 704: break
                for dx in range(-24, 25, 2):
                    xx = x + dx
                    if xx < 0 or xx + PW > 1280: continue
                    q = b[yy:yy + PH, xx:xx + PW]
                    s = np.mean((q - p) ** 2)
                    if best is None or s < best[0]:
                        best = (s, dx, dy)
            # refine dx at 1px
            s0, dx0, dy0 = best
            for dx in (dx0 - 1, dx0 + 1):
                xx = x + dx
                if 0 <= xx and xx + PW <= 1280:
                    q = b[y + dy0:y + dy0 + PH, xx:xx + PW]
                    s = np.mean((q - p) ** 2)
                    if s < best[0]: best = (s, dx, dy0)
            recs.append((f0, x + PW / 2, y + PH / 2, best[1], best[2], best[0] / (p.var() + 1)))
R = np.array(recs)
np.savetxt(os.path.join(OUT, "ground_flow.csv"), R, delimiter=",", fmt="%.3f", header="frame,x,y,dx,dy,score")
print(len(R))
