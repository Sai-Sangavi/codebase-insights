"""Render a metrics dict into a human-readable Markdown report.

This is the "make it actually readable" step -- metrics.json is the machine-
readable source of truth, metrics.md (built by this one function) is what a
person actually opens. No logic here computes anything new; it purely
formats what's already in the dict that runner.py assembled.
"""


def render_markdown(metrics: dict) -> str:
    lines = [f"# Codebase Report: {metrics['repo_path']}", ""]

    # l1_stats is entirely absent (not just empty) for an L2-only run
    # (skip_l1: true) -- checking "in metrics" rather than defaulting to {}
    # is what lets this function skip the Stack/Tests/Git sections cleanly
    # instead of rendering misleading "0 tests, 0 commits" for stats that
    # were never computed at all.
    if "l1_stats" in metrics:
        l1 = metrics["l1_stats"]

        lines += ["## Stack", "", "| Language | Files | LOC |", "|---|---|---|"]
        file_counts = l1.get("file_counts_by_language", {})
        loc_counts = l1.get("loc_by_language", {})
        for lang in sorted(file_counts):
            lines.append(f"| {lang} | {file_counts[lang]} | {loc_counts.get(lang, 0)} |")
        lines.append("")

        test_counts = l1.get("test_counts", {})
        lines += [
            "## Tests", "",
            f"{test_counts.get('total', 0)} tests ({test_counts.get('framework') or 'unknown framework'})",
            "",
        ]

        git_meta = l1.get("git_metadata", {})
        lines += [
            "## Git", "",
            f"{git_meta.get('commit_count', 0)} commits, "
            f"{git_meta.get('contributors', 0)} contributors, "
            f"{git_meta.get('repo_age_days', 0)} days old",
            "",
        ]

    # l2_patterns can be entirely absent too (claude CLI unavailable, or
    # skipped via config) -- `if l2:` handles both "key missing" and
    # "key present but None/empty" in one check.
    l2 = metrics.get("l2_patterns")
    if l2:
        lines += ["## Patterns", ""]
        for category, data in l2.get("categories", {}).items():
            title = category.replace("_", " ").title()
            lines.append(f"### {title}")
            # A category that hit a ClaudeCLIError (see llm/patterns.py's
            # analyze_category) has an "error" key instead of the normal
            # summary/consistency/example shape -- render that distinctly
            # rather than crashing on missing keys.
            if "error" in data:
                lines.append(f"_Error: {data['error']}_")
            else:
                lines.append(f"**Consistency:** {data.get('consistency', 'unknown')}")
                lines.append("")
                lines.append(data.get("summary", ""))
                example = data.get("example")
                if example:
                    lines.append("")
                    lines.append(f"```\n{example.get('snippet', '')}\n```")
                for exc in data.get("exceptions", []):
                    lines.append(f"- **Exception:** {exc}")
            lines.append("")
        # architecture_summary is free text (not per-category), rendered as
        # its own section only if the pass actually ran (config's
        # architecture_summary: true) and produced something.
        if l2.get("architecture_summary"):
            lines += ["## Architecture", "", l2["architecture_summary"], ""]

    return "\n".join(lines)
