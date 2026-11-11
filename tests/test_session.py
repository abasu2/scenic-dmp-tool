import numpy as np
import pytest

from scenic_dmp import Program, Session, View

# d is uniform on {1, 2, 3}; the view also declares 4, which never occurs.
TOY = """\
class Car: pass
ego = new Car
d = Uniform(1, 2, 3)
x = Range(0, 10)
"""


def d_view(values=(1, 2, 3, 4), fn=int):
    return View("d", ["d"], fn, values=list(values))


def x_view():
    return View("x", ["x"], float, bins=[0, 5, 10])


@pytest.fixture
def session():
    return Session(Program(TOY), d_view(), also=[x_view()], seed=1).sample(600)


def test_zero_support_value_is_locked(session):
    assert session.supported.tolist() == [True, True, True, False]
    assert session.nu[3] == 0
    with pytest.raises(ValueError, match="'4'"):
        session.set_nu({"1": 0.5, "4": 0.5})
    with pytest.raises(ValueError):
        session.drag("4", 0.2)


def test_drag_rescales_others_proportionally(session):
    before = session.nu.copy()
    session.drag("1", 0.6)
    assert session.nu[0] == pytest.approx(0.6)
    assert session.nu[2] / session.nu[1] == pytest.approx(before[2] / before[1])
    assert session.nu.sum() == pytest.approx(1)


def test_set_nu_normalizes_and_accepts_dicts(session):
    session.set_nu({"1": 2, "2": 1, "3": 1})
    assert session.nu == pytest.approx([0.5, 0.25, 0.25, 0])
    with pytest.raises(ValueError, match="unknown"):
        session.set_nu({"7": 1})


def test_uniform_and_reset(session):
    session.uniform_nu()
    assert session.nu == pytest.approx([1 / 3, 1 / 3, 1 / 3, 0])
    session.reset_nu()
    assert session.nu == pytest.approx(session.p_hat)


def test_nu_survives_sample_more(session):
    session.set_nu([0.6, 0.2, 0.2, 0])
    session.sample_more(300)
    assert session.n == 900
    assert session.nu == pytest.approx([0.6, 0.2, 0.2, 0])


def test_new_fn_reclassifies_without_resampling(session):
    scenes = list(session.samples.scenes)
    session.set_nu([0.6, 0.2, 0.2, 0])
    # Same labels: nu is kept.
    session.set_view(d_view(fn=lambda d: int(d) % 3 + 1))
    assert session.samples.scenes == scenes
    assert session.nu == pytest.approx([0.6, 0.2, 0.2, 0])
    # Different labels: nu resets to the new f#mu_hat.
    session.set_view(View("small", ["d"], lambda d: d <= 1, values=[True, False]))
    assert session.samples.scenes == scenes
    assert session.nu == pytest.approx(session.p_hat)


def test_new_args_resample(session, capsys):
    session.set_also([x_view(), View("dx", ["d * x"], float, bins=[0, 10, 30])])
    assert "resampling 600 scenes" in capsys.readouterr().out
    assert session.n == 600
    assert session.preview("dx")["before"].sum() == pytest.approx(1)


def test_blocked_when_resampling_loses_support():
    # nu puts mass on 3; then the view changes so 3 becomes impossible but the
    # labels stay the same.
    s = Session(Program(TOY), d_view(), seed=1).sample(300)
    s.set_nu([0.2, 0.2, 0.6, 0])
    s.set_view(d_view(fn=lambda d: min(int(d), 2)))
    assert s.blocked == ["3"]
    assert s.w is None and s.M is None
    assert s.preview() is None
    assert "BLOCKED" in s.summary()
    s.drag("1", 0.5)  # any drag repairs it
    assert s.blocked == []
    assert s.nu == pytest.approx([0.5, 0.5, 0, 0])


def test_numeric_view_overflow_bins(session):
    session.set_view(View("x", ["x"], float, bins=[2, 8]))
    assert session.labels == ["< 2", "[2, 8)", "≥ 8"]
    assert session.counts.sum() == session.n
    assert session.supported.all()


def test_summary_mentions_every_label(session):
    text = session.summary()
    for label in session.labels:
        assert label in text


def test_state_is_plain_json_and_listeners_fire(session):
    import json

    seen = []
    session.listeners.append(lambda s: seen.append(s.n))
    session.set_nu([2.0, 1.0, 1.0, 0.0])
    assert seen == [600]
    state = json.loads(json.dumps(session.state()))
    assert state["labels"] == ["1", "2", "3", "4"]
    assert state["supported"] == [True, True, True, False]
    assert state["nu"] == pytest.approx([0.5, 0.25, 0.25, 0])
    assert state["M"] == pytest.approx(session.M)
    (x,) = state["previews"]
    assert x["name"] == "x" and state["preview_name"] == "x"
    # The joint table of (f, g) counts has the f counts as row sums and g counts as column sums.
    joint = np.array(x["joint"])
    assert joint.sum(axis=1).tolist() == state["counts"]
    assert joint.sum(axis=0).tolist() == x["counts"]


def test_nu_is_kept_per_view(session):
    session.set_nu([0.6, 0.2, 0.2, 0])
    session.set_view(View("small", ["d"], lambda d: d <= 1, values=[True, False]))
    session.set_nu([0.5, 0.5])
    session.set_view(d_view())
    assert session.nu == pytest.approx([0.6, 0.2, 0.2, 0])


def test_stop_keeps_partial_samples(session):
    calls = []
    session.sample_more(10_000, should_stop=lambda: len(calls) > 0, on_progress=calls.append)
    assert 600 < session.n < 10_600
    assert session.counts.sum() == session.n


def test_failed_view_leaves_session_unchanged(session):
    before = session.state()
    with pytest.raises(ValueError, match="not in its declared values"):
        session.set_view(d_view(values=(1, 2)))
    assert session.state() == before
