from codebase_insights.report import render_markdown


def _sample_metrics(with_l2=False):
    metrics = {
        "repo_path": "/some/repo",
        "analyzed_at": "2026-08-13T00:00:00+00:00",
        "l1_stats": {
            "file_counts_by_language": {"python": 10, "javascript": 2},
            "loc_by_language": {"python": 500, "javascript": 20},
            "test_counts": {"total": 12, "framework": "pytest"},
            "dependency_manifests": [{"file": "requirements.txt", "count": 3}],
            "config_files": ["Dockerfile"],
            "git_metadata": {"commit_count": 42, "contributors": 3, "repo_age_days": 100},
            "commit_convention": {"detected": "conventional_commits", "confidence": "high"},
            "branch_strategy": {"signal": "trunk_based"},
            "pr_templates_present": True,
        },
    }
    if with_l2:
        metrics["l2_patterns"] = {
            "mode": "default",
            "categories": {
                "db_connection": {
                    "category": "db_connection",
                    "summary": "Uses get_session() everywhere.",
                    "example": {"file": "db/session.py", "snippet": "with get_session() as s:"},
                    "consistency": "consistent",
                    "exceptions": [],
                    "files_examined": ["db/session.py"],
                },
                "logging": {"category": "logging", "error": "claude CLI exited 1: boom"},
            },
            "architecture_summary": "This repo has a db/ module and an api/ module.",
        }
    return metrics


def test_render_markdown_includes_stack_table():
    markdown = render_markdown(_sample_metrics())
    assert "| python | 10 | 500 |" in markdown
    assert "| javascript | 2 | 20 |" in markdown


def test_render_markdown_includes_test_and_git_sections():
    markdown = render_markdown(_sample_metrics())
    assert "12 tests (pytest)" in markdown
    assert "42 commits, 3 contributors, 100 days old" in markdown


def test_render_markdown_omits_patterns_section_when_l2_absent():
    markdown = render_markdown(_sample_metrics(with_l2=False))
    assert "## Patterns" not in markdown


def test_render_markdown_includes_pattern_category_and_error_and_architecture():
    markdown = render_markdown(_sample_metrics(with_l2=True))
    assert "### Db Connection" in markdown
    assert "Uses get_session() everywhere." in markdown
    assert "### Logging" in markdown
    assert "_Error: claude CLI exited 1: boom_" in markdown
    assert "## Architecture" in markdown
    assert "This repo has a db/ module" in markdown


def test_render_markdown_omits_l1_sections_when_l1_stats_absent():
    # An L2-only run (skip_l1: true) omits l1_stats from metrics entirely;
    # the report shouldn't render misleading "0 tests"/"0 commits" sections
    # for stats that were never computed.
    metrics = {
        "repo_path": "/some/repo",
        "analyzed_at": "2026-08-13T00:00:00+00:00",
        "l2_patterns": {
            "mode": "default",
            "categories": {},
            "architecture_summary": "A repo.",
        },
    }
    markdown = render_markdown(metrics)
    assert "## Stack" not in markdown
    assert "## Tests" not in markdown
    assert "## Git" not in markdown
    assert "## Architecture" in markdown
