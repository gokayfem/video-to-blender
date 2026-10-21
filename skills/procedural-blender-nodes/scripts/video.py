#!/usr/bin/env python3
"""Video helpers for comparing the reference clip with our renders (see docs/COMPARE.md).

Dependencies: ffmpeg/ffprobe on PATH and numpy. PIL and matplotlib are NOT needed: images are decoded through
ffmpeg pipes, PNGs are written with zlib, and labels use a built-in 5x7 bitmap font (this ffmpeg has no drawtext).
If the running python lacks numpy, the script re-executes itself with Blender's bundled python (or $V2N_PYTHON).

Frame convention: a render sequence is a directory of f_####.png where frame N shows time (N-1)/fps. A sparse
directory (only some N present) is fine for stills/metrics; videos need a dense run of frames.

    python3 tools/video.py extract  --src reference/source/village_source.mp4 --times 0:20:1 --out out/compare/ref_1s
    python3 tools/video.py assemble --seq out/lead/seq --out out/lead/seq.mp4
    python3 tools/video.py sbs      --ref reference/source/village_source.mp4 --render out/lead/seq \
                                    --out out/compare/lead_sbs.mp4 [--stack v] [--start 0 --end 20] [--scale 0.5]
    python3 tools/video.py sheet    --ref reference/source/village_source.mp4 --render out/lead/seq \
                                    --times 0:20:2.5 --out out/compare/lead_sheet.png
"""
import glob
import json
import os
import re
import struct
import subprocess
import sys
import zlib


def require_numpy():
    """Import numpy, re-executing this script under a python that has it if needed."""
    try:
        import numpy  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("_V2N_REEXEC"):
        sys.exit("numpy not available (tried %s)" % sys.executable)
    cands = [os.environ.get("V2N_PYTHON", "")]
    cands += sorted(glob.glob("/Applications/Blender.app/Contents/Resources/*/python/bin/python3.*[0-9]"),
                    reverse=True)
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            os.environ["_V2N_REEXEC"] = "1"
            os.execv(c, [c, os.path.abspath(sys.argv[0])] + sys.argv[1:])
    sys.exit("numpy not found; set V2N_PYTHON to a python3 with numpy (e.g. Blender's bundled python)")


require_numpy()
import numpy as np  # noqa: E402

SEQ_RE = re.compile(r"f_(\d{4,})\.png$")


# ---------------------------------------------------------------------------------------------------------------
# sources

def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_read_packets", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / float(den), int(s.get("nb_read_packets", 0))


class Source:
    """An mp4 (or any ffmpeg-readable video) or a directory of f_####.png. Frame index i is 0-based (= N-1)."""

    def __init__(self, path, fps=24.0):
        self.path = path
        self.is_dir = os.path.isdir(path)
        if self.is_dir:
            self.files = {}
            for f in os.listdir(path):
                m = SEQ_RE.match(f)
                if m:
                    self.files[int(m.group(1)) - 1] = os.path.join(path, f)
            if not self.files:
                raise SystemExit("no f_####.png frames in %s" % path)
            self.fps = fps
            self.width, self.height, _, _ = probe(self.files[min(self.files)])
            self.n_frames = max(self.files) + 1
        else:
            self.width, self.height, self.fps, self.n_frames = probe(path)
        self.name = os.path.basename(os.path.normpath(path))

    def has(self, i):
        return (i in self.files) if self.is_dir else (0 <= i < self.n_frames)

    def index(self, t):
        return int(round(t * self.fps))

    def read(self, indices, size=None):
        """Return {i: uint8 HxWx3} for the requested frame indices that exist, scaled to size=(w, h)."""
        want = sorted({i for i in indices if self.has(i)})
        w, h = size or (self.width, self.height)
        vf = ["-vf", "scale=%d:%d:flags=area" % (w, h)] if (w, h) != (self.width, self.height) else []
        nbytes = w * h * 3
        out = {}
        if self.is_dir:
            for i in want:
                raw = subprocess.run(["ffmpeg", "-v", "error", "-i", self.files[i]] + vf +
                                     ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True,
                                     check=True).stdout
                out[i] = np.frombuffer(raw[:nbytes], np.uint8).reshape(h, w, 3)
            return out
        if not want:
            return out
        wanted = set(want)
        last = want[-1]
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", self.path, "-fps_mode", "passthrough"] + vf +
                             ["-frames:v", str(last + 1), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             stdout=subprocess.PIPE)
        i = 0
        while i <= last:
            buf = p.stdout.read(nbytes)
            if len(buf) < nbytes:
                break
            if i in wanted:
                out[i] = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
        p.stdout.close()
        p.wait()
        return out

    def stream(self, start, end, fps, size):
        """Yield (t, frame or None) at fps from start to end (exclusive) for videos; dense sequences for dirs."""
        w, h = size
        nbytes = w * h * 3
        n = int(round((end - start) * fps))
        if self.is_dir:
            first = int(round(start * self.fps))
            cmd = ["ffmpeg", "-v", "error", "-framerate", str(self.fps), "-start_number", str(first + 1),
                   "-i", os.path.join(self.path, "f_%04d.png"), "-vf", "fps=%g,scale=%d:%d:flags=area" % (fps, w, h),
                   "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
            if not self.has(first):
                cmd = None
        else:
            cmd = ["ffmpeg", "-v", "error", "-ss", "%.4f" % start, "-i", self.path,
                   "-vf", "fps=%g,scale=%d:%d:flags=area" % (fps, w, h), "-frames:v", str(n),
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE) if cmd else None
        for k in range(n):
            buf = p.stdout.read(nbytes) if p else b""
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3) if len(buf) == nbytes else None
            yield start + k / fps, frame
        if p:
            p.stdout.close()
            p.wait()


def parse_times(spec):
    """'a:b:step' (inclusive of b when it lands on the grid) or 'a,b,c'."""
    if ":" in spec:
        a, b, s = (float(x) for x in spec.split(":"))
        n = int(np.floor((b - a) / s + 1e-6)) + 1
        return [round(a + k * s, 6) for k in range(n)]
    return [float(x) for x in spec.split(",") if x.strip()]


# ---------------------------------------------------------------------------------------------------------------
# PNG writing and a tiny bitmap font

def write_png(path, img):
    img = np.ascontiguousarray(img, dtype=np.uint8)
    h, w = img.shape[:2]
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(raw, 4)) + chunk(b"IEND", b""))


_GLYPHS = {
    "0": ".###. #...# #..## #.#.# ##..# #...# .###.", "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####", "3": "####. ....# ....# .###. ....# ....# ####.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.", "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": "..##. .#... #.... ####. #...# #...# .###.", "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.", "9": ".###. #...# #...# .#### ....# ...#. .##..",
    "A": ".###. #...# #...# ##### #...# #...# #...#", "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".###. #...# #.... #.... #.... #...# .###.", "D": "####. #...# #...# #...# #...# #...# ####.",
    "E": "##### #.... #.... ####. #.... #.... #####", "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".###. #...# #.... #.### #...# #...# .####", "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": ".###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.", "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#", "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#", "N": "#...# #...# ##..# #.#.# #..## #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.", "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#", "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".#### #.... #.... .###. ....# ....# ####.", "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.", "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# #.#.# .#.#.", "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..", "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    " ": "..... ..... ..... ..... ..... ..... .....", ".": "..... ..... ..... ..... ..... .##.. .##..",
    ",": "..... ..... ..... ..... .##.. ..#.. .#...", ":": "..... .##.. .##.. ..... .##.. .##.. .....",
    "-": "..... ..... ..... ##### ..... ..... .....", "+": "..... ..#.. ..#.. ##### ..#.. ..#.. .....",
    "_": "..... ..... ..... ..... ..... ..... #####", "/": "....# ....# ...#. ..#.. .#... #.... #....",
    "(": "...#. ..#.. .#... .#... .#... ..#.. ...#.", ")": ".#... ..#.. ...#. ...#. ...#. ..#.. .#...",
    "%": "##..# ##..# ...#. ..#.. .#... #..## #..##", "=": "..... ..... ##### ..... ##### ..... .....",
    "|": "..#.. ..#.. ..#.. ..#.. ..#.. ..#.. ..#..", "<": "...#. ..#.. .#... #.... .#... ..#.. ...#.",
    ">": ".#... ..#.. ...#. ....# ...#. ..#.. .#...", "[": ".###. .#... .#... .#... .#... .#... .###.",
    "]": ".###. ...#. ...#. ...#. ...#. ...#. .###.", "#": ".#.#. .#.#. ##### .#.#. ##### .#.#. .#.#.",
    "'": "..#.. ..#.. .#... ..... ..... ..... .....", "*": "..... ..#.. #.#.# .###. #.#.# ..#.. .....",
    "@": ".###. #...# #.### #.#.# #.##. #.... .###.",
    "?": ".###. #...# ....# ...#. ..#.. ..... ..#..", "!": "..#.. ..#.. ..#.. ..#.. ..#.. ..... ..#..",
}
_GLYPH_BITS = {c: np.array([[ch == "#" for ch in row] for row in g.split()], bool) for c, g in _GLYPHS.items()}


def text_size(text, scale=2):
    return len(text) * 6 * scale, 7 * scale


def draw_text(img, x, y, text, color=(0, 0, 0), scale=2, bg=None, pad=None):
    """Draw upper-cased text with the 5x7 font; (x, y) is the top-left corner. Clipped to the image."""
    h, w = img.shape[:2]
    if bg is not None:
        p = scale * 2 if pad is None else pad
        tw, th = text_size(text, scale)
        fill_rect(img, x - p, y - p, x + tw + p - scale, y + th + p, bg)
    for k, ch in enumerate(text.upper()):
        bits = _GLYPH_BITS.get(ch, _GLYPH_BITS["?"])
        big = np.kron(bits, np.ones((scale, scale), bool))
        x0, y0 = x + k * 6 * scale, y
        x1, y1 = x0 + big.shape[1], y0 + big.shape[0]
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if cx0 >= cx1 or cy0 >= cy1:
            continue
        m = big[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
        img[cy0:cy1, cx0:cx1][m] = color


def fill_rect(img, x0, y0, x1, y1, color):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(int(x0), 0), max(int(y0), 0), min(int(x1), w), min(int(y1), h)
    if x0 < x1 and y0 < y1:
        img[y0:y1, x0:x1] = color


# ---------------------------------------------------------------------------------------------------------------
# commands

def extract(src, times, out_dir, width=None):
    s = Source(src)
    size = None
    if width:
        size = (width, int(round(width * s.height / s.width / 2)) * 2)
    idx = {t: s.index(t) for t in times}
    frames = s.read(idx.values(), size)
    os.makedirs(out_dir, exist_ok=True)
    for t, i in idx.items():
        if i in frames:
            write_png(os.path.join(out_dir, "f_%04d.png" % (i + 1)), frames[i])
    print("wrote %d frames to %s (f_N.png, N-1 = round(t*%g))" % (len(frames), out_dir, s.fps))


def assemble(seq_dir, out, fps=24.0, crf=18):
    s = Source(seq_dir, fps)
    first = min(s.files)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-start_number", str(first + 1),
                    "-i", os.path.join(seq_dir, "f_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", str(crf), "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", out], check=True)
    print("wrote", out)


def _pane_size(src_ref, scale):
    w = int(round(src_ref.width * scale / 2)) * 2
    h = int(round(src_ref.height * scale / 2)) * 2
    return w, h


def side_by_side(ref, render, out, start=0.0, end=None, stack="h", scale=0.5, fps=24.0,
                 labels=("REFERENCE", None), render_offset=0.0, crf=18):
    """Reference | render (or stacked), synchronized by time, with labels and a timecode drawn in."""
    r, q = Source(ref), Source(render, fps)
    if end is None:
        end = min(r.n_frames / r.fps, q.n_frames / q.fps - render_offset)
    w, h = _pane_size(r, scale)
    lab_r = labels[0]
    lab_q = labels[1] or ("RENDER " + q.name)
    W, H = (2 * w, h) if stack == "h" else (w, 2 * h)
    ts = max(1, int(round(h / 176)))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                            "%dx%d" % (W, H), "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-crf", str(crf), out], stdin=subprocess.PIPE)
    n = 0
    for (t, fa), (_, fb) in zip(r.stream(start, end, fps, (w, h)), q.stream(start + render_offset,
                                                                           end + render_offset, fps, (w, h))):
        canvas = np.zeros((H, W, 3), np.uint8)
        ox, oy = (w, 0) if stack == "h" else (0, h)
        if fa is not None:
            canvas[:h, :w] = fa
        if fb is not None:
            canvas[oy:oy + h, ox:ox + w] = fb
        else:
            draw_text(canvas, ox + w // 2 - 60 * ts, oy + h // 2, "NO FRAME", (200, 60, 60), 2 * ts)
        draw_text(canvas, 6 * ts, 6 * ts, lab_r, (255, 255, 255), ts, bg=(0, 0, 0))
        draw_text(canvas, ox + 6 * ts, oy + 6 * ts, lab_q, (255, 255, 255), ts, bg=(0, 0, 0))
        tc = "T %6.3fS  F %04d" % (t, int(round(t * fps)) + 1)
        tw, th = text_size(tc, ts)
        draw_text(canvas, W - tw - 6 * ts, H - th - 6 * ts, tc, (255, 255, 0), ts, bg=(0, 0, 0))
        enc.stdin.write(canvas.tobytes())
        n += 1
    enc.stdin.close()
    enc.wait()
    print("wrote %s (%d frames, %.2f-%.2f s, %dx%d)" % (out, n, start, end, W, H))


def contact_sheet(ref, render, times, out, thumb_width=320, render_offset=0.0, label=None):
    """Reference row over render row at the given times (columns), with time labels."""
    r = Source(ref)
    q = Source(render) if render else None
    th = int(round(thumb_width * r.height / r.width / 2)) * 2
    size = (thumb_width, th)
    fr = r.read([r.index(t) for t in times], size)
    fq = q.read([q.index(t + render_offset) for t in times], size) if q else {}
    gap, top, left = 4, 22, 0
    rows = 2 if q else 1
    img = np.full((top + rows * (th + gap), len(times) * (thumb_width + gap) + gap, 3), 255, np.uint8)
    for k, t in enumerate(times):
        x = gap + k * (thumb_width + gap)
        draw_text(img, x, 4, "T=%.2fS" % t, (0, 0, 0), 2)
        a = fr.get(r.index(t))
        if a is not None:
            img[top:top + th, x:x + thumb_width] = a
        if q:
            b = fq.get(q.index(t + render_offset))
            y = top + th + gap
            if b is not None:
                img[y:y + th, x:x + thumb_width] = b
            else:
                fill_rect(img, x, y, x + thumb_width, y + th, (60, 60, 60))
                draw_text(img, x + 8, y + th // 2, "NO FRAME", (255, 120, 120), 2)
    draw_text(img, gap + 4, top + 4, "REF", (255, 255, 255), 2, bg=(0, 0, 0))
    if q:
        draw_text(img, gap + 4, top + th + gap + 4, label or q.name, (255, 255, 255), 2, bg=(0, 0, 0))
    write_png(out, img)
    print("wrote", out)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("extract", help="reference (or any video) frames at times -> f_####.png")
    a.add_argument("--src", required=True)
    a.add_argument("--times", required=True, help="a:b:step or t1,t2,...")
    a.add_argument("--out", required=True)
    a.add_argument("--width", type=int)
    a = sub.add_parser("assemble", help="PNG sequence -> H.264 mp4 (yuv420p, crf 18)")
    a.add_argument("--seq", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--fps", type=float, default=24.0)
    a.add_argument("--crf", type=int, default=18)
    a = sub.add_parser("sbs", help="labelled side-by-side or stacked comparison video")
    a.add_argument("--ref", required=True)
    a.add_argument("--render", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--start", type=float, default=0.0)
    a.add_argument("--end", type=float)
    a.add_argument("--stack", choices=["h", "v"], default="h")
    a.add_argument("--scale", type=float, default=0.5)
    a.add_argument("--label", help="render label (default: RENDER <dir name>)")
    a.add_argument("--render-offset", type=float, default=0.0, help="render time = ref time + offset (s)")
    a = sub.add_parser("sheet", help="contact sheet: ref row over render row")
    a.add_argument("--ref", required=True)
    a.add_argument("--render")
    a.add_argument("--times", default="0:20:2.5")
    a.add_argument("--out", required=True)
    a.add_argument("--width", type=int, default=320)
    a.add_argument("--label")
    a.add_argument("--render-offset", type=float, default=0.0)
    args = ap.parse_args()
    if args.cmd == "extract":
        extract(args.src, parse_times(args.times), args.out, args.width)
    elif args.cmd == "assemble":
        assemble(args.seq, args.out, args.fps, args.crf)
    elif args.cmd == "sbs":
        side_by_side(args.ref, args.render, args.out, args.start, args.end, args.stack, args.scale,
                     labels=("REFERENCE", args.label), render_offset=args.render_offset)
    elif args.cmd == "sheet":
        contact_sheet(args.ref, args.render, parse_times(args.times), args.out, args.width, args.render_offset,
                      args.label)


if __name__ == "__main__":
    main()
