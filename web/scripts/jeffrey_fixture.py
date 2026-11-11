"""Write src/lib/jeffrey.fixture.json: cases computed by the Python jeffrey module.

The vitest suite checks the TypeScript port against these, so the browser's
live drag feedback agrees with the server. Run with the project venv:
    npm run fixture
"""

import json
from pathlib import Path

import numpy as np

from scenic_dmp import jeffrey

rng = np.random.default_rng(0)
cases = []
for k in [2, 3, 5, 8]:
    for _ in range(6):
        supported = rng.random(k) > 0.25
        supported[rng.integers(k)] = True
        p_hat = np.where(supported, rng.random(k), 0)
        p_hat /= p_hat.sum()
        nu = np.where(supported, rng.random(k), 0)
        nu /= nu.sum()
        y = int(rng.choice(np.flatnonzero(supported)))
        t = float(rng.choice([rng.random(), 0.0, 1.0, 1.3]))
        rescaled = jeffrey.rescale(nu, y, t, supported)
        w = jeffrey.weights(nu, p_hat)
        a, M = jeffrey.acceptance_probs(w)
        kg = int(rng.integers(2, 5))
        n = 400
        y_idx = rng.choice(k, size=n, p=p_hat)
        g_idx = rng.integers(0, kg, size=n)
        joint = np.zeros((k, kg), dtype=int)
        np.add.at(joint, (y_idx, g_idx), 1)
        counts = joint.sum(axis=1)
        p_emp = counts / n
        nu_emp = np.where(counts > 0, nu, 0)
        nu_emp /= nu_emp.sum()
        w_emp = jeffrey.weights(nu_emp, p_emp)
        sample_w = w_emp[y_idx]
        cases.append({
            "nu": nu.tolist(), "p_hat": p_hat.tolist(), "supported": supported.tolist(),
            "y": y, "t": t, "rescaled": rescaled.tolist(),
            "w": w.tolist(), "a": a.tolist(), "M": float(M),
            "joint": joint.tolist(), "n": n, "p_emp": p_emp.tolist(), "nu_emp": nu_emp.tolist(),
            "after": jeffrey.reweighted_hist(g_idx, sample_w, kg).tolist(),
            "n_eff": float(jeffrey.n_eff(sample_w)),
        })
out = Path(__file__).parent.parent / "src" / "lib" / "jeffrey.fixture.json"
out.write_text(json.dumps(cases))
print(f"wrote {len(cases)} cases to {out}")
