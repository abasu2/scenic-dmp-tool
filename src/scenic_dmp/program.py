"""Load a Scenic program and compile it with the views' arguments recorded as params.

A plain Python function applied to random values in a top-level `param` either
raises RandomControlFlowError or silently yields a constant. So only the raw
argument expressions are recorded (`param __dmp_arg_i = <expr>`), and view
functions run in Python on the sampled values.
"""

import re
from pathlib import Path

import scenic

PARAM_PREFIX = "__dmp_arg_"
_MODULAR = re.compile(r"^scenario\s+\w+", re.MULTILINE)


class ProgramError(Exception):
    pass


class Compiled:
    """A compiled scenario plus the param name holding each argument expression."""

    def __init__(self, scenario, param_names):
        self.scenario = scenario
        self.param_names = param_names


class Program:
    """A top-level static Scenic program.

    path is used to resolve the program's relative imports and localPath() calls,
    so pass it even when giving the source as a string. Extra keyword arguments
    (e.g. model=) go to scenic.scenarioFromString.
    """

    def __init__(self, source, path=None, *, mode2D=False, params=None, **compile_options):
        if _MODULAR.search(source):
            raise ProgramError(
                "modular scenarios (`scenario ...:`) aren't supported yet; "
                "define the scene at the top level"
            )
        self.source = source
        self.path = Path(path).resolve() if path is not None else None
        self.mode2D = mode2D
        self.params = dict(params or {})
        self.compile_options = compile_options

    @classmethod
    def from_file(cls, path, **kwargs):
        return cls(Path(path).read_text(), path, **kwargs)

    def with_source(self, source):
        """The same program settings with different source (e.g. the patched P′)."""
        return Program(
            source, self.path, mode2D=self.mode2D, params=self.params, **self.compile_options
        )

    def injected_source(self, arg_exprs):
        """The program source with a `param` line appended per argument expression."""
        source, _, _ = self._inject(arg_exprs)
        return source

    def compile(self, arg_exprs):
        source, names, first_line = self._inject(arg_exprs)
        filename = str(self.path) if self.path else "<scenic_dmp>"
        kwargs = dict(filename=filename, mode2D=self.mode2D, params=self.params, **self.compile_options)
        if self.path:
            # Puts the program's directory on sys.path and sets __file__.
            kwargs["path"] = filename
        try:
            scenario = scenic.scenarioFromString(source, **kwargs)
        except Exception as exc:
            expr = _blame(exc, filename, first_line, list(names))
            if expr is None:
                raise
            # An unclosed bracket in P is reported on the appended lines; blame P for it.
            own = self._syntax_error(filename)
            if own is not None:
                raise own from None
            raise ProgramError(f"view argument {expr!r} failed: {type(exc).__name__}: {exc}") from exc
        return Compiled(scenario, names)

    def _syntax_error(self, filename):
        """P's own Scenic syntax error, if it has one."""
        from scenic.syntax.parser import parse_string

        try:
            parse_string(self.source, "exec", filename=filename)
        except Exception as exc:
            return exc
        return None

    def _inject(self, arg_exprs):
        exprs = list(dict.fromkeys(arg_exprs))
        for e in exprs:
            if "\n" in e:
                raise ProgramError(f"view argument {e!r} must be a single-line expression")
        names = {e: f"{PARAM_PREFIX}{i}" for i, e in enumerate(exprs)}
        head = self.source.rstrip("\n") + "\n\n# Added by scenic_dmp: view arguments\n"
        first_line = head.count("\n") + 1
        lines = [f"param {names[e]} = {e}\n" for e in exprs]
        return head + "".join(lines), names, first_line


def _blame(exc, filename, first_line, exprs):
    """The argument expression on the injected line where exc was raised, if any."""
    if not exprs:
        return None
    lineno = None
    if getattr(exc, "filename", None) == filename and getattr(exc, "lineno", None):
        lineno = exc.lineno
    else:
        tb = exc.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == filename:
                lineno = tb.tb_lineno
            tb = tb.tb_next
    if lineno is None or lineno < first_line:
        return None
    # A syntax error in the last expression can be reported one line past it.
    return exprs[min(lineno - first_line, len(exprs) - 1)]
