# Reference breakdown: Storybook Street (village_source.mp4)

Machine-readable numbers: `docs/reference_params.json` (value, unit, method, confidence for each). Scripts that
produced every number: `reference/scripts/`. Run them with Blender's python, which has numpy:
`/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13 reference/scripts/<name>.py`. Sheets
for builders are in `reference/sheets/` (legend in section 8).

Units: **1 H = walker height** (hood top to boot sole, 344 px on screen). Street space is (s, d, h) as in
AGENTS.md, and **+d = left of travel**. Pixel coordinates are in the 1280x704 frame, origin top left.
"Rendered sRGB" means colours as they appear in the warm-graded frames, not albedos.

## 0. How the numbers were measured, and how far to trust them

| Quantity | Method | Trust |
|---|---|---|
| Horizon y_h = **355 px** | block-matched ground flow, 49k patches, fit `dy = k (y - y_h)^2`; 349-360 in 5 s windows | high |
| Camera height **0.895 H** | `(y_feet - y_h)/(y_feet - y_hood)`, feet 663, hood 318, mean of all frames | high |
| Lateral offsets d and heights h | ground rows: `d = (x - 620) hc / (y - y_h)`; static objects: `1/u` and `1/(y_h - y)` are linear in time, slopes give d and h; size = px * d / u | high/medium. **These do not depend on the focal length.** |
| V/f = **1.29e-3 /s** | same ground flow, constant to 1% over the clip | high |
| Focal length **f ~ 700 px** (vertical FOV ~53 deg) | shape priors only: pot rim ellipse (~720 px), door and window aspects in the unrolled facades, old breakdown (680-700). Motion alone can't separate f from speed | **low**: plausible 600-850 px |
| Walk speed **0.90 H/s** | 1.29e-3 * f | low in absolute terms. It matches the AGENTS.md default, so we keep it |

**Along-street lengths** (house widths, spacings, block lengths) are quoted at 0.9 H/s. They all scale with the
chosen speed, so their ratios to each other are reliable. Their ratio to heights depends on f.

**Unrolled facades** (`reference/sheets/slit_*.jpg`): one image column per frame (2 px wide), stacked over all 481
frames. Each strip is an elevation of one side of the street as it passes: **53 px = 1 H along the street**.
Vertical scale is ~170 px/H for x183 and x1057, and ~112 px/H for x328 and x912. In all strips s increases to the
right, so the left-side strips read as true elevations and the right-side strips are mirrored. Features that
stick out of the wall (signs, barrels, awning arms) are stretched horizontally by the oblique view. Flush features
(doors, windows, beams) are true size.

## 1. Road (owner: road)

The cross-section was measured on ground rows y = 560-680 in every 4th frame (`cross_section.py`). The band edges
come out the same on every row to within 0.02 H. Widths are re-centred on the cobbled carriageway centre. The
camera path runs 0.15 H right of that centre (d = -0.15).

| Band (from the centre outward) | \|d\| from carriageway centre (H) | Width (H) | Notes |
|---|---|---|---|
| Cobbled carriageway | 0 - 1.15 | **2.3** total | rounded cobbles, see below |
| Inner grass strip | 1.15 - 1.47 | **0.32** | low grass in the gutter between the cobbles and the curb. Tufts spill over both edges |
| Curb | 1.50 - 1.75 | **~0.25** top, plus a dark face of ~0.05 | long grey blocks with a rounded top edge |
| Cobbled sidewalk | 1.75 - 2.1 (right) / 2.45 (left) | **0.35-0.7** | the same cobbles, a little smaller. Pots and planters often stand on its outer edge |
| Outer grass verge | to the wall | **0.2-0.6** | taller tufts with white flower dots. Pots, barrels, ladders and planters stand here |
| Wall base (facade line) | **~2.55** (2.4-2.65) | | wall to wall ~5.1 H |

- **Five bands, not three.** The AGENTS.md defaults (Street Width 4.0 curb to curb, facade at 3.0) are about 25%
  too wide. Suggested defaults: Street Width (curb face to curb face) **3.0**, Curb Width **0.25**, sidewalk
  **0.45**, verge **0.35**, facade line **2.55**. Reference crops: `crops_road.jpg`.
- **Curb:** about **0.07 H** above the grass strip (0.05-0.1; measured from its visible face,
  `h = hc * dy / (y - y_h)`). Blocks are **~0.8 H long** (0.6-0.95, from joint spacing in the strips) with thin
  dark joints and softly rounded ends. Colour `#6D6762` in shade to `#8A8580` in sun, grey with a slight blue
  cast. The top edge catches a bright highlight.
- **Cobbles:** rounded river-stone domes, wider across the street than along it. Near the camera they are about
  **0.3 H across x 0.25 H along** (across is f-independent; along assumes f = 700). They sit in loose, irregular
  rows roughly perpendicular to the street. Joints are ~20% of the cobble size, dark warm brown. Colours: mixed
  `#846F63`, sunlit tops `#D7AA7E`, shade `#71635B`, gaps `#524334`.
- **Grass:** desaturated olive `#58553B` (p90 `#786E5F`), turning warm yellow-green where the sun hits it.
- **Path:** the street winds gently. The far scene drifts -56..+25 px horizontally over the clip, about 5 deg of
  heading change, and there is no visible slope. The far road meets the houses at y ~365, just below the horizon.

## 2. Facades (owner: facades)

Continuous terraces on both sides with no gaps. Storybook half-timbered houses with soft, bevelled, toy-like
forms. Elevations: `slit_left_x183.jpg`, `slit_left_x328.jpg`, `slit_right_x912.jpg`, `slit_right_x1057.jpg`.
Crops: `crops_houses.jpg`.

- **House width along s:** on the left, 4-5 frontages per 18 H of street (3.7, 4.1, 5.2, 3.7 H). On the right,
  about 7 (1.9-3.8 H, mean 2.6). **Overall mean ~3.2 H, range ~1.9-5.2 H.** A generator should draw widths from
  roughly 2-5 H, with a mode near 3 H, and use slightly wider houses on the sunlit (left) side if it copies the
  clip.
- **How many houses the clip samples:** **~11-12 frontages pass the camera in 20 s** (both sides together), not
  ~30. Another ~15-20 per side are visible further down the street, but small and hazy.
- **Storeys:** usually 3 (ground floor plus 2 upper), sometimes 2 or 4. Ground floor **~1.85 H** (1.7-2.0, from
  floor-beam heights in the strips, f-independent). Upper floors **~1.5 H** (1.4-1.6). Eaves at ~4.5-5 H.
- **Jetties:** each upper floor overhangs by ~0.2-0.4 H on a heavy floor beam with chunky corbels or brackets
  (`crops_houses.jpg`, tile 1). Present on most houses.
- **Timber:** dark brown, `#574235` in shade to `#825440` in sun. Nearly every house has corner and party-wall
  posts and a heavy beam at each floor line. About half have diagonal braces on the upper floors (single long
  diagonals, a few V or K pairs). A few ground floors are plain plaster or have a grey stone plinth (~0.4 H) or
  rubble-stone patches.
- **Windows:** ground-floor glass ~**0.55 W x 0.75 H**, set in deep reveals (~0.1-0.15 H). Cream-white frames
  with a cross mullion, 4-6 panes. **Shutters** come in pairs, ~0.35 H wide each, louvred or boarded,
  green-grey: lit `#A89B7A` (it reads green next to the warm plaster), shade `#4F6A55`. They appear on about
  60-70% of windows. Upper floors have 2 windows per floor on a ~3 H house, spaced ~1.3-1.5 H apart. Some windows
  have a plaster surround instead of shutters.
- **Doors:** ~**0.75 W x 1.45 H**, set in a thick dark timber frame. Round-arched heads are common (about half),
  the rest are square. Leaves are planked, teal / green / dark olive (`#463F30` in shade) or brown. About 0.7
  doors per frontage; shop frontages carry an awning and a window instead.
- **Roofs:** steep, ~**55 deg** (50-60). Warm terracotta tiles on the near houses, blue-grey slate (`#697C90`) on
  the taller ones further down, plus a slate spire and tower near the vanishing point. Eaves face the street.
  Stone or brick chimneys sit on about one house in two. Small dormers are rare.
- **Plaster palette** (rendered sRGB): sunlit cream/peach `#CC935B` (p90 `#E4B376`); shaded ochre `#B9703F`;
  yellow `#A76C3D`; shaded orange `#834C31`; shaded sage green `#72705E` (one sage house per side per clip);
  shaded right-side walls `#654029`-`#B07D53`. Rough visual mix: 40% cream/peach, 30% ochre/orange, 20% yellow, 10% sage.

## 3. Props (owner: props)

Counts per 18 H of street (one full clip) per side, read from the unrolled strips. Crops: `crops_props.jpg`.

| Prop | Left | Right | Per frontage | Size (H) and look |
|---|---|---|---|---|
| Window box, ground floor | ~4 | ~6 | ~0.9 | box 0.8-1.2 long, ~0.2 tall, terracotta `#663C23`, mounded leaves, red `#823729` / coral / white geraniums, trailing ivy |
| Window box, upper floors | most upper windows | most upper windows | ~70% of upper windows | same, slightly smaller |
| Pots on the verge or sidewalk edge | ~5 | ~8 | ~1.1 | terracotta, 0.17-0.45 tall, flared with a rim, leafy plants or a small conifer, often in 2s and 3s |
| Barrels | 1 (small) | ~6, in pairs | a pair at ~25% | 0.55 tall x 0.6 diameter (f-independent), two dark hoops, `#65361C` |
| Awnings | 2 | 1 | ~25% | over a shop window, 1.5-2.5 wide, iron arms, scalloped valance. Green-grey and cream stripes (`#A59186`-`#B0A99E` / `#D8CDBE`; the old breakdown called it blue-white), or peach and cream (`#AC6B3E` / `#C19D8E`). Stripes ~0.12 H wide (visual) |
| Hanging signs | 0-1 | 2 | ~20% | scrolled iron bracket at ~2.2-2.6 H (visual). Boards: a bread-loaf shape, ~0.6 x 0.45, or a round/shield sign with a teal bowl motif |
| Wall lanterns | 1 | 2 | ~25% | black iron box lantern, ~0.28, warm glass, beside a door at ~1.6-2 H |
| Ivy | 2-3 patches | 1-2 | ~35% | leaf curtains framing doors and running up corners |
| Ladders | 0 | 2 | ~15% | wooden, leaning on the facade on the verge |

## 4. Bunting and lanterns (owner: bunting)

Crops: `crops_bunting.jpg`. Overhead strip: `slit_overhead_x640.jpg`.

- **Spacing:** strings cross the street **every ~2.6 H on average**, about one per house. Measured from the times
  at which 7 strings leave the top of frame (t = 2.0, 5.1, 7.7, 12.7, 14.4, 16.2, 18.8 s, `string_tracks.py`).
  The gaps are irregular, 1.5-4.5 H, with one long gap around t = 10 s.
- **Height:** **3.05 H at the street centre** (7 strings, 2.86-3.27, f-independent). The strings rise to ~3.6-3.9 H
  where they meet the walls, so the sag is ~0.6 H (low confidence). Each string is one catenary across the
  street, wall to wall, roughly perpendicular to it. Dark brown rope, ~0.015 H thick (visual).
- **Flags:** triangles **~0.30 H wide x 0.32 H drop**, ~0.55 H centre to centre, so ~9 flags per string. Colours
  cycle (backlit against the sky): salmon `#AE6F66`, sage `#9BA399`, cream-khaki `#ACAC9C`, peach `#C1A087`.
  The old breakdown's "dusty blue" is sage-grey in this clip.
- **Lanterns:** capsule-shaped paper lanterns (cylinder with rounded ends, a dark cap and a bottom ring),
  **~0.34 W x 0.37 H**. Centres at **h ~2.7 H** (2.56-2.97), hanging ~0.3-0.4 H below the rope on a short cord.
  Mostly near the string ends at |d| 1.2-2.6, about 1-2 per string. Glow `#E4BB86`, with a warm halo where they
  overlap the sky.
- **Motion:** after fitting a static point to each of 5 tracked lanterns, the residuals are 1-3 px. They are the
  same on all lanterns in the same window, so they come from camera yaw, not sway. **Lantern sway < 0.01-0.02 H.**
  Flags show no visible flutter. Static, or a very gentle sway (<= 0.02 H, period 2-3 s), matches the clip.

## 5. Walker (owner: walker)

Crops: `crops_walker.jpg`. 24 fps strips: `motion_walker_t7.0-9.0s_24fps.jpg` (12 per row) and
`motion_full_t7.0-9.0s_24fps.jpg`.

- **Speed** 0.90 H/s (section 0). **Cadence 2.76 steps/s** (8.70 frames per step); **gait cycle 0.725 s**
  (17.4 frames). Step length 0.33 H.
- **Bob +/-0.024 H** at the step frequency. **Side sway +/-0.026 H** at the gait-cycle frequency. The camera does not
  bob or shake (far-street patches move < 0.6 px rms), so all of this is the walker's own motion.
- Slow lateral wander +/-0.05 H. The walker stays ~0.14 H right of the camera path, about 0.3 H right of the
  carriageway centre.
- **Ear flaps:** span **0.87 H** tip to tip (+/-0.02); tips at **0.40 H** above the ground, 0.40-0.45 H out from
  the hood centre. They barely move: tips +/-0.02 H, about +/-2.5 deg, loosely anti-phase with the bob and lagging
  it by ~3 frames. The old breakdown's ~10 deg is too much.
- **Parts** (verified on frames): a big teal felt hood dome with a centre seam and a small back point; long ear
  flaps; small orange horn nubs at the hood sides; a red knitted scarf with a back panel ending in a pom-pom
  fringe; a cream tunic; a brown satchel and mitts; short dark teal legs; chunky yellow boots.
- **Colours** (rendered, class masks over 21 frames): hood and flaps `#366470` (lit `#4A7785`, shade `#294E56`);
  scarf `#963B26`; boots `#A3662E` (highlight `#C88A45`); mitts and satchel `#65311E`; legs `#263B36`; tunic
  cream, `#B38464` in shade.

## 6. Camera, light and atmosphere (owner: lead)

- **Camera:** height **0.895 H**; level (pitch < 0.3 deg); zero roll. Vertical FOV **~53 deg** (f ~700 px of 704
  rows; low confidence, 45-60 deg). It sits **~2.0 H** behind the walker's feet (2.9e-3 * f) and 0.15 H right of
  the carriageway centre. The dolly is smooth at constant speed, with no bob, sway or shake. Heading follows the
  street's gentle bends: the travel direction sits at x = 620 (558-657 in 2 s windows), slightly left of the
  image centre.
- **Sun:** low warm sun, **ahead and to the right** (~25-35 deg elevation, low confidence). The left facades are
  sunlit, the right facades are in shade, shadows on the left wall fall back toward the camera, and the far street
  glows.
- **Shadows:** warm brown-grey, never black. Sun to shade on cobbles is ~2.3x in luma (`#D7AA7E` vs `#71635B`).
- **Sky:** cyan `#9EC6D5` at the top, a few soft cream clouds. Haze down the street goes to a cream-pink glow,
  `#E0CFC1` at the vanishing point.
- **Grade:** warm (mean R-B = +39), moderate saturation (mean HSV S = 0.40), lifted blacks (p0.5 `#241508`,
  luma p1 = 28), soft whites (p99.5 `#EED9D9`, luma p99 = 210). Mild bloom on lanterns and the bright far street.
  Distant houses are softly blurred.

## 7. Over time: what changes, and what a generator should not copy

- **The clip loops on itself.** Frame 479 matches frame 0 (mean abs diff 5.5 against ~9 between neighbouring
  frames). The last ~0.3 s *morphs* back to the opening street, so the clip covers ~18 H of street at 0.9 H/s. A
  generator should make a consistent street and not copy the morph.
- **Each side has its own rhythm:** narrower, busier houses on the shaded right, with more barrels, pots,
  ladders and signs; wider houses on the sunlit left, with awnings and ivy. This is clip content, not a rule;
  expose it as density per side.
- **AI drift:** near objects stay stable for ~3 s, but facades reshape slightly while they are in view (window and
  shutter positions slide, flower boxes change shape). Feet slide on the ground. Distant houses look denser and
  taller than near ones. Don't copy any of this; it is not the generator's job.
- **Strings:** irregular spacing (1.5-4.5 H), and far strings carry more lanterns than near ones. A generator
  should use a mean spacing of ~2.6 H with about +/-40% jitter.

## 8. Sheets legend (`reference/sheets/`)

| File | Content |
|---|---|
| `contact_00.0-09.5s_every0.5s.jpg`, `contact_10.0-20.0s_every0.5s.jpg` | one frame every 0.5 s, read left to right, top to bottom (the 2nd sheet ends with 20.0 s = 0 s) |
| `slit_left_x183.jpg`, `slit_left_x328.jpg`, `slit_right_x912.jpg`, `slit_right_x1057.jpg` | unrolled facades over the whole clip (section 0) |
| `slit_overhead_x640.jpg` | overhead column over time: bunting strings rise out of the top; the walker's hood bob shows at the bottom |
| `crops_props.jpg` | window box; pots; barrel pair; green-white awning; peach-white awning; bread sign; round sign + lanterns; wall lantern + ivy door; ladder; ivy + lantern + arched door |
| `crops_houses.jpg` | left near house (jetty corbels, deep window); left timber frame + shutters + awning; right orange house with arched door; right bread-sign house; right sage house with round sign; far street with slate roofs and spire |
| `crops_bunting.jpg` | bunting at t = 0, 7, 10, 13, 16, 19 s |
| `crops_walker.jpg` | walker at t = 0, 5, 7, 10, 13, 15, 17, 19 s |
| `crops_road.jpg` | road edges, left and right, at t = 7 and 10 s |
| `motion_walker_t7.0-9.0s_24fps.jpg`, `motion_full_t7.0-9.0s_24fps.jpg` | every frame for 2 s (48 frames) |

## 9. Corrections to the Video2GLSL breakdown (`shader-skills/prompts/village-loop/REFERENCE.md`)

1. **Cross-section:** it lists cobbles, curb and grass verge, 4 H curb to curb, 6 H wall to wall. Measured: five
   bands (cobbles, inner grass strip, curb, cobbled sidewalk, grass verge), ~3.0 H between curb faces and
   ~5.1 H wall to wall.
2. **Camera bob and sway** (+/-8 px at 2 Hz, +/-13 px at 1 Hz, "not locked to the steps"): far-scene patches show
   no shake (< 0.6 px). The +/-8 px and +/-9 px motions are the **walker's** bob (2.76 Hz) and sway (1.38 Hz),
   locked to the gait.
3. **Eye height:** 0.97 and 0.9 H are both quoted; measured 0.895 H. **Horizon:** y ~365 is the far road. The
   ground-plane horizon is **355**.
4. **Ear-flap amplitude:** ~10 deg quoted; measured ~2.5 deg (+/-0.02 H at the tips).
5. **Flag size:** 0.2 H quoted; measured 0.30 x 0.32 H. **Lantern size:** 0.3 quoted; measured 0.34 x 0.37 H,
   and the lanterns are capsule-shaped, not round. **String spacing:** 3-5 H quoted; measured ~2.6 H mean.
6. **Colours:** the boot colour `#E8A030` is a highlight (median `#A3662E`). The "blue-white" awning reads
   green-grey and cream, and the "dusty blue" flags are sage. The other palette entries roughly agree.
7. **Correct in the old breakdown:** the loop (frame 479 matches frame 0), 2.8 steps/s with a ~17-frame gait
   cycle, 0.9 H/s, barrel and pot sizes, ground-floor height of ~2 H, sun ahead-right.
