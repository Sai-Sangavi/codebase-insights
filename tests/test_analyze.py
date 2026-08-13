import json

from analyze import main, parse_args


def _make_minimal_repo(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "test_main.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return tmp_path


def test_parse_args_defaults():
    args = parse_args(["/some/repo"])
    assert args.repo_path == "/some/repo"
    assert args.config is None
    assert args.full is False
    assert args.out is None


def test_main_writes_metrics_json_with_l1_stats(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)
    exit_code = main([str(repo), "--out", str(out_path)])
    assert exit_code == 0
    metrics = json.loads(out_path.read_text(encoding="utf-8"))
    assert metrics["repo_path"] == str(repo.resolve())
    assert metrics["l1_stats"]["file_counts_by_language"]["python"] == 2
    assert metrics["l1_stats"]["test_counts"]["total"] == 1
    assert "l2_patterns" not in metrics  # L2 not wired yet in this task


def test_main_returns_1_on_malformed_config(tmp_path, capsys):
    repo = _make_minimal_repo(tmp_path)
    bad_config = tmp_path / "bad_config.yaml"
    bad_config.write_text("nonexistent_key: true\n", encoding="utf-8")
    exit_code = main([str(repo), "--config", str(bad_config)])
    assert exit_code == 1
    assert "unknown config key" in capsys.readouterr().err
