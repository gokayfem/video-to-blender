"""Walker colours: class masks inside the walker box, medians and p20/p80 over 20 frames (every second)."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames, srgb_hex
acc = {k: [] for k in ("hood_flaps_teal", "scarf_red", "boots_yellow", "tunic_cream", "brown_mitts_satchel", "legs_teal_dark")}
for i, a in frames():
    if i % 24: continue
    c = a[300:690, 470:860].reshape(-1, 3).astype(int); r, g, b = c.T
    yy = np.repeat(np.arange(300, 690), 390)
    m = {"hood_flaps_teal": (g - r > 25) & (b - r > 25) & (yy < 560),
         "scarf_red": (r - g > 60) & (r > 120) & (g < 90) & (yy > 470),
         "boots_yellow": (r - b > 90) & (g - b > 45) & (r - g > 30) & (r - g < 90) & (yy > 590),
         "tunic_cream": (r > 150) & (g > 120) & (b > 90) & (r - b < 80) & (yy > 480) & (yy < 600),
         "brown_mitts_satchel": (r > 70) & (r < 130) & (r - b > 40) & (g < 80) & (yy > 500) & (yy < 620),
         "legs_teal_dark": (g - r > 10) & (b - r > 10) & (yy > 590)}
    for k, v in m.items(): acc[k].append(c[v])
for k, v in acc.items():
    v = np.concatenate(v)
    print(f"{k:22s} median {srgb_hex(np.median(v,0))}  p20 {srgb_hex(np.percentile(v,20,0))}  p80 {srgb_hex(np.percentile(v,80,0))}  n={len(v)}")
