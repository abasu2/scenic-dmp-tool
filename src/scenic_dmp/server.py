"""The local web app: a FastAPI server over one Session.

Commands come in over REST; the server pushes typed JSON messages to every
connected WebSocket:

- {"type": "workspace", ...}  program source and settings, view specs, f, g, seed, n
- {"type": "state", ...}      Session.state() plus whether the program changed since sampling
- {"type": "job", ...}        the running or last job: sampling or checking P′
- {"type": "validation", ...} f#μ̂_{P′} against ν, or null

All Scenic compiling and sampling happens on one worker thread, since Scenic
keeps global state. The Session's lock lets ν be edited while a job runs.
"""

import asyncio
import json
import math
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .patch import PatchError, session_patch, validate
from .program import Program, ProgramError
from .scene_geom import map_json, scene_json
from .session import Session
from .source_views import auto_y, discover, merge, needs_y
from .view import View, ViewError, detect_values, spec_args, spec_function

WEB_DIST = Path(__file__).parent / "web_dist"
WORKSPACE_VERSION = 1


class AppError(Exception):
    """A command failed; reported to the client as {"error": {...}} with a status code."""

    def __init__(self, message, status=400, **info):
        super().__init__(message)
        self.status = status
        self.info = {"message": message, **info}


class Job:
    def __init__(self, kind, target):
        self.kind = kind
        self.target = target
        self.done = 0
        self.started = time.monotonic()
        self.finished = None
        self.running = True
        self.stop = threading.Event()
        self.error = None
        self.note = None
        self.last_push = 0.0

    def to_json(self):
        end = self.finished or time.monotonic()
        elapsed = end - self.started
        return {
            "kind": self.kind,
            "running": self.running,
            "done": self.done,
            "target": self.target,
            "elapsed": elapsed,
            "rate": self.done / elapsed if elapsed > 0 else None,
            "stopped": self.stop.is_set(),
            "error": self.error,
            "note": self.note,
        }


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scenic")
        self.loop = None
        self.clients = set()
        self.workspace = {
            "program": {"source": "", "path": None, "mode2D": False, "params": {}},
            "source_rev": 0,
            "views": [],
            "f": None,
            "preview": None,
            "seed": 0,
            "n": 1000,
        }
        self.pending_nu = {}  # view name -> {label: p}, from a loaded workspace
        self.session = None
        self.job = None
        self.validation = None
        self.validation_samples = None
        self._map_cache = {}

    # --- messages ------------------------------------------------------------

    def publish(self, msg):
        """Send a message to every client. Safe to call from any thread."""
        if self.loop is None or not self.clients:
            return
        data = json.dumps(msg, allow_nan=False)
        asyncio.run_coroutine_threadsafe(self._broadcast(data), self.loop)

    async def _broadcast(self, data):
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                self.clients.discard(ws)

    def messages(self):
        return [
            self.workspace_msg(),
            self.state_msg(),
            {"type": "job", "job": self.job.to_json() if self.job else None},
            {"type": "validation", "validation": self.validation},
        ]

    def workspace_msg(self):
        with self.lock:
            return {"type": "workspace", "workspace": json.loads(json.dumps(self.workspace))}

    def state_msg(self):
        session = self.session
        state = session.state() if session is not None else {"n": 0}
        program_id = None
        if session is not None and session.samples is not None:
            program_id = str(id(session.samples.compiled))
        return {"type": "state", "state": state, "dirty": self.dirty(), "program_id": program_id}

    def _on_session_change(self, _session):
        self.publish(self.state_msg())

    def push_job(self, force=False):
        job = self.job
        if job is None:
            return
        now = time.monotonic()
        if force or now - job.last_push >= 0.2:
            job.last_push = now
            self.publish({"type": "job", "job": job.to_json()})

    # --- workspace -------------------------------------------------------------

    def program(self):
        p = self.workspace["program"]
        try:
            return Program(p["source"], p["path"], mode2D=p["mode2D"], params=p["params"])
        except ProgramError as exc:
            raise AppError(str(exc), where="program") from exc

    def _program_key(self, program):
        return (program.source, str(program.path) if program.path else None, program.mode2D,
                json.dumps(program.params, sort_keys=True, default=str))

    def dirty(self):
        """Whether the program or its settings changed since the scenes were sampled."""
        session = self.session
        if session is None or session.samples is None:
            return False
        p = self.workspace["program"]
        here = (p["source"], str(Path(p["path"]).resolve()) if p["path"] else None, p["mode2D"],
                json.dumps(p["params"], sort_keys=True, default=str))
        return here != self._program_key(session.program)

    def set_program(self, source=None, path=..., mode2D=None, params=None, external=False):
        views_changed = False
        with self.lock:
            p = self.workspace["program"]
            if source is not None:
                p["source"] = source
                views_changed = self._rediscover()
            if path is not ...:
                p["path"] = str(Path(path).expanduser().resolve()) if path else None
            if mode2D is not None:
                p["mode2D"] = bool(mode2D)
            if params is not None:
                p["params"] = dict(params)
            if external:
                self.workspace["source_rev"] += 1
        if external or views_changed:
            self.publish(self.workspace_msg())
        self.publish(self.state_msg())

    def _rediscover(self):
        """Update the source views (`param view_<name> = ...`) from the program. Under self.lock."""
        ws = self.workspace
        merged = merge(ws["views"], discover(ws["program"]["source"]))
        if merged == ws["views"]:
            return False
        ws["views"] = merged
        names = [s["name"] for s in merged]
        if ws["f"] not in names:
            ws["f"] = names[0] if names else None
        if ws["preview"] not in names or ws["preview"] == ws["f"]:
            ws["preview"] = next((n for n in names if n != ws["f"]), None)
        return True

    def _reconcile(self, specs):
        """The client's specs, with source views as the program defines them.

        The client only chooses a source view's values or bins; its name,
        expression and line come from the program.
        """
        with self.lock:
            discovered = discover(self.workspace["program"]["source"])
            if discovered is None:  # the program doesn't parse right now: keep what we had
                discovered = [{k: s.get(k) for k in ("name", "param", "expr", "line")}
                              for s in self.workspace["views"] if s.get("source")]
        return merge(specs, discovered)

    def open_program(self, path, mode2D=None):
        path = Path(path).expanduser()
        try:
            source = path.read_text()
        except OSError as exc:
            raise AppError(f"can't read {path}: {exc.strerror or exc}", where="program") from exc
        self.set_program(source, path, mode2D=mode2D, external=True)

    def build_views(self, specs, f=None):
        """View objects from specs, with errors listed per view."""
        views, errors, names = [], [], set()
        for i, spec in enumerate(specs):
            try:
                view = View.from_spec(spec)
            except ViewError as exc:
                errors.append({"index": i, "view": spec.get("name"), "field": exc.field,
                               "message": str(exc)})
                continue
            except (KeyError, TypeError) as exc:
                errors.append({"index": i, "view": spec.get("name"), "field": None,
                               "message": f"malformed view spec: {exc}"})
                continue
            if view.name in names:
                errors.append({"index": i, "view": view.name, "field": "name",
                               "message": f"two views are named {view.name!r}"})
                continue
            names.add(view.name)
            views.append(view)
        if errors:
            raise AppError("some views are invalid", where="views", errors=errors)
        f_view = next((v for v in views if v.name == f), views[0] if views else None)
        also = [v for v in views if v is not f_view]
        return views, f_view, also

    def set_views(self, specs, f=None, preview=None):
        self.require_idle()
        specs = self._reconcile(specs)
        # Source views without values or bins wait for the next sample, which detects them.
        waiting = [s for s in specs if needs_y(s)]
        views, f_view, also = self.build_views([s for s in specs if not needs_y(s)], f)
        with self.lock:
            session = self.session
            resample = False
            if f_view is not None and session is not None and session.samples is not None:
                if waiting or session.needs_resample(f_view, also):
                    resample = True
                else:
                    try:
                        with session.lock:
                            session._configure(view=f_view, also=also)
                            if preview in {g.name for g in also}:
                                session.preview_name = preview
                    except ViewError as exc:
                        raise AppError(str(exc), where="views", view=_view_of(exc, f_view, also),
                                       field=exc.field) from exc
            built = {v.name: v.spec for v in views}
            self.workspace["views"] = [built.get(s["name"], s) for s in specs]
            all_names = [s["name"] for s in specs]
            self.workspace["f"] = f if f in all_names else (f_view.name if f_view else None)
            names = [n for n in all_names if n != self.workspace["f"]]
            self.workspace["preview"] = preview if preview in names else (names[0] if names else None)
            if f_view is None and not waiting:
                self.session = None
            self.clear_validation()
        self.publish(self.workspace_msg())
        self.publish(self.state_msg())
        if resample:
            self.start_sample(session.n or self.workspace["n"], fresh=True)
        with self.lock:
            ws = self.workspace
            return {"resampling": resample, "views": ws["views"], "f": ws["f"], "preview": ws["preview"]}

    def detect_rows(self, spec, n=300, seconds=5.0):
        """Sampled values of a spec's arguments: from the cached scenes, or a short probe run."""
        if spec.get("source"):
            spec = next((s for s in self._reconcile([spec]) if s["name"] == spec["name"]), spec)
        spec_function(spec)  # report spec errors before sampling
        args = spec_args(spec)
        session = self.session
        if session is not None and session.samples is not None and session.samples.has(args) \
                and not self.dirty():
            with session.lock:
                return session.samples.rows(args)
        self.require_idle()
        program = self.program()
        seed = self.workspace["seed"]
        try:
            return self.executor.submit(probe_rows, program, args, seed, n, seconds).result(
                timeout=seconds + 120)
        except (ProgramError, ViewError):
            raise
        except Exception as exc:
            raise AppError(error_info(exc, self)["message"], where="views", field="bindings") from exc

    def set_preview(self, name):
        with self.lock:
            self.workspace["preview"] = name
            if self.session is not None and self.session.samples is not None:
                try:
                    self.session.set_preview(name)
                except KeyError as exc:
                    raise AppError(f"no preview view named {name!r}") from exc

    def workspace_json(self):
        with self.lock:
            ws = self.workspace
            nus = dict(self.pending_nu)
            if self.session is not None:
                nus.update(self.session.nus_by_label())
            n = self.session.n if self.session is not None and self.session.n else ws["n"]
            return {
                "version": WORKSPACE_VERSION,
                "program": dict(ws["program"]),
                "views": ws["views"],
                "f": ws["f"],
                "preview": ws["preview"],
                "seed": ws["seed"],
                "n": n,
                "nu": {k: v for k, v in nus.items() if any(s["name"] == k for s in ws["views"])},
            }

    def load_workspace(self, data, sample=True):
        self.require_idle()
        if data.get("version") != WORKSPACE_VERSION:
            raise AppError(f"unknown workspace version {data.get('version')!r}", where="workspace")
        p = data.get("program") or {}
        self.build_views([s for s in data.get("views") or [] if not needs_y(s)])  # validate first
        with self.lock:
            self.session = None
            self.clear_validation()
            self.workspace.update({
                "views": data.get("views") or [],
                "f": data.get("f"),
                "preview": data.get("preview"),
                "seed": int(data.get("seed", 0)),
                "n": int(data.get("n", 1000)),
            })
            self.pending_nu = {k: dict(v) for k, v in (data.get("nu") or {}).items()}
        self.set_program(p.get("source", ""), p.get("path"), mode2D=p.get("mode2D", False),
                         params=p.get("params") or {}, external=True)
        if sample and self.workspace["views"] and self.workspace["program"]["source"].strip():
            self.start_sample(self.workspace["n"], fresh=True)

    # --- jobs ----------------------------------------------------------------------

    def require_idle(self):
        if self.job is not None and self.job.running:
            raise AppError("a job is running; stop it first", status=409, where="job")

    def _start_job(self, kind, target, work):
        self.require_idle()
        job = Job(kind, target)
        self.job = job
        self.push_job(force=True)

        def run():
            try:
                work(job)
            except Exception as exc:
                job.error = error_info(exc, self)
                traceback.print_exc()
            finally:
                job.running = False
                job.finished = time.monotonic()
                self.push_job(force=True)
                self.publish(self.state_msg())

        self.executor.submit(run)
        return job

    def start_sample(self, n, fresh=False, seed=None):
        n = int(n)
        if n <= 0:
            raise AppError("n must be positive", where="sample")
        with self.lock:
            if seed is not None:
                self.workspace["seed"] = int(seed)
            seed = self.workspace["seed"]
            specs = [dict(s) for s in self.workspace["views"]]
            f = self.workspace["f"]
            if not specs:
                raise AppError("define a view first", where="views")
            waiting = [s["name"] for s in specs if needs_y(s)]
            self.build_views([s for s in specs if not needs_y(s)], f)  # report errors now
            program = self.program()
            preview = self.workspace["preview"]

        def work(job):
            def progress(done):
                job.done = done
                self.push_job()

            if waiting:
                self._detect_y(job, program, specs, waiting, seed)
            _, f_view, also = self.build_views(specs, f)
            with self.lock:
                session = self.session
                fresh_ = (fresh or bool(waiting) or session is None or session.samples is None
                          or self.dirty() or session.needs_resample(f_view, also)
                          or seed != session.seed)
                if session is None:
                    session = Session(program, f_view, also, seed=seed)
                    session.listeners.append(self._on_session_change)
                    self.session = session
                for name, by_label in self.pending_nu.items():
                    if name not in session._nus:
                        session.preset_nu(name, by_label)
                self.pending_nu = {}
                if fresh_:
                    self.clear_validation()
                    self.workspace["n"] = n

            if fresh_:
                session.sample(n, program=program, view=f_view, also=also, seed=seed,
                               on_progress=progress, should_stop=job.stop.is_set)
                if preview in {g.name for g in also}:
                    session.set_preview(preview)
            else:
                session.sample_more(n, on_progress=progress, should_stop=job.stop.is_set)
            with self.lock:
                self.workspace["n"] = session.n

        return self._start_job("sample", n, work)

    def _detect_y(self, job, program, specs, names, seed):
        """Fill in values or bins for source views that have none, from a short probe. On the worker."""
        for name in names:
            spec = next(s for s in specs if s["name"] == name)
            job.note = f"Detecting the values of {name}"
            self.push_job(force=True)
            rows = probe_rows(program, spec_args(spec), seed)
            try:
                spec.update(auto_y(detect_values(spec, rows)))
            except ValueError as exc:
                raise AppError(f"view {name!r}: {exc}", where="views", view=name, field="values") from exc
        job.note = None
        with self.lock:
            for s in self.workspace["views"]:
                if s["name"] in names:
                    done = next(d for d in specs if d["name"] == s["name"])
                    for key in ("values", "bins"):
                        if done.get(key) is not None:
                            s[key] = done[key]
        self.publish(self.workspace_msg())

    def start_validate(self, n, seed=None):
        session = self.session
        if session is None or session.samples is None:
            raise AppError("sample the program first", where="validate")
        try:
            session_patch(session)
        except PatchError as exc:
            raise AppError(str(exc), where="patch") from exc

        def work(job):
            def progress(result):
                job.done = result["n"]
                self.validation = _public(result)
                self.push_job()
                self.publish({"type": "validation", "validation": self.validation})

            result, samples = validate(session, int(n), seed=seed, on_progress=progress,
                                       should_stop=job.stop.is_set)
            self.validation = _public(result)
            self.validation_samples = (samples, result["y_idx"])
            self.publish({"type": "validation", "validation": self.validation})

        return self._start_job("validate", int(n), work)

    def clear_validation(self):
        self.validation = None
        self.validation_samples = None
        self.publish({"type": "validation", "validation": None})

    def stop(self):
        if self.job is not None and self.job.running:
            self.job.stop.set()
            self.push_job(force=True)

    # --- scenes and maps ----------------------------------------------------------

    def scenes(self, source="mu", view=None, value=None, count=12, seed=0):
        session = self.session
        if session is None or session.samples is None:
            raise AppError("sample the program first", where="scenes")
        rng = np.random.default_rng(seed)
        with session.lock:
            if view is not None:
                _labels_of(session, view)  # unknown names are a client error
            if source == "pprime":
                if self.validation_samples is None:
                    raise AppError("check P′ by sampling it first", where="scenes")
                samples, idx = self.validation_samples
                weights = None
                if view is not None and view != session.view.name:
                    view = None  # P′ scenes are only classified by f
            elif source in ("mu", "muprime"):
                samples = session.samples
                idx = session.view_index(view) if view is not None else None
                weights = None
                if source == "muprime":
                    if session.w is None:
                        raise AppError("ν is blocked, so there is no μ̂′", where="scenes")
                    weights = session.w[session.y_idx]
            else:
                raise AppError(f"unknown scene source {source!r}", where="scenes")
            n = len(idx) if idx is not None else (len(weights) if weights is not None else session.n)
            candidates = np.arange(n)
            labels = None
            if view is not None:
                labels = _labels_of(session, view)
                if value is not None:
                    candidates = np.flatnonzero(np.asarray(idx)[:n] == int(value))
            if len(candidates) == 0:
                return {"total": 0, "scenes": []}
            k = min(int(count), len(candidates))
            if weights is not None:
                p = weights[candidates]
                if p.sum() <= 0:
                    return {"total": 0, "scenes": []}
                pick = rng.choice(candidates, size=k, replace=False, p=p / p.sum()) \
                    if np.count_nonzero(p) >= k else candidates[p > 0][:k]
            else:
                pick = rng.choice(candidates, size=k, replace=False)
            out = []
            for i in sorted(int(i) for i in pick):
                scene = samples.scenes[i]
                item = scene_json(scene)
                item["index"] = i
                item["args"] = {expr: _short_repr(col[i]) for expr, col in samples.columns.items()}
                item["values"] = _scene_values(session, i, source, idx, labels, view)
                out.append(item)
            return {"total": int(len(candidates)), "scenes": out}

    def map(self):
        session = self.session
        if session is None or session.samples is None:
            return None
        scenario = session.samples.compiled.scenario
        key = id(scenario)
        if key not in self._map_cache:
            self._map_cache = {key: map_json(scenario.workspace)}
        return self._map_cache[key]


def probe_rows(program, args, seed, n=300, seconds=5.0):
    """A short sample of argument values, for detecting a view's values. Runs on the worker."""
    from .sampling import SampleSet

    compiled = program.compile(args)
    deadline = time.monotonic() + seconds
    samples = SampleSet(compiled, seed)
    samples.extend(n, should_stop=lambda: time.monotonic() > deadline)
    return samples.rows(args)


def _labels_of(session, name):
    if name == session.view.name:
        return session.labels
    for g in session.also:
        if g.name == name:
            return g.labels
    raise AppError(f"no view named {name!r}", where="scenes")


def _scene_values(session, i, source, idx, labels, view):
    if source == "pprime":
        return {session.view.name: session.labels[int(idx[i])]} if idx is not None else {}
    out = {}
    if i < len(session.y_idx):
        out[session.view.name] = session.labels[int(session.y_idx[i])]
        for g in session.also:
            out[g.name] = g.labels[int(session._g_idx[g.name][i])]
    return out


def _short_repr(v, width=60):
    if isinstance(v, float):
        text = f"{v:.6g}"
    else:
        text = repr(v)
    return text if len(text) <= width else text[: width - 1] + "…"


def _view_of(exc, f_view, also):
    text = str(exc)
    for v in [f_view, *also]:
        if f"view {v.name!r}" in text:
            return v.name
    return None


def _public(result):
    out = {k: v for k, v in result.items() if k not in ("y_idx", "source")}
    for k in ("mean_iters", "predicted_iters", "M"):
        if out.get(k) is not None and not math.isfinite(out[k]):
            out[k] = None
    return out


def error_info(exc, app=None):
    """A JSON description of an exception, with its line in the program if it has one."""
    info = {"message": f"{type(exc).__name__}: {exc}", "where": "job"}
    if isinstance(exc, AppError):
        return exc.info
    if isinstance(exc, ProgramError):
        info.update(message=str(exc), where="views")
        return info
    if isinstance(exc, ViewError):
        info.update(message=str(exc), where="views", field=exc.field)
        return info
    if app is not None:
        p = app.workspace["program"]
        filename = str(Path(p["path"]).resolve()) if p["path"] else "<scenic_dmp>"
        n_lines = p["source"].rstrip("\n").count("\n") + 1
        line = col = None
        if getattr(exc, "filename", None) == filename and getattr(exc, "lineno", None):
            line, col = exc.lineno, getattr(exc, "offset", None)
            if line == n_lines + 1:  # "EOF in multi-line statement" is reported past the end
                line, col = n_lines, None
        else:
            tb = exc.__traceback__
            while tb is not None:
                if tb.tb_frame.f_code.co_filename == filename:
                    line = tb.tb_lineno
                tb = tb.tb_next
        if line is not None and line <= n_lines:
            info.update(where="program", line=line, column=col)
            msg = getattr(exc, "msg", None)
            if msg:
                info["message"] = f"{type(exc).__name__}: {msg}"
    return info


def create_app(state=None):
    state = state or AppState()

    @asynccontextmanager
    async def lifespan(_app):
        state.loop = asyncio.get_running_loop()
        yield
        if state.job is not None:
            state.job.stop.set()
        state.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="scenic-dmp", lifespan=lifespan)
    app.state.dmp = state

    @app.exception_handler(AppError)
    async def _app_error(_request, exc):
        return JSONResponse({"error": exc.info}, status_code=exc.status)

    @app.get("/api/state")
    def get_state():
        return {m["type"]: {k: v for k, v in m.items() if k != "type"} for m in state.messages()}

    @app.post("/api/program")
    def post_program(body: dict = Body(...)):
        kwargs = {}
        if "path" in body:
            kwargs["path"] = body["path"]
        state.set_program(body.get("source"), mode2D=body.get("mode2D"), params=body.get("params"),
                          **kwargs)
        return {"dirty": state.dirty()}

    @app.post("/api/program/open")
    def open_program(body: dict = Body(...)):
        state.require_idle()
        state.open_program(body["path"], mode2D=body.get("mode2D"))
        return {"ok": True}

    @app.post("/api/views")
    def post_views(body: dict = Body(...)):
        return state.set_views(body.get("views") or [], body.get("f"), body.get("preview"))

    @app.post("/api/views/detect")
    def detect(body: dict = Body(...)):
        spec = body["spec"]
        try:
            rows = state.detect_rows(spec)
            return detect_values(spec, rows)
        except ViewError as exc:
            raise AppError(str(exc), where="views", field=exc.field) from exc

    @app.post("/api/preview")
    def post_preview(body: dict = Body(...)):
        state.set_preview(body.get("name"))
        return {"ok": True}

    @app.post("/api/sample")
    def post_sample(body: dict = Body(...)):
        job = state.start_sample(body.get("n", state.workspace["n"]), fresh=bool(body.get("fresh")),
                                 seed=body.get("seed"))
        return {"job": job.to_json()}

    @app.post("/api/stop")
    def post_stop():
        state.stop()
        return {"ok": True}

    def _session():
        if state.session is None or state.session.samples is None:
            raise AppError("sample the program first", where="nu")
        return state.session

    @app.put("/api/nu")
    def put_nu(body: dict = Body(...)):
        try:
            _session().set_nu(body["nu"])
        except ValueError as exc:
            raise AppError(str(exc), where="nu") from exc
        return {"ok": True}

    @app.post("/api/nu/reset")
    def reset_nu():
        _session().reset_nu()
        return {"ok": True}

    @app.post("/api/nu/uniform")
    def uniform_nu():
        _session().uniform_nu()
        return {"ok": True}

    @app.get("/api/patch")
    def get_patch():
        session = _session()
        try:
            patch = session_patch(session)
        except PatchError as exc:
            raise AppError(str(exc), where="patch") from exc
        return {**patch, "original": session.program.source}

    @app.post("/api/patch/preview")
    def preview_patch(body: dict = Body(...)):
        session = _session()
        try:
            patch = session_patch(session, nu=body["nu"])
        except PatchError as exc:
            raise AppError(str(exc), where="patch") from exc
        return {**patch, "original": session.program.source}

    @app.post("/api/validate")
    def post_validate(body: dict = Body(...)):
        job = state.start_validate(body.get("n", 2000), seed=body.get("seed"))
        return {"job": job.to_json()}

    @app.get("/api/scenes")
    def get_scenes(source: str = "mu", view: str | None = None, value: int | None = None,
                   count: int = 12, seed: int = 0):
        return state.scenes(source, view, value, count, seed)

    @app.get("/api/map")
    def get_map():
        return {"map": state.map()}

    @app.get("/api/workspace")
    def get_workspace():
        return state.workspace_json()

    @app.post("/api/workspace/save")
    def save_workspace(body: dict = Body(...)):
        path = Path(body["path"]).expanduser()
        data = state.workspace_json()
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise AppError(f"can't write {path}: {exc.strerror or exc}", where="workspace") from exc
        return {"path": str(path.resolve())}

    @app.post("/api/workspace/load")
    def load_workspace(body: dict = Body(...)):
        if "path" in body:
            path = Path(body["path"]).expanduser()
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise AppError(f"can't read workspace {path}: {exc}", where="workspace") from exc
        else:
            data = body["workspace"]
        state.load_workspace(data, sample=body.get("sample", True))
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        state.clients.add(ws)
        try:
            for msg in state.messages():
                await ws.send_text(json.dumps(msg, allow_nan=False))
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            state.clients.discard(ws)

    if (WEB_DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def no_frontend():
            return (
                "<h1>scenic-dmp</h1><p>The frontend isn't built. Run</p>"
                "<pre>npm --prefix web install\nnpm --prefix web run build</pre>"
                "<p>or use the Vite dev server: <code>npm --prefix web run dev</code>.</p>"
            )

    return app
