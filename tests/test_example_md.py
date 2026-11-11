"""Integration test on the program from scenic-dmp/example.md."""

import math
from pathlib import Path

import numpy as np
import pytest

from scenic_dmp import Program, Session, View

PEDESTRIAN = Path(__file__).parent.parent / "examples" / "pedestrian.scenic"


def brake_view():
    return View(
        "brake",
        ["d", "c"],
        lambda d, c: "brake" if d <= 2 and math.isclose(c, math.pi / 2) else "continue",
        values=["brake", "continue"],
    )


@pytest.fixture(scope="module")
def session():
    d_view = View("d", ["d"], int, values=[1, 2, 3])
    return Session(Program.from_file(PEDESTRIAN), brake_view(), also=[d_view], seed=0).sample(5000)


def test_pushforward_matches_example(session):
    assert session.labels == ["brake", "continue"]
    lo, hi = session.ci
    assert lo[0] < 0.35 < hi[0]
    assert session.mean_iterations == 1.0
    # nu starts at f#mu_hat: the identity patch.
    assert session.nu == pytest.approx(session.p_hat)
    assert session.M == pytest.approx(1)


def test_jeffrey_readout(session):
    session.set_nu([0.5, 0.5])
    p = session.p_hat
    assert session.w == pytest.approx([0.5 / p[0], 0.5 / p[1]])
    assert session.w[0] == pytest.approx(10 / 7, rel=0.05)
    assert session.acceptance == pytest.approx(0.7, rel=0.05)
    assert session.projected_iterations == pytest.approx(session.M)

    preview = session.preview("d")
    assert preview["before"] == pytest.approx([0.2, 0.5, 0.3], abs=0.03)
    assert preview["after"][0] == pytest.approx(1 / 7 + 1 / 13, abs=0.03)
    assert preview["after"].sum() == pytest.approx(1)
    assert 0 < preview["n_eff"] < session.n


def test_same_seed_is_reproducible_and_chunk_invariant():
    program = Program.from_file(PEDESTRIAN)
    a = Session(program, brake_view(), seed=3).sample(2000)
    b = Session(program, brake_view(), seed=3).sample(1000).sample_more(1000)
    assert np.array_equal(a.y_idx, b.y_idx)
