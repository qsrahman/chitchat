import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("check_script", Path(__file__).parent.parent / "scripts" / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.fixture
def runs(monkeypatch):
    """Record the commands the script runs; the test says which one fails."""
    ran, failing = [], set()

    def fake_run(command, **kwargs):
        ran.append(command[2] if command[0] == "uv" and command[1] == "run" else command[0])
        name = next(n for n, c in check.STEPS if c == command)
        return subprocess.CompletedProcess(command, 1 if name in failing else 0)

    monkeypatch.setattr(check.subprocess, "run", fake_run)
    monkeypatch.setattr(check.shutil, "which", lambda name: "/usr/bin/" + name)
    return ran, failing


def test_all_steps_run_in_order_and_pass(runs, capsys):
    ran, _ = runs
    assert check.main() == 0
    assert ran == ["ruff", "pyright", "npx", "npx", "pytest"]
    assert "all checks passed" in capsys.readouterr().out


@pytest.mark.parametrize("failing_step, expected_ran", [("ruff", ["ruff"]), ("pyright", ["ruff", "pyright"]),
                                                        ("eslint", ["ruff", "pyright", "npx"]),
                                                        ("tsc", ["ruff", "pyright", "npx", "npx"]),
                                                        ("tests", ["ruff", "pyright", "npx", "npx", "pytest"])])
def test_it_stops_at_the_first_failure_and_says_which(runs, capsys, failing_step, expected_ran):
    ran, failing = runs
    failing.add(failing_step)
    assert check.main() == 1
    assert ran == expected_ran
    assert f"-- {failing_step} FAILED" in capsys.readouterr().out


def test_without_node_the_javascript_checks_are_skipped_not_failed(runs, monkeypatch, capsys):
    ran, _ = runs
    monkeypatch.setattr(check.shutil, "which", lambda name: None)
    assert check.main() == 0
    assert ran == ["ruff", "pyright", "pytest"]
    out = capsys.readouterr().out
    assert "eslint: skipped" in out and "tsc: skipped" in out


def test_the_steps_are_what_the_docs_say():
    assert [n for n, _ in check.STEPS] == ["ruff", "pyright", "eslint", "tsc", "tests"]
    hook = (Path(__file__).parent.parent / ".githooks" / "pre-commit").read_text()
    assert "scripts/check.py" in hook
