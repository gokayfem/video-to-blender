"""Global grade statistics over frames sampled every second: luminance percentiles, black/white points per
channel, mean HSV saturation, mean R-B warmth."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames, srgb_hex
P = []; S = []; W = []
for i, a in frames():
    if i % 24: continue
    x = a.reshape(-1, 3).astype(float)
    mx, mn = x.max(1), x.min(1); S.append(np.mean((mx - mn) / np.maximum(mx, 1)))
    W.append(np.mean(x[:, 0] - x[:, 2])); P.append(x)
X = np.concatenate(P)
L = X @ [0.2126, 0.7152, 0.0722]
print("luma p1 %.0f p5 %.0f p50 %.0f p95 %.0f p99 %.0f" % tuple(np.percentile(L, [1, 5, 50, 95, 99])))
print("channel p0.5:", srgb_hex(np.percentile(X, 0.5, 0)), " p99.5:", srgb_hex(np.percentile(X, 99.5, 0)), " mean:", srgb_hex(X.mean(0)))
print("mean HSV saturation %.2f, mean R-B %.1f" % (np.mean(S), np.mean(W)))
