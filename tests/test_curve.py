import numpy as np
import nkt
from library.curve import curve_frame


def test_frame_on_straight_poly():
    """On a straight poly curve along +Y, s maps to y, left is -X, offsets and heights add exactly."""
    path = nkt.poly([(0, 0, 0), (0, 10, 0)])
    s = [0.0, 2.5, 5.0, 9.0]
    out = nkt.field(curve_frame(), {"Curve": path, "Offset": 0.5, "Height": 1.0}, per_point={"Length": s},
                    outputs={"Position": "VECTOR", "Left": "VECTOR", "Tangent": "VECTOR"})
    assert nkt.close(out["Position"], [(-0.5, v, 1.0) for v in s]), out["Position"]
    assert nkt.close(out["Left"], [(-1, 0, 0)] * 4)
    assert nkt.close(out["Tangent"], [(0, 1, 0)] * 4)


def test_frame_orthonormal_on_hilly_bend():
    """Tangent and left stay unit length, level (z = 0) and perpendicular on a bent, climbing curve."""
    path = nkt.curve([(0, 0, 0), (6, 8, 1), (-4, 16, 3), (2, 25, 2)])
    out = nkt.field(curve_frame(), {"Curve": path}, per_point={"Length": np.linspace(0, 20, 21)},
                    outputs={"Tangent": "VECTOR", "Left": "VECTOR"})
    t, l = out["Tangent"], out["Left"]
    assert nkt.close(np.linalg.norm(t, axis=1), 1.0) and nkt.close(np.linalg.norm(l, axis=1), 1.0)
    assert nkt.close(t[:, 2], 0.0) and nkt.close(l[:, 2], 0.0)
    assert nkt.close(np.sum(t * l, axis=1), 0.0)
