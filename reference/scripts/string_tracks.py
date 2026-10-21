"""Bunting string heights over the street centre. At image column XC, find the string (thin dark line on
light sky) in rows 0..YMAX per frame, link detections into tracks rising out of the top, and fit
1/(YH - y) linear in time: slope = -K/(h - hc)  ->  string height h at the centre column (f-independent;
the column is near the travel direction so this is the string at d ~ 0, i.e. near its lowest point).
"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames
YH, HC, K = 355.0, 0.895, 1.29e-3
XC = int(sys.argv[1]) if len(sys.argv) > 1 else 640
YMAX = 140
det = []
for i, a in frames():
    c = a[:YMAX, XC - 1:XC + 2].astype(float).mean(1)
    lum = c.mean(1)
    bg = np.convolve(lum, np.ones(15) / 15, "same")
    dark = (bg - lum > 18) & (c[:, 2] < 150)
    ys = np.flatnonzero(dark)
    # group adjacent rows
    groups = np.split(ys, np.flatnonzero(np.diff(ys) > 2) + 1) if len(ys) else []
    for g in groups:
        if 1 <= len(g) <= 6 and g.mean() > 3: det.append((i, g.mean()))
det = np.array(det)
# link: a string moves up (y decreases) by 0..6 px per frame
tracks = []
for i, y in det:
    for tr in tracks:
        li, ly = tr[-1]
        if 0 < i - li <= 3 and -1 <= ly - y <= 6 * (i - li) + 1:
            tr.append((i, y)); break
    else:
        tracks.append([(i, y)])
for tr in tracks:
    tr = np.array(tr)
    if len(tr) < 20 or tr[0, 1] - tr[-1, 1] < 40: continue
    t = tr[:, 0] / 24; w = YH - tr[:, 1]
    sl = np.polyfit(t, 1 / w, 1)[0]
    h = HC - K / sl
    # time when it leaves the top (y=0): extrapolate
    tt = np.polyfit(1 / w, t, 1); t_top = np.polyval(tt, 1 / YH)
    print(f"track frames {int(tr[0,0])}-{int(tr[-1,0])}  y {tr[0,1]:.0f}->{tr[-1,1]:.0f}   h = {h:.2f} H   leaves top at t = {t_top:.2f} s")
