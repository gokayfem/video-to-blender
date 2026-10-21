# Animation and Simulation

Motion in a node system is either **analytic** (a closed-form function of a `Time` input, valid at any frame in
any order) or **simulated** (a simulation zone that steps state forward frame by frame). Choose deliberately: it
decides cost, scrubbing, baking and how the effect can be verified.

## Contents

- [The decision rule](#the-decision-rule)
- [Time plumbing](#time-plumbing)
- [Analytic recipes](#analytic-recipes)
- [Loops](#loops)
- [Simulation zones in 5.x](#simulation-zones-in-5x)
- [Simulation recipes](#simulation-recipes)
- [Verifying motion numerically](#verifying-motion-numerically)

## The decision rule

| The motion needs... | Use | Examples |
|---|---|---|
| **state**: the present depends on the history (where it went, what it hit) | simulation | growth that spreads, a trail, a rope that settles after a hit |
| **interaction**: pieces react to each other or to geometry that moves | simulation | collisions, pushing, piling up, avoidance |
| **accumulation**: something builds up and stays | simulation | snow settling, leaves landing and staying, footprints, wear |
| periodic or quasi-periodic motion | analytic | walk cycles, swinging signs, wind sway, bobbing |
| a function of a driven quantity (distance walked, a path, a keyed speed) | analytic | planted feet, wheels rolling, a camera on a path |
| independent particles with lifetimes | analytic | falling leaves that vanish, sparks, rain, bubbles |
| a damped response to known events | analytic | flaps lagging the body, a sign ringing after a gust |

If both fit, choose analytic: it scrubs, renders any frame alone, needs no bake, and can be tested at any time.
State the choice and the reason in the deliverable ("no simulation zone: the reference shows nothing that needs
stored state" is a valid finding; the storybook street is fully analytic).

## Time plumbing

- Only the top (modifier) group reads **Scene Time** (`GeometryNodeInputSceneTime`, `Seconds`). Every part takes a
  `Time` input (FLOAT, seconds). Parts are then testable at any time, retimable and reusable.
- Top group: `time = Scene Seconds * Time Scale + Time Offset` (`Time Offset` subtype `TIME_ABSOLUTE`).
- Per-piece time: `t_i = Time + offset_i` with `offset_i` hashed from the piece id, so pieces do not move in sync.
- Anything outside Geometry Nodes that must agree (a camera rig on a path) reads the same modifier inputs through a
  driver (`build.py` in storybook-street): `offset = (Walk Start + Walk Speed * (frame/fps * Time Scale +
  Time Offset) + along) / curve_length`. Drivers in background mode update only for `bpy.context.window.scene`.

## Analytic recipes

**Integrated phase.** Never write `phase = speed * t` when speed changes: changing speed then jumps the phase.
Integrate distance, then derive phase from distance:

```text
s(t)     = s0 + ∫ v dt                (piecewise: constant segments add v_k * Δt_k;
                                        a linear ramp from v0 to v1 over T adds v0 τ + (v1 − v0) τ² / (2T))
phase(t) = s(t) / stride              (gait cycles; feet are locked to distance walked)
```

**Planted feet.** For each foot with phase offset `o` (0 left, 0.5 right): `u = phase − o`, cycle `k = floor(u)`,
fraction `f = u − k`. During stance (`f < STANCE`) the foot sits at a fixed arc length `plant = (k + o + STANCE/2)
* stride` (plus a toe offset), placed through the curve frame, so it is fixed in the world on any curve. During
swing, travel from this plant to the next with smootherstep `e = w³(6w² − 15w + 10)` (zero velocity at both ends),
lift `∝ w(1 − w)²`. See `SS Walker Step` in `prompts/storybook-street/street/groups/walker.py`.

**Body motion** from the same phase: bob `−A cos(4π phase)` (twice per cycle), sway `cos(2π phase)` over the
stance foot, arm swing opposite to the legs, twist with the arms.

**Springs (secondary motion).** A damped spring with natural frequency `fn`, damping ratio `ζ`, driven by a sine
at `fd`, has a closed-form steady state:

```text
r = fd / fn
gain = 1 / sqrt((1 − r²)² + (2ζr)²)
lag  = atan2(2ζr, 1 − r²)
response = A * gain * cos(drive_phase − lag)
```

Flaps, scarves, antennae and hanging bags lag the body and overshoot near resonance. For a single event at time
`t0` (a landing, a gust onset), add the impulse response
`A e^(−ζω(t − t0)) sin(ω_d (t − t0))` for `t > t0`, `ω = 2π fn`, `ω_d = ω sqrt(1 − ζ²)`.

**Wind.** A gust envelope: slow noise in time, shifted by position so gusts travel (`noise(t − lag − s / gust_speed)`),
mapped to `max(1 + gust * n, 0)`. Each part responds with the lagged envelope (steady deflection) plus a ring at its
own pendulum period scaled by the envelope. At small angles this linear response is accurate and needs no state.
See `SS Bunting Wind` in storybook-street; the `motion` library module has reusable versions.

**Pendulum / sign swing.** `angle = A (sin(2π t / T + φ_i) + 0.15 sin(4π t / T + 1.3))`, `T = 2π sqrt(L / g)`,
`φ_i` hashed per piece.

**Ballistic.** `z = z0 + v0 τ − g τ² / 2`; bounces lose height by restitution `e < 1` per contact; spin matches
distance rolled (`angle = distance / radius`).

**Independent particles with lifetimes** (falling leaves, sparks): `age = fract((t + φ_i) / life) * life`,
position = spawn_i + v_i age + sway(age), fade or scale in and out near the ends of life so recycling never pops.

**Wheels, tracks, conveyor textures**: angle or UV offset = distance / radius, from the same integrated `s(t)`.

## Loops

A loop of length `L` seconds is seamless when every periodic term completes a whole number of cycles in `L`:

- choose periods `L / n`; derive stride or speed from that instead of the reverse;
- noise that must loop: sample 4D noise on a circle in two dimensions, `(cos 2πt/L, sin 2πt/L) * radius`, or
  use the W input of 4D noise with a periodic coordinate;
- a translating camera or walker loops only if the world repeats: use a closed path, or a periodic layout whose
  period matches `speed * L`;
- verify: frame 1 and frame `L*fps + 1` are identical (image difference 0, or attribute difference below 1e-5).

## Simulation zones in 5.x

```python
zin, zout = g.zone("SIMULATION", [("VECTOR", "Velocity")])
g.connect(points, zin.i("Geometry"))                  # initial state, read on the start frame only
g.connect(initial_velocity, zin.i("Velocity"))
dt = zin["Delta Time"]                                # 0 on the start frame, which still runs one step
...                                                   # update fields with dt
g.connect(new_geo, zout.i("Geometry")); g.connect(new_vel, zout.i("Velocity"))
out = zout["Geometry"]
```

Behaviour, verified in Blender 5.2.2 (background, 24 fps):

| Fact | Detail |
|---|---|
| Delta Time | seconds per frame, 1/fps (0.041667 at 24 fps). Use it for every rate so the result does not depend on fps |
| First frame | the start frame already runs **one step with Delta Time 0**: the zone body is evaluated on the initial state and its output is shown. Anything scaled by Delta Time does not move, but per-step events do happen once (a step counter reads 1, a trail appends a point, `Random(id, step)` branches, Duplicate/Delete per step). Gate such events with `Delta Time > 0`, or connect `Delta Time < 1e-9` to `zout.i("Skip")` to show the untouched initial state on the start frame (test: `tests/test_motion.py::test_simulation_first_frame_runs_a_zero_dt_step`) |
| Start frame | `scene.frame_start`, or `scene.use_custom_simulation_range` + `simulation_frame_start/end`. Before the start the initial state is shown |
| Returning to the start frame | resets the simulation |
| **Skipping frames** | jumping from frame 3 to 10 without a cache advanced the state by **one** step, not seven. Scripts must step every frame in order from the start (`for f in range(start, end+1): scene.frame_set(f)`) or bake first |
| Cache | filled during playback (purple line in the timeline); edits upstream invalidate it |
| Bake | `mod.bakes[i]` per zone; after `geometry_node_bake_single` every frame is exact in any order (verified) |
| Skip | `zout.i("Skip")` true passes the state through unchanged (pause a simulation) |
| Inputs | nodes linked into the zone input are evaluated once at the start; nodes inside are evaluated every step |

Rules:

- Render or hand off a simulation only baked. Say so in the deliverable, and say which controls need a re-bake.
- Keep the state small: the attributes you need, not the whole visual geometry. Build the visual mesh after the
  zone from the state (instancing leaves on a trail after the zone, not inside it).
- Stability: explicit integration of a spring needs `ω dt < ~0.5`. For stiff springs or constraints, substep with a
  repeat zone inside the simulation zone (`dt_sub = dt / n`).
- Seed every random choice inside the zone with the step (Scene Frame or an accumulated step counter) plus the id,
  or every step repeats the same choice.
- 5.2 adds an experimental physics system (Cloth and Hair Dynamics assets, an XPBD Solver node, colliders and
  effectors). Use it for cloth and hair that must collide; label it experimental; it is not wrapped by nodekit.

## Simulation recipes

**Growth over a mesh** (ivy, moss, lichen). State: tip points with `direction`, `age`, `alive`; a trail point
cloud. Each step: move tips by `speed * dt` along `direction` (blended toward the surface tangent and a noise
field), snap to the surface with Sample Nearest Surface, append the old tip positions to the trail (Join), branch:
duplicate tips where `Random Value(id, step) < rate * dt`, kill tips that age out or leave the surface. After the
zone: Points to Curves or Curve Line segments for stems, leaves instanced on the trail by age. Template:
`growth-sim`.

**Spring settle** (a sign hit by a gust, a curtain). State: position, velocity per point.
`v += (−k (x − rest) − c v + F) dt; x += v dt` (semi-implicit Euler), pinned points keep `x = rest`.

**Accumulation** (snow, leaves that land). Analytic fall until contact (Raycast down from each flake); on contact,
mark `landed` and store the position in the state; landed items stay.

**Verlet rope.** State: positions and previous positions on a curve; each step `x' = 2x − x_prev + a dt²`, then a
repeat zone of distance-constraint passes along the curve.

## Verifying motion numerically

Judge motion as numbers and sequences, never one still.

- **Sample attributes over time.** Store a probe attribute (`nk_probe` on the foot, root, a sign tip) and read it
  from the evaluated mesh at every frame:

```python
vals = []
for f in range(1, 49):
    sc.frame_set(f)
    me = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    vals.append([v.co.copy() for v, p in zip(me.vertices, me.attributes["nk_probe"].data) if p.value > 0.5])
```

- **Planted feet**: during stance the foot's world position changes by less than 1e-4 units per frame.
- **Continuity**: first differences (velocity) have no spikes; second differences (acceleration) spike only at
  physical events (contact, takeoff). Flag any jump above 3× the median.
- **Phase continuity across speed changes**: phase is monotonic and its derivative equals speed / stride.
- **Springs settle**: after a step input the response decays by `e^(−ζω t)`; check the overshoot and settle time.
- **Bounded wind**: maximum angle over a long run stays within the stated amplitude.
- **Loops**: frame 1 equals frame `L*fps + 1`.
- **Simulation determinism**: bake twice, compare states at several frames (identical); step without a bake from
  the start frame and compare with the bake.
- Put these checks in a property test (`tests/test_motion.py` pattern) or a project script, and report the
  numbers.
