"""Fit the ground-flow model dy = k*(y - y_h)^2 + c to out/ground_flow.csv (STEP=2 frames)."""
import os, numpy as np
R = np.loadtxt(os.path.join(os.path.dirname(__file__), "out", "ground_flow.csv"), delimiter=",")
f, x, y, dx, dy, sc = R.T
ok = (sc < 0.35) & (dy > -2)
print("kept", ok.mean())
FIXC = True
def fit(mask):
    best = None
    for yh in np.arange(330, 400, 0.5):
        A = np.c_[(y[mask] - yh) ** 2, np.zeros(mask.sum())] if FIXC else np.c_[(y[mask] - yh) ** 2, np.ones(mask.sum())]
        sol, res, *_ = np.linalg.lstsq(A, dy[mask], rcond=None) if not FIXC else (np.array([np.median(dy[mask] / A[:, 0]), 0.0]), None)
        r = dy[mask] - A @ sol
        e = np.median(np.abs(r))
        if best is None or e < best[0]:
            best = (e, yh, sol)
    return best
for name, m in [("all", ok), ("left", ok & (x < 640)), ("right", ok & (x > 640)), ("t<10", ok & (f < 240)), ("t>=10", ok & (f >= 240))]:
    e, yh, (k, c) = fit(m)
    print(f"{name:6s} y_h={yh:.1f} k={k:.3e}/2fr c={c:.2f} medres={e:.2f}")
# row medians
for yy in np.unique(y):
    m = ok & (y == yy)
    print(int(yy), "dy med %.2f  n=%d   dx left %.2f right %.2f" % (np.mean(dy[m]), m.sum(), np.median(dx[m & (x < 640)]), np.median(dx[m & (x > 640)])))

# Ground-only fit: rows >= 540, columns that are road/curb/sidewalk in every frame.
print("--- ground-only (rows>=540, x in [100,470] U [860,1060]) sqrt-linear fit on row means")
g = ok & (y >= 540) & (((x >= 100) & (x <= 470)) | ((x >= 860) & (x <= 1060)))
for label, sel in [("all", g), ("left", g & (x < 640)), ("right", g & (x > 640))] + [(f"{a}-{a+5}s", g & (f >= a*24) & (f < (a+5)*24)) for a in (0,5,10,15)]:
    ys = np.unique(y[sel]); mv = np.array([dy[sel & (y == v)].mean() for v in ys])
    A = np.c_[ys, np.ones_like(ys)]
    (sl, ic), *_ = np.linalg.lstsq(A, np.sqrt(mv), rcond=None)
    print(f"{label:8s} y_h={-ic/sl:.1f}  k={sl**2:.3e} px^-1 per 2 frames  ->  V/(f*hc) = {sl**2*12:.3e} /s")
