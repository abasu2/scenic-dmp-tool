"""Views defined in the program as `param view_<name> = <expr>`."""

import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from scenic_dmp import Program, Session, View, session_patch, validate
from scenic_dmp.server import create_app
from scenic_dmp.source_views import auto_y, discover, merge, nice_bins
from test_view_spec import BRAKE_SPEC

EXAMPLE = Path(__file__).parent.parent / "examples" / "pedestrian_views.scenic"


def source_spec(name, **y):
    found = {d["name"]: d for d in discover(EXAMPLE.read_text())}
    return {**found[name], "source": True, **y}


def test_discover():
    source = EXAMPLE.read_text() + "param other = 3, view_gap = (distance\n    from ego to ped)\n"
    found = discover(source)
    assert [(d["name"], d["param"], d["expr"]) for d in found] == [
        ("brake", "view_brake", "brake(d, c)"),
        ("d", "view_d", "d"),
        ("gap", "view_gap", "distance from ego to ped"),
    ]
    lines = source.splitlines()
    assert lines[found[0]["line"] - 1] == "param view_brake = brake(d, c)"
    assert discover(source + "x = (\n") is None


def test_merge_keeps_values_by_name():
    old = [
        {"name": "brake", "source": True, "param": "view_brake", "expr": "f(d)", "line": 3, "values": ["a"]},
        {"name": "gone", "source": True, "param": "view_gone", "expr": "d", "line": 4, "bins": [1, 2]},
        BRAKE_SPEC | {"name": "form"},
    ]
    new = merge(old, [{"name": "brake", "param": "view_brake", "expr": "brake(d, c)", "line": 9}])
    assert [s["name"] for s in new] == ["brake", "form"]
    assert new[0]["expr"] == "brake(d, c)" and new[0]["values"] == ["a"] and new[0]["line"] == 9
    assert merge(old, None) is old


def test_auto_y_and_nice_bins():
    assert auto_y({"values": ["1", "2"]}) == {"values": ["1", "2"]}
    assert auto_y({"numeric": True, "min": 21.3, "max": 49.8}) == {"bins": [20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]}
    # A maximum on an edge gets one more edge, so it lands in a bin rather than the overflow.
    assert nice_bins(0, 1) == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2]
    with pytest.raises(ValueError):
        auto_y({"values": None, "too_many": True})


def test_source_view_matches_form_view():
    program = Program.from_file(EXAMPLE)
    a = Session(program, View.from_spec(BRAKE_SPEC), seed=5).sample(1500)
    src = View.from_spec(source_spec("brake", values=["brake", "continue"]))
    assert src.args == ("globalParameters.view_brake",)
    b = Session(program, src, seed=5).sample(1500)
    assert np.array_equal(a.y_idx, b.y_idx)


def test_source_patch_calls_the_programs_function():
    program = Program.from_file(EXAMPLE)
    s = Session(program, View.from_spec(source_spec("brake", values=["brake", "continue"])), seed=0).sample(4000)
    s.set_nu({"brake": 0.5, "continue": 0.5})
    block = session_patch(s)["block"]
    assert "def __dmp_view" not in block and "import" not in block
    assert f"require not (brake(d, c) == 'continue') or __dmp_u < {s.a[1]:.6g}" in block
    result, _ = validate(s, 3000)
    assert result["nu_in_ci"] == [True, True]


def test_source_patch_parenthesizes_scenic_operators():
    program = Program(EXAMPLE.read_text() + "param view_gap = distance from ego to ped\n", EXAMPLE)
    gap = {**discover(program.source)[-1], "source": True, "bins": [2.5, 3.5]}
    s = Session(program, View.from_spec(gap), seed=0).sample(2000)
    assert s.labels == ["< 2.5", "[2.5, 3.5)", "≥ 3.5"]
    s.set_nu([1, 1, 1])
    block = session_patch(s)["block"]
    # "< 2.5" has the largest weight (â = 1), so only the other two bins get a requirement.
    assert "(distance from ego to ped) < 2.5" not in block
    assert "require not (2.5 <= (distance from ego to ped) < 3.5) or __dmp_u <" in block
    result, _ = validate(s, 2000)
    assert all(result["nu_in_ci"])


def wait(client, timeout=60):
    state = client.app.state.dmp
    end = time.monotonic() + timeout
    while state.job is not None and state.job.running:
        assert time.monotonic() < end, "job didn't finish"
        time.sleep(0.02)
    return state.job.to_json()


def test_server_discovers_detects_and_follows_edits():
    with TestClient(create_app()) as c:
        c.post("/api/program/open", json={"path": str(EXAMPLE)})
        ws = c.get("/api/state").json()["workspace"]["workspace"]
        assert [(v["name"], v.get("values")) for v in ws["views"]] == [("brake", None), ("d", None)]
        assert ws["f"] == "brake" and ws["preview"] == "d"

        # Detect works before any sampling, from a probe.
        r = c.post("/api/views/detect", json={"spec": ws["views"][1]}).json()
        assert r == {"values": ["1", "2", "3"]}

        # Sampling detects the missing values first.
        c.post("/api/sample", json={"n": 2000})
        job = wait(c)
        assert job["error"] is None and job["done"] == 2000
        s = c.get("/api/state").json()
        views = s["workspace"]["workspace"]["views"]
        assert views[0]["values"] == ["brake", "continue"] and views[1]["values"] == ["1", "2", "3"]
        assert s["state"]["state"]["labels"] == ["brake", "continue"]
        assert s["state"]["state"]["previews"][0]["name"] == "d"

        # The client can't change a source view's expression, only its values.
        stale = [{**views[0], "expr": "something else", "values": ["continue", "brake"]}, views[1]]
        r = c.post("/api/views", json={"views": stale, "f": "brake"}).json()
        assert r["views"][0]["expr"] == "brake(d, c)" and r["views"][0]["values"] == ["continue", "brake"]

        # Removing a view's param from P removes the view; f falls back.
        source = EXAMPLE.read_text().replace("param view_brake = brake(d, c)\n", "")
        c.post("/api/program", json={"source": source})
        ws = c.get("/api/state").json()["workspace"]["workspace"]
        assert [v["name"] for v in ws["views"]] == ["d"] and ws["f"] == "d"

        # A syntax error while typing keeps the last good views.
        c.post("/api/program", json={"source": source + "x = (\n"})
        ws = c.get("/api/state").json()["workspace"]["workspace"]
        assert [v["name"] for v in ws["views"]] == ["d"]
