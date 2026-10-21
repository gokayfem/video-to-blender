"""Track the walker per frame: hood top, boot bottom, hood centre/width, boot positions.
Output: reference/scripts/out/walker_track.csv
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames, ROOT

OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
X0, X1, Y0 = 380, 900, 250
rows = []
for i, a in frames():
    c = a[Y0:, X0:X1].astype(np.int16)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    teal = (g - r > 25) & (b - r > 25) & (g < 190) & (b < 200)
    boot = (r > 110) & (r - b > 90) & (g - b > 45) & (r - g > 30) & (r - g < 90)
    ty, tx = np.nonzero(teal)
    by, bx = np.nonzero(boot)
    # keep the big connected-ish blob: restrict to rows with many teal pixels
    cnt = teal.sum(1)
    hood_rows = np.nonzero(cnt > 12)[0]
    top = hood_rows.min() + Y0 if len(hood_rows) else -1
    # hood width at 30% down the hood
    cols = teal.sum(0)
    hood_x = (tx.mean() + X0) if len(tx) else -1
    # flap span: widest teal row
    ext = np.zeros(len(cnt))
    for yy in range(teal.shape[0]):
        xs = np.nonzero(teal[yy])[0]
        if len(xs) > 12:
            ext[yy] = np.percentile(xs, 99) - np.percentile(xs, 1)
    span = ext.max()
    span_row = ext.argmax() + Y0
    bcnt = boot.sum(1)
    brows = np.nonzero(bcnt > 3)[0]
    brows = brows[brows + Y0 > 560]
    bot = brows.max() + Y0 if len(brows) else -1
    # left/right boot bottoms (split at hood centre)
    lb = rb = -1
    if len(by):
        cx = hood_x - X0
        L = by[bx < cx]; R = by[bx >= cx]
        lb = L.max() + Y0 if len(L) > 20 else -1
        rb = R.max() + Y0 if len(R) > 20 else -1
    rows.append((i, top, bot, lb, rb, hood_x, span, span_row, len(tx), len(bx)))
np.savetxt(os.path.join(OUT, "walker_track.csv"), np.array(rows), delimiter=",", fmt="%.2f",
           header="frame,hood_top,boot_bottom,left_boot_bottom,right_boot_bottom,teal_cx,teal_max_row_width,teal_widest_row,teal_px,boot_px")
A = np.array(rows, float)
print("hood top mean/min/max", A[:,1].mean(), A[:,1].min(), A[:,1].max())
print("boot bottom mean/min/max", A[:,2].mean(), A[:,2].min(), A[:,2].max())
print("height px mean", (A[:,2]-A[:,1]).mean(), "std", (A[:,2]-A[:,1]).std())
print("cx mean/std/min/max", A[:,5].mean(), A[:,5].std(), A[:,5].min(), A[:,5].max())
print("span mean", A[:,6].mean(), A[:,6].min(), A[:,6].max())
