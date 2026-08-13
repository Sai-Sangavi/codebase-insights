"""Orchestration: load config, walk the repo, compute L1 + L2, write outputs.

This is the module that ties everything else together. cli.py only parses
argv and calls run() below -- all the actual "what does one invocation of
codebase-insights do" logic lives here. Reading this file top-to-bottom
(collect_l1_stats -> collect_l2_patterns -> run) is the fastest way to
understand the whole tool's control flow.
"""

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
    """Assemble every L1 (deterministic, no-LLM) stat into one dict -- this
    IS the "l1_stats" key in the final output. Every function called here
    lives in stats/stats.py; this function's only job is gluing their
    results together under one shape."""
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
    """Assemble every L2 (LLM-based) finding -- one analyze_category() call
    per entry in config["pattern_categories"], plus the architecture-summary
    pass if enabled. This is where config drives which categories actually
    run: an empty pattern_categories list just produces an empty categories
    dict below with zero LLM calls made.

    Raises FileNotFoundError if the claude CLI isn't on PATH — caller decides
    what that means (run()'s below skips L2 entirely and warns).
    """
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
    """The ONE place FileNotFoundError (claude CLI missing entirely) gets
    caught -- turns "no claude installed" into a single stderr warning and a
    None result, rather than a crash. run() below treats None as "omit
    l2_patterns from the output entirely", so a machine without Claude Code
    installed still gets a complete, correct L1-only result."""
    try:
        return collect_l2_patterns(repo_path, files, config)
    except FileNotFoundError:
        print("warning: claude CLI not found on PATH; skipping pattern detection", file=sys.stderr)
        return None


def _has_l2_content(metrics: dict) -> bool:
    """True only if l2_patterns actually contains a finding — a non-empty
    categories dict or a real architecture_summary. An empty-but-present
    l2_patterns (e.g. pattern_categories: [] with architecture_summary: false)
    is not 'full analysis', just L2's inert default shape."""
    l2 = metrics.get("l2_patterns")
    if not l2:
        return False
    return bool(l2.get("categories")) or bool(l2.get("architecture_summary"))


def _default_output_paths(repo_path: str, metrics: dict) -> tuple[Path, Path]:
    """Smart default when neither --out nor config's output_path is set: write
    into codebase-insights' own output/<category>/json/ and .../md/, named
    after the analyzed repo, so every run's results are archived in one place.

    <category> is full-analysis if the output actually contains L2 pattern
    findings, basic-stats otherwise (L2 skipped via config, empty via
    pattern_categories: [], or the claude CLI was unavailable).
    """
    repo_name = Path(repo_path).resolve().name
    category = "full-analysis" if _has_l2_content(metrics) else "basic-stats"
    json_dir = _PACKAGE_ROOT / "output" / category / "json"
    md_dir = _PACKAGE_ROOT / "output" / category / "md"
    json_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)
    return json_dir / f"{repo_name}-metrics.json", md_dir / f"{repo_name}-metrics.md"


def run(
    repo_path: str,
    config_path: str | None = None,
    full: bool = False,
    out: str | None = None,
) -> int:
    """The whole pipeline for one invocation, called by cli.main() with the
    already-parsed argv values. Returns a process exit code (0 success,
    1 any handled failure) -- never raises for expected failure modes.

    Order of operations, and why:
      1. Validate repo_path FIRST, before touching config -- a typo'd path
         should fail immediately, not after loading config successfully.
      2. Load + validate config -- fails fast on a bad config.yaml before
         any file-walking or LLM calls happen.
      3. Walk the repo once -- both L1 and L2 need this same file list.
      4. Run L2 before assembling L1 into `metrics` -- purely an ordering
         choice in the code below (L2 is the slow part; computing it first
         means the L1 dict-literal construction happens right before the
         write, not that L1 depends on L2 in any way).
      5. Only include l1_stats/l2_patterns in the output dict if they
         actually ran (skip_l1 config, or L2 returning None) -- the report
         renderer and downstream consumers treat an absent key as "this
         level wasn't computed", not as a zero/empty result.
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        print(f"error: repo_path does not exist or is not a directory: {repo_path}", file=sys.stderr)
        return 1

    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # --full CLI flag always wins over config.yaml's full_repo_mode, so a
    # project can default to full mode in its config while still letting
    # someone request the fast/narrow mode without editing that file.
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

    # --out (or config's output_path) always wins over the smart default --
    # a single fixed path, .md derived by swapping the extension. Otherwise,
    # fall through to _default_output_paths' output/<category>/ scheme.
    explicit_out = out or config["output_path"]
    if explicit_out:
        output_path = Path(explicit_out)
        md_path = output_path.with_suffix(".md")
    else:
        output_path, md_path = _default_output_paths(repo_path, metrics)

    try:
        output_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        md_path.write_text(render_markdown(metrics), encoding="utf-8")
    except OSError as e:
        print(f"error: could not write output: {e}", file=sys.stderr)
        return 1
    print(f"wrote {output_path} and {md_path}")
    return 0
