"""Orchestration: load config, walk the repo, compute L1 + L2, write outputs."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import ConfigError, get_effective_excludes, load_config
from .llm.patterns import analyze_category, summarize_architecture
from .report import render_markdown
from .stats.file_walker import walk_files
from .stats.stats import (
    check_pr_templates,
    count_files_by_language,
    count_loc_by_language,
    count_tests,
    detect_branch_strategy,
    detect_commit_convention,
    git_metadata,
    inventory_config_files,
    inventory_dependency_manifests,
)

# codebase-insights' own repo root (this file lives at <root>/codebase_insights/runner.py).
# Used as the anchor for the smart default output location below. Tests monkeypatch this
# constant to a tmp_path so they never write into the real repo.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def collect_l1_stats(repo_path: str, files: list) -> dict:
    return {
        "file_counts_by_language": count_files_by_language(files),
        "loc_by_language": count_loc_by_language(repo_path, files),
        "test_counts": count_tests(repo_path, files),
        "dependency_manifests": inventory_dependency_manifests(repo_path),
        "config_files": inventory_config_files(repo_path),
        "git_metadata": git_metadata(repo_path),
        "commit_convention": detect_commit_convention(repo_path),
        "branch_strategy": detect_branch_strategy(repo_path),
        "pr_templates_present": check_pr_templates(repo_path),
    }


def collect_l2_patterns(repo_path: str, files: list, config: dict) -> dict:
    """Raises FileNotFoundError if the claude CLI isn't on PATH — caller decides
    what that means (run()'s below skips L2 entirely and warns)."""
    file_paths = [f.path for f in files]
    categories = {
        category: analyze_category(
            category, repo_path, file_paths,
            full_repo_mode=config["full_repo_mode"],
            batch_size=config["batch_size"],
        )
        for category in config["pattern_categories"]
    }
    architecture_summary = (
        summarize_architecture(repo_path, file_paths)
        if config["architecture_summary"] else None
    )
    return {
        "mode": "full_repo" if config["full_repo_mode"] else "default",
        "categories": categories,
        "architecture_summary": architecture_summary,
    }


def _run_l2_or_none(repo_path: str, files: list, config: dict) -> dict | None:
    try:
        return collect_l2_patterns(repo_path, files, config)
    except FileNotFoundError:
        print("warning: claude CLI not found on PATH; skipping pattern detection", file=sys.stderr)
        return None


def _default_output_paths(repo_path: str) -> tuple[Path, Path]:
    """Smart default when neither --out nor config's output_path is set: write
    into codebase-insights' own output/json/ and output/md/, named after the
    analyzed repo, so every run's results are archived in one place."""
    repo_name = Path(repo_path).resolve().name
    json_dir = _PACKAGE_ROOT / "output" / "json"
    md_dir = _PACKAGE_ROOT / "output" / "md"
    json_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)
    return json_dir / f"{repo_name}-metrics.json", md_dir / f"{repo_name}-metrics.md"


def run(
    repo_path: str,
    config_path: str | None = None,
    full: bool = False,
    out: str | None = None,
) -> int:
    repo = Path(repo_path)
    if not repo.is_dir():
        print(f"error: repo_path does not exist or is not a directory: {repo_path}", file=sys.stderr)
        return 1

    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if full:
        config["full_repo_mode"] = True

    files = walk_files(
        repo_path,
        exclude=get_effective_excludes(config),
        languages=config["languages"] or None,
    )

    l2_patterns = _run_l2_or_none(repo_path, files, config)

    metrics = {
        "repo_path": str(repo.resolve()),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
    if not config["skip_l1"]:
        metrics["l1_stats"] = collect_l1_stats(repo_path, files)
    if l2_patterns is not None:
        metrics["l2_patterns"] = l2_patterns

    explicit_out = out or config["output_path"]
    if explicit_out:
        output_path = Path(explicit_out)
        md_path = output_path.with_suffix(".md")
    else:
        output_path, md_path = _default_output_paths(repo_path)

    try:
        output_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        md_path.write_text(render_markdown(metrics), encoding="utf-8")
    except OSError as e:
        print(f"error: could not write output: {e}", file=sys.stderr)
        return 1
    print(f"wrote {output_path} and {md_path}")
    return 0
