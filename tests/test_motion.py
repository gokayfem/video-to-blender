import math
import numpy as np
import nkt
from library.motion import damped_spring, gait_step, wind_gust, pendulum_sway, time_remap, flicker


def _spring_ode(fn, zeta, amp, t_end, dt=1e-4):
    """RK4 of x'' + 2 zeta wn x' + wn^2 x = wn^2 amp from rest; returns (times, x)."""
    wn = 2 * math.pi * fn
    def acc(x, v):
        return wn * wn * (amp - x) - 2 * zeta * wn * v
    n = int(round(t_end / dt))
    xs, x, v = np.zeros(n + 1), 0.0, 0.0
    for i in range(n):
        k1x, k1v = v, acc(x, v)
        k2x, k2v = v + 0.5 * dt * k1v, acc(x + 0.5 * dt * k1x, v + 0.5 * dt * k1v)
        k3x, k3v = v + 0.5 * dt * k2v, acc(x + 0.5 * dt * k2x, v + 0.5 * dt * k2v)
        k4x, k4v = v + dt * k3v, acc(x + dt * k3x, v + dt * k3v)
        x += dt / 6 * (k1x + 2 * k2x + 2 * k3x + k4x)
        v += dt / 6 * (k1v + 2 * k2v + 2 * k3v + k4v)
        xs[i + 1] = x
    return np.arange(n + 1) * dt, xs


def test_spring_gain_and_lag_match_formula():
    """Gain, lag and the periodic response equal the analytic steady state at several drive frequencies."""
    fn, zeta, amp, ph = 2.0, 0.25, 0.7, 0.4
    times = np.linspace(0.0, 3.0, 13)
    for fd in (0.5, 1.9, 2.0, 5.0):
        out = nkt.field(damped_spring(), {"Drive Frequency": fd, "Natural Frequency": fn, "Damping": zeta,
                                          "Amplitude": amp, "Phase": ph},
                        per_point={"Time": times}, outputs={"Response": "FLOAT", "Gain": "FLOAT", "Lag": "FLOAT"})
        r = fd / fn
        gain = 1 / math.sqrt((1 - r * r) ** 2 + (2 * zeta * r) ** 2)
        lag = math.atan2(2 * zeta * r, 1 - r * r)
        assert nkt.close(out["Gain"], gain, 1e-4 * gain), (fd, out["Gain"][0], gain)
        assert nkt.close(out["Lag"], lag, 1e-5), (fd, out["Lag"][0], lag)
        want = amp * gain * np.cos(2 * math.pi * fd * times + ph - lag)
        assert nkt.close(out["Response"], want, 2e-4 * max(1.0, gain)), (fd, out["Response"], want)


def test_spring_step_matches_ode_and_settles():
    """Step response equals an RK4 integration (under-, critically and overdamped) and settles to Amplitude."""
    fn, amp, start = 1.5, 0.8, 0.5
    times = np.linspace(0.0, 6.0, 61)
    for zeta in (0.2, 1.0, 2.5):
        out = nkt.field(damped_spring(), {"Natural Frequency": fn, "Damping": zeta, "Amplitude": amp,
                                          "Step Start": start},
                        per_point={"Time": times}, outputs={"Step Response": "FLOAT"})["Step Response"]
        ts, xs = _spring_ode(fn, zeta, amp, 6.0 - start)
        want = np.where(times < start, 0.0, np.interp(np.maximum(times - start, 0.0), ts, xs))
        assert nkt.close(out, want, 2e-3), (zeta, np.max(np.abs(out - want)))
        assert abs(out[-1] - amp) < 0.01 * amp, (zeta, out[-1])
    over = nkt.field(damped_spring(), {"Natural Frequency": fn, "Damping": 0.2, "Amplitude": amp},
                     per_point={"Time": np.linspace(0, 2, 81)}, outputs={"Step Response": "FLOAT"})
    assert over["Step Response"].max() > 1.3 * amp            # light damping overshoots


def _gait(times, **inputs):
    base = {"Stride": 1.2, "Stance": 0.6, "Lift": 0.1, "Offset": 0.25}
    base.update(inputs)
    per = {"Time": times}
    if isinstance(base.get("Distance"), np.ndarray):
        per["Distance"] = base.pop("Distance")
    return nkt.field(gait_step(), base, per_point=per,
                     outputs={"Foot Distance": "FLOAT", "Lift": "FLOAT", "Swing": "FLOAT", "Phase": "FLOAT",
                              "Stance Weight": "FLOAT", "Foot Offset": "FLOAT"})


def test_gait_planted_foot_does_not_slide():
    """While a foot is in stance its distance along the path is constant (zero slide), and it is on the ground."""
    times = np.linspace(0.0, 6.0, 601)
    out = _gait(times, Speed=0.9)
    stance = out["Swing"] <= 0.0
    k = np.floor(out["Phase"] - 0.25)
    assert stance.sum() > 200 and (~stance).sum() > 100
    for cyc in np.unique(k[stance]):
        sel = stance & (k == cyc)
        assert np.ptp(out["Foot Distance"][sel]) < 1e-4, (cyc, np.ptp(out["Foot Distance"][sel]))
    assert nkt.close(out["Lift"][stance], 0.0, 1e-6) and nkt.close(out["Stance Weight"][stance], 1.0, 1e-6)
    # each plant is one stride further on, and the foot keeps up with the body on average
    plants = [out["Foot Distance"][stance & (k == c)][0] for c in np.unique(k[stance])]
    assert nkt.close(np.diff(plants), 1.2, 1e-4)
    assert abs(np.mean(out["Foot Offset"])) < 0.2


def test_gait_swing_zero_velocity_at_ends():
    """Foot travel and lift have zero velocity at lift-off and touch-down (finite differences), lift peaks at
    Lift mid-swing."""
    stride, stance, speed = 1.2, 0.6, 1.0
    t_swing = (1 - stance) * stride / speed
    # this leg (offset 0.25) lifts off when phase - 0.25 = stance, i.e. d = (0.25 + 0.6) * stride
    t0 = (0.25 + stance) * stride / speed
    h = 1e-3
    probe = np.array([t0, t0 + h, t0 + t_swing - h, t0 + t_swing, t0 + 0.5 * t_swing])
    out = _gait(probe, Speed=speed)
    fd, lift = out["Foot Distance"], out["Lift"]
    v_start, v_end = (fd[1] - fd[0]) / h, (fd[3] - fd[2]) / h
    mean_v = stride / t_swing
    assert abs(v_start) < 0.01 * mean_v and abs(v_end) < 0.01 * mean_v, (v_start, v_end, mean_v)
    assert abs((lift[1] - lift[0]) / h) < 0.01 and abs((lift[3] - lift[2]) / h) < 0.01
    assert abs(lift[4] - 0.1) < 1e-4
    assert abs(fd[3] - fd[0] - stride) < 1e-4


def test_gait_phase_continuous_when_speed_changes():
    """With an integrated distance (speed 0.6 then 1.8 from t = 2 s) phase and foot distance stay continuous."""
    times = np.linspace(0.0, 4.0, 2001)
    v1, v2, tc = 0.6, 1.8, 2.0
    dist = np.where(times < tc, v1 * times, v1 * tc + v2 * (times - tc))
    out = _gait(times, Speed=0.0, Distance=dist)
    dt = times[1] - times[0]
    assert np.max(np.abs(np.diff(out["Phase"]))) <= v2 * dt / 1.2 * 1.01
    max_foot_speed = 1.875 / (1 - 0.6) * v2
    assert np.max(np.abs(np.diff(out["Foot Distance"]))) <= max_foot_speed * dt * 1.05
    assert np.all(np.diff(out["Foot Distance"]) >= -1e-5)        # feet never step backward


def test_wind_gust_bounded_continuous_travelling():
    """Gusts stay in [0, Strength], change smoothly, and arrive x / speed later further along."""
    times = np.linspace(0.0, 60.0, 3001)
    for seed, pos in ((0, 0.0), (3, 7.0), (11, -20.0)):
        out = nkt.field(wind_gust(), {"Strength": 2.0, "Gustiness": 1.0, "Gust Period": 3.0, "Seed": seed,
                                      "Position": pos},
                        per_point={"Time": times}, outputs={"Gust": "FLOAT", "Envelope": "FLOAT"})
        g = out["Gust"]
        assert g.min() >= -1e-6 and g.max() <= 2.0 + 1e-6, (g.min(), g.max())
        assert np.ptp(g) > 0.8, np.ptp(g)                       # it really comes and goes
        slope = np.max(np.abs(np.diff(g))) / (times[1] - times[0])
        assert slope * 3.0 / 2.0 < 6.0, slope                   # no faster than ~calm-to-full in a sixth of a period
    a = nkt.field(wind_gust(), {"Travel Speed": 4.0}, per_point={"Time": times, "Position": np.zeros_like(times)},
                  outputs={"Gust": "FLOAT"})["Gust"]
    b = nkt.field(wind_gust(), {"Travel Speed": 4.0},
                  per_point={"Time": times + 2.5, "Position": np.full_like(times, 10.0)}, outputs={"Gust": "FLOAT"})
    assert nkt.close(a, b["Gust"], 1e-4)
    steady = nkt.field(wind_gust(), {"Gustiness": 0.0, "Strength": 1.5}, per_point={"Time": times[:50]},
                       outputs={"Gust": "FLOAT"})["Gust"]
    assert nkt.close(steady, 1.5, 1e-6)


def test_pendulum_period_and_bound():
    """Period is 2 pi sqrt(L / g), the sway repeats with it under steady wind, and stays within its bound."""
    L, wind = 0.6, 1.4
    T = 2 * math.pi * math.sqrt(L / 9.81)
    times = np.linspace(0.0, 5.0, 201)
    ins = {"Length": L, "Wind": wind, "Lean": 0.03, "Swing": 0.05, "Wobble": 0.15, "Phase": 0.7}
    a = nkt.field(pendulum_sway(), ins, per_point={"Time": times}, outputs={"Angle": "FLOAT", "Period": "FLOAT"})
    b = nkt.field(pendulum_sway(), ins, per_point={"Time": times + T}, outputs={"Angle": "FLOAT"})
    assert nkt.close(a["Period"], T, 1e-5)
    assert nkt.close(a["Angle"], b["Angle"], 2e-5)
    assert np.max(np.abs(a["Angle"])) <= wind * (0.03 + 0.05 * 1.15) + 1e-6
    assert np.ptp(a["Angle"]) > 0.1


def test_time_remap_loops_exactly():
    """f(t) == f(t + L) for a loop, f(t) == f(t + 2L) for ping-pong, endpoints mirrored, identity without a loop."""
    L = 2.5
    t = np.linspace(0.0, 20.0, 401) + 0.013
    for ease in (0.0, 1.0):
        ins = {"Loop Length": L, "Ease": ease, "Offset": 0.3, "Speed": 1.0}
        a = nkt.field(time_remap(), ins, per_point={"Time": t}, outputs={"Time": "FLOAT", "Factor": "FLOAT"})
        b = nkt.field(time_remap(), ins, per_point={"Time": t + L}, outputs={"Time": "FLOAT"})
        assert nkt.close(a["Time"], b["Time"], 2e-4), np.max(np.abs(a["Time"] - b["Time"]))
        assert a["Time"].min() >= 0.0 and a["Time"].max() <= L + 1e-5
    ins = {"Loop Length": L, "Ping Pong": True, "Ease": 0.5}
    a = nkt.field(time_remap(), ins, per_point={"Time": t}, outputs={"Time": "FLOAT"})["Time"]
    b = nkt.field(time_remap(), ins, per_point={"Time": t + 2 * L}, outputs={"Time": "FLOAT"})["Time"]
    c = nkt.field(time_remap(), ins, per_point={"Time": 2 * L - t}, outputs={"Time": "FLOAT"})["Time"]
    assert nkt.close(a, b, 2e-4) and nkt.close(a, c, 2e-4)
    assert np.max(np.abs(np.diff(a))) < 0.1                    # ping-pong has no jump
    free = nkt.field(time_remap(), {"Speed": 2.0, "Offset": 1.0}, per_point={"Time": t},
                     outputs={"Time": "FLOAT"})["Time"]
    assert nkt.close(free, (t - 1.0) * 2.0, 1e-4)


def test_flicker_bounded_and_smooth():
    """Flicker stays in [Strength (1 - Amount), Strength], varies, and changes smoothly at 1 ms steps."""
    times = np.linspace(0.0, 20.0, 20001)
    for seed in (0, 5):
        v = nkt.field(flicker(), {"Strength": 3.0, "Amount": 0.4, "Rate": 2.0, "Seed": seed},
                      per_point={"Time": times}, outputs={"Value": "FLOAT"})["Value"]
        assert v.min() >= 3.0 * 0.6 - 1e-5 and v.max() <= 3.0 + 1e-5, (v.min(), v.max())
        assert np.ptp(v) > 0.4
        assert np.max(np.abs(np.diff(v))) < 0.03, np.max(np.abs(np.diff(v)))


# ---- Blender behaviour the simulation recipes rely on (references/animation-and-simulation.md) -----------------
def _sim_counter(skip_first):
    """A one-point simulation counting steps and summing Delta Time; Skip on dt == 0 when skip_first."""
    import bpy
    from nodekit.graph import Graph
    w = Graph(nkt._name("NKT Sim"), description="simulation zone probe", modifier=True)
    w.input("Geometry", "GEOMETRY", desc="ignored")
    zin, zout = w.zone("SIMULATION", [("FLOAT", "Steps"), ("FLOAT", "T"), ("FLOAT", "DT")])
    w.connect(w.node("GeometryNodePoints", Count=1)["Points"], zin.i("Geometry"))
    w.connect(zin["Geometry"], zout.i("Geometry"))
    w.connect(w.math("ADD", zin["Steps"], 1.0), zout.i("Steps"))
    w.connect(w.math("ADD", zin["T"], zin["Delta Time"]), zout.i("T"))
    w.connect(zin["Delta Time"], zout.i("DT"))
    if skip_first:
        w.connect(w.math("LESS_THAN", zin["Delta Time"], 1e-9), zout.i("Skip"))
    cur = w.node("GeometryNodePointsToVertices", Points=zout["Geometry"])["Mesh"]
    for n in ("Steps", "T", "DT"):
        cur = w.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                     Geometry=cur, Name=n, Value=zout[n])["Geometry"]
    w.output("Geometry", "GEOMETRY", cur)
    w.finish()
    ob = bpy.data.objects.new(w.nt.name, bpy.data.meshes.new(w.nt.name))
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("nkt", "NODES").node_group = w.nt
    return ob


def test_simulation_first_frame_runs_a_zero_dt_step():
    """Blender 5.2: the start frame already runs one step with Delta Time 0 (so a step counter reads 1 there and
    the state sums dt exactly); Skip when Delta Time is 0 makes the start frame show the initial state."""
    import bpy
    sc = bpy.context.scene
    sc.render.fps, sc.frame_start = 24, 1
    ob = _sim_counter(skip_first=False)
    got = []
    for f in (1, 2, 3, 4):
        sc.frame_set(f)
        a = nkt.attrs(ob, ["Steps", "T", "DT"])
        got.append((a["Steps"][0], a["T"][0], a["DT"][0]))
    assert nkt.close([s for s, _, _ in got], [1, 2, 3, 4]), got            # a step on frame 1 too
    assert nkt.close([d for _, _, d in got], [0, 1 / 24, 1 / 24, 1 / 24], 1e-6), got
    assert nkt.close([t for _, t, _ in got], [0, 1 / 24, 2 / 24, 3 / 24], 1e-6), got
    sc.frame_set(1)
    ob2 = _sim_counter(skip_first=True)
    steps = []
    for f in (1, 2, 3):
        sc.frame_set(f)
        steps.append(nkt.attrs(ob2, ["Steps"])["Steps"][0])
    assert nkt.close(steps, [0, 1, 2]), steps                              # initial state on frame 1
