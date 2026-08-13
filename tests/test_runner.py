import json

from codebase_insights import runner
from codebase_insights.runner import run


def _make_minimal_repo(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "test_main.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp_path


def test_run_writes_metrics_json_with_l1_stats(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "collect_l2_patterns", lambda repo_path, files, config: None)
    exit_code = run(str(repo), out=str(out_path))
    assert exit_code == 0
    metrics = json.loads(out_path.read_text(encoding="utf-8"))
    assert metrics["repo_path"] == str(repo.resolve())
    assert metrics["l1_stats"]["file_counts_by_language"]["python"] == 2
    assert metrics["l1_stats"]["test_counts"]["total"] == 1
    assert "l2_patterns" not in metrics


def test_run_uses_smart_default_output_location_when_out_not_given(tmp_path, monkeypatch):
    # Redirect the "repo root" anchor to a throwaway directory so this test
    # never writes into the real codebase-insights repo.
    fake_repo_root = tmp_path / "fake-package-root"
    monkeypatch.setattr(runner, "_PACKAGE_ROOT", fake_repo_root)

    analyzed = tmp_path / "target-repo"
    analyzed.mkdir()
    repo = _make_minimal_repo(analyzed)
    monkeypatch.setattr(runner, "collect_l2_patterns", lambda repo_path, files, config: None)

    exit_code = run(str(repo))

    assert exit_code == 0
    json_path = fake_repo_root / "output" / "json" / "target-repo-metrics.json"
    md_path = fake_repo_root / "output" / "md" / "target-repo-metrics.md"
    assert json_path.exists()
    assert md_path.exists()
    metrics = json.loads(json_path.read_text(encoding="utf-8"))
    assert metrics["repo_path"] == str(repo.resolve())


def test_run_returns_1_on_malformed_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    repo = _make_minimal_repo(tmp_path)
    bad_config = tmp_path / "bad_config.yaml"
    bad_config.write_text("nonexistent_key: true\n", encoding="utf-8")
    exit_code = run(str(repo), config_path=str(bad_config))
    assert exit_code == 1
    assert "unknown config key" in capsys.readouterr().err


def test_run_returns_1_when_repo_path_does_not_exist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    exit_code = run(str(tmp_path / "does-not-exist"))
    assert exit_code == 1
    assert "does not exist" in capsys.readouterr().err


def test_run_returns_1_when_output_cannot_be_written(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "collect_l2_patterns", lambda repo_path, files, config: None)
    bad_out = tmp_path / "no-such-dir" / "metrics.json"
    exit_code = run(str(repo), out=str(bad_out))
    assert exit_code == 1


def test_run_writes_metrics_md_alongside_json(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "collect_l2_patterns", lambda repo_path, files, config: None)
    exit_code = run(str(repo), out=str(out_path))
    assert exit_code == 0
    md_path = out_path.with_suffix(".md")
    assert md_path.exists()
    assert "# Codebase Report" in md_path.read_text(encoding="utf-8")


def test_run_includes_l2_patterns_when_claude_cli_succeeds(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)

    fake_l2 = {
        "mode": "default",
        "categories": {"logging": {"category": "logging", "summary": "uses logging",
                                    "example": None, "consistency": "consistent",
                                    "exceptions": [], "files_examined": []}},
        "architecture_summary": "A simple repo.",
    }
    monkeypatch.setattr(runner, "collect_l2_patterns", lambda repo_path, files, config: fake_l2)
    exit_code = run(str(repo), out=str(out_path))
    assert exit_code == 0
    metrics = json.loads(out_path.read_text(encoding="utf-8"))
    assert metrics["l2_patterns"] == fake_l2


def test_run_omits_l2_patterns_when_claude_cli_missing(tmp_path, monkeypatch, capsys):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)

    def raise_missing(repo_path, files, config):
        raise FileNotFoundError("no claude on PATH")

    monkeypatch.setattr(runner, "collect_l2_patterns", raise_missing)
    exit_code = run(str(repo), out=str(out_path))
    assert exit_code == 0
    metrics = json.loads(out_path.read_text(encoding="utf-8"))
    assert "l2_patterns" not in metrics
    err = capsys.readouterr().err
    assert "claude CLI not found" in err
