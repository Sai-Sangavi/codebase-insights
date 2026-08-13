import json
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


def test_synthesize_pattern_parses_full_json_response():
    from patterns import synthesize_pattern

    def fake_cli(prompt):
        return json.dumps({
            "summary": "Uses get_session() everywhere.",
            "example": {"file": "db/session.py", "snippet": "with get_session() as s:"},
            "consistency": "consistent",
            "exceptions": [],
        })

    result = synthesize_pattern(
        "db_connection", "how DB connections are obtained",
        {"db/session.py": "def get_session(): ..."}, run_cli=fake_cli,
    )
    assert result["category"] == "db_connection"
    assert result["summary"] == "Uses get_session() everywhere."
    assert result["consistency"] == "consistent"
    assert result["files_examined"] == ["db/session.py"]


def test_synthesize_pattern_with_no_candidates_returns_unknown():
    from patterns import synthesize_pattern

    result = synthesize_pattern(
        "db_connection", "how DB connections are obtained", {}, run_cli=lambda p: "{}"
    )
    assert result["consistency"] == "unknown"
    assert result["files_examined"] == []


def test_analyze_category_default_reads_narrowed_files_and_synthesizes(tmp_path):
    from patterns import analyze_category_default

    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "session.py").write_text("def get_session(): ...", encoding="utf-8")

    calls = []

    def fake_cli(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return '["db/session.py"]'
        return json.dumps({
            "summary": "Uses get_session().", "example": None,
            "consistency": "consistent", "exceptions": [],
        })

    result = analyze_category_default(
        "db_connection", "how DB connections are obtained",
        str(tmp_path), ["db/session.py"], run_cli=fake_cli,
    )
    assert len(calls) == 2  # one narrow call, one synthesis call
    assert result["summary"] == "Uses get_session()."
