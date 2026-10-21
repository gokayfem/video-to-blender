"""Crop sheets per object class from the 1 s frames (reference/frames/tNN.png).
Each tile is a crop scaled to a common height and padded; tiles run left to right, top to bottom in the order
listed here (the legend is repeated in docs/REFERENCE.md section 8)."""
import os, subprocess
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FR = os.path.join(ROOT, "reference", "frames"); OUT = os.path.join(ROOT, "reference", "sheets")
SHEETS = {
 "crops_props.jpg": (220, 5, [
   ("window box, geraniums", 0, 1075, 300, 205, 140), ("pots on verge", 7, 1060, 410, 215, 195),
   ("barrel pair", 0, 1010, 415, 255, 200), ("blue-white awning", 7, 355, 235, 170, 120),
   ("pink-white awning", 7, 870, 170, 230, 230), ("bread sign", 3, 835, 205, 160, 110),
   ("round sign + lantern", 10, 735, 150, 140, 175), ("wall lantern + ivy door", 3, 0, 120, 260, 340),
   ("ladder", 0, 900, 355, 85, 120), ("ivy, lantern, arched door", 0, 250, 150, 140, 300)]),
 "crops_houses.jpg": (300, 3, [
   ("left near: jetty corbels, cream plaster, deep window", 0, 0, 0, 420, 500),
   ("left: timber frame, shutters, awning", 7, 0, 0, 540, 470), ("right: orange house, arched door, awning", 7, 860, 0, 420, 480),
   ("right: bread-sign house", 3, 820, 0, 460, 480), ("right: sage house, round sign", 10, 730, 0, 550, 520),
   ("far street, slate roofs, spire", 7, 430, 60, 440, 320)]),
 "crops_bunting.jpg": (280, 3, [("t0", 0, 380, 0, 480, 280), ("t7", 7, 430, 0, 480, 280), ("t10", 10, 380, 60, 480, 280),
   ("t13", 13, 380, 0, 480, 280), ("t16", 16, 380, 0, 480, 280), ("t19", 19, 380, 0, 480, 280)]),
 "crops_walker.jpg": (360, 4, [(f"t{t}", t, 440, 290, 400, 414) for t in (0, 5, 7, 10, 13, 15, 17, 19)]),
 "crops_road.jpg": (260, 2, [("left t7", 7, 0, 420, 640, 284), ("right t7", 7, 640, 420, 640, 284),
   ("left t10", 10, 0, 420, 640, 284), ("right t10", 10, 640, 420, 640, 284)]),
}
for name, (h, cols, tiles) in SHEETS.items():
    args = []; fc = []
    for k, (_, t, x, y, w, hh) in enumerate(tiles):
        args += ["-i", os.path.join(FR, f"t{t:02d}.png")]
        fc.append(f"[{k}:v]crop={w}:{hh}:{x}:{y},scale=-2:{h},pad=iw+8:ih+8:4:4:white[c{k}]")
    n = len(tiles); rows = (n + cols - 1) // cols
    # pad each row to the widest by xstack with a fill
    layout = []
    for k in range(n):
        r, c = divmod(k, cols)
        xs = "+".join(f"w{r*cols+j}" for j in range(c)) or "0"
        ys = "+".join(f"h{j*cols}" for j in range(r)) or "0"
        layout.append(f"{xs}_{ys}")
    fc.append("".join(f"[c{k}]" for k in range(n)) + f"xstack=inputs={n}:layout={'|'.join(layout)}:fill=white[o]")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args, "-filter_complex", ";".join(fc), "-map", "[o]", "-q:v", "4",
                    os.path.join(OUT, name)], check=True)
    print(name, [t[0] for t in tiles])
