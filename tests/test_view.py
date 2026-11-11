import numpy as np
import pytest

from scenic_dmp.view import View


def test_numeric_bins_with_overflow():
    v = View("x", ["x"], float, bins=[0, 1, 2])
    assert v.labels == ["< 0", "[0, 1)", "[1, 2)", "≥ 2"]
    idx = v.classify([(-0.5,), (0,), (0.99,), (1,), (2,), (7,)])
    assert idx.tolist() == [0, 1, 1, 2, 3, 3]


def test_numeric_nan_raises():
    v = View("x", ["x"], float, bins=[0, 1])
    with pytest.raises(ValueError, match="NaN"):
        v.classify([(float("nan"),)])


def test_bins_must_increase():
    with pytest.raises(ValueError):
        View("x", ["x"], float, bins=[0, 0, 1])
    with pytest.raises(ValueError):
        View("x", ["x"], float, bins=[0])


def test_categorical():
    v = View("brake", ["d", "c"], lambda d, c: "brake" if d <= 2 and c else "continue",
             values=["brake", "continue"])
    assert v.labels == ["brake", "continue"]
    assert v.classify([(1, True), (3, True), (2, False)]).tolist() == [0, 1, 1]


def test_categorical_unexpected_values_listed():
    v = View("d", ["d"], int, values=[1, 2])
    with pytest.raises(ValueError, match="3, 4"):
        v.classify([(1,), (3,), (4,), (3,)])


def test_exactly_one_of_values_or_bins():
    with pytest.raises(ValueError):
        View("x", ["x"], float)
    with pytest.raises(ValueError):
        View("x", ["x"], float, values=[1], bins=[0, 1])


def test_single_arg_string():
    assert View("d", "d", int, values=[1]).args == ("d",)


def test_changing_fn_reclassifies():
    rows = [(1,), (2,), (3,)]
    a = View("d", ["d"], lambda d: d <= 1, values=[True, False])
    b = View("d", ["d"], lambda d: d <= 2, values=[True, False])
    assert a.classify(rows).tolist() == [0, 1, 1]
    assert b.classify(rows).tolist() == [0, 0, 1]
