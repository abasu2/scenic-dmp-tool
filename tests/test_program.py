import random
from pathlib import Path

import pytest

from scenic_dmp.program import Program, ProgramError
from scenic_dmp.sampling import SampleSet

TOY = """\
class Car: pass
ego = new Car
x = Range(0, 1)
"""


def test_injected_params_are_sampled():
    compiled = Program(TOY).compile(["x", "x * 2", "x"])
    assert list(compiled.param_names) == ["x", "x * 2"]
    samples = SampleSet(compiled, seed=0).extend(20)
    for x, x2 in samples.rows(["x", "x * 2"]):
        assert 0 <= x <= 1
        assert x2 == pytest.approx(2 * x)


def test_unknown_name_blames_the_expression():
    with pytest.raises(ProgramError, match="'nosuchname'"):
        Program(TOY).compile(["x", "nosuchname + 1"])


def test_syntax_error_blames_the_expression():
    with pytest.raises(ProgramError, match=r"'\(x \+'"):
        Program(TOY).compile(["x", "(x +"])


def test_errors_in_the_program_itself_are_not_blamed_on_views():
    with pytest.raises(Exception) as info:
        Program("class Car: pass\nego = new Car\ny = undefined_thing\n").compile(["1"])
    assert not isinstance(info.value, ProgramError)


def test_modular_programs_are_rejected():
    src = "scenario Main():\n    setup:\n        ego = new Object\n"
    with pytest.raises(ProgramError, match="modular"):
        Program(src)


def test_multiline_expression_is_rejected():
    with pytest.raises(ProgramError, match="single-line"):
        Program(TOY).compile(["x +\n 1"])


def test_relative_paths_resolve_against_the_program(tmp_path):
    (tmp_path / "helper.py").write_text("SCALE = 3\n")
    prog = tmp_path / "prog.scenic"
    prog.write_text("from helper import SCALE\n" + TOY + "param here = localPath('data.txt')\n")
    compiled = Program.from_file(prog).compile(["SCALE"])
    scene, _ = compiled.scenario.generate()
    assert scene.params[compiled.param_names["SCALE"]] == 3
    assert Path(scene.params["here"]) == (tmp_path / "data.txt").resolve()


def test_same_seed_same_scenes_and_extend_is_chunk_invariant():
    compiled = Program(TOY).compile(["x"])
    a = SampleSet(compiled, seed=7).extend(30)
    b = SampleSet(compiled, seed=7).extend(10)
    random.random()  # other code touching the global RNG must not matter
    b.extend(20)
    assert a.columns["x"] == b.columns["x"]
    assert SampleSet(compiled, seed=8).extend(30).columns["x"] != a.columns["x"]


def test_sampling_leaves_global_rng_alone():
    compiled = Program(TOY).compile(["x"])
    random.seed(123)
    expected = random.random()
    random.seed(123)
    SampleSet(compiled, seed=0).extend(5)
    assert random.random() == expected
