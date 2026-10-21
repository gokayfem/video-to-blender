"""Periodicity of walker signals from out/walker_track.csv (24 fps)."""
import os, numpy as np
A = np.loadtxt(os.path.join(os.path.dirname(__file__), "out", "walker_track.csv"), delimiter=",")
fr, top, bot, lb, rb, cx, span, srow = A[:, :8].T
def spec(sig, name, fmin=0.3, fmax=6):
    s = sig - np.convolve(sig, np.ones(49) / 49, "same")  # remove slow drift (>2 s)
    s = s[30:-30]
    n = 4096
    F = np.abs(np.fft.rfft(s * np.hanning(len(s)), n)); fq = np.fft.rfftfreq(n, 1 / 24)
    m = (fq > fmin) & (fq < fmax)
    i = np.argmax(F * m)
    amp = 0.5 * (np.percentile(s, 95) - np.percentile(s, 5))
    print(f"{name:22s} peak {fq[i]:.3f} Hz (period {1/fq[i]:.3f} s = {24/fq[i]:.1f} fr)   amp(p5-p95)/2 = {amp:.2f} px")
    return fq[i]
spec(top, "hood top y")
spec(bot, "planted boot bottom y")
spec(lb - rb, "left-right boot diff")
spec(lb, "left boot bottom")
spec(cx, "hood centre x")
spec(span, "flap span")
spec(srow, "widest teal row")
print("hood top mean %.1f  boot bottom mean %.1f  height px %.1f" % (top.mean(), bot.mean(), (bot - top).mean()))
print("hood cx mean %.1f, slow drift range %.1f..%.1f" % (cx.mean(), np.convolve(cx, np.ones(49)/49, 'valid').min(), np.convolve(cx, np.ones(49)/49, 'valid').max()))
print("span mean %.1f px = %.3f H" % (span.mean(), span.mean() / (bot - top).mean()))
