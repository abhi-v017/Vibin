"""End-to-end tests: compile + run real programs, compare printed output.

Each program is run BOTH with and without the optimizer. Identical output in
both modes is the correctness check for the optimizer.
"""
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROGRAMS = sorted((ROOT / "tests" / "programs").glob("*.chill"))


def run_chill(path, *flags):
    """Run the compiler in a subprocess (as the web API will) and capture output."""
    return subprocess.run(
        [sys.executable, "-m", "chill", str(path), "--run", *flags],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.stem)
@pytest.mark.parametrize("flags", [[], ["-O0"]], ids=["optimized", "unoptimized"])
def test_program_output(path, flags):
    expected = path.with_suffix(".expected").read_text()
    result = run_chill(path, *flags)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


def test_compile_error_exit_code_and_message(tmp_path):
    bad = tmp_path / "bad.chill"
    bad.write_text("say ghost\n")
    result = run_chill(bad)
    assert result.returncode == 1
    assert "hasn't been made yet" in result.stdout


@pytest.mark.parametrize("flags", [[], ["-O0"]], ids=["optimized", "unoptimized"])
def test_divide_by_zero_stops_with_clear_error(tmp_path, flags):
    program = tmp_path / "dz.chill"
    program.write_text("say 10 divided by 2\nmake z be 0\nsay 1 divided by z\nsay 99\n")
    result = run_chill(program, *flags)
    assert result.returncode == 1
    assert result.stdout == "5\nRuntime error: you divided by zero.\n"
