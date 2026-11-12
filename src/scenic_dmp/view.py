"""Views: a plain Python function over sampled Scenic expressions, with a declared finite Y.

A view can be built from a Python callable (`View(...)`) or from a text spec
(`View.from_spec(...)`), as the web app does. A spec view keeps its source, so
it can be saved and written into the patched program.
"""

import ast
import builtins
import keyword
import math

import numpy as np


class ViewError(ValueError):
    """A view spec is malformed, or its function failed on a sampled scene."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


# Names a spec expression may use besides its bindings. `deg` converts degrees to
# radians, matching Scenic's `90 deg`.
MATH_HELPERS = {
    name: getattr(math, name)
    for name in [
        "pi", "e", "inf", "tau",
        "sqrt", "exp", "log", "log10", "log2", "pow",
        "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "hypot",
        "floor", "ceil", "trunc", "fabs", "copysign", "fmod",
        "isclose", "isfinite", "isnan", "degrees", "radians",
    ]
}
DEG_HELPER = {"deg": math.radians}
SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in [
        "abs", "min", "max", "round", "int", "float", "str", "bool", "len",
        "sum", "any", "all", "sorted", "tuple", "list", "range",
    ]
}
HELPERS = {**MATH_HELPERS, **DEG_HELPER}
_GLOBALS = {"__builtins__": SAFE_BUILTINS, **HELPERS}


class View:
    """A view f: Scene -> Y with a finite, declared Y.

    args are Scenic expressions over the program's top-level names (e.g. "d",
    "distance from ego to ped"). Their sampled values are passed to fn. Give
    exactly one of:

    - values: the exact list of values fn may return (categorical view);
    - bins: increasing edges e_0 < ... < e_K for a numeric fn. Y is then the K
      bins [e_i, e_{i+1}) plus the overflow bins "< e_0" and ">= e_K".
    """

    def __init__(self, name, args, fn, *, values=None, bins=None):
        if (values is None) == (bins is None):
            raise ValueError("give exactly one of values= or bins=")
        if isinstance(args, str):
            args = [args]
        if not args:
            raise ValueError(f"view {name!r} needs at least one argument expression")
        self.name = name
        self.args = tuple(args)
        self.fn = fn
        self.spec = None
        if values is not None:
            values = list(values)
            if not values:
                raise ViewError(f"view {name!r} needs at least one value", "values")
            if len(set(values)) != len(values):
                raise ViewError(f"view {name!r} has duplicate values", "values")
            self.values = values
            self.bins = None
            self._index = {v: i for i, v in enumerate(values)}
        else:
            bins = np.asarray(bins, dtype=float)
            if bins.ndim != 1 or len(bins) < 2 or np.any(np.diff(bins) <= 0):
                raise ViewError(
                    f"view {name!r} needs at least two strictly increasing bin edges", "bins"
                )
            self.values = None
            self.bins = bins

    @classmethod
    def from_spec(cls, spec):
        """Build a view from a JSON-able spec.

        spec = {"name": str, "bindings": [{"name": str, "expr": str}, ...],
                "expr": str, and one of "values": [str, ...] or "bins": [number, ...]}

        Each binding names a Scenic expression; expr is a Python expression over
        the binding names and HELPERS. Values are parsed as Python literals where
        possible, so "1" is the int 1 and "brake" is the string "brake".
        """
        name = str(spec.get("name", "")).strip()
        if not name:
            raise ViewError("a view needs a name", "name")
        args, fn, names = spec_function(spec)
        values = spec.get("values")
        bins = spec.get("bins")
        if (values is None) == (bins is None):
            hint = " (Detect fills them in)" if spec.get("source") else ""
            raise ViewError(f"view {name!r}: give either values or bins{hint}", "values")
        if values is not None:
            values = [parse_value(v) for v in values]
        else:
            try:
                bins = [float(b) for b in bins]
            except (TypeError, ValueError):
                raise ViewError(f"view {name!r}: bin edges must be numbers", "bins") from None
        view = cls(name, args, fn, values=values, bins=bins)
        view.spec = normalize_spec(spec)
        view.binding_names = names
        return view

    @property
    def labels(self):
        if self.values is not None:
            return [str(v) for v in self.values]
        e = [f"{x:g}" for x in self.bins]
        inner = [f"[{a}, {b})" for a, b in zip(e, e[1:])]
        return [f"< {e[0]}", *inner, f"≥ {e[-1]}"]

    @property
    def K(self):
        return len(self.labels)

    def apply(self, rows, start=0):
        """fn(*row) for each row, with failures reported against the view.

        start is the index of the first row's scene, for error messages.
        """
        out = []
        for i, row in enumerate(rows, start):
            try:
                out.append(self.fn(*row))
            except Exception as exc:
                raise ViewError(
                    f"view {self.name!r} failed on scene {i} with arguments {_short(row)}: "
                    f"{type(exc).__name__}: {exc}",
                    "expr",
                ) from exc
        return out

    def classify(self, rows, start=0):
        """Map each row of argument values to the index of fn(*row) in Y."""
        results = self.apply(rows, start)
        if self.values is not None:
            idx = []
            unexpected = set()
            for r in results:
                try:
                    i = self._index.get(r)
                except TypeError:  # unhashable
                    i = None
                if i is None:
                    unexpected.add(repr(r))
                    i = -1
                idx.append(i)
            if unexpected:
                shown = ", ".join(sorted(unexpected)[:10])
                raise ViewError(
                    f"view {self.name!r} returned values not in its declared values: {shown}",
                    "values",
                )
            return np.array(idx, dtype=int)
        try:
            vals = np.array([float(r) for r in results])
        except (TypeError, ValueError) as exc:
            raise ViewError(f"view {self.name!r} must return numbers for bins: {exc}", "expr") from exc
        if np.any(np.isnan(vals)):
            raise ViewError(f"view {self.name!r} returned NaN", "expr")
        # Number of edges <= v: 0 for v < e_0, K+1 for v >= e_K.
        return np.searchsorted(self.bins, vals, side="right")

    def __repr__(self):
        y = f"values={self.values!r}" if self.values is not None else f"bins={self.bins.tolist()!r}"
        return f"View({self.name!r}, args={list(self.args)!r}, {y})"


def deg(x):
    """Degrees to radians, for comparing against Scenic angles."""
    return math.radians(x)


# --- spec helpers -------------------------------------------------------------


def normalize_spec(spec):
    """A clean copy of a spec with only the known keys."""
    if spec.get("source"):
        out = {
            "name": str(spec["name"]).strip(),
            "source": True,
            "param": spec["param"],
            "expr": str(spec["expr"]).strip(),
            "line": spec.get("line"),
        }
    else:
        out = {
            "name": str(spec["name"]).strip(),
            "bindings": [
                {"name": str(b["name"]).strip(), "expr": str(b["expr"]).strip()}
                for b in spec["bindings"]
            ],
            "expr": str(spec["expr"]).strip(),
        }
    if spec.get("values") is not None:
        out["values"] = [str(v) if not isinstance(v, str) else v for v in spec["values"]]
    else:
        out["bins"] = [float(b) for b in spec["bins"]]
    return out


def spec_function(spec):
    """(argument expressions, fn, binding names) for a spec.

    A form view's arguments are its bindings and fn evaluates its expression. A
    source view (`param view_<name> = ...` in the program) records the param
    itself, so fn is the identity.
    """
    if spec.get("source"):
        from .source_views import record_arg

        if not str(spec.get("param", "")).startswith("view_"):
            raise ViewError(f"source view {spec.get('name')!r} has no param", "expr")
        return [record_arg(spec)], _identity, []
    names, code = compile_expr(spec)
    args = [str(b["expr"]).strip() for b in spec["bindings"]]
    return args, _evaluator(code, names), names


def spec_args(spec):
    """The argument expressions a spec needs recorded per scene."""
    if spec.get("source"):
        from .source_views import record_arg

        return [record_arg(spec)]
    return [str(b.get("expr", "")).strip() for b in spec.get("bindings") or []]


def _identity(value):
    return value


def parse_value(text):
    """A declared value typed as text: a Python literal if it parses, else the string."""
    if not isinstance(text, str):
        return text
    s = text.strip()
    try:
        v = ast.literal_eval(s)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return s
    try:
        hash(v)
    except TypeError:
        return s
    return v


def compile_expr(spec):
    """Check a spec's bindings and expression; return (binding names, code)."""
    bindings = spec.get("bindings") or []
    if not bindings:
        raise ViewError("a view needs at least one binding", "bindings")
    names = []
    for b in bindings:
        bname = str(b.get("name", "")).strip()
        expr = str(b.get("expr", "")).strip()
        if not bname.isidentifier() or keyword.iskeyword(bname):
            raise ViewError(f"binding name {bname!r} is not a valid Python name", "bindings")
        if bname.startswith("__"):
            raise ViewError(f"binding name {bname!r} can't start with '__'", "bindings")
        if bname in names:
            raise ViewError(f"binding {bname!r} is defined twice", "bindings")
        if not expr:
            raise ViewError(f"binding {bname!r} needs a Scenic expression", "bindings")
        if "\n" in expr:
            raise ViewError(f"binding {bname!r} must be a single-line expression", "bindings")
        names.append(bname)
    source = str(spec.get("expr", "")).strip()
    if not source:
        raise ViewError("a view needs an expression", "expr")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ViewError(f"expression syntax error: {exc.msg} (column {exc.offset})", "expr") from None
    unknown = sorted(free_names(tree) - set(names) - set(HELPERS) - set(SAFE_BUILTINS))
    if unknown:
        raise ViewError(
            f"expression uses undefined names: {', '.join(unknown)}. "
            "Add a binding for each Scenic value it needs.",
            "expr",
        )
    return names, compile(tree, "<view>", "eval")


def free_names(tree):
    """Names an expression reads that it doesn't bind itself (lambda args, comprehensions)."""
    loads, bound = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (loads if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return loads - bound


def _evaluator(code, names):
    # Bindings go in the globals so comprehensions and lambdas can see them.
    def fn(*vals):
        return eval(code, {**_GLOBALS, **dict(zip(names, vals))})

    return fn


def detect_values(spec, rows, limit=40):
    """Distinct results of a spec's expression over sampled rows.

    Returns {"values": [...]} with values as text (sorted) when there are at most
    `limit`, or {"numeric": True, "min": ..., "max": ...} for many numbers.
    """
    _args, fn, _names = spec_function(spec)
    probe = View("probe", ["_"], fn, values=[0])
    probe.name = spec.get("name", "view")
    results = probe.apply(rows)
    distinct = {}
    for r in results:
        key = repr(r)
        if key not in distinct:
            distinct[key] = r
        if len(distinct) > limit:
            break
    if len(distinct) <= limit:
        vals = list(distinct.values())
        try:
            vals.sort()
        except TypeError:
            vals.sort(key=repr)
        return {"values": [r if isinstance(r, str) else repr(r) for r in vals]}
    try:
        nums = np.array([float(r) for r in results])
    except (TypeError, ValueError):
        return {"values": None, "too_many": True}
    return {"numeric": True, "min": float(nums.min()), "max": float(nums.max())}


def _short(row, width=80):
    text = ", ".join(repr(v) for v in row)
    return text if len(text) <= width else text[: width - 1] + "…"
