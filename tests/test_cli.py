import json

from codebase_insights import runner
from codebase_insights.cli import main, parse_args


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


def test_main_parses_argv_and_delegates_to_run(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "collect_l2_patterns", lambda repo_path, files, config: None)

    exit_code = main([str(repo), "--out", str(out_path), "--full"])

    assert exit_code == 0
    metrics = json.loads(out_path.read_text(encoding="utf-8"))
    assert metrics["repo_path"] == str(repo.resolve())
    assert metrics["l1_stats"]["file_counts_by_language"]["python"] == 2
