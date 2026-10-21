#!/usr/bin/env python3
"""Compare a render with the reference ACROSS TIME, per screen region (see docs/COMPARE.md).

    python3 tools/compare.py --ref reference/source/village_source.mp4 --render out/lead/seq \
        --times 0:20:0.5 --out out/compare/run1 [--regions my_regions.json] [--render-offset 0] [--width 640]
    python3 tools/compare.py --dump-regions out/compare/regions.json     # write the default regions to edit

--render is a directory of f_####.png (frame N = time (N-1)/24 s; sparse is fine: missing times become gaps) or a
video. For every sampled time t, frame i = round(t*fps) and its successor i+1 are read from both sources (scaled to
the reference's analysis size), and colour, structure and motion metrics are computed per region.

Outputs in --out: metrics.csv (long: time,region,metric,ref,render), metrics.json, summary.md, and plots
colour.png, structure.png, motion.png, grid_<metric>.png (3x3 screen grid laid out spatially).

Dependencies: ffmpeg and numpy (re-executes under Blender's bundled python if the system python has no numpy).
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video  # noqa: E402  (also guarantees numpy)
from video import Source, draw_text, fill_rect, parse_times, text_size, write_png  # noqa: E402
import numpy as np  # noqa: E402

# Fractional rects [x0, y0, x1, y1] in the 1280x704 reference frame (y down). "exclude" rects are cut out.
# Tuned on reference/frames/t05.png: facades flank a narrow sky strip with bunting; walker centred at the bottom.
DEFAULT_REGIONS = {
    "full": {"rect": [0.0, 0.0, 1.0, 1.0]},
    "sky_strip": {"rect": [0.36, 0.0, 0.64, 0.30], "note": "narrow sky between the roofs (contains bunting)"},
    "bunting": {"rect": [0.33, 0.0, 0.70, 0.24], "note": "flag strings across the street; flutter lives here"},
    "left_facade": {"rect": [0.0, 0.05, 0.30, 0.62], "note": "near left wall, streams out to the left"},
    "right_facade": {"rect": [0.70, 0.05, 1.0, 0.62], "note": "near right wall, streams out to the right"},
    "road": {"rect": [0.0, 0.70, 1.0, 1.0], "exclude": [[0.37, 0.44, 0.63, 0.95]],
             "note": "cobbles, curbs and verges below the horizon, walker cut out"},
    "walker": {"rect": [0.37, 0.44, 0.63, 0.95], "note": "hooded walker box"},
}
GRID = ["g%d%d" % (r, c) for r in range(3) for c in range(3)]  # g<row><col>, row 0 = top

COLOUR = ["srgb_r", "srgb_g", "srgb_b", "ok_L", "ok_a", "ok_b", "chroma", "luma_p10", "luma_p50", "luma_p90"]
STRUCT = ["edge", "edge_frac", "ssim"]
MOTION = ["mad", "flow_x", "flow_y", "flow_conf", "flutter"]
METRICS = COLOUR + STRUCT + MOTION
PAIR_ONLY = {"ssim"}  # one value per time (ref vs render), stored in the "render" column, ref column = 1

UNITS = {"srgb_r": "0-1", "srgb_g": "0-1", "srgb_b": "0-1", "ok_L": "0-1", "ok_a": "", "ok_b": "",
         "chroma": "", "luma_p10": "0-1", "luma_p50": "0-1", "luma_p90": "0-1", "edge": "grad", "edge_frac": "frac",
         "ssim": "", "mad": "luma/frame", "flow_x": "px/frame@1280", "flow_y": "px/frame@1280",
         "flow_conf": "peak", "flutter": "luma/frame"}


# ---------------------------------------------------------------------------------------------------------------
# image maths

def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def oklab(rgb):
    lin = srgb_to_linear(rgb)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    lms = np.cbrt(lin @ m1.T)
    return lms @ m2.T


def luma(rgb):
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def sobel_mag(y):
    p = np.pad(y, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:] - p[:-2, :-2] - 2 * p[1:-1, :-2] - p[2:, :-2]) / 4
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:] - p[:-2, :-2] - 2 * p[:-2, 1:-1] - p[:-2, 2:]) / 4
    return np.hypot(gx, gy)


def down(img, f):
    h, w = img.shape[0] // f * f, img.shape[1] // f * f
    img = img[:h, :w]
    return img.reshape(h // f, f, w // f, f, *img.shape[2:]).mean(axis=(1, 3))


def box(x, r):
    """Mean filter of size (2r+1)^2 with edge padding, via cumulative sums."""
    p = np.pad(x, r + 1, mode="edge")
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s[:x.shape[0], :x.shape[1]] / (k * k)


def ssim_map(a, b, r=3):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ma, mb = box(a, r), box(b, r)
    va = box(a * a, r) - ma * ma
    vb = box(b * b, r) - mb * mb
    cov = box(a * b, r) - ma * mb
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))


def phase_corr(a, b, weight):
    """Shift d (dx, dy) such that b(x) ~ a(x - d), with parabolic sub-pixel refinement, plus peak height."""
    a = (a - (a * weight).sum() / max(weight.sum(), 1e-9)) * weight
    b = (b - (b * weight).sum() / max(weight.sum(), 1e-9)) * weight
    A, B = np.fft.fft2(a), np.fft.fft2(b)
    R = B * np.conj(A)
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    py, px = np.unravel_index(np.argmax(r), r.shape)
    h, w = r.shape

    def sub(m, z, p):
        if abs(m - 2 * z + p) < 1e-12:
            return 0.0
        return float(np.clip(0.5 * (m - p) / (m - 2 * z + p), -0.5, 0.5))
    dx = px + sub(r[py, (px - 1) % w], r[py, px], r[py, (px + 1) % w])
    dy = py + sub(r[(py - 1) % h, px], r[py, px], r[(py + 1) % h, px])
    if dx > w / 2:
        dx -= w
    if dy > h / 2:
        dy -= h
    return dx, dy, float(r[py, px])


def fourier_shift(img, dx, dy):
    """img sampled at x + d (moves content by -d), circular."""
    h, w = img.shape
    ky = np.fft.fftfreq(h)[:, None]
    kx = np.fft.fftfreq(w)[None, :]
    return np.fft.ifft2(np.fft.fft2(img) * np.exp(2j * np.pi * (kx * dx + ky * dy))).real


def region_masks(regions, w, h):
    masks, boxes = {}, {}
    for name, spec in regions.items():
        x0, y0, x1, y1 = spec["rect"]
        bx = (int(round(x0 * w)), int(round(y0 * h)), int(round(x1 * w)), int(round(y1 * h)))
        m = np.zeros((h, w), bool)
        m[bx[1]:bx[3], bx[0]:bx[2]] = True
        for e in spec.get("exclude", []):
            m[int(round(e[1] * h)):int(round(e[3] * h)), int(round(e[0] * w)):int(round(e[2] * w))] = False
        masks[name], boxes[name] = m, bx
    return masks, boxes


# ---------------------------------------------------------------------------------------------------------------
# per-frame metrics

def frame_metrics(fa, fb, masks, boxes, w, fps):
    """Colour/structure from fa; motion from fa -> fb (fb may be None). Returns {region: {metric: value}}."""
    rgb = fa.astype(np.float64) / 255
    lab = oklab(rgb)
    y = luma(rgb)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    grad = sobel_mag(y)
    yb = luma(fb.astype(np.float64) / 255) if fb is not None else None
    # flow at half the analysis resolution
    y2 = down(y, 2)
    yb2 = down(yb, 2) if yb is not None else None
    px_scale = 1280.0 / (w / 2)  # half-res px -> 1280-wide px
    out = {}
    for name, m in masks.items():
        v = {}
        sel = rgb[m]
        v["srgb_r"], v["srgb_g"], v["srgb_b"] = sel.mean(0)
        L = lab[m]
        v["ok_L"], v["ok_a"], v["ok_b"] = L.mean(0)
        v["chroma"] = chroma[m].mean()
        v["luma_p10"], v["luma_p50"], v["luma_p90"] = np.percentile(y[m], [10, 50, 90])
        v["edge"] = grad[m].mean()
        v["edge_frac"] = (grad[m] > 0.08).mean()
        if yb is None:
            for k in MOTION:
                v[k] = np.nan
        else:
            v["mad"] = np.abs(yb - y)[m].mean()
            x0, y0, x1, y1 = (c // 2 for c in boxes[name])
            a, b = y2[y0:y1, x0:x1], yb2[y0:y1, x0:x1]
            m2 = down(m.astype(float), 2)[y0:y1, x0:x1]
            win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])) * m2
            dx, dy, conf = phase_corr(a, b, win)
            v["flow_x"], v["flow_y"], v["flow_conf"] = dx * px_scale, dy * px_scale, conf
            comp = fourier_shift(b, dx, dy)
            mx, my = int(np.ceil(abs(dx))) + 2, int(np.ceil(abs(dy))) + 2
            inner = m2[my:-my or None, mx:-mx or None] > 0.5
            res = np.abs(comp - a)[my:-my or None, mx:-mx or None]
            v["flutter"] = res[inner].mean() if inner.any() else np.nan
        out[name] = v
    return out


def ssim_by_region(fa, fb, masks):
    a = down(luma(fa.astype(np.float64) / 255), 4)
    b = down(luma(fb.astype(np.float64) / 255), 4)
    s = ssim_map(a, b)
    return {n: float(s[down(m.astype(float), 4)[:s.shape[0], :s.shape[1]] > 0.5].mean()) for n, m in masks.items()}


# ---------------------------------------------------------------------------------------------------------------
# plotting (numpy raster + bitmap font; no matplotlib)

REF_C, REN_C, GRID_C, AX_C = (40, 80, 170), (230, 110, 20), (225, 225, 225), (90, 90, 90)


def nice_ticks(lo, hi, n=4):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** np.floor(np.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    t0 = np.ceil(lo / step - 1e-9) * step
    return [t0 + k * step for k in range(int((hi - t0) / step + 1e-9) + 1)]


def fmt(v):
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 100:
        return "%.0f" % v
    if a >= 10:
        return "%.1f" % v
    if a >= 1:
        return "%.2f" % v
    if a >= 0.01:
        return ("%.3f" % v).replace("0.", ".", 1)
    if a >= 0.001:
        return ("%.4f" % v).replace("0.", ".", 1)
    return "%.0e" % v


def draw_line(img, x0, y0, x1, y1, color, th=2):
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    h, w = img.shape[:2]
    for ox in range(th):
        for oy in range(th):
            xi = np.clip(np.round(xs).astype(int) + ox - th // 2, 0, w - 1)
            yi = np.clip(np.round(ys).astype(int) + oy - th // 2, 0, h - 1)
            img[yi, xi] = color


def draw_panel(img, x, y, w, h, title, times, series, ylabel=""):
    """series: list of (values, color, thickness). NaNs break the line."""
    fill_rect(img, x, y, x + w, y + h, (255, 255, 255))
    draw_text(img, x + 4, y + 4, title, (0, 0, 0), 2)
    if ylabel:
        tw, _ = text_size(ylabel, 1)
        draw_text(img, x + w - tw - 6, y + 8, ylabel, (110, 110, 110), 1)
    px0, py0, px1, py1 = x + 64, y + 26, x + w - 10, y + h - 24
    allv = np.concatenate([np.asarray(v, float) for v, _, _ in series]) if series else np.array([np.nan])
    allv = allv[np.isfinite(allv)]
    if allv.size == 0:
        draw_text(img, px0 + 10, (py0 + py1) // 2, "NO DATA", (150, 150, 150), 2)
        return
    lo, hi = float(allv.min()), float(allv.max())
    if hi - lo < 1e-9 * max(1.0, abs(hi)) or hi - lo < 1e-12:
        lo, hi = lo - max(abs(lo) * 0.05, 1e-3), hi + max(abs(hi) * 0.05, 1e-3)
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    t0, t1 = times[0], times[-1] if times[-1] > times[0] else times[0] + 1

    def X(t):
        return px0 + (t - t0) / (t1 - t0) * (px1 - px0)

    def Y(v):
        return py1 - (v - lo) / (hi - lo) * (py1 - py0)
    for tv in nice_ticks(lo, hi, 3):
        yy = int(round(Y(tv)))
        fill_rect(img, px0, yy, px1, yy + 1, GRID_C)
        s = fmt(tv)
        tw, _ = text_size(s, 2)
        draw_text(img, px0 - tw - 4, yy - 7, s, AX_C, 2)
    for tt in nice_ticks(t0, t1, 5):
        xx = int(round(X(tt)))
        fill_rect(img, xx, py0, xx + 1, py1, GRID_C)
        s = "%g" % round(tt, 2)
        tw, _ = text_size(s, 2)
        draw_text(img, xx - tw // 2, py1 + 6, s, AX_C, 2)
    if lo < 0 < hi:
        yy = int(round(Y(0)))
        fill_rect(img, px0, yy, px1, yy + 1, (170, 170, 170))
    fill_rect(img, px0, py0, px0 + 1, py1 + 1, AX_C)
    fill_rect(img, px0, py1, px1, py1 + 1, AX_C)
    for vals, col, th in series:
        prev = None
        for t, v in zip(times, vals):
            if v is None or not np.isfinite(v):
                prev = None
                continue
            pt = (X(t), Y(v))
            if prev:
                draw_line(img, prev[0], prev[1], pt[0], pt[1], col, th)
            else:
                fill_rect(img, pt[0] - 1, pt[1] - 1, pt[0] + 2, pt[1] + 2, col)
            prev = pt


def figure(path, title, times, cells, ncols, pw=380, ph=190, ref_label="REFERENCE", ren_label="RENDER"):
    """cells: list of (panel title, [(values, color)], unit) or None, laid out row-major with ncols columns."""
    nrows = (len(cells) + ncols - 1) // ncols
    head = 40
    img = np.full((head + nrows * (ph + 6) + 6, ncols * (pw + 6) + 6, 3), 238, np.uint8)
    draw_text(img, 8, 10, title, (0, 0, 0), 2)
    x = 8 + text_size(title + "   ", 2)[0]
    for lab, col in ((ref_label, REF_C), (ren_label, REN_C)):
        fill_rect(img, x, 14, x + 24, 18, col)
        draw_text(img, x + 30, 10, lab, (0, 0, 0), 2)
        x += 30 + text_size(lab + "   ", 2)[0]
    for k, cell in enumerate(cells):
        if cell is None:
            continue
        r, c = divmod(k, ncols)
        t, series, unit = cell
        draw_panel(img, 6 + c * (pw + 6), head + r * (ph + 6), pw, ph, t, times, series, unit)
    write_png(path, img)


# ---------------------------------------------------------------------------------------------------------------

def run(args):
    regions = dict(DEFAULT_REGIONS)
    if args.regions:
        with open(args.regions) as f:
            regions = json.load(f)
    for r in range(3):
        for c in range(3):
            regions.setdefault("g%d%d" % (r, c), {"rect": [c / 3, r / 3, (c + 1) / 3, (r + 1) / 3]})
    named = [n for n in regions if n not in GRID]

    ref, ren = Source(args.ref), Source(args.render, args.fps)
    times = parse_times(args.times)
    w = args.width
    h = int(round(w * ref.height / ref.width / 4)) * 4
    w = w // 4 * 4
    if abs(ren.width / ren.height - ref.width / ref.height) > 0.01:
        print("warning: aspect differs (ref %dx%d, render %dx%d); render is stretched to the ref aspect"
              % (ref.width, ref.height, ren.width, ren.height))
    masks, boxes = region_masks(regions, w, h)

    def pairs(src, offset):
        res = {}
        for t in times:
            i = src.index(t + offset)
            if src.has(i):
                res[t] = (i, i + 1 if src.has(i + 1) else None)
        return res
    pr, pq = pairs(ref, 0.0), pairs(ren, args.render_offset)
    print("reading %d ref and %d render frames at %dx%d ..." % (2 * len(pr), 2 * len(pq), w, h))
    fr = ref.read([i for p in pr.values() for i in p if i is not None], (w, h))
    fq = ren.read([i for p in pq.values() for i in p if i is not None], (w, h))

    data = {n: {m: {"ref": [], "render": []} for m in METRICS} for n in regions}
    for t in times:
        mr = mq = None
        if t in pr:
            i, j = pr[t]
            mr = frame_metrics(fr[i], fr.get(j), masks, boxes, w, ref.fps)
        if t in pq:
            i, j = pq[t]
            mq = frame_metrics(fq[i], fq.get(j), masks, boxes, w, ren.fps)
        ss = ssim_by_region(fr[pr[t][0]], fq[pq[t][0]], masks) if (mr and mq) else {}
        for n in regions:
            for m in METRICS:
                if m in PAIR_ONLY:
                    data[n][m]["ref"].append(1.0 if ss else np.nan)
                    data[n][m]["render"].append(ss.get(n, np.nan))
                else:
                    data[n][m]["ref"].append(float(mr[n][m]) if mr else np.nan)
                    data[n][m]["render"].append(float(mq[n][m]) if mq else np.nan)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "metrics.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["time", "region", "metric", "ref", "render", "diff"])
        for n in regions:
            for m in METRICS:
                for k, t in enumerate(times):
                    a, b = data[n][m]["ref"][k], data[n][m]["render"][k]
                    wr.writerow([t, n, m, "%.6g" % a, "%.6g" % b, "%.6g" % (b - a)])

    def clean(x):
        return None if not np.isfinite(x) else round(float(x), 6)
    with open(os.path.join(args.out, "metrics.json"), "w") as f:
        json.dump({"ref": args.ref, "render": args.render, "render_offset": args.render_offset, "times": times,
                   "analysis_size": [w, h], "regions": regions, "units": UNITS,
                   "metrics": {n: {m: {s: [clean(v) for v in d[s]] for s in d} for m, d in md.items()}
                               for n, md in data.items()}}, f, indent=1)

    # summary: median |render - ref| and median (render - ref) over time
    def stats(n, m):
        a = np.array(data[n][m]["ref"])
        b = np.array(data[n][m]["render"])
        ok = np.isfinite(a) & np.isfinite(b)
        if not ok.any():
            return np.nan, np.nan, np.nan, np.nan
        d = b[ok] - a[ok]
        return np.median(np.abs(d)), np.median(d), np.median(a[ok]), np.median(b[ok])

    def table(names, cell):
        lines = ["| metric | unit | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
        for m in METRICS:
            row = [cell(*stats(n, m), m) for n in names]
            lines.append("| %s | %s | %s |" % (m, UNITS[m], " | ".join(row)))
        return "\n".join(lines)

    def mad_cell(mad, bias, a, b, m):
        if not np.isfinite(mad):
            return "-"
        if m in PAIR_ONLY:
            return "%s" % fmt(b)
        return "%s (%s%s)" % (fmt(mad), "+" if bias >= 0 else "", fmt(bias))

    def val_cell(mad, bias, a, b, m):
        if not np.isfinite(mad):
            return "-"
        return fmt(b) if m in PAIR_ONLY else "%s / %s" % (fmt(a), fmt(b))
    n_ok = sum(1 for k in range(len(times)) if np.isfinite(data["full"]["ok_L"]["ref"][k])
               and np.isfinite(data["full"]["ok_L"]["render"][k]))
    md = ["# Compare: %s vs %s" % (args.ref, args.render), "",
          "Times `%s` (%d samples, %d with both frames), render offset %+g s, analysis %dx%d." %
          (args.times, len(times), n_ok, args.render_offset, w, h), "",
          "## Median |render - ref| over time (median signed bias in brackets; ssim: median value)", "",
          table(named, mad_cell), "", "### 3x3 grid (g<row><col>, row 0 = top)", "", table(GRID, mad_cell), "",
          "## Median values over time: ref / render", "", table(named, val_cell), ""]
    with open(os.path.join(args.out, "summary.md"), "w") as f:
        f.write("\n".join(md))
    print("\n".join(md[:7]))

    # plots
    rl, ql = "REF", "RENDER " + ren.name + (" %+gS" % args.render_offset if args.render_offset else "")

    def cell(n, m):
        d = data[n][m]
        if m in PAIR_ONLY:
            return ("%s: %s" % (n, m), [(d["render"], REN_C, 2)], UNITS[m])
        return ("%s: %s" % (n, m), [(d["ref"], REF_C, 4), (d["render"], REN_C, 2)], UNITS[m])
    sets = {"colour": ["ok_L", "chroma", "ok_a", "ok_b", "luma_p10", "luma_p90"],
            "structure": ["edge", "edge_frac", "ssim"],
            "motion": ["flow_x", "flow_y", "mad", "flutter"]}
    for fname, ms in sets.items():
        cells = [cell(n, m) for n in named for m in ms]
        figure(os.path.join(args.out, fname + ".png"), fname.upper() + " VS TIME (S)", times, cells, len(ms),
               ref_label=rl, ren_label=ql)
    for m in args.grid_metrics.split(","):
        cells = [cell(g, m) for g in GRID]
        figure(os.path.join(args.out, "grid_%s.png" % m), "%s ON THE 3X3 SCREEN GRID VS TIME (S)" % m.upper(),
               times, cells, 3, ref_label=rl, ren_label=ql)
    print("wrote", args.out, "(metrics.csv, metrics.json, summary.md, colour/structure/motion/grid_*.png)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="reference/source/village_source.mp4")
    ap.add_argument("--render")
    ap.add_argument("--times", default="0:20:0.5", help="a:b:step (inclusive) or t1,t2,... in seconds")
    ap.add_argument("--out")
    ap.add_argument("--regions", help="JSON {name: {rect: [x0,y0,x1,y1], exclude: [[...]]}} (fractions, y down)")
    ap.add_argument("--render-offset", type=float, default=0.0, help="render time = ref time + offset (s)")
    ap.add_argument("--fps", type=float, default=24.0, help="fps of a PNG-sequence render")
    ap.add_argument("--width", type=int, default=640, help="analysis width (both sources are scaled to it)")
    ap.add_argument("--grid-metrics", default="ok_L,chroma,edge,flow_x,flow_y,mad")
    ap.add_argument("--dump-regions", metavar="PATH", help="write the default regions JSON and exit")
    args = ap.parse_args()
    if args.dump_regions:
        with open(args.dump_regions, "w") as f:
            json.dump(DEFAULT_REGIONS, f, indent=1)
        print("wrote", args.dump_regions)
        return
    if not (args.render and args.out):
        ap.error("--render and --out are required")
    run(args)


if __name__ == "__main__":
    main()
