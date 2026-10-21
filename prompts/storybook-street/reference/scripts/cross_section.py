"""Ground cross-section from grass-mask runs along image rows.
Lateral offset of a ground point: d = (x - x_foe) * hc / (y - y_h)  [H], f-independent.
Prints, per row, the median (over frames) column ranges of green runs, converted to H.
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
YH, XF, HC = 355.0, 620.0, 0.895
ROWS = [560, 600, 640, 680]
runs = {r: [] for r in ROWS}
curb = {r: np.zeros(1280) for r in ROWS}
nf = 0
for i, a in frames():
    if i % 4: continue
    nf += 1
    for r in ROWS:
        band = a[r - 3:r + 4].astype(np.int16).mean(0)
        R, G, B = band[:, 0], band[:, 1], band[:, 2]
        green = (G - R >= -6) & (G - B >= 18)
        # smooth: majority over 9 px
        cb = (np.abs(R - G) < 14) & (B > G - 10) & (B > 85)
        curb[r] += np.convolve(cb.astype(float), np.ones(5) / 5, 'same') > 0.6
        k = np.convolve(green.astype(float), np.ones(9) / 9, "same") > 0.5
        edges = np.flatnonzero(np.diff(k.astype(int)))
        segs = []
        st = 0 if k[0] else None
        for e in edges:
            if k[e + 1]: st = e + 1
            elif st is not None: segs.append((st, e)); st = None
        if st is not None: segs.append((st, len(k) - 1))
        segs = [s for s in segs if s[1] - s[0] >= 8]
        runs[r].append((i, segs))
for r in ROWS:
    v = r - YH
    print(f"row {r} (v={v:.0f}):")
    allsegs = [s for _, ss in runs[r] for s in ss]
    # histogram of grass coverage per column
    cov = np.zeros(1280)
    for _, ss in runs[r]:
        for s in ss: cov[s[0]:s[1] + 1] += 1
    cov /= len(runs[r])
    # report columns where coverage crosses 0.5
    m = cov > 0.4
    ed = np.flatnonzero(np.diff(m.astype(int)))
    print("  grass>40% boundaries x:", ed.tolist(), " d[H]:", [round((e - XF) * HC / v, 2) for e in ed])
    c = curb[r] / nf
    mc = c > 0.4
    ed = np.flatnonzero(np.diff(mc.astype(int)))
    print("  curb-grey>40% boundaries x:", ed.tolist(), " d[H]:", [round((e - XF) * HC / v, 2) for e in ed])
