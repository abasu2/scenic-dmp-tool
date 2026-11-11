from pathlib import Path

import pytest

from scenic_dmp import Program
from scenic_dmp.sampling import SampleSet
from scenic_dmp.scene_geom import map_json, scene_json

PEDESTRIAN = Path(__file__).parent.parent / "examples" / "pedestrian.scenic"
SCENIC = Path.home() / "research/scenic-example/vendor/Scenic"


def test_pedestrian_scene_geometry():
    compiled = Program.from_file(PEDESTRIAN).compile(["d"])
    samples = SampleSet(compiled, seed=0).extend(1)
    out = scene_json(samples.scenes[0])
    ego, ped = out["objects"]
    assert ego["ego"] and not ped["ego"]
    assert (ego["cls"], ped["cls"]) == ("Car", "Pedestrian")
    assert len(ped["footprint"]) == 4
    assert ped["y"] == pytest.approx(samples.columns["d"][0] + 1)  # ego front to ped back
    assert map_json(compiled.scenario.workspace) is None


@pytest.mark.slow
def test_driving_map_geometry():
    path = SCENIC / "examples/driving/badlyParkedCarPullingIn.scenic"
    if not path.exists():
        pytest.skip("no vendored Scenic checkout")
    compiled = Program.from_file(path, mode2D=True).compile(["distance from ego to parkedCar"])
    out = map_json(compiled.scenario.workspace)
    assert out["layers"]["roadRegion"]
    minx, miny, maxx, maxy = out["bounds"]
    assert maxx > minx and maxy > miny
    scene = SampleSet(compiled, seed=0).extend(1).scenes[0]
    assert len(scene_json(scene)["objects"]) >= 2
