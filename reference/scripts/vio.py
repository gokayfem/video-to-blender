"""Shared video IO for reference measurements (run with Blender's bundled python3: it has numpy).

Frames are decoded with ffmpeg to raw RGB24; no PIL needed.
"""
import os, subprocess, numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "reference", "source", "village_source.mp4")
W, H, FPS, N = 1280, 704, 24, 481


def frames(start=0, count=N, gray=False):
    """Yield (index, HxWx3 uint8 array) for frames [start, start+count)."""
    cmd = ["ffmpeg", "-loglevel", "error", "-i", SRC, "-vf",
           f"select=between(n\\,{start}\\,{start+count-1})", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n = W * H * 3
    i = start
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        a = np.frombuffer(b, np.uint8).reshape(H, W, 3)
        yield i, (a.mean(2).astype(np.float32) if gray else a)
        i += 1
    p.wait()


def load_gray():
    import tempfile
    cache = os.environ.get("V2N_GRAY_CACHE", os.path.join(tempfile.gettempdir(), "v2n_gray_cache.npy"))
    if os.path.exists(cache):
        return np.load(cache, mmap_mode="r")
    arr = np.zeros((N, H, W), np.uint8)
    for i, f in frames(gray=True):
        arr[i] = f.astype(np.uint8)
    np.save(cache, arr)
    return arr


def srgb_hex(rgb):
    r, g, b = [int(round(float(c))) for c in rgb]
    return f"#{r:02X}{g:02X}{b:02X}"
