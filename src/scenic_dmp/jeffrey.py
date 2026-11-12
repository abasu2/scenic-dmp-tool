"""Jeffrey's update on a finite view, estimated from samples.

Everything here works on arrays indexed by view value y (0..K-1) or by sample,
and knows nothing about Scenic.
"""

import numpy as np


def weights(nu, p_hat):
    """Jeffrey weights w(y) = nu(y) / p_hat(y) on supported y, 1 elsewhere.

    A value with no samples may still have (f#mu)(y) > 0, so it gets weight 1:
    the patch leaves its scenes alone rather than forbidding them (notes.tex,
    "Program Patch"). This never sets M, since the weights on supported values
    average to 1 under p_hat, so their max is at least 1.

    Raises if nu puts mass on a y with p_hat(y) = 0: reweighting can't create it.
    """
    nu = np.asarray(nu, dtype=float)
    p_hat = np.asarray(p_hat, dtype=float)
    supported = p_hat > 0
    if np.any(nu[~supported] > 0):
        raise ValueError("nu puts mass on view values with no samples")
    w = np.ones_like(p_hat)
    w[supported] = nu[supported] / p_hat[supported]
    return w


def acceptance_probs(w):
    """Per-value acceptance probabilities a(y) = w(y) / M, and M = max w."""
    w = np.asarray(w, dtype=float)
    M = w.max()
    return w / M, M


def reweighted_hist(g_idx, sample_weights, K):
    """Distribution of a second view g under the reweighted samples."""
    sample_weights = np.asarray(sample_weights, dtype=float)
    hist = np.bincount(np.asarray(g_idx, dtype=int), weights=sample_weights, minlength=K)
    return hist / sample_weights.sum()


def n_eff(sample_weights):
    """Kish effective sample size (sum w)^2 / sum w^2."""
    sample_weights = np.asarray(sample_weights, dtype=float)
    return sample_weights.sum() ** 2 / (sample_weights**2).sum()


def rescale(nu, y, t, supported):
    """Set nu(y) = t and rescale the other supported values proportionally.

    This is Jeffrey's rule on the partition {y, not y}: the other values keep
    their ratios. Unsupported values are forced to 0. If the other supported
    values sum to 0, the remaining 1 - t is spread over them uniformly.
    """
    nu = np.asarray(nu, dtype=float)
    supported = np.asarray(supported, dtype=bool)
    if not supported[y]:
        raise ValueError("cannot put mass on a view value with no samples")
    others = supported.copy()
    others[y] = False
    out = np.zeros_like(nu)
    if not others.any():
        out[y] = 1.0
        return out
    t = float(np.clip(t, 0.0, 1.0))
    out[y] = t
    rest = nu[others].sum()
    if rest > 0:
        out[others] = nu[others] * (1 - t) / rest
    else:
        out[others] = (1 - t) / others.sum()
    return out


def uniform(supported):
    """The uniform distribution over the supported view values."""
    supported = np.asarray(supported, dtype=bool)
    return supported / supported.sum()
