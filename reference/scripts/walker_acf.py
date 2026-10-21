"""Autocorrelation periods of walker signals (more robust than one FFT peak)."""
import os, numpy as np
A = np.loadtxt(os.path.join(os.path.dirname(__file__), "out", "walker_track.csv"), delimiter=",")
fr, top, bot, lb, rb, cx, span, srow = A[:, :8].T
def acf(sig, name, lo, hi):
    s = sig - np.convolve(sig, np.ones(49) / 49, "same"); s = s[30:-30]; s = s - s.mean()
    r = np.correlate(s, s, "full")[len(s) - 1:]; r /= r[0]
    L = np.arange(lo, hi); k = L[np.argmax(r[lo:hi])]
    # parabolic refine
    y0, y1, y2 = r[k - 1], r[k], r[k + 1]; d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
    print(f"{name:20s} ACF peak lag {k + d:.2f} fr = {(k + d) / 24:.3f} s  (r={y1:.2f}); 2nd-multiple check r(2k)={r[2*k]:.2f}")
    # Windowed estimates
    out = []
    for a in range(30, len(sig) - 30 - 96, 48):
        w = sig[a:a + 96] - np.convolve(sig, np.ones(49) / 49, "same")[a:a + 96]; w = w - w.mean()
        rr = np.correlate(w, w, "full")[95:]; rr /= rr[0]
        out.append(L[np.argmax(rr[lo:hi])])
    print("   per-4s windows lag(fr):", out)
acf(lb - rb, "L-R boot diff (cycle)", 12, 26)
acf(lb, "left boot bottom", 5, 26)
acf(top, "hood top (step)", 5, 14)
acf(cx, "hood centre x", 10, 26)
acf(span, "flap span", 5, 40)
