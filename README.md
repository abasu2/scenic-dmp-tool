# scenic-dmp-tool

A direct manipulation programming tool for Scenic. It visualizes the pushforward f#μ of a Scenic program's scene
distribution μ under a view f. You edit a desired distribution ν by dragging bars, and the tool writes the patched
program P′ whose distribution is the Jeffrey update of μ, so that f#μ_{P′} = ν.

The tool shows:
- the Jeffrey weights ŵ(y) = ν(y) / f#μ̂(y)
- the acceptance probabilities â(y) = ŵ(y) / M
- the acceptance rate 1/M of the `require` patch
- how a second view g changes under the reweighted samples

It can also sample P′ to check the patch, and show example scenes for each view value. Background:
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

- **Program.** The left pane edits P. **Open…** reads a .scenic file from disk; the path is kept so `localPath()` and
  relative imports resolve. Edits made in the pane are not written back to the file. Tick **2D** for driving
  programs.
- **Views.** A view binds names to Scenic expressions (`dist = distance from ego to parkedCar`) and computes f as
  one Python expression over those names. The expression can use `isclose`, `deg`, `sqrt` and the other `math`
  functions. Declare Y as values (`brake, continue`) or bin edges (`20, 25, 30`). **Detect** fills them in from
  sampled scenes. One view is f, whose ν you edit; the others are previews.
- **Sampling.** **Sample** recompiles and draws n scenes, and **+ more** adds to them. The estimates update while
  scenes stream in, and **Stop** keeps what has been drawn. Changing a view's expression or values reclassifies the
  cached scenes. A new binding expression triggers a resample.
- **ν.** Drag a bar; the others rescale proportionally. Double-click a bar to type a value. Until you edit it, ν
  follows f#μ̂, which is the identity patch. **Reset** returns to that. Values with no samples are locked at 0.
- **P′.** The **P′** tab shows P with the Jeffrey patch appended, and updates while you drag. **Check P′** samples
  it and compares f#μ̂_{P′} (with 95% CIs) to ν, and its iterations per scene to P's × M.
- **Scenes.** Click a bar to see scenes with that value: from μ̂, from μ̂′ (drawn ∝ ŵ), or from P′'s own samples.
- **Workspaces.** **Save…** writes the program, views and ν to JSON. **Load…** reopens one and resamples with the
  same seed and n, so the same numbers come back.

### The patch

For each view value y with â(y) < 1, P′ adds

```
require not (f(s) == y) or __dmp_u < â(y)
```

where `__dmp_u = Range(0, 1)` is drawn afresh on every rejection-sampling iteration, and f is the view's expression
written as a function. Scenic's soft requirements (`require[p]`) would not work here, because Scenic picks the
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
  - `program.py`, `view.py`, `sampling.py`, `session.py`, `jeffrey.py` and `estimate.py` sample P and estimate
    f#μ̂ and ν.
  - `patch.py` writes P′ and checks it.
  - `scene_geom.py` turns scenes and maps into JSON.
  - `server.py` and `cli.py` run the web app.
- `web/`: the React frontend.
