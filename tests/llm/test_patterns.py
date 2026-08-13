import json
import shutil
import subprocess

import pytest

from llm.patterns import ClaudeCLIError, narrow_candidates, run_claude_cli

FAKE_CLAUDE_PATH = r"C:\fake\bin\claude.CMD"


@pytest.fixture
def resolved_claude(monkeypatch):
    """Make shutil.which("claude") resolve to a fixed fake path."""
    monkeypatch.setattr(shutil, "which", lambda name: FAKE_CLAUDE_PATH)
    return FAKE_CLAUDE_PATH


def test_run_claude_cli_returns_stdout_on_success(monkeypatch, resolved_claude):
    def fake_run(cmd, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="hello", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_claude_cli("prompt") == "hello"


def test_run_claude_cli_invokes_resolved_path_with_prompt_on_stdin(monkeypatch, resolved_claude):
    seen = {}

    def fake_run(cmd, input, capture_output, text, encoding, timeout):
        seen["cmd"] = cmd
        seen["input"] = input
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="hello", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_claude_cli("a very long prompt")
    # The resolved path is used (not the bare name, which never resolves to
    # claude.CMD on Windows), and the prompt goes via stdin, not argv, so it
    # can't blow the OS argv-length limit.
    assert seen["cmd"] == [FAKE_CLAUDE_PATH, "-p"]
    assert seen["input"] == "a very long prompt"
    assert "a very long prompt" not in seen["cmd"]


def test_run_claude_cli_encodes_stdin_as_utf8_for_non_ascii_prompts(monkeypatch, resolved_claude):
    # Regression test: subprocess.run(..., text=True) with no explicit
    # encoding falls back to the OS locale codec (cp1252 on this machine),
    # which raises UnicodeEncodeError for CJK/Cyrillic/emoji content — the
    # kind of thing a real "arbitrary codebase" is likely to contain.
    # Passing encoding="utf-8" explicitly avoids that regardless of locale.
    captured = {}

    def fake_run(cmd, input, capture_output, text, encoding, timeout):
        captured["encoding"] = encoding
        captured["input"] = input
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    non_ascii_prompt = "Explain this: 日本語 emoji 🎉 Кириллица"
    run_claude_cli(non_ascii_prompt)
    assert captured["encoding"] == "utf-8"
    assert captured["input"] == non_ascii_prompt


def test_run_claude_cli_raises_on_nonzero_exit(monkeypatch, resolved_claude):
    def fake_run(cmd, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError, match="boom"):
        run_claude_cli("prompt")


def test_run_claude_cli_raises_on_timeout(monkeypatch, resolved_claude):
    def fake_run(cmd, input, capture_output, text, encoding, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError, match="timed out"):
        run_claude_cli("prompt", timeout=5)


def test_run_claude_cli_propagates_file_not_found(monkeypatch, resolved_claude):
    def fake_run(cmd, input, capture_output, text, encoding, timeout):
        raise FileNotFoundError("no such file: claude")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(FileNotFoundError):
        run_claude_cli("prompt")


def test_run_claude_cli_raises_file_not_found_when_which_finds_nothing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)

    def unreachable_run(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("subprocess.run must not be called when which() fails")

    monkeypatch.setattr(subprocess, "run", unreachable_run)
    with pytest.raises(FileNotFoundError, match="not found on PATH"):
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
    from llm.patterns import synthesize_pattern

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
    from llm.patterns import synthesize_pattern

    result = synthesize_pattern(
        "db_connection", "how DB connections are obtained", {}, run_cli=lambda p: "{}"
    )
    assert result["consistency"] == "unknown"
    assert result["files_examined"] == []


def test_analyze_category_default_reads_narrowed_files_and_synthesizes(tmp_path):
    from llm.patterns import analyze_category_default

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


from llm.patterns import (
    analyze_category,
    describe_category,
    merge_batch_results,
    summarize_architecture,
)


def test_describe_category_known_category_uses_named_description():
    assert "database connection" in describe_category("db_connection")


def test_describe_category_unknown_category_falls_back_to_generic_text():
    assert describe_category("custom_thing") == "how this codebase handles custom thing"


def test_merge_batch_results_unions_files_and_exceptions_takes_worst_consistency():
    results = [
        {
            "category": "db_connection", "summary": "uses get_session()",
            "example": {"file": "a.py", "snippet": "..."},
            "consistency": "consistent", "exceptions": [], "files_examined": ["a.py"],
        },
        {
            "category": "db_connection", "summary": "uses get_session()",
            "example": {"file": "a.py", "snippet": "..."},
            "consistency": "inconsistent", "exceptions": ["b.py opens raw connection"],
            "files_examined": ["b.py"],
        },
    ]
    merged = merge_batch_results(results)
    assert merged["consistency"] == "inconsistent"
    assert merged["files_examined"] == ["a.py", "b.py"]
    assert merged["exceptions"] == ["b.py opens raw connection"]


def test_merge_batch_results_when_nothing_found_returns_first_result():
    results = [
        {"category": "logging", "summary": "", "example": None,
         "consistency": "unknown", "exceptions": [], "files_examined": []},
    ]
    assert merge_batch_results(results) == results[0]


def test_analyze_category_default_mode_delegates_to_narrow_and_synthesize(tmp_path):
    (tmp_path / "a.py").write_text("import logging", encoding="utf-8")
    calls = []

    def fake_cli(prompt):
        calls.append(prompt)
        return '["a.py"]' if len(calls) == 1 else '{"summary": "uses logging", "example": null, "consistency": "consistent", "exceptions": []}'

    result = analyze_category("logging", str(tmp_path), ["a.py"], run_cli=fake_cli)
    assert result["summary"] == "uses logging"


def test_analyze_category_full_mode_batches_and_merges(tmp_path):
    for i in range(4):
        (tmp_path / f"f{i}.py").write_text("import logging", encoding="utf-8")
    file_paths = [f"f{i}.py" for i in range(4)]

    def fake_cli(prompt):
        # Narrow calls return the batch's own files; synthesis calls return a fixed pattern.
        if "Respond with ONLY a JSON array" in prompt:
            return json.dumps([p for p in file_paths if p in prompt])
        return '{"summary": "uses logging", "example": null, "consistency": "consistent", "exceptions": []}'

    result = analyze_category(
        "logging", str(tmp_path), file_paths, full_repo_mode=True, batch_size=2, run_cli=fake_cli
    )
    assert result["consistency"] == "consistent"
    assert len(result["files_examined"]) == 4


def test_analyze_category_catches_claude_cli_error_per_category():
    def failing_cli(prompt):
        raise ClaudeCLIError("boom")

    result = analyze_category("logging", "/unused", ["a.py"], run_cli=failing_cli)
    assert result == {"category": "logging", "error": "boom"}


def test_summarize_architecture_returns_cli_output_stripped():
    result = summarize_architecture("/unused", ["a.py", "b.py"], run_cli=lambda p: "  Some summary.  \n")
    assert result == "Some summary."


def test_summarize_architecture_handles_cli_error_gracefully():
    def failing_cli(prompt):
        raise ClaudeCLIError("boom")

    result = summarize_architecture("/unused", ["a.py"], run_cli=failing_cli)
    assert "unavailable" in result


def test_analyze_category_full_mode_with_empty_file_list_does_not_crash():
    result = analyze_category("logging", "/unused", [], full_repo_mode=True, run_cli=lambda p: "[]")
    assert result["consistency"] == "unknown"
    assert result["files_examined"] == []


def test_merge_batch_results_with_empty_results_list_does_not_crash():
    result = merge_batch_results([])
    assert result["consistency"] == "unknown"
    assert result["files_examined"] == []


def test_analyze_category_full_mode_with_non_evenly_divisible_batch_boundary(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text("import logging", encoding="utf-8")
    file_paths = [f"f{i}.py" for i in range(5)]

    def fake_cli(prompt):
        if "Respond with ONLY a JSON array" in prompt:
            return json.dumps([p for p in file_paths if p in prompt])
        return '{"summary": "uses logging", "example": null, "consistency": "consistent", "exceptions": []}'

    result = analyze_category(
        "logging", str(tmp_path), file_paths, full_repo_mode=True, batch_size=2, run_cli=fake_cli
    )
    assert result["consistency"] == "consistent"
    assert len(result["files_examined"]) == 5
    assert set(result["files_examined"]) == set(file_paths)
