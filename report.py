"""Render a metrics dict into a human-readable Markdown report."""


def render_markdown(metrics: dict) -> str:
    lines = [f"# Codebase Report: {metrics['repo_path']}", ""]
    l1 = metrics.get("l1_stats", {})

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

    l2 = metrics.get("l2_patterns")
    if l2:
        lines += ["## Patterns", ""]
        for category, data in l2.get("categories", {}).items():
            title = category.replace("_", " ").title()
            lines.append(f"### {title}")
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
        if l2.get("architecture_summary"):
            lines += ["## Architecture", "", l2["architecture_summary"], ""]

    return "\n".join(lines)
