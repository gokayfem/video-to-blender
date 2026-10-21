"""SS Walker: the hooded storybook walker seen from behind, built and animated entirely in Geometry Nodes.

Structure (each part is a sub-group with its own pivot, modelled at rest in the body frame: +X forward, +Y left,
+Z up, origin on the ground under the hips, 1 unit = H = the walker's height):

    SS Walker Rig      Time -> s(t), gait phase, joint values: root and feet on the path (SS Street Point),
                       hips, bob, sway, twist, arm swing and the spring-damped secondary angles
    SS Walker Step     one foot's gait: plant point along s, swing arc, heel-off pitch (used twice)
    SS Walker Spring   steady-state response of a damped spring to a sinusoidal drive (gain + phase lag)
    SS Walker Hood     felt dome, teardrop pad (ray-projected onto the dome), seam, orange horn nubs
    SS Walker Flap     one ear flap, pivot at its root on the hood
    SS Walker Tunic    lathed coat with flared hem, belt
    SS Walker Scarf    knitted collar, back panel hinged at the collar, pom-poms
    SS Walker Arm      sleeve + mitten, pivot at the shoulder
    SS Walker Satchel  leather pouch, pivot at the strap on the left hip
    SS Walker Leg      boot at its foot transform (pivot at the toe), leg tube up to the hip

Gait: phase = s / Stride, so the feet are locked to distance walked; a planted foot sits at a fixed arc length,
fixed in the world while planted. Motion maths follows the shader-skills village-loop character
(src/40-character.glsl), translated into node fields.
"""
import math
from nodekit.graph import Graph
from street.groups import frame
from street.materials import walker as mats

NAME = "SS Walker"

# ---- gait constants (H units) -------------------------------------------------------------------------------
STANCE = 0.56          # fraction of the gait cycle each foot is planted (> 0.5: a walk with double support)
TOE = 0.08             # toe pivot ahead of the boot's middle
FOOT_X = 0.07          # lateral foot spacing from the centre line
STEP_LIFT = 0.085      # peak swing height of a boot
HEEL_OFF = 0.8         # boot pitch (rad, heel up) at toe-off
HIP = 0.2              # hip height
HIP_X = 0.065          # hip half-spacing
LEAN = 0.07            # forward lean of the upper body (rad)
SWAY = 0.026           # lateral sway amplitude (gait rate)
TWIST = 0.07           # shoulder twist (rad)
ARM_SWING = 0.55       # arm swing amplitude (rad)
NECK = 0.475           # collar height
TEAR_Y = 0.695         # teardrop point height


def srgb(h):
    v = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in v) + (1.0,)


PAL = {"Hood": "#2C7072", "Scarf": "#C24A35", "Tunic": "#DCC6A2", "Boots": "#E8A030", "Mittens": "#6A3A28",
       "Satchel": "#8A5030"}
LEGS, BELT, HORN, POM = srgb("#2E6A66"), srgb("#5C3820"), srgb("#E0703A"), srgb("#EDBBA4")


# ---- small helpers over Graph --------------------------------------------------------------------------------
def xyz(g, v):
    s = g.separate(v)
    return s["X"], s["Y"], s["Z"]


def pos(g):
    return g.node("GeometryNodeInputPosition")["Position"]


def euler(g, x=0.0, y=0.0, z=0.0):
    return g.node("FunctionNodeEulerToRotation", Euler=g.combine(x, y, z))["Rotation"]


def xform(g, geo, t=None, r=None, s=None, label=None):
    return g.node("GeometryNodeTransform", label, Geometry=geo, Translation=t, Rotation=r, Scale=s)["Geometry"]


def sphere(g, seg=24, rings=12):
    return g.node("GeometryNodeMeshUVSphere", Segments=seg, Rings=rings, Radius=1.0)["Mesh"]


def ellipsoid(g, radii, center=(0, 0, 0), seg=24, rings=12, rot=None):
    return xform(g, sphere(g, seg, rings), t=center, r=rot, s=radii)


def set_pos(g, geo, p):
    return g.node("GeometryNodeSetPosition", Geometry=geo, Position=p)["Geometry"]


def smooth(g, geo, level=0):
    if level:
        geo = g.node("GeometryNodeSubdivisionSurface", Mesh=geo, Level=level)["Mesh"]
    return g.node("GeometryNodeSetShadeSmooth", Mesh=geo)["Mesh"]


def paint(g, geo, color, material, extra=None):
    """Tag a part for its material: ss_color tint, ss_local rest position (texture coordinates), material."""
    geo = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_COLOR", "domain": "POINT"},
                 Geometry=geo, Name="ss_color", Value=color)["Geometry"]
    geo = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT_VECTOR", "domain": "POINT"},
                 Geometry=geo, Name="ss_local", Value=pos(g))["Geometry"]
    for name, v in (extra or {}).items():
        geo = g.node("GeometryNodeStoreNamedAttribute", props={"data_type": "FLOAT", "domain": "POINT"},
                     Geometry=geo, Name=name, Value=v)["Geometry"]
    return g.node("GeometryNodeSetMaterial", Geometry=geo, Material=material)["Geometry"]


def join(g, *geos):
    j = g.node("GeometryNodeJoinGeometry")
    for x in reversed(geos):
        g.connect(x, j.i("Geometry"))
    return j["Geometry"]


def mirror(g, geo):
    """Mirror a left-side part to the right (Y -> -Y) and flip its faces so normals stay outward."""
    return g.node("GeometryNodeFlipFaces", Mesh=xform(g, geo, s=(1, -1, 1)))["Mesh"]


def smoothstep(g, e0, e1, x):
    return g.map_range(x, e0, e1, 0.0, 1.0, interp="SMOOTHSTEP")


def clamp(g, x, lo, hi):
    return g.math("MINIMUM", g.math("MAXIMUM", x, lo), hi)


def M(g, *ops):
    """Left-fold chain: M(g, a, ("MULTIPLY", b), ("ADD", c)) = a * b + c."""
    v = ops[0]
    for op, b in ops[1:]:
        v = g.math(op, v, b)
    return v


# ---- motion sub-groups ---------------------------------------------------------------------------------------
def build_spring():
    g = Graph("SS Walker Spring", description="Steady-state response of a damped spring driven by a sine: "
                                              "Amplitude * gain * cos(Phase - lag). Hanging parts bounce with "
                                              "the body, amplified near resonance and lagging behind it")
    ph = g.input("Phase", "FLOAT", 0.0, subtype="ANGLE", desc="Phase of the drive (radians)")
    fd = g.input("Drive Frequency", "FLOAT", 3.0, min=0.0, desc="Drive frequency in Hz (step or gait rate)")
    fn = g.input("Natural Frequency", "FLOAT", 3.0, min=0.05, desc="The part's own bounce frequency in Hz")
    zeta = g.input("Damping", "FLOAT", 0.3, min=0.01, max=2.0, desc="Damping ratio (low = springy overshoot)")
    amp = g.input("Amplitude", "FLOAT", 0.1, desc="Response amplitude before the spring's gain")
    with g.frame("Frequency ratio r = drive / natural"):
        r = g.math("DIVIDE", fd, fn)
        one_m = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", r, r))
        c = M(g, zeta, ("MULTIPLY", 2.0), ("MULTIPLY", r))
    with g.frame("Gain 1/sqrt((1-r^2)^2 + (2 zeta r)^2) and phase lag atan2(2 zeta r, 1-r^2)"):
        gain = g.math("INVERSE_SQRT", g.math("ADD", g.math("MULTIPLY", one_m, one_m), g.math("MULTIPLY", c, c)))
        lag = g.math("ARCTAN2", c, one_m)
    with g.frame("Response"):
        resp = M(g, g.math("COSINE", g.math("SUBTRACT", ph, lag)), ("MULTIPLY", gain), ("MULTIPLY", amp))
    g.output("Response", "FLOAT", resp)
    g.output("Lag", "FLOAT", lag)
    return g.finish()


def build_step():
    g = Graph("SS Walker Step", description="One foot's gait from the walk phase: planted at a fixed arc length "
                                            "during stance (heel lifts, toe stays), then swings to the next plant "
                                            "on a lifted arc with zero velocity at both ends")
    phase = g.input("Phase", "FLOAT", 0.0, desc="Gait phase in cycles (distance walked / Stride)")
    offset = g.input("Offset", "FLOAT", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                     desc="This foot's phase offset (0 left, 0.5 right)")
    stride = g.input("Stride", "FLOAT", 0.6, min=0.05, subtype="DISTANCE", desc="Distance walked per gait cycle")
    scale = g.input("Scale", "FLOAT", 1.0, min=0.01, desc="Walker scale (toe offset and lift)")
    with g.frame("Cycle k and fraction f of this foot"):
        u = g.math("SUBTRACT", phase, offset)
        k = g.math("FLOOR", u)
        f = g.math("SUBTRACT", u, k)
    with g.frame("Plant point: where the root is at this foot's mid-stance, plus the toe offset"):
        plant = M(g, k, ("ADD", offset), ("ADD", 0.5 * STANCE), ("MULTIPLY", stride))
        plant = g.math("ADD", plant, g.math("MULTIPLY", TOE, scale))
    with g.frame("Swing progress w (0 in stance) and smootherstep travel e"):
        w = clamp(g, g.math("DIVIDE", g.math("SUBTRACT", f, STANCE), 1.0 - STANCE), 0.0, 1.0)
        # e = w^3 (w (6w - 15) + 10)
        inner = M(g, w, ("MULTIPLY", 6.0), ("SUBTRACT", 15.0), ("MULTIPLY", w), ("ADD", 10.0))
        e = M(g, w, ("MULTIPLY", w), ("MULTIPLY", w), ("MULTIPLY", inner))
        length = g.math("ADD", plant, g.math("MULTIPLY", e, stride))
    with g.frame("Lift: heel flicks up early, peak at w = 1/3"):
        omw = g.math("SUBTRACT", 1.0, w)
        lift = M(g, w, ("MULTIPLY", omw), ("MULTIPLY", omw), ("MULTIPLY", STEP_LIFT * 6.75), ("MULTIPLY", scale))
    with g.frame("Pitch: heel rises late in stance, carries into swing, toe up before the plant"):
        h = smoothstep(g, STANCE - 0.22, STANCE, f)
        heel = M(g, h, ("MULTIPLY", h), ("MULTIPLY", HEEL_OFF))
        carry = M(g, omw, ("MULTIPLY", omw), ("MULTIPLY", g.math("MULTIPLY_ADD", w, 2.0, 1.0)))
        toe_up = M(g, w, ("MULTIPLY", w), ("MULTIPLY", omw))
        pitch = g.math("SUBTRACT", g.math("MULTIPLY", heel, carry), toe_up)
    g.output("Length", "FLOAT", length)
    g.output("Lift", "FLOAT", lift)
    g.output("Pitch", "FLOAT", pitch)
    g.output("Swing", "FLOAT", g.math("GREATER_THAN", f, STANCE))
    return g.finish()


def build_rig():
    pt, step, spring = frame.build(), build_step(), build_spring()
    g = Graph("SS Walker Rig", description="The walker's skeleton over time: root and feet on the path curve, "
                                           "hips, bob, sway, twist, arm swing and the springy secondary angles")
    curve = g.input("Curve", "GEOMETRY", desc="The street's path curve")
    time = g.input("Time", "FLOAT", 0.0, desc="Time in seconds")
    start = g.input("Walk Start", "FLOAT", 10.0, subtype="DISTANCE", desc="Arc length at Time 0")
    speed = g.input("Walk Speed", "FLOAT", 0.9, desc="Walking speed in H per second")
    off = g.input("Walk Offset", "FLOAT", 0.0, subtype="DISTANCE", desc="Lateral offset from the centre line")
    stride = g.input("Stride", "FLOAT", 0.652, min=0.05, subtype="DISTANCE", desc="Distance per gait cycle")
    bob_a = g.input("Bob", "FLOAT", 0.024, min=0.0, subtype="DISTANCE", desc="Body bob amplitude")
    flap_a = g.input("Flap Swing", "FLOAT", 0.022, min=0.0, subtype="ANGLE", desc="Ear flap bounce")
    flap_p = g.input("Flap Lag", "FLOAT", 0.3, min=0.05, max=3.0, desc="Ear flap spring period (s)")
    scarf_a = g.input("Scarf Swing", "FLOAT", 0.05, min=0.0, subtype="ANGLE", desc="Scarf and satchel swing")
    scale = g.input("Scale", "FLOAT", 1.0, min=0.01, desc="Walker scale")
    lift_g = g.input("Ground Lift", "FLOAT", 0.03, subtype="DISTANCE", desc="Height of the soles above the curve")

    with g.frame("Distance walked s = Walk Start + Walk Speed * Time; phase = s / Stride"):
        s = g.math("MULTIPLY_ADD", speed, time, start)
        phase = g.math("DIVIDE", s, stride)
        cyc = g.math("MULTIPLY", g.math("SUBTRACT", phase, 0.5 * STANCE), 2 * math.pi, label="cycle angle")
        cyc2 = g.math("MULTIPLY", cyc, 2.0, label="step angle")
        f_gait = g.math("DIVIDE", speed, stride, label="gait Hz")
        f_step = g.math("MULTIPLY", f_gait, 2.0, label="step Hz")
    with g.frame("Body: bob twice per cycle (low at mid-stance), sway over the stance foot, twist with the arms"):
        bob = g.math("MULTIPLY", g.math("COSINE", cyc2), g.math("MULTIPLY", bob_a, -1.0))
        sway = M(g, g.math("COSINE", cyc), ("MULTIPLY", SWAY), ("MULTIPLY", scale))
        arm = g.math("MULTIPLY", g.math("COSINE", M(g, phase, ("SUBTRACT", 0.09), ("MULTIPLY", 2 * math.pi))),
                     -1.0, label="arm swing (left forward +)")
        twist = g.math("MULTIPLY", arm, TWIST)
    with g.frame("Root: street point at s, heading from the curve tangent"):
        root = g.group(pt, Curve=curve, Length=s, Offset=g.math("ADD", off, sway), Height=lift_g)
        hip_z = g.math("MULTIPLY", g.math("ADD", HIP, bob), scale)
        hips = []
        for side in (1.0, -1.0):
            local = g.combine(0.0, g.math("MULTIPLY", side * HIP_X, scale), hip_z)
            rv = g.node("FunctionNodeRotateVector", Vector=local, Rotation=root["Rotation"])
            hips.append(g.vmath("ADD", root["Position"], rv))
    feet = []
    with g.frame("Feet: each foot's gait, placed at its own arc length (planted feet stay put on any curve)"):
        for side, phase_off in ((1.0, 0.0), (-1.0, 0.5)):
            st = g.group(step, Phase=phase, Offset=phase_off, Stride=stride, Scale=scale)
            d = g.math("ADD", off, g.math("MULTIPLY", side * FOOT_X, scale))
            h = g.math("ADD", st["Lift"], lift_g)
            fp = g.group(pt, Curve=curve, Length=st["Length"], Offset=d, Height=h)
            pitch = g.node("FunctionNodeAxisAngleToRotation", Axis=(0, 1, 0), Angle=st["Pitch"])
            rot = g.node("FunctionNodeRotateRotation", props={"rotation_space": "LOCAL"},
                         Rotation=fp["Rotation"], **{"Rotate By": pitch["Rotation"]})
            feet.append((fp["Position"], rot["Rotation"]))
    with g.frame("Ear flaps: spring response to the bob (step rate), counter-roll with the sway (gait rate)"):
        fn = g.math("DIVIDE", 1.0, flap_p, label="flap Hz")
        lift = g.group(spring, Phase=cyc2, **{"Drive Frequency": f_step, "Natural Frequency": fn,
                                                "Damping": 0.3, "Amplitude": g.math("MULTIPLY", flap_a, -1.0)})
        roll = g.group(spring, Phase=cyc, **{"Drive Frequency": f_gait, "Natural Frequency": fn,
                                               "Damping": 0.3, "Amplitude": g.math("MULTIPLY", flap_a, 0.5)})
        flap_l = g.math("ADD", lift["Response"], roll["Response"])
        flap_r = g.math("SUBTRACT", lift["Response"], roll["Response"])
    with g.frame("Scarf panel and satchel: slower springs hanging from collar and hip"):
        sc_p = g.group(spring, Phase=cyc2, **{"Drive Frequency": f_step, "Natural Frequency": 2.1, "Damping": 0.25,
                                               "Amplitude": g.math("MULTIPLY", scarf_a, -1.0)})
        sc_r = g.group(spring, Phase=cyc, **{"Drive Frequency": f_gait, "Natural Frequency": 2.1, "Damping": 0.25,
                                              "Amplitude": g.math("MULTIPLY", scarf_a, 2.0)})
        scarf_pitch = g.math("ADD", sc_p["Response"], 0.12, label="rest: hangs slightly back")
        pom = M(g, cyc2, ("SUBTRACT", sc_p["Lag"]), ("ADD", math.pi))
        sa_p = g.group(spring, Phase=cyc2, **{"Drive Frequency": f_step, "Natural Frequency": 1.8, "Damping": 0.2,
                                               "Amplitude": g.math("MULTIPLY", scarf_a, -1.6)})
        sa_r = g.group(spring, Phase=cyc, **{"Drive Frequency": f_gait, "Natural Frequency": 1.8, "Damping": 0.2,
                                              "Amplitude": g.math("MULTIPLY", scarf_a, 2.4)})
    g.output("Root Position", "VECTOR", root["Position"])
    g.output("Root Rotation", "ROTATION", root["Rotation"])
    g.output("Bob", "FLOAT", bob)
    g.output("Twist", "FLOAT", twist)
    g.output("Arm Swing", "FLOAT", arm)
    g.output("Hip Left", "VECTOR", hips[0])
    g.output("Hip Right", "VECTOR", hips[1])
    g.output("Foot Left Position", "VECTOR", feet[0][0])
    g.output("Foot Left Rotation", "ROTATION", feet[0][1])
    g.output("Foot Right Position", "VECTOR", feet[1][0])
    g.output("Foot Right Rotation", "ROTATION", feet[1][1])
    g.output("Flap Lift Left", "FLOAT", flap_l)
    g.output("Flap Lift Right", "FLOAT", flap_r)
    g.output("Scarf Pitch", "FLOAT", scarf_pitch)
    g.output("Scarf Roll", "FLOAT", sc_r["Response"])
    g.output("Pom Phase", "FLOAT", pom)
    g.output("Satchel Pitch", "FLOAT", sa_p["Response"])
    g.output("Satchel Roll", "FLOAT", sa_r["Response"])
    return g.finish()


# ---- body parts ----------------------------------------------------------------------------------------------
def build_hood():
    g = Graph("SS Walker Hood", description="Felt hood in the body frame: bell-shaped dome with a flat hem over "
                                            "the shoulders, padded teardrop on the back of the crown, centre seam, "
                                            "orange horn nubs")
    color = g.input("Color", "COLOR", srgb(PAL["Hood"]), desc="Felt colour")
    felt = mats.felt()
    with g.frame("Dome: ellipsoid widest low (where the flaps leave), narrower toward the crown, bottom flattened into the hem plane"):
        px, py, pz = xyz(g, pos(g))
        qz = g.math("MULTIPLY", pz, 0.31)
        dz = clamp(g, qz, -0.10, 0.31)
        x = g.math("DIVIDE", g.math("MULTIPLY", px, 0.27), g.math("MULTIPLY_ADD", dz, 0.15, 1.0))
        y = g.math("DIVIDE", g.math("MULTIPLY", py, 0.28), g.math("MULTIPLY_ADD", dz, 0.75, 1.0))
        z = g.math("ADD", qz, 0.675)
        hem = g.math("MULTIPLY_ADD", x, 0.15, 0.565)
        z = g.math("SMOOTH_MAX", z, hem, 0.03)
        dome = smooth(g, set_pos(g, sphere(g, 96, 48), g.combine(x, y, z)))
    with g.frame("Teardrop pad: a 2D teardrop seen from behind, ray-projected (from behind, slightly above) onto the dome and puffed out"):
        sx, sy, sz = xyz(g, pos(g))
        a = g.math("MULTIPLY_ADD", sz, 0.5, 0.5, label="0 tip .. 1 top")
        half = g.math("MULTIPLY_ADD", g.math("POWER", a, 1.5), 0.18, 0.012, label="half width")
        ty = g.math("MULTIPLY", sy, half)
        tz = g.math("MULTIPLY_ADD", a, 0.30, 0.685)
        src = g.combine(-0.45, ty, tz)
        aim = g.vmath("NORMALIZE", (1.0, 0.0, -0.2))
        ray = g.node("GeometryNodeRaycast", **{"Target Geometry": dome, "Source Position": src,
                                               "Ray Direction": aim, "Ray Length": 2.0})
        puff = g.math("MULTIPLY_ADD", g.math("ABSOLUTE", sx), 0.03, -0.004, label="pillow, edges sunk in")
        pad_pos = g.vmath("ADD", ray["Hit Position"], g.vmath("SCALE", ray["Hit Normal"], scale=puff))
        pad = smooth(g, set_pos(g, sphere(g, 32, 24), pad_pos))
    with g.frame("Horn nubs: small orange crescents on the hood's front sides"):
        nub = ellipsoid(g, (0.045, 0.085, 0.04), seg=16, rings=8)
        nx, ny, nz = xyz(g, pos(g))
        nub = set_pos(g, nub, g.combine(nx, ny, g.math("ADD", nz, g.math("MULTIPLY", g.math("MULTIPLY", ny, ny),
                                                                                     4.0))))
        nub = xform(g, nub, t=(0.05, 0.25, 0.73), r=euler(g, 0.2, 0.0, 0.45))
        nubs = smooth(g, join(g, nub, mirror(g, nub)))
        nubs = paint(g, nubs, HORN, felt)
    with g.frame("Baked felt shading on the dome (ss_occ): soft shadow around the pad, darker low on the back"):
        prox = g.node("GeometryNodeProximity", props={"target_element": "FACES"}, Target=pad)
        _, _, dzw = xyz(g, pos(g))
        near = g.math("EXPONENT", g.math("MULTIPLY", prox["Distance"], -70.0))
        under = g.map_range(dzw, 0.93, 0.78, 0.0, 1.0, interp="SMOOTHSTEP")
        low = g.map_range(dzw, 0.55, 0.88, 0.38, 0.0, interp="SMOOTHSTEP")
        occ = g.math("ADD", M(g, near, ("MULTIPLY", under), ("MULTIPLY", 0.5)), low)
    with g.frame("Felt tint; the dome carries ss_seam so the material stitches the centre seam"):
        dome = paint(g, dome, color, felt, {"ss_seam": 1.0, "ss_occ": occ})
        pad = paint(g, pad, color, felt)
    g.output("Geometry", "GEOMETRY", join(g, dome, pad, nubs))
    return g.finish()


def build_flap():
    g = Graph("SS Walker Flap", description="One long felt ear flap (left side), pivot at its root on the hood: a "
                                            "flattened lobe with a rounded tip, drooping out and down, tip levelling "
                                            "out, tips trailing back")
    length = g.input("Length", "FLOAT", 0.40, min=0.05, max=1.0, subtype="DISTANCE", desc="Root to tip length")
    lift = g.input("Lift", "FLOAT", 0.0, subtype="ANGLE", desc="Extra rotation at the root, positive lifts the tip")
    color = g.input("Color", "COLOR", srgb(PAL["Hood"]), desc="Felt colour")
    with g.frame("Lobe profile along a = 0 (root) .. 1 (tip): tapering width, rounded tip and root"):
        px, py, pz = xyz(g, pos(g))
        a = g.math("MULTIPLY_ADD", pz, 0.5, 0.5)
        ring = g.vmath("NORMALIZE", g.combine(px, py, 0.0))
        rx, ry, _ = xyz(g, ring)
        tip = clamp(g, g.math("DIVIDE", g.math("SUBTRACT", a, 0.72), 0.28), 0.0, 1.0)
        root = clamp(g, g.math("DIVIDE", g.math("SUBTRACT", 0.12, a), 0.12), 0.0, 1.0)
        round_ = g.math("MULTIPLY", g.math("SQRT", g.math("SUBTRACT", 1.0, g.math("MULTIPLY", tip, tip))),
                        g.math("SQRT", g.math("SUBTRACT", 1.0, g.math("MULTIPLY", root, root))))
        width = M(g, a, ("MULTIPLY", -0.3), ("ADD", 1.0), ("MULTIPLY", round_), ("MULTIPLY", 0.09))
        thick = M(g, a, ("MULTIPLY", -0.5), ("ADD", 1.0), ("MULTIPLY", round_), ("MULTIPLY", 0.04))
    with g.frame("Flap frame: along +Y, broad face toward the back, bent up toward the tip"):
        along = g.math("MULTIPLY", a, length)
        bend = M(g, a, ("MULTIPLY", a), ("MULTIPLY", length), ("MULTIPLY", 0.2))
        p = g.combine(g.math("MULTIPLY", ry, thick), along, g.math("ADD", g.math("MULTIPLY", rx, width), bend))
        lobe = smooth(g, set_pos(g, sphere(g, 32, 24), p))
        lobe = paint(g, lobe, color, mats.felt())
    with g.frame("Root joint: droop 1.0 rad below horizontal (minus Lift), trail back 0.3 rad"):
        out = xform(g, lobe, r=euler(g, g.math("SUBTRACT", lift, 1.0), 0.0, 0.3))
    g.output("Geometry", "GEOMETRY", out)
    return g.finish()


def build_tunic():
    g = Graph("SS Walker Tunic", description="Cream tunic lathed from a radius profile (flared hem, waist, "
                                             "rounded shoulders) with a brown belt")
    color = g.input("Color", "COLOR", srgb(PAL["Tunic"]), desc="Tunic colour")
    felt = mats.felt()
    with g.frame("Lathe: a cylinder whose radius follows the profile curve from hem (0) to neck (1)"):
        cyl = g.node("GeometryNodeMeshCylinder", Vertices=40, **{"Side Segments": 24, "Radius": 1.0, "Depth": 1.0})
        px, py, pz = xyz(g, pos(g))
        t = g.math("ADD", pz, 0.5)
        prof = g.node("ShaderNodeFloatCurve", "Tunic radius profile", Value=t)
        pts = [(0.0, 0.88), (0.10, 0.84), (0.24, 0.67), (0.34, 0.59), (0.55, 0.56), (0.76, 0.58), (0.90, 0.48),
               (1.0, 0.27)]
        cm = prof.b.mapping
        c = cm.curves[0]
        c.points[0].location, c.points[1].location = pts[0], pts[-1]
        for xy in pts[1:-1]:
            c.points.new(*xy)
        cm.update()
        r = g.math("MULTIPLY", prof["Value"], 0.2)
        p = g.combine(M(g, px, ("MULTIPLY", r), ("MULTIPLY", 0.82)), g.math("MULTIPLY", py, r),
                      g.math("MULTIPLY_ADD", t, 0.29, 0.2))
        tunic = paint(g, smooth(g, set_pos(g, cyl["Mesh"], p)), color, felt)
    with g.frame("Belt: a band around the waist"):
        band = g.node("GeometryNodeMeshCylinder", props={"fill_type": "NONE"}, Vertices=40,
                      **{"Side Segments": 1, "Radius": 1.0, "Depth": 0.035})
        band = xform(g, band["Mesh"], t=(0.0, 0.0, 0.295), s=(0.1, 0.122, 1.0))
        belt = paint(g, smooth(g, band), BELT, mats.leather())
    g.output("Geometry", "GEOMETRY", join(g, tunic, belt))
    return g.finish()


def build_scarf():
    g = Graph("SS Walker Scarf", description="Red knitted scarf: collar ring, back panel hinged at the collar's "
                                             "back, and a row of cream-pink pom-poms that wobble on the hem")
    pitch = g.input("Pitch", "FLOAT", 0.12, subtype="ANGLE", desc="Panel swing about the hinge, + swings back")
    roll = g.input("Roll", "FLOAT", 0.0, subtype="ANGLE", desc="Panel side-to-side swing")
    pom_ph = g.input("Pom Phase", "FLOAT", 0.0, subtype="ANGLE", desc="Pom-pom wobble phase")
    color = g.input("Color", "COLOR", srgb(PAL["Scarf"]), desc="Scarf colour")
    knit = mats.knit()
    with g.frame("Collar: a knitted ring around the neck"):
        ring = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=32, Radius=0.1)
        tube = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=12, Radius=0.05)
        collar = g.node("GeometryNodeCurveToMesh", Curve=ring["Curve"], **{"Profile Curve": tube["Curve"]})
        collar = xform(g, collar["Mesh"], t=(-0.005, 0.0, NECK), s=(0.95, 1.05, 0.9))
        collar = paint(g, smooth(g, collar), color, knit)
    with g.frame("Back panel hanging from the hinge, wrapped slightly round the back"):
        cube = g.node("GeometryNodeMeshCube", Size=(0.036, 0.15, 0.22), **{"Vertices X": 2, "Vertices Y": 4,
                                                                           "Vertices Z": 5})
        panel = smooth(g, cube["Mesh"], 2)
        px, py, pz = xyz(g, pos(g))
        panel = set_pos(g, panel, g.combine(g.math("MULTIPLY_ADD", g.math("MULTIPLY", py, py), 2.0, px), py,
                                            g.math("SUBTRACT", pz, 0.1)))
        panel = paint(g, panel, color, knit)
    with g.frame("Pom-poms: five along the hem, each wobbling a little later than its neighbour"):
        line = g.node("GeometryNodeMeshLine", props={"mode": "OFFSET"}, Count=5,
                      **{"Start Location": (0.0, -0.064, -0.225), "Offset": (0.0, 0.032, 0.0)})
        idx = g.math("SUBTRACT", g.node("GeometryNodeInputIndex")["Index"], 2.0)
        wob = M(g, g.math("SINE", g.math("SUBTRACT", pom_ph, g.math("MULTIPLY", idx, 0.7))), ("MULTIPLY", 0.008),
                ("SUBTRACT", 0.004))
        pts = g.node("GeometryNodeSetPosition", Geometry=line["Mesh"], Offset=g.combine(wob, 0.0, 0.0))
        size = M(g, g.math("SINE", g.math("MULTIPLY", idx, 2.3)), ("MULTIPLY", 0.12), ("ADD", 1.0))
        ball = smooth(g, sphere(g, 16, 10))
        inst = g.node("GeometryNodeInstanceOnPoints", Points=pts["Geometry"], Instance=ball,
                      Scale=g.vmath("SCALE", (0.026, 0.026, 0.028), scale=size))
        poms = g.node("GeometryNodeRealizeInstances", Geometry=inst["Instances"])["Geometry"]
        poms = paint(g, poms, POM, knit)
    with g.frame("Hinge at the collar's back: swing (pitch) and roll"):
        hung = xform(g, join(g, panel, poms), t=(-0.125, 0.0, NECK - 0.01),
                     r=euler(g, roll, pitch, 0.0))
    g.output("Geometry", "GEOMETRY", join(g, collar, hung))
    return g.finish()


def build_arm():
    g = Graph("SS Walker Arm", description="Left arm, pivot at the shoulder: short cream sleeve and a brown mitten, "
                                           "held out from the body, swinging fore and aft")
    swing = g.input("Swing", "FLOAT", 0.0, subtype="ANGLE", desc="Fore-aft swing, + brings the mitten forward")
    sleeve_c = g.input("Sleeve Color", "COLOR", srgb(PAL["Tunic"]), desc="Sleeve colour")
    mitt_c = g.input("Mitten Color", "COLOR", srgb(PAL["Mittens"]), desc="Mitten colour")
    felt = mats.felt()
    with g.frame("Sleeve and mitten hanging straight down from the shoulder"):
        cyl = g.node("GeometryNodeMeshCylinder", Vertices=20, **{"Side Segments": 3, "Radius": 0.042,
                                                                  "Depth": 0.1})
        sleeve = join(g, xform(g, cyl["Mesh"], t=(0, 0, -0.05)), ellipsoid(g, (0.045, 0.045, 0.045)))
        sleeve = paint(g, smooth(g, sleeve), sleeve_c, felt)
        mitt = smooth(g, ellipsoid(g, (0.05, 0.046, 0.056), (0.008, 0.0, -0.13)))
        mitt = paint(g, mitt, mitt_c, felt)
    with g.frame("Shoulder joint: held out 0.8 rad, swung about the side axis"):
        out = xform(g, join(g, sleeve, mitt), r=euler(g, 0.8, g.math("MULTIPLY", swing, -1.0), 0.0))
    g.output("Geometry", "GEOMETRY", out)
    return g.finish()


def build_satchel():
    g = Graph("SS Walker Satchel", description="Small leather pouch on the left hip, pivot at its strap, broad "
                                               "face turned back-left, swinging on a spring")
    pitch = g.input("Pitch", "FLOAT", 0.0, subtype="ANGLE", desc="Swing about the side axis")
    roll = g.input("Roll", "FLOAT", 0.0, subtype="ANGLE", desc="Swing out from the hip")
    color = g.input("Color", "COLOR", srgb(PAL["Satchel"]), desc="Leather colour")
    leather = mats.leather()
    with g.frame("Pouch body and a darker front flap"):
        body = g.node("GeometryNodeMeshCube", Size=(0.045, 0.11, 0.12), **{"Vertices X": 2, "Vertices Y": 3,
                                                                            "Vertices Z": 3})
        body = paint(g, smooth(g, body["Mesh"], 2), color, leather)
        flap = g.node("GeometryNodeMeshCube", Size=(0.012, 0.112, 0.07), **{"Vertices X": 2, "Vertices Y": 3,
                                                                             "Vertices Z": 2})
        dark = g.mix(1.0, color, (0.0, 0.0, 0.0, 1.0), data_type="RGBA")
        dark.b.blend_type = "MIX"
        g.connect(0.3, dark.i("Factor"))
        flap = xform(g, smooth(g, flap["Mesh"], 2), t=(-0.022, 0.0, 0.03))
        flap = paint(g, flap, dark["Result"], leather)
        bag = xform(g, join(g, body, flap), t=(-0.03, 0.03, -0.08), r=euler(g, 0.0, 0.0, -0.6))
    with g.frame("Strap pivot: swing and roll"):
        out = xform(g, bag, r=euler(g, g.math("MULTIPLY", roll, -1.0), pitch, 0.0))
    g.output("Geometry", "GEOMETRY", out)
    return g.finish()


def build_boot():
    g = Graph("SS Walker Boot", description="Chunky rubber boot in its own frame, toe pivot at the origin: a "
                                            "rounded box (superellipsoid) foot and a short shaft. Static: built "
                                            "once, then only transformed by each leg")
    color = g.input("Color", "COLOR", srgb(PAL["Boots"]), desc="Boot colour")
    with g.frame("Foot: sphere pushed toward a box (|p|^0.55 per axis), toe pivot at the front of the sole"):
        px, py, pz = xyz(g, pos(g))
        box = [g.math("MULTIPLY", g.math("SIGN", c), g.math("POWER", g.math("ABSOLUTE", c), 0.55))
               for c in (px, py, pz)]
        foot = set_pos(g, sphere(g, 24, 12), g.combine(*box))
        foot = xform(g, smooth(g, foot), t=(-TOE, 0.0, 0.0475), s=(0.09, 0.0575, 0.0475))
    with g.frame("Shaft up to the leg"):
        shaft = g.node("GeometryNodeMeshCylinder", Vertices=20, **{"Side Segments": 1, "Radius": 0.053,
                                                                    "Depth": 0.13})
        shaft = xform(g, smooth(g, shaft["Mesh"]), t=(-TOE - 0.025, 0.0, 0.12))
    g.output("Geometry", "GEOMETRY", paint(g, join(g, foot, shaft), color, mats.rubber()))
    return g.finish()


def build_leg():
    g = Graph("SS Walker Leg", description="One leg in world space: the (pre-built) boot moved to its foot transform (pivot at "
                                           "the toe) and a short teal leg tube from the boot shaft to the hip")
    hip = g.input("Hip", "VECTOR", (0, 0, 0.2), desc="Hip joint, world position")
    fpos = g.input("Foot Position", "VECTOR", (0, 0, 0), desc="Toe pivot on the ground, world position")
    frot = g.input("Foot Rotation", "ROTATION", desc="Boot orientation (street frame plus heel pitch)")
    scale = g.input("Scale", "FLOAT", 1.0, min=0.01, desc="Walker scale")
    boot = g.input("Boot", "GEOMETRY", desc="The boot in its own frame (SS Walker Boot), toe pivot at the origin")
    with g.frame("Place the boot: scale, foot rotation, foot position"):
        boot = xform(g, boot, t=fpos, r=frot, s=g.combine(scale, scale, scale))
    with g.frame("Leg: tube from the ankle (boot shaft top) to the hip"):
        ankle_l = g.vmath("SCALE", (-TOE - 0.025, 0.0, 0.17), scale=scale)
        ankle = g.vmath("ADD", fpos, g.node("FunctionNodeRotateVector", Vector=ankle_l, Rotation=frot))
        line = g.node("GeometryNodeCurvePrimitiveLine", Start=ankle, End=hip)
        prof = g.node("GeometryNodeCurvePrimitiveCircle", Resolution=12, Radius=0.036)
        tube = g.node("GeometryNodeCurveToMesh", Curve=line["Curve"], **{"Profile Curve": prof["Curve"],
                                                                         "Scale": scale, "Fill Caps": True})
        leg = paint(g, smooth(g, tube["Mesh"]), LEGS, mats.felt())
    g.output("Geometry", "GEOMETRY", join(g, boot, leg))
    return g.finish()


# ---- top group -----------------------------------------------------------------------------------------------
def build():
    rig, hood, flap, tunic = build_rig(), build_hood(), build_flap(), build_tunic()
    scarf, arm, satchel, leg, boot = build_scarf(), build_arm(), build_satchel(), build_leg(), build_boot()
    g = Graph(NAME, description="The hooded storybook walker, seen from behind, walking along the path curve at "
                                "s = Walk Start + Walk Speed * Time with planted feet, body bob and sway, arm swing "
                                "and springy ear flaps, scarf and satchel")
    curve = g.input("Curve", "GEOMETRY", desc="The street's path curve")
    time = g.input("Time", "FLOAT", 0.0, desc="Time in seconds")
    start = g.input("Walk Start", "FLOAT", 10.0, subtype="DISTANCE", panel="Walk",
                    desc="Arc length along the path at Time 0")
    speed = g.input("Walk Speed", "FLOAT", 0.9, min=0.0, max=5.0, panel="Walk",
                    desc="Walking speed in H (walker heights) per second")
    off = g.input("Walk Offset", "FLOAT", 0.0, min=-3.0, max=3.0, subtype="DISTANCE", panel="Walk",
                  desc="Lateral offset d from the street centre line (+ left)")
    stride = g.input("Stride", "FLOAT", 0.652, min=0.1, max=2.0, subtype="DISTANCE", panel="Walk",
                     desc="Distance walked per gait cycle (two steps); cadence = 2 * speed / stride")
    bob = g.input("Bob", "FLOAT", 0.024, min=0.0, max=0.2, subtype="DISTANCE", panel="Walk",
                  desc="Body bob amplitude (twice per gait cycle)")
    lift_g = g.input("Ground Lift", "FLOAT", 0.03, min=-0.2, max=0.5, subtype="DISTANCE", panel="Walk",
                     desc="Height of the boot soles above the path curve (sits them on the cobble crowns)")
    flap_a = g.input("Flap Swing", "FLOAT", 0.022, min=0.0, max=1.0, subtype="ANGLE", panel="Secondary",
                     desc="Ear flap bounce angle (before the spring's resonance gain)")
    flap_p = g.input("Flap Lag", "FLOAT", 0.3, min=0.05, max=2.0, panel="Secondary",
                     desc="Ear flap spring period in seconds: longer is floppier and lags further behind the bob")
    scarf_a = g.input("Scarf Swing", "FLOAT", 0.05, min=0.0, max=1.0, subtype="ANGLE", panel="Secondary",
                      desc="Scarf panel and satchel swing angle")
    cols = {k: g.input(k, "COLOR", srgb(v), panel="Palette", desc=f"{k} colour") for k, v in PAL.items()}
    hood_s = g.input("Hood Size", "FLOAT", 1.0, min=0.5, max=2.0, panel="Shape",
                     desc="Scale of the hood, flaps and horns about the neck")
    flap_l = g.input("Flap Length", "FLOAT", 0.40, min=0.1, max=0.8, subtype="DISTANCE", panel="Shape",
                     desc="Ear flap length from root to tip")
    scale = g.input("Scale", "FLOAT", 1.0, min=0.1, max=10.0, panel="Shape",
                    desc="Overall size of the walker (1 = 1 H tall); stride and speed stay as set")

    with g.frame("Rig: the skeleton's joint values at this Time"):
        r = g.group(rig, Curve=curve, Time=time, Stride=stride, Bob=bob, Scale=scale, **{"Ground Lift": lift_g},
                    **{"Walk Start": start, "Walk Speed": speed, "Walk Offset": off, "Flap Swing": flap_a,
                       "Flap Lag": flap_p, "Scarf Swing": scarf_a})
    with g.frame("Head: hood plus ear flaps at their roots, scaled about the neck by Hood Size"):
        h = g.group(hood, Color=cols["Hood"])
        fl = g.group(flap, Length=flap_l, Lift=r["Flap Lift Left"], Color=cols["Hood"])
        fr = g.group(flap, Length=flap_l, Lift=r["Flap Lift Right"], Color=cols["Hood"])
        fl = xform(g, fl, t=(-0.03, 0.17, 0.65))
        fr = mirror(g, xform(g, fr, t=(-0.03, 0.17, 0.65)))
        head = xform(g, join(g, h, fl, fr), t=(0, 0, -0.5))
        head = xform(g, head, t=(0, 0, 0.5), s=g.combine(hood_s, hood_s, hood_s))
    with g.frame("Torso: tunic, scarf on its hinge, arms at the shoulders, satchel on the left hip"):
        tu = g.group(tunic, Color=cols["Tunic"])
        sc = g.group(scarf, Pitch=r["Scarf Pitch"], Roll=r["Scarf Roll"], Color=cols["Scarf"],
                     **{"Pom Phase": r["Pom Phase"]})
        swing = g.math("MULTIPLY", r["Arm Swing"], ARM_SWING)
        al = g.group(arm, Swing=swing, **{"Sleeve Color": cols["Tunic"], "Mitten Color": cols["Mittens"]})
        ar = g.group(arm, Swing=g.math("MULTIPLY", swing, -1.0),
                     **{"Sleeve Color": cols["Tunic"], "Mitten Color": cols["Mittens"]})
        al = xform(g, al, t=(0.0, 0.105, 0.42))
        ar = mirror(g, xform(g, ar, t=(0.0, 0.105, 0.42)))
        sa = g.group(satchel, Pitch=r["Satchel Pitch"], Roll=r["Satchel Roll"], Color=cols["Satchel"])
        sa = xform(g, sa, t=(-0.04, 0.13, 0.34))
    with g.frame("Upper body joint at the hips: lean forward, twist, bob"):
        upper = xform(g, join(g, head, tu, sc, al, ar, sa), t=(0, 0, -HIP))
        upper = xform(g, upper, t=g.combine(0.0, 0.0, g.math("ADD", r["Bob"], HIP)),
                      r=euler(g, 0.0, LEAN, r["Twist"]))
    with g.frame("Root: body frame to the street point at s (scale, heading, position)"):
        body = xform(g, upper, t=r["Root Position"], r=r["Root Rotation"], s=g.combine(scale, scale, scale))
    with g.frame("Legs: one static boot, moved to each foot's world transform; tubes up to the hips"):
        bt = g.group(boot, Color=cols["Boots"])
        ll = g.group(leg, Hip=r["Hip Left"], Scale=scale, **{"Foot Position": r["Foot Left Position"],
                                                            "Foot Rotation": r["Foot Left Rotation"], "Boot": bt})
        lr = g.group(leg, Hip=r["Hip Right"], Scale=scale, **{"Foot Position": r["Foot Right Position"],
                                                             "Foot Rotation": r["Foot Right Rotation"], "Boot": bt})
    g.output("Geometry", "GEOMETRY", join(g, body, ll, lr))
    return g.finish()
