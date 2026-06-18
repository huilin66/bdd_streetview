import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.shp2pan import (  # noqa: E402
    LL_TO_2326,
    TO_WGS84,
    Building,
    angle_diff_deg,
    azimuth_deg,
    outward_normal,
    vector_azimuth_deg,
)


def make_square(ring):
    return Building(
        shape_index=0,
        building_id="b1",
        building_cs="cs1",
        properties={},
        exteriors=[ring],
        bbox=(0.0, 0.0, 10.0, 10.0),
    )


def test_epsg2326_wgs84_roundtrip():
    lng, lat = 114.168, 22.284
    x, y = LL_TO_2326.transform(lng, lat)
    out_lng, out_lat = TO_WGS84.transform(x, y)

    assert abs(out_lng - lng) < 1e-8
    assert abs(out_lat - lat) < 1e-8


def test_outward_normal_does_not_depend_on_ring_winding():
    ccw = make_square([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    cw = make_square([(10.0, 0.0), (0.0, 0.0), (0.0, 10.0), (10.0, 10.0)])

    normal_ccw = outward_normal(ccw, (0.0, 0.0), (10.0, 0.0))
    normal_cw = outward_normal(cw, (10.0, 0.0), (0.0, 0.0))

    assert math.isclose(vector_azimuth_deg(normal_ccw), 180.0, abs_tol=1e-6)
    assert math.isclose(vector_azimuth_deg(normal_cw), 180.0, abs_tol=1e-6)


def test_candidate_view_angle_matches_opposite_outward_normal():
    facade_mid = (5.0, 0.0)
    street_on_outside = (5.0, -10.0)
    street_on_inside_side = (5.0, 10.0)
    outward_azimuth = 180.0
    expected_view = (outward_azimuth + 180.0) % 360.0

    good_view = azimuth_deg(street_on_outside, facade_mid)
    bad_view = azimuth_deg(street_on_inside_side, facade_mid)

    assert math.isclose(good_view, 0.0, abs_tol=1e-6)
    assert math.isclose(angle_diff_deg(good_view, expected_view), 0.0, abs_tol=1e-6)
    assert math.isclose(angle_diff_deg(bad_view, expected_view), 180.0, abs_tol=1e-6)

