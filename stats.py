"""L1 deterministic stats: no LLM involved anywhere in this module."""

import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from file_walker import WalkedFile


def count_files_by_language(files: list[WalkedFile]) -> dict:
    counts = Counter(f.language for f in files if f.language is not None)
    return dict(counts)


def count_loc_by_language(repo_path: str, files: list[WalkedFile]) -> dict:
    totals: Counter = Counter()
    root = Path(repo_path)
    for f in files:
        if f.language is None:
            continue
        try:
            text = (root / f.path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        totals[f.language] += len(text.splitlines())
    return dict(totals)


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    if name.startswith("test_"):
        return True
    stem = name.split(".")[0]
    if stem.endswith("_test"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    return False


def count_tests(repo_path: str, files: list[WalkedFile]) -> dict:
    root = Path(repo_path)
    total = 0
    framework = None
    for f in files:
        if not _is_test_file(f.path):
            continue
        try:
            text = (root / f.path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if f.language == "python":
            matches = re.findall(r"^\s*def (test_\w+)", text, re.MULTILINE)
            total += len(matches)
            if matches:
                framework = framework or "pytest"
        else:
            matches = re.findall(r"(?<!\.)\b(?:it|test)\(", text)
            total += len(matches)
            if matches:
                framework = framework or "jest"
    return {"total": total, "framework": framework}


_PARSE_FAILED = object()


def _count_requirements_txt(text: str) -> int:
    return len([
        line for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ])


def _count_pyproject_toml(text: str) -> int:
    """Heuristic line-based counter -- not a full TOML parse. Handles PEP 621
    dependencies = [...] arrays (single- or multi-line) and Poetry-style
    [tool.poetry.dependencies] tables. Real edge cases (inline tables,
    dependency groups, environment markers) are out of scope for this stat."""
    lines = text.splitlines()
    count = 0
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()

        if re.match(r"dependencies\s*=\s*\[", stripped):
            if "]" in stripped:
                inner = stripped[stripped.index("[") + 1 : stripped.rindex("]")]
                count += len(re.findall(r"['\"][^'\"]+['\"]", inner))
                i += 1
                continue
            i += 1
            while i < n and "]" not in lines[i]:
                if re.search(r"['\"][^'\"]+['\"]", lines[i]):
                    count += 1
                i += 1
            i += 1  # skip the closing "]" line
            continue

        if stripped == "[tool.poetry.dependencies]":
            i += 1
            while i < n and not lines[i].strip().startswith("["):
                entry = lines[i].strip()
                if entry and "=" in entry and not entry.startswith("#"):
                    key = entry.split("=", 1)[0].strip()
                    if key != "python":  # interpreter constraint, not a real dependency
                        count += 1
                i += 1
            continue

        i += 1
    return count


def _count_package_json(text: str):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _PARSE_FAILED
    return len(data.get("dependencies", {})) + len(data.get("devDependencies", {}))


_MANIFEST_COUNTERS = {
    "requirements.txt": _count_requirements_txt,
    "pyproject.toml": _count_pyproject_toml,
    "package.json": _count_package_json,
}


def inventory_dependency_manifests(repo_path: str) -> list[dict]:
    root = Path(repo_path)
    results = []
    for filename, counter in _MANIFEST_COUNTERS.items():
        path = root / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        count = counter(text)
        if count is _PARSE_FAILED:
            continue
        results.append({"file": filename, "count": count})
    return results


CONFIG_FILE_CANDIDATES = [
    "Dockerfile",
    "docker-compose.yml",
    ".github/workflows",
    ".eslintrc.json",
    ".eslintrc.js",
    ".flake8",
    "pyproject.toml",
    ".pre-commit-config.yaml",
]


def inventory_config_files(repo_path: str) -> list[str]:
    root = Path(repo_path)
    found = []
    for candidate in CONFIG_FILE_CANDIDATES:
        target = root / candidate
        if target.is_dir():
            for p in sorted(target.iterdir()):
                if p.is_file():
                    found.append(f"{candidate}/{p.name}")
        elif target.is_file():
            found.append(candidate)
    return found


def _run_git(repo_path: str, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo_path, capture_output=True, text=True, timeout=30
        )
    except (FileNotFoundError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_metadata(repo_path: str) -> dict:
    commit_count_raw = _run_git(repo_path, ["rev-list", "--count", "HEAD"])
    commit_count = int(commit_count_raw) if commit_count_raw.isdigit() else 0

    contributors_raw = _run_git(repo_path, ["shortlog", "-sn", "--all"])
    contributors = len([line for line in contributors_raw.splitlines() if line.strip()])

    all_timestamps_raw = _run_git(repo_path, ["log", "--format=%at"])
    timestamps = [line for line in all_timestamps_raw.splitlines() if line.strip()]
    repo_age_days = 0
    if timestamps:
        first_commit_epoch = timestamps[-1]  # oldest commit — log defaults to newest-first
        if first_commit_epoch.isdigit():
            first_commit = datetime.fromtimestamp(int(first_commit_epoch), tz=timezone.utc)
            repo_age_days = (datetime.now(tz=timezone.utc) - first_commit).days

    return {
        "commit_count": commit_count,
        "contributors": contributors,
        "repo_age_days": repo_age_days,
    }


_CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|chore|refactor|test|style|perf|build|ci)(\(.+\))?:\s"
)


def detect_commit_convention(repo_path: str) -> dict:
    log = _run_git(repo_path, ["log", "-50", "--format=%s"])
    messages = [line for line in log.splitlines() if line.strip()]
    if not messages:
        return {"detected": "unknown", "confidence": "low"}
    matching = sum(1 for m in messages if _CONVENTIONAL_COMMIT_RE.match(m))
    ratio = matching / len(messages)
    if ratio >= 0.7:
        return {"detected": "conventional_commits", "confidence": "high"}
    if ratio >= 0.3:
        return {"detected": "conventional_commits", "confidence": "medium"}
    return {"detected": "none", "confidence": "high"}


def detect_branch_strategy(repo_path: str) -> dict:
    branches_raw = _run_git(repo_path, ["branch", "-a"])
    branches = [
        b.strip().lstrip("* ").replace("remotes/origin/", "")
        for b in branches_raw.splitlines() if b.strip()
    ]
    gitflow_markers = ("develop", "release", "hotfix")
    if any(b == marker or b.startswith(marker + "/") for b in branches for marker in gitflow_markers):
        return {"signal": "gitflow"}
    if len(set(branches)) <= 2:
        return {"signal": "trunk_based"}
    return {"signal": "unclear"}


def check_pr_templates(repo_path: str) -> bool:
    root = Path(repo_path)
    candidates = [
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE",
        "PULL_REQUEST_TEMPLATE.md",
    ]
    return any((root / c).exists() for c in candidates)
