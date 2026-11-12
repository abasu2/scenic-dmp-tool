# scenic-dmp-tool

A direct manipulation programming tool for Scenic. It visualizes the pushforward $f_\sharp\mu$ of a Scenic program's
scene distribution $\mu$ under a view $f$. You edit a desired distribution $\nu$ by dragging bars, and the tool writes
the patched program $P'$ whose distribution is the Jeffrey update of $\mu$, so that $f_\sharp\mu_{P'} = \nu$.

The tool shows:
- the Jeffrey weights $\hat w(y) = \nu(y) / f_\sharp\hat\mu(y)$
- the acceptance probabilities $\hat a(y) = \hat w(y) / M$
- the acceptance rate $1/M$ of the `require` patch
- how a second view $g$ changes under the reweighted samples

It can also sample $P'$ to check the patch, and show example scenes for each view value. Background:
`~/research/scenic-dmp/notes.tex` and `example.md`.

## Setup

```sh
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm --prefix web install
npm --prefix web run build      # writes the frontend into src/scenic_dmp/web_dist/
```

## The web app

```sh
.venv/bin/scenic-dmp serve examples/pedestrian.scenic       # or a saved workspace .json
.venv/bin/scenic-dmp serve path/to/driving.scenic --mode2D
```

Then open http://127.0.0.1:8765/. The server only listens on localhost, because it runs the view expressions you
type as Python.

- **Program.** The left pane edits $P$. **Open…** reads a .scenic file from disk; the path is kept so `localPath()` and
  relative imports resolve. Edits made in the pane are not written back to the file. Tick **2D** for driving
  programs.
- **Views.** A view is either written in $P$ (see below) or built in the form. A form view binds names to Scenic
  expressions (`dist = distance from ego to parkedCar`) and computes $f$ as one Python expression over those names.
  The expression can use `isclose`, `deg`, `sqrt` and the other `math` functions. Declare $Y$ as values
  (`brake, continue`) or bin edges (`20, 25, 30`). **Detect** fills them in from sampled scenes. One view is $f$, whose
  $\nu$ you edit; the others are previews.
- **Sampling.** **Sample** recompiles and draws $n$ scenes, and **+ more** adds to them. The estimates update while
  scenes stream in, and **Stop** keeps what has been drawn. Changing a view's expression or values reclassifies the
  cached scenes. A new binding expression triggers a resample.
- **$\nu$.** Drag a bar; the others rescale proportionally. Double-click a bar to type a value. Until you edit it,
  $\nu$ follows $f_\sharp\hat\mu$, which is the identity patch. **Reset** returns to that. Values with no samples are
  locked at 0.
- **$P'$.** The **$P'$** tab shows $P$ with the Jeffrey patch appended, and updates while you drag. **Check $P'$**
  samples it and compares $f_\sharp\hat\mu_{P'}$ (with 95% CIs) to $\nu$, and its iterations per scene to $P$'s
  $\times M$. Values with no samples in $P$ aren't checked, since $P'$ leaves them alone. $\nu$ is compared with
  $P'$'s distribution among the other values.
- **Scenes.** Click a bar to see scenes with that value: from $\hat\mu$, from $\hat\mu'$ (drawn $\propto \hat w$), or
  from $P'$'s own samples.
- **Workspaces.** **Save…** writes the program, views and $\nu$ to JSON. **Load…** reopens one and resamples with the
  same seed and $n$, so the same numbers come back.

### Views in the program

Any top-level `param view_<name> = <expr>` in $P$ is a view named `<name>`. Scenic computes and records its value in
every scene. To branch on random values, wrap a function with Scenic's `distributionFunction`, which delays the call
until the scene is sampled (see `examples/pedestrian_views.scenic`):

```scenic
from scenic.core.distributions import distributionFunction

@distributionFunction
def brake(d, c):
    return "brake" if d <= 2 and isclose(c, 90 deg) else "continue"

param view_brake = brake(d, c)
param view_gap = distance from ego to ped
```

The function must take its inputs as arguments: reading `d` from inside the body, or leaving off the decorator,
raises `RandomControlFlowError`. The app picks these views up as you edit $P$ and shows them as cards. There you set
their values or bins, or leave them empty and they are detected on the next sample. Edits to a view in $P$ are
program edits, so they take effect after resampling. Form views reclassify the cached scenes instantly. The patch
for a view in $P$ calls $P$'s own expression (`require not (brake(d, c) == 'continue') or …`) rather than a copy of it.

### The patch

For each view value $y$ with $\hat a(y) \lt 1$, $P'$ adds

```
require not (f(s) == y) or __dmp_u < â(y)
```

where `__dmp_u = Range(0, 1)` is drawn afresh on every rejection-sampling iteration, and $f$ is the view's expression
written as a function. A value with no samples may still occur in $P$, so it gets $\hat w(y) = 1$ and
$\hat a(y) = 1/M$: $P'$ leaves its scenes alone instead of forbidding them. Scenic's soft requirements (`require[p]`) would not work here, because Scenic picks the
active ones once per scene, outside the rejection loop.

## From Python

```python
import math
from scenic_dmp import Program, Session, View, deg, session_patch, validate

P = Program.from_file("examples/pedestrian.scenic")
brake = View.from_spec({
    "name": "brake",
    "bindings": [{"name": "d", "expr": "d"}, {"name": "c", "expr": "c"}],
    "expr": '"brake" if d <= 2 and isclose(c, deg(90)) else "continue"',
    "values": ["brake", "continue"],
})
d = View("d", ["d"], int, values=[1, 2, 3])   # views can also be plain Python callables

s = Session(P, brake, also=[d]).sample(5000)
s.set_nu({"brake": 0.5, "continue": 0.5})
print(s.summary())                    # f#μ̂ with 95% CIs, ν, ŵ, â, M, 1/M
s.preview("d")                        # d#μ̂ and d#μ̂′, with n_eff
print(session_patch(s)["source"])     # P′ (needs a view built from a spec)
result, _ = validate(s, 3000)         # sample P′ and compare f#μ̂_{P′} with ν
```

`notebooks/explore.ipynb` walks through these.

- **Programs.** Only top-level static programs are supported, not modular `scenario` definitions. Driving programs
  need `mode2D=True`. Their maps come from a Scenic source checkout, since the pip package has none.
- **Arguments.** Each binding expression is recorded per scene as `param __dmp_arg_i = <expr>`, and the view
  function runs in Python on the sampled values.

## Development

```sh
.venv/bin/python -m pytest                    # all Python tests
.venv/bin/python -m pytest -m 'not slow'      # skip the driving-domain tests
npm --prefix web test                         # the TypeScript Jeffrey math against Python fixtures
npm --prefix web run fixture                  # regenerate those fixtures
```

For frontend work, run the server and the Vite dev server together, then open http://localhost:5173/. Vite proxies
`/api` and `/ws` to the server.

```sh
.venv/bin/scenic-dmp serve examples/pedestrian.scenic
npm --prefix web run dev
```

Layout:
- `src/scenic_dmp/`: the core and the server.
  - `program.py`, `view.py`, `sampling.py`, `session.py`, `jeffrey.py` and `estimate.py` sample $P$ and estimate
    $f_\sharp\hat\mu$ and $\nu$.
  - `patch.py` writes $P'$ and checks it.
  - `scene_geom.py` turns scenes and maps into JSON.
  - `server.py` and `cli.py` run the web app.
- `web/`: the React frontend.
