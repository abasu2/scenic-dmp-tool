"""The patched program P′: its text, and that sampling it gives f#μ_{P′} ≈ ν."""

from pathlib import Path

import numpy as np
import pytest

from scenic_dmp import PatchError, Program, Session, View, session_patch, validate
from test_view_spec import BRAKE_SPEC

PEDESTRIAN = Path(__file__).parent.parent / "examples" / "pedestrian.scenic"

TOY = """\
class Car: pass
ego = new Car
x = Range(0, 10)
"""


@pytest.fixture(scope="module")
def brake_session():
    d_view = View.from_spec({"name": "d", "bindings": [{"name": "d", "expr": "d"}],
                             "expr": "d", "values": ["1", "2", "3"]})
    return Session(Program.from_file(PEDESTRIAN), View.from_spec(BRAKE_SPEC), also=[d_view],
                   seed=0).sample(5000)


def test_identity_patch_has_no_requirements(brake_session):
    brake_session.reset_nu()
    patch = session_patch(brake_session)
    assert not [line for line in patch["block"].splitlines() if line.startswith("require")]
    assert "no requirement is needed" in patch["block"]


def test_patch_text(brake_session):
    brake_session.set_nu({"brake": 0.5, "continue": 0.5})
    patch = session_patch(brake_session)
    block = patch["block"]
    assert patch["source"].startswith(PEDESTRIAN.read_text().rstrip())
    assert patch["source"].splitlines()[patch["first_line"] - 1] == block.splitlines()[0]
    assert "from math import radians as __dmp_deg, isclose as __dmp_isclose" in block
    assert "def __dmp_view_brake(d, c):" in block
    assert "__dmp_isclose(c, __dmp_deg(90))" in block
    assert "__dmp_u = Range(0, 1)" in block
    # brake has â = 1, so only continue gets a requirement.
    requires = [line for line in block.splitlines() if line.startswith("require")]
    assert len(requires) == 1
    a = brake_session.a[1]
    assert requires[0].startswith(
        f"require not (__dmp_view_brake((d), (c)) == 'continue') or __dmp_u < {a:.6g}"
    )


def test_sampling_patch_gives_nu(brake_session):
    brake_session.set_nu({"brake": 0.5, "continue": 0.5})
    progress = []
    result, samples = validate(brake_session, 4000, on_progress=progress.append)
    assert progress and progress[-1]["n"] == 4000
    assert result["n"] == samples.n == 4000
    assert result["nu_in_ci"] == [True, True]
    assert result["mean_iters"] == pytest.approx(result["predicted_iters"], rel=0.05)
    assert result["predicted_iters"] == pytest.approx(brake_session.M)


def test_zero_nu_is_a_hard_requirement():
    view = View.from_spec({"name": "x", "bindings": [{"name": "x", "expr": "x"}],
                           "expr": "x", "bins": [2, 5, 8]})
    s = Session(Program(TOY), view, seed=2).sample(2000)
    assert s.labels == ["< 2", "[2, 5)", "[5, 8)", "≥ 8"]
    s.set_nu([0.4, 0.0, 0.3, 0.3])
    block = session_patch(s)["block"]
    assert "require not (2 <= __dmp_view_x((x)) < 5)  # [2, 5): ν = 0, never kept" in block
    assert "require not (__dmp_view_x((x)) >= 8) or __dmp_u <" in block
    result, samples = validate(s, 1500)
    assert result["counts"][1] == 0
    assert all(result["nu_in_ci"])


def test_no_patch_when_blocked_or_lambda_view():
    s = Session(Program(TOY), View("x", ["x"], float, bins=[2, 5]), seed=0).sample(100)
    with pytest.raises(PatchError, match="no expression source"):
        session_patch(s)
