"""Estimate f#mu from the view indices of i.i.d. samples."""

import numpy as np


def counts(y_idx, K):
    """Number of samples landing on each of the K view values."""
    return np.bincount(np.asarray(y_idx, dtype=int), minlength=K)


def wilson(k, n, z=1.96):
    """Wilson score interval for a binomial proportion k/n (elementwise over k)."""
    k = np.asarray(k, dtype=float)
    if n == 0:
        return np.zeros_like(k), np.ones_like(k)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    lo = np.clip(center - half, 0, 1)
    hi = np.clip(center + half, 0, 1)
    # Exact at the ends; rounding can otherwise leave lo slightly above 0 for k = 0.
    lo[k == 0] = 0
    hi[k == n] = 1
    return lo, hi
