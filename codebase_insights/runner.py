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

    l1_stats = collect_l1_stats(repo_path, files)
    l2_patterns = _run_l2_or_none(repo_path, files, config)

    metrics = {
        "repo_path": str(repo.resolve()),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "l1_stats": l1_stats,
    }
    if l2_patterns is not None:
        metrics["l2_patterns"] = l2_patterns

    output_path = Path(out or config["output_path"])
    try:
        output_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        output_path.with_suffix(".md").write_text(render_markdown(metrics), encoding="utf-8")
    except OSError as e:
        print(f"error: could not write output: {e}", file=sys.stderr)
        return 1
    print(f"wrote {output_path} and {output_path.with_suffix('.md')}")
    return 0
