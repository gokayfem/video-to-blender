"""Median sRGB of hand-placed sample boxes (frame, x0, y0, x1, y1). Boxes were placed by looking at
gridded frames; draw_boxes() writes reference/sheets/palette_boxes_tNN.jpg so they can be checked.
Output: out/palette.json and reference/sheets/palette_swatches.jpg.
"""
import os, sys, json, subprocess, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from vio import frames, ROOT, srgb_hex
S = [  # name, frame, x0, y0, x1, y1
 ("sky_top", 240, 560, 20, 700, 60), ("sky_mid", 240, 600, 200, 640, 230), ("far_street_glow", 168, 738, 335, 760, 352),
 ("plaster_cream_sunlit", 0, 20, 120, 90, 200), ("plaster_peach_left_mid", 72, 230, 60, 280, 110),
 ("plaster_ochre_shade_right", 0, 1150, 40, 1250, 110), ("plaster_yellow_right", 240, 1020, 110, 1080, 220),
 ("plaster_sage_right", 240, 950, 280, 980, 330), ("plaster_orange_right", 168, 1180, 100, 1240, 170),
 ("timber_post_left", 168, 60, 250, 72, 460), ("timber_beam_right", 168, 880, 210, 1000, 225),
 ("shutter_green", 168, 105, 260, 140, 390), ("door_teal", 72, 298, 300, 325, 420), ("door_green", 168, 1170, 230, 1230, 400),
 ("roof_slate_blue", 168, 530, 80, 580, 150), ("cobbles_near", 168, 300, 640, 560, 700), ("curb_top", 168, 1050, 612, 1075, 622),
 ("grass_strip", 168, 880, 565, 915, 595), ("flower_red", 168, 1060, 432, 1095, 448), ("flowerbox_terracotta", 168, 960, 470, 1090, 500),
 ("pot_terracotta", 168, 1150, 525, 1240, 585), ("barrel_wood", 0, 1110, 480, 1230, 560), ("lantern_glow", 0, 760, 140, 778, 166),
 ("hood_teal_lit", 0, 640, 335, 665, 350), ("hood_teal_shade", 0, 600, 420, 630, 445), ("scarf_red", 0, 630, 515, 670, 560),
 ("boot_yellow", 0, 670, 620, 690, 650), ("tunic_cream", 0, 600, 515, 612, 540),
]
out = {}
fr = {s[1] for s in S}
for i, a in frames(0, max(fr) + 1):
    for name, f, x0, y0, x1, y1 in S:
        if f == i:
            px = a[y0:y1, x0:x1].reshape(-1, 3)
            med = np.median(px, 0); p10 = np.percentile(px, 10, 0); p90 = np.percentile(px, 90, 0)
            out[name] = {"frame": f, "box": [x0, y0, x1, y1], "median": srgb_hex(med), "p10": srgb_hex(p10), "p90": srgb_hex(p90)}
json.dump(out, open(os.path.join(os.path.dirname(__file__), "out", "palette.json"), "w"), indent=1)
for k, v in out.items(): print(f"{k:28s} {v['median']}  (p10 {v['p10']}, p90 {v['p90']})  t={v['frame']/24:.1f}s")
