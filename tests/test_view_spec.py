"""Views built from text specs, as the web app makes them."""

import math
from pathlib import Path

import numpy as np
import pytest

from scenic_dmp import Program, Session, View, ViewError
from scenic_dmp.view import detect_values, parse_value

PEDESTRIAN = Path(__file__).parent.parent / "examples" / "pedestrian.scenic"

BRAKE_SPEC = {
    "name": "brake",
    "bindings": [{"name": "d", "expr": "d"}, {"name": "c", "expr": "c"}],
    "expr": '"brake" if d <= 2 and isclose(c, deg(90)) else "continue"',
    "values": ["brake", "continue"],
}


def test_spec_view_matches_lambda_view():
    program = Program.from_file(PEDESTRIAN)
    lam = View(
        "brake",
        ["d", "c"],
        lambda d, c: "brake" if d <= 2 and math.isclose(c, math.pi / 2) else "continue",
        values=["brake", "continue"],
    )
    a = Session(program, lam, seed=4).sample(1000)
    b = Session(program, View.from_spec(BRAKE_SPEC), seed=4).sample(1000)
    assert np.array_equal(a.y_idx, b.y_idx)
    assert b.view.spec["expr"] == BRAKE_SPEC["expr"]


def test_values_are_parsed_as_literals():
    assert parse_value("1") == 1
    assert parse_value("2.5") == 2.5
    assert parse_value("True") is True
    assert parse_value("brake") == "brake"
    assert parse_value("'1'") == "1"
    view = View.from_spec({**BRAKE_SPEC, "name": "d", "bindings": [{"name": "d", "expr": "d"}],
                           "expr": "int(d)", "values": ["1", "2", "3"]})
    assert view.values == [1, 2, 3]
    assert view.labels == ["1", "2", "3"]


def test_bins_spec():
    view = View.from_spec({
        "name": "dist",
        "bindings": [{"name": "dist", "expr": "distance from ego to ped"}],
        "expr": "dist",
        "bins": [1, 2.5, 4],
    })
    assert view.args == ("distance from ego to ped",)
    assert view.labels == ["< 1", "[1, 2.5)", "[2.5, 4)", "≥ 4"]


@pytest.mark.parametrize(
    "change, field, message",
    [
        ({"expr": "d + q"}, "expr", "undefined names: q"),
        ({"expr": "d +"}, "expr", "syntax error"),
        ({"bindings": [{"name": "d", "expr": "d"}, {"name": "d", "expr": "c"}]}, "bindings", "twice"),
        ({"bindings": [{"name": "if", "expr": "d"}]}, "bindings", "not a valid"),
        ({"bindings": [{"name": "__x", "expr": "d"}]}, "bindings", "can't start"),
        ({"bindings": []}, "bindings", "at least one binding"),
        ({"name": " "}, "name", "needs a name"),
        ({"values": ["a", "a"]}, "values", "duplicate"),
    ],
)
def test_spec_errors_name_the_field(change, field, message):
    with pytest.raises(ViewError, match=message) as info:
        View.from_spec({**BRAKE_SPEC, **change})
    assert info.value.field == field


def test_comprehension_sees_bindings():
    view = View.from_spec({
        "name": "n_small",
        "bindings": [{"name": "a", "expr": "a"}, {"name": "b", "expr": "b"}],
        "expr": "sum(1 for v in (a, b) if v < a + 1)",
        "values": ["0", "1", "2"],
    })
    assert view.classify([(0, 0.5), (0, 3)]).tolist() == [2, 1]


def test_runtime_error_names_the_scene():
    view = View.from_spec({**BRAKE_SPEC, "expr": "1 / (d - d)", "values": ["1"]})
    with pytest.raises(ViewError, match="scene 7 .*ZeroDivisionError"):
        view.classify([(1, 0)], start=7)


def test_detect_values():
    spec = {**BRAKE_SPEC}
    assert detect_values(spec, [(1, math.pi / 2), (3, 0)]) == {"values": ["brake", "continue"]}
    many = detect_values({**spec, "expr": "d * 1.5"}, [(i, 0) for i in range(100)])
    assert many == {"numeric": True, "min": 0.0, "max": 148.5}
