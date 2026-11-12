"""Exact checks against the worked example in scenic-dmp/example.md.

The six scenes (d, c) have probabilities 0.1, 0.1, 0.25, 0.25, 0.15, 0.15, so
20 equally weighted samples with multiplicities 2, 2, 5, 5, 3, 3 represent mu
exactly.
"""

import numpy as np
import pytest

from scenic_dmp import estimate, jeffrey

BRAKE, CONTINUE = 0, 1
# (d, c in degrees, f(s), multiplicity out of 20)
SCENES = [
    (1, 90, BRAKE, 2),
    (1, 0, CONTINUE, 2),
    (2, 90, BRAKE, 5),
    (2, 0, CONTINUE, 5),
    (3, 90, CONTINUE, 3),
    (3, 0, CONTINUE, 3),
]


def samples():
    rows = [s for s in SCENES for _ in range(s[3])]
    d_idx = np.array([r[0] - 1 for r in rows])
    c_idx = np.array([r[1] == 90 for r in rows], dtype=int)
    f_idx = np.array([r[2] for r in rows])
    return d_idx, c_idx, f_idx


def test_pushforward():
    _, _, f_idx = samples()
    p_hat = estimate.counts(f_idx, 2) / len(f_idx)
    assert p_hat == pytest.approx([0.35, 0.65])


def test_weights_and_acceptance():
    p_hat = np.array([0.35, 0.65])
    nu = np.array([0.5, 0.5])
    w = jeffrey.weights(nu, p_hat)
    assert w == pytest.approx([10 / 7, 10 / 13])
    a, M = jeffrey.acceptance_probs(w)
    assert M == pytest.approx(10 / 7)
    assert a == pytest.approx([1, 7 / 13])
    assert (p_hat * a).sum() == pytest.approx(1 / M) == pytest.approx(0.7)


def test_weights_reject_unsupported_mass():
    with pytest.raises(ValueError):
        jeffrey.weights([0.5, 0.5, 0.0], [0.0, 1.0, 0.0])


def test_unsupported_values_get_weight_one():
    # A value with no samples is left alone (notes.tex, "Program Patch").
    assert jeffrey.weights([0.0, 1.0, 0.0], [0.0, 1.0, 0.0]) == pytest.approx([1, 1, 1])
    w = jeffrey.weights([0.5, 0.5, 0.0], [0.35, 0.65, 0.0])
    assert w == pytest.approx([10 / 7, 10 / 13, 1])
    a, M = jeffrey.acceptance_probs(w)
    # It never sets M, so its acceptance probability is 1/M.
    assert M == pytest.approx(10 / 7)
    assert a == pytest.approx([1, 7 / 13, 7 / 10])


def test_reweighting_matches_mu_prime():
    d_idx, c_idx, f_idx = samples()
    n = len(f_idx)
    w = jeffrey.weights([0.5, 0.5], estimate.counts(f_idx, 2) / n)
    sw = w[f_idx]
    # Self-normalization is free: the weights already sum to n.
    assert sw.sum() == pytest.approx(n)

    assert jeffrey.reweighted_hist(f_idx, sw, 2) == pytest.approx([0.5, 0.5])
    mu_d = jeffrey.reweighted_hist(d_idx, sw, 3)
    assert mu_d[0] == pytest.approx(1 / 7 + 1 / 13)

    # Under mu', d and c are no longer independent (example.md, last paragraph).
    joint = jeffrey.reweighted_hist(d_idx * 2 + c_idx, sw, 6).reshape(3, 2)
    assert joint[0, 1] / joint[0].sum() == pytest.approx(13 / 20)
    assert joint[2, 1] / joint[2].sum() == pytest.approx(1 / 2)


def test_n_eff():
    assert jeffrey.n_eff(np.ones(10)) == pytest.approx(10)
    assert jeffrey.n_eff([1, 0, 0, 0]) == pytest.approx(1)


class TestRescale:
    def test_keeps_sum_and_ratios(self):
        nu = np.array([0.2, 0.3, 0.5])
        out = jeffrey.rescale(nu, 0, 0.6, [True, True, True])
        assert out.sum() == pytest.approx(1)
        assert out[0] == pytest.approx(0.6)
        assert out[2] / out[1] == pytest.approx(0.5 / 0.3)

    def test_unsupported_stay_zero(self):
        out = jeffrey.rescale([0.0, 0.4, 0.6], 1, 0.1, [False, True, True])
        assert out == pytest.approx([0.0, 0.1, 0.9])

    def test_unsupported_mass_is_dropped(self):
        # A blocked nu (mass on an unsupported value) is repaired by any drag.
        out = jeffrey.rescale([0.3, 0.3, 0.4], 1, 0.5, [False, True, True])
        assert out == pytest.approx([0.0, 0.5, 0.5])

    def test_clamps_t(self):
        assert jeffrey.rescale([0.5, 0.5], 0, 1.7, [True, True]) == pytest.approx([1, 0])
        assert jeffrey.rescale([0.5, 0.5], 0, -1, [True, True]) == pytest.approx([0, 1])

    def test_others_all_zero_spread_uniformly(self):
        out = jeffrey.rescale([1.0, 0.0, 0.0], 0, 0.4, [True, True, True])
        assert out == pytest.approx([0.4, 0.3, 0.3])

    def test_only_supported_value_is_fixed_at_one(self):
        assert jeffrey.rescale([0.0, 1.0], 1, 0.3, [False, True]) == pytest.approx([0, 1])

    def test_refuses_unsupported_target(self):
        with pytest.raises(ValueError):
            jeffrey.rescale([0.0, 1.0], 0, 0.3, [False, True])


def test_uniform():
    assert jeffrey.uniform([True, False, True]) == pytest.approx([0.5, 0, 0.5])


def test_wilson():
    lo, hi = estimate.wilson(np.array([0, 35, 100]), 100)
    assert lo[0] == 0 and hi[0] > 0
    assert lo[1] < 0.35 < hi[1]
    assert hi[2] == pytest.approx(1)
    lo, hi = estimate.wilson(np.array([3]), 0)
    assert (lo[0], hi[0]) == (0, 1)
