"""Ear-flap tips: leftmost/rightmost teal pixel per frame (x, y) relative to the hood top centre, in H
(344 px = 1 H). Reports amplitude, dominant period and phase lag vs the body bob (hood top y)."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
PX = 344.4
X0, X1, Y0 = 380, 900, 250
rows = []
for i, a in frames():
    c = a[Y0:, X0:X1].astype(np.int16); r, g, b = c[..., 0], c[..., 1], c[..., 2]
    teal = (g - r > 25) & (b - r > 25) & (g < 190) & (b < 200)
    ys, xs = np.nonzero(teal)
    if len(xs) < 500: rows.append((i,) + (np.nan,) * 7); continue
    top = ys.min(); cx = xs[ys < top + 30].mean()
    lo = np.percentile(xs, 0.3); hi = np.percentile(xs, 99.7)
    ly = ys[xs <= lo + 3].mean(); ry = ys[xs >= hi - 3].mean()
    rows.append((i, top + Y0, cx + X0, lo + X0, ly + Y0, hi + X0, ry + Y0, ys.max() + Y0))
A = np.array(rows, float)
np.savetxt(os.path.join(os.path.dirname(__file__), "out", "flap_track.csv"), A, delimiter=",", fmt="%.2f",
           header="frame,hood_top_y,hood_top_cx,left_tip_x,left_tip_y,right_tip_x,right_tip_y,lowest_teal_y")
f, top, cx, lx, ly, rx, ry, low = A.T
def hp(s): return (s - np.convolve(s, np.ones(25) / 25, "same"))[20:-20]
def per(s, lo=5, hi=40):
    s = s - s.mean(); r = np.correlate(s, s, "full")[len(s) - 1:]; r /= r[0]; k = lo + np.argmax(r[lo:hi]); return k, r[k]
for name, s in [("hood top y", top), ("left tip y (rel hood top)", ly - top), ("right tip y (rel hood top)", ry - top),
                ("left tip x (rel hood cx)", lx - cx), ("right tip x (rel hood cx)", rx - cx), ("hood cx", cx)]:
    h = hp(s); k, r = per(h)
    print(f"{name:28s} mean {np.nanmean(s)/PX:+.3f} H  amp(p5-p95)/2 {0.5*(np.percentile(h,95)-np.percentile(h,5))/PX:.3f} H  period {k/24:.3f}s (r={r:.2f})")
# lag of tip y vs hood top y (step frequency)
b = hp(top); t = hp(ly - top)
cc = [np.corrcoef(b[:len(b) - L], t[L:])[0, 1] for L in range(0, 9)]
print("corr(hood bob, left-tip y lagged by L frames) L=0..8:", np.round(cc, 2).tolist())
