"""Views defined in the program itself, as `param view_<name> = <expr>`.

Scenic evaluates the expression and records its value in every scene, so a
source view needs no bindings or Python expression. To branch on random values,
wrap a function with Scenic's `distributionFunction`, so it runs once the scene
is sampled:

    from scenic.core.distributions import distributionFunction

    @distributionFunction
    def brake(d, c):
        return "brake" if d <= 2 and abs(c - 90 deg) < 1e-6 else "continue"

    param view_brake = brake(d, c)
    param view_gap = distance from ego to ped

The values or bins of a source view (its Y) are not part of the program; the
app keeps them in the view's spec, and detects them on the first sample if
they're missing. The tool reads the value back as `globalParameters.view_<name>`,
which is the same random value, so the expression isn't evaluated twice.
"""

import ast
import math

PREFIX = "view_"


def discover(source, filename="<scenic_dmp>"):
    """The `param view_<name> = <expr>` statements at the top level of a program.

    Returns [{"name", "param", "expr", "line"}] in program order, or None if the
    program doesn't parse (so callers can keep the last good list while it's
    being edited).
    """
    from scenic.syntax.parser import parse_string

    try:
        tree = parse_string(source, "exec", filename=filename)
    except Exception:
        return None
    found = []
    for node in tree.body:
        if type(node).__name__ != "Param":
            continue
        for p in node.elts:
            ident = getattr(p, "identifier", "")
            if not ident.startswith(PREFIX) or len(ident) == len(PREFIX):
                continue
            text = ast.get_source_segment(source, p.value)
            if text is None:
                continue
            found.append({
                "name": ident[len(PREFIX):],
                "param": ident,
                "expr": one_line(text),
                "line": p.lineno,
            })
    return found


def one_line(text):
    """An expression on one line: continuation backslashes and newlines become spaces."""
    return " ".join(text.replace("\\\n", " ").split())


def record_arg(spec):
    """The expression the tool records per scene for a source view."""
    return f"globalParameters.{spec['param']}"


def needs_y(spec):
    return bool(spec.get("source")) and spec.get("values") is None and spec.get("bins") is None


def merge(specs, discovered):
    """The views after the program changed: source views follow the program, form views stay.

    A source view keeps the values or bins it had under the same name. Source
    views come first, in program order.
    """
    if discovered is None:
        return specs
    old = {s["name"]: s for s in specs if s.get("source")}
    out = []
    for d in discovered:
        spec = {"name": d["name"], "source": True, "param": d["param"], "expr": d["expr"], "line": d["line"]}
        prev = old.get(d["name"])
        if prev is not None:
            for key in ("values", "bins"):
                if prev.get(key) is not None:
                    spec[key] = prev[key]
        out.append(spec)
    return out + [s for s in specs if not s.get("source")]


def auto_y(detected):
    """Values or bins for a view, from detect_values() on sampled scenes."""
    if detected.get("values"):
        return {"values": detected["values"]}
    if detected.get("numeric"):
        return {"bins": nice_bins(detected["min"], detected["max"])}
    raise ValueError("too many distinct values that aren't numbers; set the values by hand")


def nice_bins(lo, hi, k=6):
    """About k equal-width bins with round edges covering [lo, hi]."""
    if not hi > lo:
        base = math.floor(lo)
        return [float(base), float(base + 1)]
    raw = (hi - lo) / k
    mag = 10 ** math.floor(math.log10(raw))
    step = next((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), 10 * mag)
    start = math.floor(lo / step) * step
    edges = []
    e = start
    while e <= hi + step / 2:
        edges.append(float(f"{e:.12g}"))
        e += step
    if edges[-1] <= hi:
        edges.append(float(f"{edges[-1] + step:.12g}"))
    return edges
