"""Write the Jeffrey update for a view into a patched program P′, and check P′ by sampling it.

P′ is P with a block appended (notes.tex, "Program Patch"). For each view value
y with acceptance probability â(y) < 1 it adds

    require not (f(s) == y) or u < â(y)

where u = Range(0, 1) is drawn afresh on every rejection-sampling iteration, so
a scene with f(s) = y is kept with probability â(y). (Scenic's soft
requirements, `require[p]`, are no substitute: Scenic decides which ones are
active once per generated scene, outside the rejection loop.)

f is the view's expression, written as a Python function in P′. The helpers it
uses (isclose, deg, ...) are imported under prefixed names so they can't clash
with the program's own names.
"""

import ast
import re

import numpy as np

from . import estimate, jeffrey
from .sampling import SampleSet
from .view import HELPERS, free_names

PREFIX = "__dmp_"


class PatchError(ValueError):
    pass


def session_patch(session, nu=None):
    """P′ for the session's current view and nu, or for a trial nu that isn't committed.

    Returns {"view", "source", "block", "first_line", "nu", "M", "predicted_iters"}:
    the full P′ source, the appended block alone, and the 1-based line where it starts.
    """
    with session.lock:
        if session.samples is None or getattr(session, "y_idx", None) is None:
            raise PatchError("sample the program first")
        if nu is None:
            nu, w, a, M = session.nu, session.w, session.a, session.M
            blocked = session.blocked
        else:
            nu = np.asarray(nu, dtype=float)
            if nu.shape != session.p_hat.shape or np.any(nu < 0) or nu.sum() <= 0:
                raise PatchError("ν must be nonnegative, with one entry per view value")
            nu = nu / nu.sum()
            blocked = [session.labels[i] for i in np.flatnonzero((nu > 0) & ~session.supported)]
            if not blocked:
                w = jeffrey.weights(nu, session.p_hat)
                a, M = jeffrey.acceptance_probs(w)
        if blocked:
            raise PatchError(
                f"ν puts mass on values with no samples ({', '.join(blocked)}), "
                "so there is no patch"
            )
        view = session.view
        if view.spec is None:
            raise PatchError(f"view {view.name!r} has no expression source to write into P′")
        block = patch_block(view, nu=nu, p_hat=session.p_hat, w=w, a=a, M=M, n=session.n)
        source = session.program.source
        text, first_line = append_block(source, block)
        return {
            "view": view.name,
            "source": text,
            "block": block,
            "first_line": first_line,
            "nu": [float(x) for x in nu],
            "M": float(M),
            "predicted_iters": float(session.mean_iterations * M),
        }


def append_block(source, block):
    head = source.rstrip("\n") + "\n\n"
    return head + block + "\n", head.count("\n") + 1


def patch_block(view, *, nu, p_hat, w, a, M, n):
    """The lines appended to P for the Jeffrey update on `view`."""
    spec = view.spec
    labels = view.labels
    fname = PREFIX + "view_" + _identifier(view.name)
    call = f"{fname}({', '.join(f'({b})' for b in view.args)})"

    width = max(len(label) for label in labels)
    lines = [
        f"# --- Added by scenic-dmp: Jeffrey update for view {view.name!r} ---",
        f"# f#μ̂ estimated from n = {n} scenes of P. A scene with view value y is kept with",
        "# probability â(y) = ŵ(y) / M, where ŵ(y) = ν(y) / f#μ̂(y).",
    ]
    for i, label in enumerate(labels):
        row = f"#   {label:<{width}}  f#μ̂ {p_hat[i]:7.2%}  ν {nu[i]:7.2%}"
        if p_hat[i] > 0:
            row += f"  ŵ {w[i]:.4g}  â {a[i]:.4g}"
        else:
            row += "  (no samples)"
        lines.append(row)
    lines.append(
        f"# M = {M:.4g}: P′ needs about {M:.3g}× as many iterations per scene as P "
        f"(acceptance 1/M = {1 / M:.1%})."
    )

    requires = []
    for i, label in enumerate(labels):
        cond = _condition(view, i, call)
        if a[i] >= 1 - 1e-9:
            continue
        if a[i] <= 0:
            note = "no samples, so ν = 0" if p_hat[i] == 0 else "ν = 0"
            requires.append(f"require not ({cond})  # {label}: {note}, never kept")
        else:
            requires.append(f"require not ({cond}) or {PREFIX}u < {a[i]:.6g}  # {label}")

    if not requires:
        lines.append("# ν = f#μ̂, so no requirement is needed.")
        return "\n".join(lines)

    tree = ast.parse(spec["expr"], mode="eval")
    renamable = (free_names(tree) & set(HELPERS)) - set(view.binding_names)
    renamer = _Rename(renamable)
    body = ast.unparse(renamer.visit(tree))
    if renamer.used:
        imports = ", ".join(
            f"{'radians' if h == 'deg' else h} as {PREFIX}{h}" for h in sorted(renamer.used)
        )
        lines.append(f"from math import {imports}")
    lines.append(f"def {fname}({', '.join(view.binding_names)}):")
    lines.append(f"    return {body}")
    if any(f"{PREFIX}u <" in r for r in requires):
        lines.append(f"{PREFIX}u = Range(0, 1)")
    lines.extend(requires)
    return "\n".join(lines)


def _condition(view, i, call):
    if view.values is not None:
        return f"{call} == {view.values[i]!r}"
    e = view.bins
    K = len(e)
    if i == 0:
        return f"{call} < {_num(e[0])}"
    if i == K:
        return f"{call} >= {_num(e[-1])}"
    return f"{_num(e[i - 1])} <= {call} < {_num(e[i])}"


def _num(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


def _identifier(name):
    ident = re.sub(r"\W", "_", name)
    return ident if ident and not ident[0].isdigit() else "_" + ident


class _Rename(ast.NodeTransformer):
    def __init__(self, names):
        self.names = names
        self.used = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.names:
            self.used.add(node.id)
            return ast.copy_location(ast.Name(PREFIX + node.id, node.ctx), node)
        return node


# --- checking P′ ---------------------------------------------------------------


def validate(session, n, *, seed=None, max_iterations=2000, on_progress=None, should_stop=None):
    """Sample P′ and compare f#μ̂_{P′} with ν.

    Returns (result, samples). result holds f#μ̂_{P′} with Wilson 95% CIs,
    whether each ν(y) lies in its CI, and P′'s measured iterations per scene
    against the prediction (P's iterations × M). on_progress(result) is called
    after every chunk with the partial result.
    """
    patch = session_patch(session)
    with session.lock:
        view = session.view
        program = session.program.with_source(patch["source"])
        seed = session.seed + 1 if seed is None else seed
    compiled = program.compile(list(view.args))
    samples = SampleSet(compiled, seed)
    nu = np.array(patch["nu"])
    result = None

    def summarize():
        rows = samples.rows(view.args)
        y_idx = view.classify(rows)
        k = len(y_idx)
        counts = estimate.counts(y_idx, view.K)
        lo, hi = estimate.wilson(counts, k)
        return {
            "view": view.name,
            "labels": view.labels,
            "n": k,
            "target": n,
            "counts": [int(c) for c in counts],
            "p_hat": [float(c / k) for c in counts],
            "ci_lo": [float(x) for x in lo],
            "ci_hi": [float(x) for x in hi],
            "nu": [float(x) for x in nu],
            "nu_in_ci": [bool(lo[i] <= nu[i] <= hi[i]) for i in range(view.K)],
            "mean_iters": float(np.mean(samples.iterations)),
            "predicted_iters": patch["predicted_iters"],
            "M": patch["M"],
            "source": patch["source"],
            "y_idx": y_idx,
        }

    def on_chunk(_done):
        nonlocal result
        result = summarize()
        if on_progress is not None:
            on_progress(result)

    samples.extend(n, max_iterations, on_chunk=on_chunk, should_stop=should_stop)
    if result is None:
        raise PatchError("P′ produced no scenes")
    return result, samples
