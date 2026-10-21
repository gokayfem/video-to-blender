# Comparing renders with the reference

Owner: compare. Tools: `tools/compare.py` (metrics over time) and `tools/video.py` (frames, videos, sheets).

## The point

The reference is a stylized AI video; our street is a generator. Individual houses will never line up, so a pixel
match on one frame means nothing. What should match is the *statistics of the street over time*: how bright and
warm each part of the screen is, how busy (edgy) it is, how fast the walls and cobbles stream past and in which
direction, and how much the bunting flutters. Every metric is therefore sampled across the whole clip (default
every 0.5 s) and per screen region, and read as a pair of curves (reference vs render), not as a single score.

## Dependencies

- `ffmpeg`/`ffprobe` (Homebrew). This build has no `drawtext`, so all labels are drawn by our own 5x7 bitmap
  font in numpy.
- `numpy`. The system `python3` (3.9) has neither numpy nor PIL nor matplotlib, so both scripts re-execute
  themselves with Blender's bundled python (`/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13`,
  numpy 2.3) when numpy is missing. Override with `V2N_PYTHON=/path/to/python3`. No PIL or matplotlib needed:
  frames are decoded through ffmpeg pipes, PNGs are written with zlib, plots are rasterised in numpy.

## Commands

```bash
cd /Users/gokay/Video2Nodes
REF=reference/source/village_source.mp4

# metrics over time (render = PNG dir of f_####.png, frame N = time (N-1)/24 s, or any video)
python3 tools/compare.py --ref $REF --render out/lead/seq --times 0:20:0.5 --out out/compare/run1
#   --render-offset S   compare ref time t with render time t+S
#   --regions R.json    custom regions (start from: python3 tools/compare.py --dump-regions R.json)
#   --width 640         analysis width; --fps 24 for PNG sequences; --grid-metrics ok_L,chroma,edge,...

# videos and stills
python3 tools/video.py assemble --seq out/lead/seq --out out/lead/seq.mp4            # H.264 yuv420p crf 18
python3 tools/video.py sbs   --ref $REF --render out/lead/seq --out out/compare/lead_sbs.mp4 [--stack v]
                             [--start 0 --end 20 --scale 0.5 --label LEAD --render-offset 0]
python3 tools/video.py sheet --ref $REF --render out/lead/seq --times 0:20:2.5 --out out/compare/lead_sheet.png
python3 tools/video.py extract --src $REF --times 0:20:1 --out out/compare/ref_1s [--width 640]
```

`sbs` draws labels and a timecode (`T seconds  F frame-number`) into every frame; a missing render frame shows
`NO FRAME`. `extract` writes `f_####.png` with the same numbering as renders, so an extracted set can itself be
passed as `--render`.

Single stills are fine: render time t as `f_{round(t*24)+1:04d}.png` (a sparse directory). Add the next frame
(N+1) too if you want motion metrics at that time; without it motion columns are blank for that time.

## Regions

Fractional rects `[x0, y0, x1, y1]` (y down) in the frame, tuned on `reference/frames/t05.png`; optional `exclude`
rects are cut out. Defaults (`--dump-regions` writes them as JSON):

| region | rect | what it is |
|---|---|---|
| `full` | whole frame | |
| `sky_strip` | .36,0 - .64,.30 | narrow sky between the roofs (contains bunting) |
| `bunting` | .33,0 - .70,.24 | flag strings across the street; where flutter is measured |
| `left_facade` | 0,.05 - .30,.62 | near left wall |
| `right_facade` | .70,.05 - 1,.62 | near right wall |
| `road` | 0,.70 - 1,1 minus walker box | cobbles, curbs, verges |
| `walker` | .37,.44 - .63,.95 | the hooded walker |
| `g<row><col>` | 3x3 grid, row 0 = top | always added |

## Metrics (per time, per region)

Both sources are scaled to the same analysis size (640x352 by default) first.

Colour (from frame t)
- `srgb_r/g/b`: mean gamma-encoded sRGB, 0-1.
- `ok_L`, `ok_a`, `ok_b`: mean Oklab (perceptual lightness; a = green-red, b = blue-yellow; warm grade = b > 0).
- `chroma`: mean per-pixel Oklab chroma sqrt(a^2+b^2) (saturation; not the chroma of the mean colour).
- `luma_p10/p50/p90`: percentiles of Rec.709 luma Y'. p10 = shadow floor (the reference keeps shadows warm and
  lifted), p90 = highlights, p90 - p10 = contrast.

Structure
- `edge`: mean Sobel gradient magnitude of luma (texture busyness: cobbles, timber, window frames).
- `edge_frac`: fraction of pixels with gradient > 0.08 (how much of the region is "detail").
- `ssim`: SSIM of luma at 160x88, averaged in the region (one value per time, ref vs render). Reported, but weak
  here: SSIM rewards the same object at the same pixel. The reference against itself shifted by only 0.5 s already
  drops to about 0.3 (facades 0.13), so for a generator any value in that range is "as good as it gets". Use it
  only to catch gross framing errors (camera height, horizon, walker placement) on carefully aligned stills.

Motion (frame t -> frame t + 1/24 s, on the same source)
- `mad`: mean |luma(t+1) - luma(t)|: how much the region changes per frame (speed x texture contrast).
- `flow_x`, `flow_y`: dominant translation of the region by phase correlation (Hann-windowed, sub-pixel), in
  pixels per frame at 1280-wide scale (+x right, +y down). This is the streaming speed: in the reference the left
  wall moves left (about -3 to -4.5), the right wall right (+3 to +8), the road downward (+2 to +4), the sky and
  bunting slowly upward. A forward-moving camera produces expansion, not one translation, so per-region values
  (and the 3x3 grid) are what to compare; `full` is close to zero for forward motion.
- `flow_conf`: phase-correlation peak height (0-1). Low (< 0.05) means no single clean translation; treat that
  sample's flow as noise.
- `flutter`: mean residual |luma| after shifting t+1 back by the measured flow: motion NOT explained by the
  region's translation. In `bunting` this is flag flutter plus parallax; compare its level and variability, not
  individual samples.

## Outputs (in `--out`)

- `metrics.csv`: long format `time, region, metric, ref, render, diff` (diff = render - ref).
- `metrics.json`: same data as arrays plus regions, units and settings.
- `summary.md` (top table also printed): per metric and region, median |render - ref| over time with the median
  signed bias in brackets (+ = render higher), the 3x3 grid table, and median ref / render values.
- `colour.png`, `structure.png`, `motion.png`: rows = named regions, columns = metrics, x = time (s).
  Blue thick = reference, orange thin = render (identical curves hide the blue line under the orange). Each panel
  has its own y range; read the tick labels before judging a gap.
- `grid_<metric>.png`: the metric on the 3x3 screen grid, laid out like the screen.

## Reading the plots

- A constant offset between curves = a grade or exposure difference (fix in materials/world/lighting).
- Same level, different wiggle = different rhythm (house widths, bunting spacing, gait).
- Flow sign and magnitude per region = whether the street streams past at the right speed and direction. Walk
  Speed and camera FOV both scale it; compare `left_facade`/`right_facade`/`road` and the grid's outer cells.
- The reference has a slow 20 s arc (darker and cooler mid-clip around 13-16 s in `full: ok_L`); a generator need
  not copy that arc, but its mean level should sit inside the reference's range.
- Noise floor: the reference against itself shifted by 0.5 s gives colour differences of about 0.002-0.02,
  edge 0.001-0.003, flow about 0.05-0.5 px/frame on walls and road (walker up to 4.5: gait phase). Differences of
  that size are "same clip"; 5-10x that is a real difference.

## Validation (2026-10-21)

- Reference vs itself: every difference exactly 0, SSIM 1.00.
- Reference vs itself `--render-offset 0.5` (times 0:19.5): differences at the noise floor quoted above;
  SSIM 0.13-0.48.
- Reference vs the earlier GLSL reconstruction (`~/Downloads/4jpNrAqBSF61HOhVi4jIUQ.mp4`, identical to
  `shader-skills/prompts/village-loop/renders/village-loop-left.mp4`): the tools flag what is visibly different,
  a side-on camera: `flow_x` +4..+16 in every cell (everything streams right) where the reference has walls
  diverging left/right; sky strip much darker (ok_L -0.19) because there is no sky; road brighter (+0.07);
  edge density lower everywhere; luma p10 higher (+0.08, flatter shadows). The render's 480 frames leave t = 20 s
  blank, as intended.
