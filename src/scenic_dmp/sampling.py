"""Draw scenes one at a time, keeping per-scene iteration counts and view arguments."""

import random
import time
from contextlib import nullcontext

import numpy as np


def _get_rng_state():
    return random.getstate(), np.random.get_state()


def _set_rng_state(state):
    random.setstate(state[0])
    np.random.set_state(state[1])


class SampleSet:
    """i.i.d. scenes from a compiled program.

    Scenic samples from the global `random` and `numpy.random` generators. The
    set keeps its own copy of their state and swaps it in only while sampling,
    so extend(a) then extend(b) gives the same scenes as extend(a + b) no matter
    what else uses those generators in between, or where a run was stopped.
    """

    def __init__(self, compiled, seed=0):
        self.compiled = compiled
        self.seed = seed
        self.scenes = []
        self.iterations = []
        self.columns = {expr: [] for expr in compiled.param_names}
        saved = _get_rng_state()
        try:
            random.seed(seed)
            np.random.seed(seed)
            self._rng_state = _get_rng_state()
        finally:
            _set_rng_state(saved)

    @property
    def n(self):
        return len(self.scenes)

    def extend(
        self,
        n,
        max_iterations=2000,
        *,
        on_chunk=None,
        should_stop=None,
        lock=None,
        chunk_seconds=0.25,
    ):
        """Draw up to n more scenes. max_iterations bounds the rejection loop per scene.

        Scenes are drawn in chunks of about chunk_seconds. Each chunk is appended
        while holding `lock` (if given), then on_chunk(drawn_so_far) is called.
        should_stop() is checked before every scene; a stopped run keeps the
        scenes drawn so far.
        """
        lock = lock or nullcontext()
        done = 0
        while done < n:
            buf, exc = self._draw(n - done, max_iterations, should_stop, chunk_seconds)
            with lock:
                self._append(buf)
            done += len(buf)
            if buf and on_chunk is not None:
                on_chunk(done)
            if exc is not None:
                raise exc
            if should_stop is not None and should_stop():
                break
        return self

    def _draw(self, n, max_iterations, should_stop, chunk_seconds):
        """Up to n scenes or chunk_seconds of sampling; returns (scenes, exception)."""
        buf = []
        exc = None
        start = time.monotonic()
        saved = _get_rng_state()
        _set_rng_state(self._rng_state)
        try:
            while len(buf) < n:
                if should_stop is not None and should_stop():
                    break
                try:
                    scene, iterations = self.compiled.scenario.generate(maxIterations=max_iterations)
                except Exception as e:  # keep what was drawn before the failure
                    exc = e
                    break
                buf.append((scene, iterations))
                if time.monotonic() - start >= chunk_seconds:
                    break
        finally:
            self._rng_state = _get_rng_state()
            _set_rng_state(saved)
        return buf, exc

    def _append(self, buf):
        for scene, iterations in buf:
            self.scenes.append(scene)
            self.iterations.append(iterations)
            for expr, name in self.compiled.param_names.items():
                self.columns[expr].append(scene.params[name])

    def has(self, args):
        return all(a in self.columns for a in args)

    def rows(self, args, start=0):
        """Per-scene tuples of the sampled values of the given argument expressions."""
        return list(zip(*(self.columns[a][start:] for a in args)))
