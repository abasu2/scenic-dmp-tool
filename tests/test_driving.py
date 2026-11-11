"""A driving-domain program on the Town05 map from the vendored Scenic checkout."""

from pathlib import Path

import pytest

from scenic_dmp import Program, Session, View

SCENIC = Path.home() / "research/scenic-example/vendor/Scenic"
PROGRAM = SCENIC / "examples/driving/badlyParkedCarPullingIn.scenic"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not PROGRAM.exists(), reason=f"needs {PROGRAM}"),
]


def test_binned_distance_view():
    # The program requires the parked car to be > 20 m from ego, so "< 20"
    # should have no samples and be locked.
    distance = View("distance", ["distance from ego to parkedCar"], float, bins=[20, 30, 40, 50])
    side = View(
        "angle side",
        ["badAngle"],
        lambda a: "left" if a > 0 else "right",
        values=["left", "right"],
    )
    program = Program.from_file(PROGRAM, mode2D=True, params={"map_options": {"writeCache": False}})
    s = Session(program, distance, also=[side], seed=0).sample(200)

    assert s.counts.sum() == 200
    assert s.labels[0] == "< 20"
    assert not s.supported[0]
    assert s.mean_iterations > 1  # the program's own require rejects samples

    s.drag("[20, 30)", 0.6)
    assert s.M > 1
    assert s.preview("angle side")["after"].sum() == pytest.approx(1)
