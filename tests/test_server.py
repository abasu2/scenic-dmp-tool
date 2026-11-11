"""The web app's API, end to end through FastAPI's TestClient."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scenic_dmp.server import create_app
from test_view_spec import BRAKE_SPEC

PEDESTRIAN = Path(__file__).parent.parent / "examples" / "pedestrian.scenic"
D_SPEC = {"name": "d", "bindings": [{"name": "d", "expr": "d"}], "expr": "d", "values": ["1", "2", "3"]}


def wait(client, timeout=60):
    """Wait for the running job to finish and return it."""
    state = client.app.state.dmp
    end = time.monotonic() + timeout
    while state.job is not None and state.job.running:
        if time.monotonic() > end:
            raise TimeoutError("job didn't finish")
        time.sleep(0.02)
    return state.job.to_json() if state.job else None


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def sampled(client):
    assert client.post("/api/program/open", json={"path": str(PEDESTRIAN)}).status_code == 200
    r = client.post("/api/views", json={"views": [BRAKE_SPEC, D_SPEC], "f": "brake", "preview": "d"})
    assert r.status_code == 200, r.text
    r = client.post("/api/sample", json={"n": 3000})
    assert r.status_code == 200, r.text
    job = wait(client)
    assert job["error"] is None and job["done"] == 3000
    return client


def test_websocket_sends_everything_on_connect(sampled):
    with sampled.websocket_connect("/ws") as ws:
        types = [ws.receive_json()["type"] for _ in range(4)]
    assert types == ["workspace", "state", "job", "validation"]


def test_sample_edit_patch_validate(sampled):
    c = sampled
    state = c.get("/api/state").json()["state"]["state"]
    assert state["n"] == 3000 and state["labels"] == ["brake", "continue"]
    assert state["previews"][0]["name"] == "d"
    assert not state["nu_edited"]

    assert c.put("/api/nu", json={"nu": [0.5, 0.5]}).status_code == 200
    state = c.get("/api/state").json()["state"]["state"]
    assert state["nu"] == pytest.approx([0.5, 0.5]) and state["nu_edited"]
    assert state["M"] == pytest.approx(0.5 / state["p_hat"][0])

    patch = c.get("/api/patch").json()
    assert "__dmp_view_brake" in patch["block"]
    # A trial ν gives its own patch and commits nothing.
    trial = c.post("/api/patch/preview", json={"nu": [0.2, 0.8]}).json()
    assert "'brake') or __dmp_u <" in trial["block"]
    assert c.get("/api/patch").json()["block"] == patch["block"]
    assert patch["original"] == PEDESTRIAN.read_text()

    assert c.post("/api/validate", json={"n": 2000}).status_code == 200
    assert wait(c)["error"] is None
    v = c.get("/api/state").json()["validation"]["validation"]
    assert v["n"] == 2000 and v["nu_in_ci"] == [True, True]
    assert "y_idx" not in v and "source" not in v

    # Scenes from P′ are classified by f.
    r = c.get("/api/scenes", params={"source": "pprime", "view": "brake", "value": 0, "count": 3}).json()
    assert len(r["scenes"]) == 3
    assert all(s["values"] == {"brake": "brake"} for s in r["scenes"])


def test_bad_nu_and_unknown_values_are_400(sampled):
    r = sampled.put("/api/nu", json={"nu": [1, 2, 3]})
    assert r.status_code == 400 and r.json()["error"]["where"] == "nu"


def test_view_errors_come_back_per_view(client):
    r = client.post("/api/views", json={"views": [BRAKE_SPEC, {**D_SPEC, "expr": "d + q"}]})
    assert r.status_code == 400
    (err,) = r.json()["error"]["errors"]
    assert err["view"] == "d" and err["field"] == "expr" and "q" in err["message"]


def test_reclassify_without_resampling(sampled):
    c = sampled
    session = c.app.state.dmp.session
    scenes = list(session.samples.scenes)
    stricter = {**BRAKE_SPEC, "expr": '"brake" if d <= 1 and isclose(c, deg(90)) else "continue"'}
    r = c.post("/api/views", json={"views": [stricter, D_SPEC], "f": "brake"})
    assert r.json()["resampling"] is False
    assert r.json()["views"][0]["expr"] == stricter["expr"]
    assert session.samples.scenes == scenes
    # A value the view doesn't declare is reported against that view, and nothing changes.
    r = c.post("/api/views", json={"views": [BRAKE_SPEC, {**D_SPEC, "values": ["1", "2"]}]})
    assert r.status_code == 400 and r.json()["error"]["view"] == "d"
    assert c.app.state.dmp.workspace["views"][0]["expr"] == stricter["expr"]


def test_new_binding_resamples(sampled):
    c = sampled
    gap = {"name": "gap", "bindings": [{"name": "g", "expr": "distance from ego to ped"}],
           "expr": "g", "bins": [2, 3, 4]}
    r = c.post("/api/views", json={"views": [BRAKE_SPEC, D_SPEC, gap], "f": "brake"})
    assert r.json()["resampling"] is True
    assert wait(c)["error"] is None
    state = c.get("/api/state").json()["state"]["state"]
    assert [p["name"] for p in state["previews"]] == ["d", "gap"]
    assert state["n"] == 3000


def test_jobs_are_exclusive_and_stoppable(sampled):
    c = sampled
    assert c.post("/api/sample", json={"n": 2_000_000}).status_code == 200
    assert c.post("/api/sample", json={"n": 10}).status_code == 409
    assert c.post("/api/views", json={"views": [BRAKE_SPEC]}).status_code == 409
    assert c.put("/api/nu", json={"nu": [0.4, 0.6]}).status_code == 200  # ν stays editable
    time.sleep(0.3)
    c.post("/api/stop")
    job = wait(c)
    assert job["stopped"] and 0 < job["done"] < 2_000_000
    assert c.app.state.dmp.session.n == 3000 + job["done"]


def test_program_errors_point_at_a_line(client):
    client.post("/api/program", json={"source": "class Car: pass\nego = new Car\nx = Range(0, 1\n"})
    x_spec = {"name": "x", "bindings": [{"name": "x", "expr": "x"}], "expr": "x", "bins": [0.5, 1]}
    assert client.post("/api/views", json={"views": [x_spec]}).status_code == 200
    assert client.post("/api/sample", json={"n": 10}).status_code == 200
    job = wait(client)
    assert job["error"]["where"] == "program"
    assert job["error"]["line"] in (3, 4)


def test_program_edit_marks_dirty(sampled):
    c = sampled
    assert c.get("/api/state").json()["state"]["dirty"] is False
    source = PEDESTRIAN.read_text().replace("2: 0.5", "2: 0.6")
    assert c.post("/api/program", json={"source": source}).json() == {"dirty": True}
    c.post("/api/sample", json={"n": 100})  # dirty, so a fresh sample of the new program
    assert wait(c)["error"] is None
    s = c.get("/api/state").json()["state"]
    assert s["dirty"] is False and s["state"]["n"] == 100


def test_scenes(sampled):
    c = sampled
    r = c.get("/api/scenes", params={"view": "d", "value": 0, "count": 5}).json()
    assert len(r["scenes"]) == 5 and r["total"] > 400
    for scene in r["scenes"]:
        assert scene["values"]["d"] == "1"
        assert scene["args"]["d"] == "1"
        assert [o["cls"] for o in scene["objects"]] == ["Car", "Pedestrian"]
    c.put("/api/nu", json={"nu": [1, 0]})
    r = c.get("/api/scenes", params={"source": "muprime", "count": 8}).json()
    assert all(s["values"]["brake"] == "brake" for s in r["scenes"])
    assert c.get("/api/scenes", params={"view": "nope"}).status_code == 400
    assert c.get("/api/map").json() == {"map": None}


def test_workspace_round_trip(sampled, tmp_path):
    c = sampled
    c.put("/api/nu", json={"nu": [0.5, 0.5]})
    before = c.get("/api/state").json()["state"]["state"]
    path = tmp_path / "ws.json"
    assert c.post("/api/workspace/save", json={"path": str(path)}).status_code == 200

    with TestClient(create_app()) as fresh:
        assert fresh.post("/api/workspace/load", json={"path": str(path)}).status_code == 200
        assert wait(fresh)["error"] is None
        after = fresh.get("/api/state").json()
    assert after["workspace"]["workspace"]["program"]["path"] == str(PEDESTRIAN.resolve())
    state = after["state"]["state"]
    assert state["n"] == before["n"]
    assert state["p_hat"] == before["p_hat"]
    assert state["nu"] == pytest.approx(before["nu"])
    assert state["preview_name"] == "d"


def test_detect_values(sampled):
    c = sampled
    assert c.post("/api/views/detect", json={"spec": D_SPEC}).json() == {"values": ["1", "2", "3"]}
    # Bindings the cache lacks are probed with a short sample.
    gap = {"name": "gap", "bindings": [{"name": "g", "expr": "distance from ego to ped"}], "expr": "g"}
    r = c.post("/api/views/detect", json={"spec": gap}).json()
    assert r == {"values": ["2.0", "3.0", "4.0"]}
    r = c.post("/api/views/detect", json={"spec": {**gap, "expr": "g + q"}})
    assert r.status_code == 400 and r.json()["error"]["field"] == "expr"
