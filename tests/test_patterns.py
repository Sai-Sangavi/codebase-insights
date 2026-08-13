import subprocess

import pytest

from patterns import ClaudeCLIError, narrow_candidates, run_claude_cli


def test_run_claude_cli_returns_stdout_on_success(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="hello", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_claude_cli("prompt") == "hello"


def test_run_claude_cli_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError, match="boom"):
        run_claude_cli("prompt")


def test_run_claude_cli_raises_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError, match="timed out"):
        run_claude_cli("prompt", timeout=5)


def test_run_claude_cli_propagates_file_not_found(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise FileNotFoundError("no such file: claude")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(FileNotFoundError):
        run_claude_cli("prompt")


def test_narrow_candidates_parses_json_array_and_filters_to_known_paths():
    def fake_cli(prompt):
        return 'Sure, here you go:\n["db/session.py", "made/up.py"]\nhope that helps'

    result = narrow_candidates(
        "db_connection", "how DB connections are obtained",
        ["db/session.py", "api/routes.py"], run_cli=fake_cli,
    )
    assert result == ["db/session.py"]  # "made/up.py" filtered out — not in file_paths


def test_narrow_candidates_returns_empty_list_on_unparseable_output():
    result = narrow_candidates(
        "db_connection", "how DB connections are obtained",
        ["db/session.py"], run_cli=lambda prompt: "not json at all",
    )
    assert result == []
