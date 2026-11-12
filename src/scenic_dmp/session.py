"""A session: one program, the view f whose nu is being edited, and preview views g."""

import threading

import numpy as np

from . import estimate, jeffrey
from .sampling import SampleSet


class Session:
    """Estimate f#mu from samples of a program and hold the desired nu.

    Until nu is edited it follows f#mu_hat (the identity patch), also while
    samples stream in; reset_nu() returns to that. An edited nu is the user's
    intent, so it survives re-estimation (sample_more, a new view fn) as long as
    the view's labels stay the same. It is kept per view name, so switching
    which view is f and back doesn't lose an edit. If nu puts
    mass on a value with no samples, the session is blocked: w, a and M are None
    until nu is fixed.

    The session is thread-safe: `lock` guards its state, and sampling holds it
    only while appending a chunk of scenes and refreshing the estimates, so nu
    can be edited while sampling runs in another thread. Listeners are called
    (under the lock) after every change.
    """

    def __init__(self, program, view, also=(), *, seed=0):
        self.program = program
        self.seed = seed
        self.samples = None
        self.lock = threading.RLock()
        self.listeners = []
        self._view = view
        self._also = _also_map(also)
        self._nus = {}  # view name -> (labels, edited nu); a view not here follows f#mu_hat
        self._cls = {}  # id(view) -> (view, samples, y_idx), so new scenes are classified once
        self.preview_name = None
        self._fix_preview_name()

    # --- configuration -----------------------------------------------------

    @property
    def view(self):
        return self._view

    @property
    def also(self):
        return list(self._also.values())

    def set_view(self, view):
        """Switch the edited view. Resamples only if it needs new arguments."""
        self._configure(view=view)

    def set_also(self, views):
        self._configure(also=views)

    def needs_resample(self, view=None, also=None):
        """Whether these views need argument expressions the cached scenes lack."""
        if self.samples is None:
            return True
        view = view or self._view
        also_map = self._also if also is None else _also_map(also)
        return not self.samples.has(_arg_exprs(view, also_map))

    def _configure(self, view=None, also=None):
        new_view = view or self._view
        new_also = self._also if also is None else _also_map(also)
        if self.samples is None:
            with self.lock:
                self._view, self._also = new_view, new_also
                self._fix_preview_name()
            return
        if self.samples.has(_arg_exprs(new_view, new_also)):
            with self.lock:
                old = (self._view, self._also, self.preview_name)
                self._view, self._also = new_view, new_also
                self._fix_preview_name()
                try:
                    self._refresh()
                except Exception:
                    self._view, self._also, self.preview_name = old
                    raise
        else:
            n = self.samples.n
            print(f"New view arguments: recompiling and resampling {n} scenes.")
            self.sample(n, view=new_view, also=list(new_also.values()))

    def set_preview(self, name):
        with self.lock:
            if name is not None and name not in self._also:
                raise KeyError(name)
            self.preview_name = name
            self._push()

    def _fix_preview_name(self):
        if self.preview_name not in self._also:
            self.preview_name = next(iter(self._also), None)

    # --- sampling ----------------------------------------------------------

    def sample(
        self,
        n,
        max_iterations=2000,
        *,
        program=None,
        view=None,
        also=None,
        seed=None,
        on_progress=None,
        should_stop=None,
    ):
        """Compile the program with the views' arguments and draw n fresh scenes.

        program, view, also and seed replace the session's own once the first
        chunk of scenes is in, so until then the old estimates stay visible.
        """
        program = program or self.program
        view = view or self._view
        also_map = self._also if also is None else _also_map(also)
        seed = self.seed if seed is None else seed
        compiled = program.compile(_arg_exprs(view, also_map))
        new = SampleSet(compiled, seed)
        swapped = False

        def on_chunk(done):
            nonlocal swapped
            with self.lock:
                if not swapped:
                    old = self._snapshot()
                    self.program, self._view, self._also = program, view, also_map
                    self.samples, self.seed = new, seed
                    self._cls.clear()
                    self._fix_preview_name()
                    swapped = True
                    try:
                        self._refresh()
                    except Exception:
                        self._restore(old)
                        raise
                else:
                    self._refresh()
            if on_progress is not None:
                on_progress(done)

        new.extend(n, max_iterations, on_chunk=on_chunk, should_stop=should_stop)
        return self

    def sample_more(self, n, max_iterations=2000, *, on_progress=None, should_stop=None):
        if self.samples is None:
            return self.sample(n, max_iterations, on_progress=on_progress, should_stop=should_stop)

        def on_chunk(done):
            with self.lock:
                self._refresh()
            if on_progress is not None:
                on_progress(done)

        self.samples.extend(
            n, max_iterations, on_chunk=on_chunk, should_stop=should_stop, lock=self.lock
        )
        return self

    def _snapshot(self):
        return (self.program, self._view, self._also, self.samples, self.seed, self.preview_name)

    def _restore(self, old):
        self.program, self._view, self._also, self.samples, self.seed, self.preview_name = old
        self._cls.clear()

    @property
    def n(self):
        """The number of scenes behind the current estimates."""
        if self.samples is None:
            return 0
        y_idx = getattr(self, "y_idx", None)
        return self.samples.n if y_idx is None else len(y_idx)

    @property
    def mean_iterations(self):
        """P's own mean rejection-sampling iterations per accepted scene."""
        return float(np.mean(self.samples.iterations[: self.n]))

    # --- estimates ---------------------------------------------------------

    def _classify(self, view):
        cached = self._cls.get(id(view))
        if cached is not None and cached[0] is view and cached[1] is self.samples:
            old = cached[2]
        else:
            old = np.empty(0, dtype=int)
        start = len(old)
        if start < self.samples.n:
            new = view.classify(self.samples.rows(view.args, start), start=start)
            idx = np.concatenate([old, new]).astype(int)
        else:
            idx = old
        self._cls[id(view)] = (view, self.samples, idx)
        return idx

    def _refresh(self):
        """Recompute every estimate from the samples. Commits nothing if a view fails."""
        view = self._view
        y_idx = self._classify(view)
        g_idx = {name: self._classify(g) for name, g in self._also.items()}
        n = len(y_idx)
        labels = view.labels
        counts = estimate.counts(y_idx, view.K)
        joint = {}
        for name, g in self._also.items():
            table = np.zeros((view.K, g.K), dtype=int)
            np.add.at(table, (y_idx, g_idx[name]), 1)
            joint[name] = table
        live = {id(view)} | {id(g) for g in self._also.values()}
        self._cls = {k: v for k, v in self._cls.items() if k in live}

        self.labels = labels
        self.y_idx = y_idx
        self.counts = counts
        self.p_hat = counts / n
        self.ci = estimate.wilson(counts, n)
        self.supported = counts > 0
        self._g_idx = g_idx
        self._joint = joint
        stored = self._nus.get(view.name)
        if stored is not None and list(stored[0]) != labels:
            del self._nus[view.name]
        self._update()

    def _update(self):
        nu = self.nu
        unsupported_mass = (nu > 0) & ~self.supported
        self.blocked = [self.labels[i] for i in np.flatnonzero(unsupported_mass)]
        if self.blocked:
            self.w = self.a = self.M = self.acceptance = None
        else:
            self.w = jeffrey.weights(nu, self.p_hat)
            self.a, self.M = jeffrey.acceptance_probs(self.w)
            self.acceptance = 1 / self.M
        self._push()

    @property
    def nu(self):
        stored = self._nus.get(self._view.name)
        if stored is not None:
            return stored[1]
        p_hat = getattr(self, "p_hat", None)
        return None if p_hat is None else p_hat.copy()

    @property
    def nu_edited(self):
        return self._view.name in self._nus

    @property
    def projected_iterations(self):
        """Expected iterations per scene of the patched program: P's iterations times M."""
        return None if self.M is None else self.mean_iterations * self.M

    def preview(self, name=None):
        """g#mu_hat and g#mu_hat' for preview view g, with the effective sample size."""
        with self.lock:
            name = name or self.preview_name
            if name is None:
                return None
            g = self._also[name]
            g_idx = self._g_idx[name]
            before = estimate.counts(g_idx, g.K) / self.n
            after = n_eff = None
            if self.w is not None:
                sample_weights = self.w[self.y_idx]
                after = jeffrey.reweighted_hist(g_idx, sample_weights, g.K)
                n_eff = jeffrey.n_eff(sample_weights)
            return {"name": name, "labels": g.labels, "before": before, "after": after, "n_eff": n_eff}

    def view_index(self, name):
        """Per-scene value indices of the edited view f or a preview view g."""
        with self.lock:
            if name == self._view.name:
                return self.y_idx
            return self._g_idx[name]

    # --- editing nu --------------------------------------------------------

    def set_nu(self, nu):
        """Set nu from a sequence over the view's labels or a {label: prob} dict.

        Values are normalized. Mass on a value with no samples is refused.
        """
        with self.lock:
            if isinstance(nu, dict):
                unknown = set(map(str, nu)) - set(self.labels)
                if unknown:
                    raise ValueError(f"unknown view values: {sorted(unknown)}")
                by_label = {str(k): v for k, v in nu.items()}
                nu = [by_label.get(label, 0.0) for label in self.labels]
            nu = np.asarray(nu, dtype=float)
            if nu.shape != (len(self.labels),):
                raise ValueError(f"nu needs {len(self.labels)} entries, got {nu.shape}")
            if not np.all(np.isfinite(nu)) or np.any(nu < 0):
                raise ValueError("nu must be finite and nonnegative")
            bad = [self.labels[i] for i in np.flatnonzero((nu > 0) & ~self.supported)]
            if bad:
                raise ValueError(f"no samples have these view values, so nu must be 0 there: {bad}")
            if nu.sum() <= 0:
                raise ValueError("nu must have positive total mass")
            self._nus[self._view.name] = (tuple(self.labels), nu / nu.sum())
            self._update()

    def drag(self, label, t):
        """Set nu(label) = t, rescaling the other values proportionally."""
        with self.lock:
            self.set_nu(jeffrey.rescale(self.nu, self.labels.index(str(label)), t, self.supported))

    def reset_nu(self):
        """Make nu follow f#mu_hat again: the identity patch."""
        with self.lock:
            self._nus.pop(self._view.name, None)
            self._update()

    def uniform_nu(self):
        with self.lock:
            self.set_nu(jeffrey.uniform(self.supported))

    def preset_nu(self, view_name, by_label):
        """Store nu for a view by label, to apply once its estimates match those labels."""
        with self.lock:
            labels = tuple(str(k) for k in by_label)
            self._nus[view_name] = (labels, np.array([float(v) for v in by_label.values()]))

    def nus_by_label(self):
        """Every edited nu as {view name: {label: prob}}."""
        with self.lock:
            return {
                name: {label: float(p) for label, p in zip(labels, nu)}
                for name, (labels, nu) in self._nus.items()
            }

    # --- display -----------------------------------------------------------

    def summary(self):
        """A plain-text table of f#mu_hat, nu, w and a."""
        with self.lock:
            lines = [
                f"view {self._view.name!r}: n = {self.n}, "
                f"P iterations/scene = {self.mean_iterations:.3g}"
            ]
            if self.blocked:
                lines.append(f"BLOCKED: nu has mass on values with no samples: {self.blocked}")
            else:
                lines.append(
                    f"M = {self.M:.4g}, acceptance 1/M = {self.acceptance:.4g}, "
                    f"P' iterations/scene ≈ {self.projected_iterations:.3g}"
                )
            width = max(len(label) for label in self.labels)
            for i, label in enumerate(self.labels):
                row = (
                    f"  {label:<{width}}  {self.counts[i]:>7}/{self.n}  {self.p_hat[i]:7.2%} "
                    f"[{self.ci[0][i]:6.2%}, {self.ci[1][i]:6.2%}]  ν {self.nu[i]:7.2%}"
                )
                if self.w is not None:
                    row += f"  ŵ {self.w[i]:.4g}  â {self.a[i]:.4g}"
                if not self.supported[i]:
                    row += "  (no samples)"
                lines.append(row)
            return "\n".join(lines)

    def state(self):
        """Everything a front end needs to draw f#mu_hat, nu and the previews, as plain JSON."""
        with self.lock:
            if self.samples is None or getattr(self, "y_idx", None) is None:
                return {"n": 0, "view": self._view.name, "seed": self.seed}
            previews = []
            for name, g in self._also.items():
                previews.append({
                    "name": name,
                    "labels": g.labels,
                    "counts": [int(k) for k in estimate.counts(self._g_idx[name], g.K)],
                    "joint": self._joint[name].tolist(),
                })
            return {
                "n": self.n,
                "seed": self.seed,
                "view": self._view.name,
                "labels": self.labels,
                "counts": [int(k) for k in self.counts],
                "p_hat": _floats(self.p_hat),
                "ci_lo": _floats(self.ci[0]),
                "ci_hi": _floats(self.ci[1]),
                "supported": [bool(s) for s in self.supported],
                "nu": _floats(self.nu),
                "nu_edited": self.nu_edited,
                "w": _floats(self.w),
                "a": _floats(self.a),
                "M": _float(self.M),
                "acceptance": _float(self.acceptance),
                "mean_iters_P": self.mean_iterations,
                "blocked": self.blocked,
                "previews": previews,
                "preview_name": self.preview_name,
            }

    def _push(self):
        for listener in list(self.listeners):
            listener(self)


def _also_map(views):
    out = {}
    for g in views:
        if g.name in out:
            raise ValueError(f"two preview views are named {g.name!r}")
        out[g.name] = g
    return out


def _arg_exprs(view, also_map):
    exprs = list(view.args)
    for g in also_map.values():
        exprs.extend(g.args)
    return list(dict.fromkeys(exprs))


def _floats(xs):
    return None if xs is None else [float(x) for x in xs]


def _float(x):
    return None if x is None else float(x)
