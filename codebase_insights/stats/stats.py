"""L1 deterministic stats: no LLM involved anywhere in this module.

Every function here takes a repo path (and usually the file list from
file_walker) and returns a plain dict/list -- pure computation, no
subjective judgment. Contrast with llm/patterns.py, where the L2 layer asks
Claude to characterize *conventions*, which necessarily involves judgment.
"""

import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .file_walker import WalkedFile


def count_files_by_language(files: list[WalkedFile]) -> dict:
    """{"python": 34, "javascript": 15, ...} -- files with no recognized
    language (WalkedFile.language is None) are silently excluded, not
    counted as a fake "unknown" bucket."""
    counts = Counter(f.language for f in files if f.language is not None)
    return dict(counts)


def count_loc_by_language(repo_path: str, files: list[WalkedFile]) -> dict:
    """Lines of code per language. Reads every classified file's content --
    if a file can't be decoded as UTF-8 (binary content sneaking past
    file_walker's extension-based classification) it's silently skipped
    from the LOC count, not treated as an error."""
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
    """Filename-based test-file detection. Anchored deliberately (prefix/
    suffix/dotted-segment, never a bare substring) -- an earlier, naive
    version matched "test_" anywhere in the name and misclassified real
    source files like contest_winners.py or attestation_service.py as
    tests. The bare tests.py/test.py case was added after a real validation
    run (against miguelgrinberg/microblog) showed a whole project's test
    suite going undetected because it lived in one un-prefixed file."""
    name = Path(path).name
    if name in ("test.py", "tests.py"):
        return True
    if name.startswith("test_"):
        return True
    stem = name.split(".")[0]
    if stem.endswith("_test"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    return False


def count_tests(repo_path: str, files: list[WalkedFile]) -> dict:
    """Count test functions across every file _is_test_file recognizes.
    Two counting strategies depending on language, since "what a test
    function looks like" differs by ecosystem:
      - Python: regex for `def test_...` -- this is pytest's own discovery
        convention, so matching it directly is both simple and accurate.
      - everything else: regex for bare `it(...)`/`test(...)` calls, the
        jest/mocha declaration style. `framework` is reported as "jest" for
        this branch regardless of whether the repo actually uses jest or
        mocha -- we can't tell them apart from syntax alone, and the two
        are close enough for this stat's purposes.
    `framework` is set from whichever branch fires first and never
    overwritten -- a polyglot repo with both Python and JS tests reports
    only the first one encountered, a known simplification.
    """
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
            # (?<!\.) excludes method-call syntax like `someRegex.test(x)`
            # (JS's native RegExp.prototype.test) -- without it, ordinary
            # non-test code using .test() would inflate the count.
            matches = re.findall(r"(?<!\.)\b(?:it|test)\(", text)
            total += len(matches)
            if matches:
                framework = framework or "jest"
    return {"total": total, "framework": framework}


# Sentinel distinguishing "this manifest failed to parse" from "this
# manifest parsed fine and genuinely has 0 dependencies" -- a malformed
# package.json must be skipped entirely (per the spec's "don't silently
# report a fact about broken input" rule), not reported as count: 0, which
# would look identical to a real empty-deps package.json.
_PARSE_FAILED = object()


def _count_requirements_txt(text: str) -> int:
    """Every non-blank, non-comment line is one dependency spec."""
    return len([
        line for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ])


def _count_pyproject_toml(text: str) -> int:
    """Heuristic line-based counter -- not a full TOML parse. Handles PEP 621
    dependencies = [...] arrays (single- or multi-line) and Poetry-style
    [tool.poetry.dependencies] tables. Real edge cases (inline tables,
    dependency groups, environment markers) are out of scope for this stat.

    Line-based rather than a real TOML parser on purpose: this is a "roughly
    how many deps does this project have" stat, not something anything
    downstream depends on being exact.
    """
    lines = text.splitlines()
    count = 0
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()

        if re.match(r"dependencies\s*=\s*\[", stripped):
            if "]" in stripped:
                # Single-line array: `dependencies = ["a", "b"]` -- count the
                # quoted entries between the brackets on this one line and
                # move on. (An earlier version of this function didn't
                # special-case this and left its "inside an array" flag
                # stuck on, so it kept counting entries from the NEXT
                # unrelated array too -- caught by a real validation run.)
                inner = stripped[stripped.index("[") + 1 : stripped.rindex("]")]
                count += len(re.findall(r"['\"][^'\"]+['\"]", inner))
                i += 1
                continue
            # Multi-line array: consume lines until the closing "]",
            # counting each quoted entry along the way.
            i += 1
            while i < n and "]" not in lines[i]:
                if re.search(r"['\"][^'\"]+['\"]", lines[i]):
                    count += 1
                i += 1
            i += 1  # skip the closing "]" line itself
            continue

        if stripped == "[tool.poetry.dependencies]":
            # Poetry's table format is `name = "version"` per line, one
            # dependency per line, until the next `[section]` header.
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
    """Real dependency count via json.loads (package.json is always valid
    JSON when it parses at all, so this one doesn't need a heuristic).
    Returns _PARSE_FAILED instead of 0 for invalid JSON -- see the sentinel
    comment above for why that distinction matters."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _PARSE_FAILED
    return len(data.get("dependencies", {})) + len(data.get("devDependencies", {}))


# Which manifest filenames we know how to count, and how. Add a new
# ecosystem (e.g. Cargo.toml, go.mod) by adding one entry here plus its
# counter function above -- inventory_dependency_manifests below doesn't
# need to change.
_MANIFEST_COUNTERS = {
    "requirements.txt": _count_requirements_txt,
    "pyproject.toml": _count_pyproject_toml,
    "package.json": _count_package_json,
}


def inventory_dependency_manifests(repo_path: str) -> list[dict]:
    """[{"file": "requirements.txt", "count": 34}, ...] for every known
    manifest that's actually present at the repo root. A manifest that
    fails to parse is skipped entirely (see _PARSE_FAILED), not reported
    with a misleading count."""
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


# Known config/tooling files worth flagging in the report -- a fixed
# candidate list, not exhaustive. (".flaskenv", "Procfile" and similar are
# deliberately NOT here; this is meant to be the common/high-signal set,
# not every possible config file a project could have.)
CONFIG_FILE_CANDIDATES = [
    "Dockerfile",
    "docker-compose.yml",
    ".github/workflows",   # a directory -- every file inside gets listed (see below)
    ".eslintrc.json",
    ".eslintrc.js",
    ".flake8",
    "pyproject.toml",
    ".pre-commit-config.yaml",
]


def inventory_config_files(repo_path: str) -> list[str]:
    """Which of CONFIG_FILE_CANDIDATES actually exist in this repo. A
    candidate that's a directory (only .github/workflows today) expands to
    every file inside it, e.g. ".github/workflows/ci.yml"."""
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
    """Shared subprocess wrapper for every git-based stat below. Degrades to
    "" (empty string) rather than raising, on either of two real failure
    modes: git isn't installed at all (FileNotFoundError), or repo_path
    isn't a git repo / the command fails for any reason (non-zero exit).
    Callers below all treat "" the same as "couldn't determine this" and
    fall back to a sensible default -- so a repo with no git history (or a
    machine with no git binary) still gets a complete, non-crashing L1
    result, just with git_metadata/commit_convention/etc. reporting
    unknowns instead of real data."""
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
    """Commit count, contributor count, and repo age in days (from the
    OLDEST commit to now).

    The repo_age calculation deliberately does NOT use
    `git log --reverse --format=%at -1` even though that reads like "the
    first commit's timestamp" -- it isn't. git applies the `-1` limit
    BEFORE `--reverse` takes effect, so that idiom actually returns the
    NEWEST commit, making "repo age" silently mean "days since last
    commit" instead. (Caught by a real validation run's reviewer, who
    verified the bug empirically.) The fix here pulls every commit
    timestamp (`git log` defaults to newest-first) and takes the LAST line,
    which is genuinely the oldest.
    """
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


# Conventional Commits (https://www.conventionalcommits.org/) prefix shape:
# "feat: ...", "fix(scope): ...", etc.
_CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|chore|refactor|test|style|perf|build|ci)(\(.+\))?:\s"
)


def detect_commit_convention(repo_path: str) -> dict:
    """Sample the last 50 commit messages and see what fraction follow
    Conventional Commits. Threshold-based confidence rather than a strict
    yes/no, since real repos are rarely 100% consistent even when they do
    "follow" a convention."""
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
    """A coarse signal, not a precise classifier -- "gitflow" if any branch
    is literally named develop/release/hotfix (or a "release/..." style
    prefix), "trunk_based" if there are at most 2 distinct branches, else
    "unclear".

    The `b == marker or b.startswith(marker + "/")` check is deliberately
    NOT a bare `b.startswith(marker)` -- that looser version was caught (via
    a real validation run) false-positiving on branches that merely start
    with the same word, like "developer-notes" or "release-checklist",
    which have nothing to do with gitflow.
    """
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
    """Simple existence check against known PR/issue-template locations."""
    root = Path(repo_path)
    candidates = [
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE",
        "PULL_REQUEST_TEMPLATE.md",
    ]
    return any((root / c).exists() for c in candidates)
