# codebase-insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-command Python tool (`python analyze.py <repo_path>`) that computes deterministic L1 stats and LLM-detected L2 conventions/patterns for an arbitrary codebase, writing `metrics.json` + `metrics.md`.

**Architecture:** Six small, single-purpose modules (`config`, `file_walker`, `stats`, `patterns`, `report`) composed by one entrypoint (`analyze.py`). L1 (stats) has zero LLM dependency and always runs; L2 (patterns) shells out to the Claude Code CLI per pattern category and is skipped gracefully if `claude` isn't on PATH.

**Tech Stack:** Python 3.10+, PyYAML (config parsing), pytest (testing), stdlib only otherwise (argparse, subprocess, pathlib, re, json, dataclasses, datetime).

**Spec:** `docs/superpowers/specs/2026-08-13-codebase-insights-design.md`

## Global Constraints

- Must be validated against a downloaded open-source repository — never the team's own internal platform codebase (spec, Constraints).
- Nothing project-specific may be hardcoded; excludes, language allowlist, pattern categories, and mode all come from `config.yaml`, with built-in defaults when omitted (spec, Config shape).
- Single command: `python analyze.py <repo_path> [--config config.yaml] [--full] [--out metrics.json]` (spec, Decisions).
- L1 always runs and always produces output, independent of L2 (spec, Output schema).
- L2 runs only if the `claude` CLI is present on PATH; if missing, skip L2 entirely with a stderr warning rather than failing (spec, Error handling).
- Per-category L2 failures (CLI present but call fails/times out) are isolated to that category — other categories still complete (spec, Error handling).
- Malformed `config.yaml` fails fast with a clear error before any work starts (spec, Error handling).
- Output is always both `metrics.json` (machine-readable) and `metrics.md` (rendered from the JSON) (spec, Decisions).

---

## Shared Interfaces Reference

(Populated as tasks land — kept here so later tasks can see exact signatures without re-reading earlier task bodies.)

```python
# config.py
DEFAULT_EXCLUDES: list[str]
DEFAULT_CONFIG: dict
class ConfigError(Exception): ...
def load_config(config_path: str | None) -> dict: ...
def get_effective_excludes(config: dict) -> list[str]: ...

# file_walker.py
@dataclass(frozen=True)
class WalkedFile:
    path: str               # POSIX-style, relative to repo root
    language: str | None
def classify_language(path: str) -> str | None: ...
def walk_files(repo_path: str, exclude: list[str] | None = None,
                languages: list[str] | None = None) -> list[WalkedFile]: ...

# stats.py
def count_files_by_language(files: list[WalkedFile]) -> dict: ...
def count_loc_by_language(repo_path: str, files: list[WalkedFile]) -> dict: ...
def count_tests(repo_path: str, files: list[WalkedFile]) -> dict: ...
def inventory_dependency_manifests(repo_path: str) -> list[dict]: ...
def inventory_config_files(repo_path: str) -> list[str]: ...
def git_metadata(repo_path: str) -> dict: ...
def detect_commit_convention(repo_path: str) -> dict: ...
def detect_branch_strategy(repo_path: str) -> dict: ...
def check_pr_templates(repo_path: str) -> bool: ...

# patterns.py
class ClaudeCLIError(Exception): ...
def run_claude_cli(prompt: str, timeout: int = 60) -> str: ...        # FileNotFoundError propagates if claude missing
def narrow_candidates(category: str, description: str, file_paths: list[str],
                       run_cli=run_claude_cli, max_candidates: int = 10) -> list[str]: ...
def synthesize_pattern(category: str, description: str, candidate_contents: dict,
                        run_cli=run_claude_cli) -> dict: ...
def merge_batch_results(results: list[dict]) -> dict: ...
def describe_category(category: str) -> str: ...
def analyze_category(category: str, repo_path: str, file_paths: list[str],
                      full_repo_mode: bool = False, batch_size: int = 150,
                      run_cli=run_claude_cli) -> dict: ...
def summarize_architecture(repo_path: str, file_paths: list[str], run_cli=run_claude_cli) -> str: ...

# report.py
def render_markdown(metrics: dict) -> str: ...

# analyze.py
def parse_args(argv=None) -> argparse.Namespace: ...
def collect_l1_stats(repo_path: str, files: list) -> dict: ...
def collect_l2_patterns(repo_path: str, files: list, config: dict) -> dict | None: ...
def main(argv=None) -> int: ...
```

---

### Task 1: Project scaffolding + config.py

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `config.py`
- Create: `config.example.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `DEFAULT_EXCLUDES`, `DEFAULT_CONFIG`, `ConfigError`, `load_config(config_path)`, `get_effective_excludes(config)` — see Shared Interfaces Reference.

- [ ] **Step 1: Create requirements files and pytest config**

`requirements.txt`:
```
PyYAML>=6.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=7.4
```

`pytest.ini`:
```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements-dev.txt`

- [ ] **Step 3: Write the failing tests**

`tests/test_config.py`:
```python
import pytest

from config import ConfigError, DEFAULT_CONFIG, get_effective_excludes, load_config


def test_load_config_with_no_path_returns_defaults():
    config = load_config(None)
    assert config == DEFAULT_CONFIG


def test_load_config_merges_overrides(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("output_path: custom.json\n", encoding="utf-8")
    config = load_config(str(config_file))
    assert config["output_path"] == "custom.json"
    assert config["pattern_categories"] == DEFAULT_CONFIG["pattern_categories"]


def test_load_config_missing_file_raises_config_error():
    with pytest.raises(ConfigError):
        load_config("/nonexistent/config.yaml")


def test_load_config_malformed_yaml_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("exclude: [unterminated\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_unknown_key_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("nonexistent_key: true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_get_effective_excludes_includes_builtin_defaults():
    config = load_config(None)
    excludes = get_effective_excludes(config)
    assert "node_modules/**" in excludes
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL/ERROR — `config` module does not exist yet.

- [ ] **Step 5: Implement config.py**

```python
"""Load and validate the optional config.yaml, with built-in defaults."""

import copy

import yaml

DEFAULT_EXCLUDES = [
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "dist/**",
    "build/**",
    ".git/**",
    "__pycache__/**",
    "*.min.js",
]

DEFAULT_CONFIG = {
    "exclude": [],
    "languages": [],
    "pattern_categories": [
        "date_handling",
        "db_connection",
        "queue_access",
        "logging",
        "error_handling",
        "config_loading",
    ],
    "architecture_summary": True,
    "full_repo_mode": False,
    "batch_size": 150,
    "output_path": "metrics.json",
}


class ConfigError(Exception):
    """Raised when config.yaml is missing, malformed, or has unknown keys."""


def load_config(config_path: str | None) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if config_path is None:
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {config_path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {config_path}: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping at the top level")

    unknown_keys = set(raw) - set(DEFAULT_CONFIG)
    if unknown_keys:
        raise ConfigError(
            f"unknown config key(s) in {config_path}: {', '.join(sorted(unknown_keys))}"
        )

    config.update(raw)
    return config


def get_effective_excludes(config: dict) -> list[str]:
    return DEFAULT_EXCLUDES + config["exclude"]
```

- [ ] **Step 6: Create config.example.yaml**

```yaml
# --- L1 scope ---
exclude:                      # glob patterns, merged with built-in defaults
                               # (node_modules, .venv, venv, dist, build, .git,
                               # __pycache__, *.min.js are always excluded)
  - "*.min.js"
languages: []                 # empty = auto-detect all; or restrict e.g. [python, javascript]

# --- L2 scope ---
pattern_categories:
  - date_handling
  - db_connection
  - queue_access
  - logging
  - error_handling
  - config_loading
  # Additional categories are supported -- uncomment any of these to opt in,
  # or add your own project-specific ones. No code changes needed.
  # - migration_pattern
  # - http_client
  # - auth_check
  # - validation
  # - serialization
  # - dependency_injection
  # - retry_backoff
  # - test_fixtures
  # - secrets_management
  # - tenant_scoping
architecture_summary: true

full_repo_mode: false          # true = chunk+cover-everything instead of narrow-to-handful
batch_size: 150                # files per batch, only used when full_repo_mode: true
# The --full CLI flag, if passed, overrides full_repo_mode: true regardless of
# this value; the config key lets a project default to full mode without
# needing the flag on every invocation.

# --- output ---
output_path: metrics.json
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (6 passed)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini config.py config.example.yaml tests/test_config.py
git commit -m "feat: add config loading with validation and defaults"
```

---

### Task 2: file_walker.py

**Files:**
- Create: `file_walker.py`
- Test: `tests/test_file_walker.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WalkedFile`, `classify_language(path)`, `walk_files(repo_path, exclude, languages)` — see Shared Interfaces Reference.

- [ ] **Step 1: Write the failing tests**

`tests/test_file_walker.py`:
```python
from file_walker import WalkedFile, classify_language, walk_files


def _make_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "src" / "app.js").write_text("console.log('hi')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("// vendored\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_classify_language_known_extensions():
    assert classify_language("src/main.py") == "python"
    assert classify_language("src/app.js") == "javascript"
    assert classify_language("README.md") == "markdown"


def test_classify_language_unknown_extension_returns_none():
    assert classify_language("image.png") is None


def test_walk_files_finds_all_non_excluded_files(tmp_path):
    repo = _make_repo(tmp_path)
    files = walk_files(str(repo), exclude=["node_modules/**"])
    paths = {f.path for f in files}
    assert "src/main.py" in paths
    assert "src/app.js" in paths
    assert "README.md" in paths
    assert "image.png" in paths  # walked, just language=None
    assert not any(p.startswith("node_modules/") for p in paths)


def test_walk_files_classifies_language_per_file(tmp_path):
    repo = _make_repo(tmp_path)
    files = walk_files(str(repo), exclude=["node_modules/**"])
    by_path = {f.path: f for f in files}
    assert by_path["src/main.py"] == WalkedFile(path="src/main.py", language="python")
    assert by_path["image.png"].language is None


def test_walk_files_language_allowlist_filters_results(tmp_path):
    repo = _make_repo(tmp_path)
    files = walk_files(str(repo), exclude=["node_modules/**"], languages=["python"])
    paths = {f.path for f in files}
    assert paths == {"src/main.py"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_file_walker.py -v`
Expected: FAIL/ERROR — `file_walker` module does not exist yet.

- [ ] **Step 3: Implement file_walker.py**

```python
"""Enumerate repo files, applying excludes and language classification."""

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

LANGUAGE_EXTENSIONS = {
    "python": [".py"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx"],
    "java": [".java"],
    "go": [".go"],
    "ruby": [".rb"],
    "rust": [".rs"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".cc", ".hpp"],
    "csharp": [".cs"],
    "php": [".php"],
    "shell": [".sh", ".bash"],
    "yaml": [".yml", ".yaml"],
    "markdown": [".md"],
    "html": [".html", ".htm"],
    "css": [".css", ".scss"],
}

_EXT_TO_LANGUAGE = {ext: lang for lang, exts in LANGUAGE_EXTENSIONS.items() for ext in exts}


@dataclass(frozen=True)
class WalkedFile:
    path: str
    language: str | None


def classify_language(path: str) -> str | None:
    return _EXT_TO_LANGUAGE.get(Path(path).suffix.lower())


def _is_excluded(rel_path: str, exclude_patterns: list[str]) -> bool:
    posix_path = rel_path.replace("\\", "/")
    return any(fnmatch(posix_path, pattern) for pattern in exclude_patterns)


def walk_files(
    repo_path: str,
    exclude: list[str] | None = None,
    languages: list[str] | None = None,
) -> list[WalkedFile]:
    exclude = exclude or []
    root = Path(repo_path)
    results = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel, exclude):
            continue
        lang = classify_language(rel)
        if languages and lang not in languages:
            continue
        results.append(WalkedFile(path=rel, language=lang))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_file_walker.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add file_walker.py tests/test_file_walker.py
git commit -m "feat: add file walker with excludes and language classification"
```

---

### Task 3: stats.py — file/LOC/test counts

**Files:**
- Create: `stats.py`
- Test: `tests/test_stats.py`

**Interfaces:**
- Consumes: `WalkedFile` (Task 2).
- Produces: `count_files_by_language(files)`, `count_loc_by_language(repo_path, files)`, `count_tests(repo_path, files)` — see Shared Interfaces Reference.

- [ ] **Step 1: Write the failing tests**

`tests/test_stats.py`:
```python
from file_walker import WalkedFile
from stats import count_files_by_language, count_loc_by_language, count_tests


def test_count_files_by_language_ignores_unclassified_files():
    files = [
        WalkedFile(path="a.py", language="python"),
        WalkedFile(path="b.py", language="python"),
        WalkedFile(path="c.js", language="javascript"),
        WalkedFile(path="d.png", language=None),
    ]
    assert count_files_by_language(files) == {"python": 2, "javascript": 1}


def test_count_loc_by_language_sums_lines_per_language(tmp_path):
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("line1\n", encoding="utf-8")
    files = [
        WalkedFile(path="a.py", language="python"),
        WalkedFile(path="b.py", language="python"),
    ]
    assert count_loc_by_language(str(tmp_path), files) == {"python": 4}


def test_count_loc_by_language_skips_undecodable_files(tmp_path):
    (tmp_path / "a.py").write_bytes(b"\xff\xfe\x00\x01")
    files = [WalkedFile(path="a.py", language="python")]
    assert count_loc_by_language(str(tmp_path), files) == {}


def test_count_tests_detects_python_pytest_functions(tmp_path):
    (tmp_path / "test_thing.py").write_text(
        "def test_one():\n    assert True\n\n"
        "def test_two():\n    assert True\n",
        encoding="utf-8",
    )
    files = [WalkedFile(path="test_thing.py", language="python")]
    result = count_tests(str(tmp_path), files)
    assert result == {"total": 2, "framework": "pytest"}


def test_count_tests_with_no_test_files_returns_zero():
    files = [WalkedFile(path="main.py", language="python")]
    result = count_tests("/unused", files)
    assert result == {"total": 0, "framework": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -v`
Expected: FAIL/ERROR — `stats` module does not exist yet.

- [ ] **Step 3: Implement stats.py (file/LOC/test counting section)**

```python
"""L1 deterministic stats: no LLM involved anywhere in this module."""

import re
from collections import Counter
from pathlib import Path

from file_walker import WalkedFile

TEST_FILENAME_MARKERS = ("test_", "_test.", ".test.", ".spec.")


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
    return any(marker in name for marker in TEST_FILENAME_MARKERS)


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
            matches = re.findall(r"\b(?:it|test)\(", text)
            total += len(matches)
            if matches:
                framework = framework or "jest"
    return {"total": total, "framework": framework}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stats.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add stats.py tests/test_stats.py
git commit -m "feat: add file/LOC/test-count stats"
```

---

### Task 4: stats.py — dependency manifest + config file inventory

**Files:**
- Modify: `stats.py`
- Modify: `tests/test_stats.py`

**Interfaces:**
- Produces: `inventory_dependency_manifests(repo_path)`, `inventory_config_files(repo_path)` — see Shared Interfaces Reference.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_stats.py`:
```python
import json

from stats import inventory_config_files, inventory_dependency_manifests


def test_inventory_dependency_manifests_parses_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\nrequests==2.31\npyyaml\n\n", encoding="utf-8"
    )
    result = inventory_dependency_manifests(str(tmp_path))
    assert {"file": "requirements.txt", "count": 2} in result


def test_inventory_dependency_manifests_parses_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18"}, "devDependencies": {"jest": "^29"}}),
        encoding="utf-8",
    )
    result = inventory_dependency_manifests(str(tmp_path))
    assert {"file": "package.json", "count": 2} in result


def test_inventory_dependency_manifests_skips_absent_files(tmp_path):
    result = inventory_dependency_manifests(str(tmp_path))
    assert result == []


def test_inventory_config_files_finds_known_files(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "workflows").mkdir()
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    result = inventory_config_files(str(tmp_path))
    assert "Dockerfile" in result
    assert ".github/workflows/ci.yml" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -v`
Expected: FAIL/ERROR on the four new tests — functions not defined yet.

- [ ] **Step 3: Append implementation to stats.py**

```python
import json as _json  # co-locate with existing `import re` etc. at top of file instead in real edit


def _count_requirements_txt(text: str) -> int:
    return len([
        line for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ])


def _count_pyproject_toml(text: str) -> int:
    count = 0
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies") and "=" in stripped:
            in_deps = True
            continue
        if in_deps:
            if stripped.startswith("]"):
                in_deps = False
                continue
            if stripped.startswith('"') or stripped.startswith("'"):
                count += 1
    return count


def _count_package_json(text: str) -> int:
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        return 0
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
        results.append({"file": filename, "count": counter(text)})
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
```

Note: move the `import json as _json` line to the top of `stats.py` alongside the existing `import re` — don't leave an import mid-file. Rename references to plain `json` if preferred; `_json` alias used above only to make the diff obvious in this plan.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stats.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add stats.py tests/test_stats.py
git commit -m "feat: add dependency manifest and config file inventory stats"
```

---

### Task 5: stats.py — git metadata, commit convention, branch strategy, PR templates

**Files:**
- Modify: `stats.py`
- Modify: `tests/test_stats.py`

**Interfaces:**
- Produces: `git_metadata(repo_path)`, `detect_commit_convention(repo_path)`, `detect_branch_strategy(repo_path)`, `check_pr_templates(repo_path)` — see Shared Interfaces Reference.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_stats.py`:
```python
import subprocess

from stats import (
    check_pr_templates,
    detect_branch_strategy,
    detect_commit_convention,
    git_metadata,
)


def _init_git_repo(path, commit_messages):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    for i, message in enumerate(commit_messages):
        (path / f"file{i}.txt").write_text(str(i), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)


def test_git_metadata_reports_commit_count_and_contributors(tmp_path):
    _init_git_repo(tmp_path, ["feat: first", "fix: second"])
    result = git_metadata(str(tmp_path))
    assert result["commit_count"] == 2
    assert result["contributors"] == 1
    assert result["repo_age_days"] >= 0


def test_detect_commit_convention_high_confidence_when_mostly_conventional(tmp_path):
    _init_git_repo(tmp_path, ["feat: a", "fix: b", "chore: c", "random message"])
    result = detect_commit_convention(str(tmp_path))
    assert result == {"detected": "conventional_commits", "confidence": "high"}


def test_detect_commit_convention_none_when_not_conventional(tmp_path):
    _init_git_repo(tmp_path, ["did a thing", "did another thing"])
    result = detect_commit_convention(str(tmp_path))
    assert result == {"detected": "none", "confidence": "high"}


def test_detect_branch_strategy_trunk_based_with_single_branch(tmp_path):
    _init_git_repo(tmp_path, ["feat: first"])
    result = detect_branch_strategy(str(tmp_path))
    assert result == {"signal": "trunk_based"}


def test_check_pr_templates_true_when_present(tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("template", encoding="utf-8")
    assert check_pr_templates(str(tmp_path)) is True


def test_check_pr_templates_false_when_absent(tmp_path):
    assert check_pr_templates(str(tmp_path)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -v`
Expected: FAIL/ERROR on the six new tests — functions not defined yet.

- [ ] **Step 3: Append implementation to stats.py**

Add `import re, subprocess` and `from datetime import datetime, timezone` to the top-of-file imports (merge with existing ones), then append:

```python
def _run_git(repo_path: str, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_path, capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_metadata(repo_path: str) -> dict:
    commit_count_raw = _run_git(repo_path, ["rev-list", "--count", "HEAD"])
    commit_count = int(commit_count_raw) if commit_count_raw.isdigit() else 0

    contributors_raw = _run_git(repo_path, ["shortlog", "-sn", "--all"])
    contributors = len([line for line in contributors_raw.splitlines() if line.strip()])

    first_commit_epoch = _run_git(repo_path, ["log", "--reverse", "--format=%at", "-1"])
    repo_age_days = 0
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
    if any(b.startswith(marker) for b in branches for marker in gitflow_markers):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stats.py -v`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
git add stats.py tests/test_stats.py
git commit -m "feat: add git metadata, commit convention, branch strategy, PR template stats"
```

---

### Task 6: analyze.py — L1 orchestration (CLI + metrics.json)

**Files:**
- Create: `analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `load_config`, `get_effective_excludes` (Task 1), `walk_files` (Task 2), all `stats.py` functions (Tasks 3–5).
- Produces: `parse_args(argv)`, `collect_l1_stats(repo_path, files)`, `main(argv=None)` — see Shared Interfaces Reference. (`collect_l2_patterns` and full L2 wiring land in Task 11.)

- [ ] **Step 1: Write the failing tests**

`tests/test_analyze.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analyze.py -v`
Expected: FAIL/ERROR — `analyze` module does not exist yet.

- [ ] **Step 3: Implement analyze.py (L1-only orchestration)**

```python
"""Entrypoint: python analyze.py <repo_path> [--config config.yaml] [--full] [--out metrics.json]"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import ConfigError, get_effective_excludes, load_config
from file_walker import walk_files
from stats import (
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


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Understand a codebase quickly: deterministic stats + LLM-detected patterns."
    )
    parser.add_argument("repo_path", help="Path to the repository to analyze")
    parser.add_argument("--config", default=None, help="Path to an optional config.yaml")
    parser.add_argument(
        "--full", action="store_true", help="Use exhaustive full-repo pattern coverage"
    )
    parser.add_argument("--out", default=None, help="Override output_path from config")
    return parser.parse_args(argv)


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


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.full:
        config["full_repo_mode"] = True

    files = walk_files(
        args.repo_path,
        exclude=get_effective_excludes(config),
        languages=config["languages"] or None,
    )

    metrics = {
        "repo_path": str(Path(args.repo_path).resolve()),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "l1_stats": collect_l1_stats(args.repo_path, files),
    }

    output_path = args.out or config["output_path"]
    Path(output_path).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analyze.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add analyze.py tests/test_analyze.py
git commit -m "feat: wire up L1 orchestration — analyze.py writes metrics.json"
```

---

### Task 7: patterns.py — Claude CLI wrapper + narrowing

**Files:**
- Create: `patterns.py`
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone module).
- Produces: `ClaudeCLIError`, `run_claude_cli(prompt, timeout=60)`, `narrow_candidates(category, description, file_paths, run_cli=run_claude_cli, max_candidates=10)` — see Shared Interfaces Reference.

- [ ] **Step 1: Write the failing tests**

`tests/test_patterns.py`:
```python
import subprocess

import pytest

from patterns import ClaudeCLIError, narrow_candidates, run_claude_cli


def test_run_claude_cli_returns_stdout_on_success(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="hello", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_claude_cli("prompt") == "hello"


def test_run_claude_cli_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError, match="boom"):
        run_claude_cli("prompt")


def test_run_claude_cli_raises_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ClaudeCLIError, match="timed out"):
        run_claude_cli("prompt", timeout=5)


def test_run_claude_cli_propagates_file_not_found(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise FileNotFoundError("no such file: claude")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(FileNotFoundError):
        run_claude_cli("prompt")


def test_narrow_candidates_parses_json_array_and_filters_to_known_paths():
    def fake_cli(prompt):
        return 'Sure, here you go:\n["db/session.py", "made/up.py"]\nhope that helps'

    result = narrow_candidates(
        "db_connection", "how DB connections are obtained",
        ["db/session.py", "api/routes.py"], run_cli=fake_cli,
    )
    assert result == ["db/session.py"]  # "made/up.py" filtered out — not in file_paths


def test_narrow_candidates_returns_empty_list_on_unparseable_output():
    result = narrow_candidates(
        "db_connection", "how DB connections are obtained",
        ["db/session.py"], run_cli=lambda prompt: "not json at all",
    )
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_patterns.py -v`
Expected: FAIL/ERROR — `patterns` module does not exist yet.

- [ ] **Step 3: Implement patterns.py (CLI wrapper + narrowing section)**

```python
"""L2 pattern detection: shells out to the Claude Code CLI per category."""

import json
import subprocess


class ClaudeCLIError(Exception):
    """Raised when the claude CLI is present but the call fails or times out."""


def run_claude_cli(prompt: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["claude", "-p", prompt], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude CLI timed out after {timeout}s") from e
    if result.returncode != 0:
        raise ClaudeCLIError(f"claude CLI exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def _extract_json(text: str):
    start_candidates = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not start_candidates:
        raise ValueError("no JSON payload found in CLI output")
    start = min(start_candidates)
    end = max(text.rfind("]"), text.rfind("}"))
    return json.loads(text[start : end + 1])


def narrow_candidates(
    category: str,
    description: str,
    file_paths: list[str],
    run_cli=run_claude_cli,
    max_candidates: int = 10,
) -> list[str]:
    prompt = (
        f"Here are {len(file_paths)} file paths from a code repository.\n"
        f"Which up to {max_candidates} are most likely to show {description}?\n"
        "Respond with ONLY a JSON array of file path strings, nothing else.\n\n"
        + "\n".join(file_paths)
    )
    output = run_cli(prompt)
    try:
        candidates = _extract_json(output)
    except (ValueError, json.JSONDecodeError):
        return []
    if not isinstance(candidates, list):
        return []
    valid = set(file_paths)
    return [c for c in candidates if isinstance(c, str) and c in valid][:max_candidates]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_patterns.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add patterns.py tests/test_patterns.py
git commit -m "feat: add Claude CLI wrapper and candidate-narrowing step"
```

---

### Task 8: patterns.py — synthesis + default-mode category analysis

**Files:**
- Modify: `patterns.py`
- Modify: `tests/test_patterns.py`

**Interfaces:**
- Produces: `synthesize_pattern(category, description, candidate_contents, run_cli=run_claude_cli)`, `analyze_category_default(category, description, repo_path, file_paths, run_cli=run_claude_cli)` — see Shared Interfaces Reference (the latter is an internal helper the dispatcher in Task 9 calls; not itself in the public reference table, but needed by it).

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_patterns.py`:
```python
from patterns import analyze_category_default, synthesize_pattern


def test_synthesize_pattern_parses_full_json_response():
    def fake_cli(prompt):
        return json.dumps({
            "summary": "Uses get_session() everywhere.",
            "example": {"file": "db/session.py", "snippet": "with get_session() as s:"},
            "consistency": "consistent",
            "exceptions": [],
        })

    result = synthesize_pattern(
        "db_connection", "how DB connections are obtained",
        {"db/session.py": "def get_session(): ..."}, run_cli=fake_cli,
    )
    assert result["category"] == "db_connection"
    assert result["summary"] == "Uses get_session() everywhere."
    assert result["consistency"] == "consistent"
    assert result["files_examined"] == ["db/session.py"]


def test_synthesize_pattern_with_no_candidates_returns_unknown():
    result = synthesize_pattern(
        "db_connection", "how DB connections are obtained", {}, run_cli=lambda p: "{}"
    )
    assert result["consistency"] == "unknown"
    assert result["files_examined"] == []


def test_analyze_category_default_reads_narrowed_files_and_synthesizes(tmp_path):
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "session.py").write_text("def get_session(): ...", encoding="utf-8")

    calls = []

    def fake_cli(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return '["db/session.py"]'
        return json.dumps({
            "summary": "Uses get_session().", "example": None,
            "consistency": "consistent", "exceptions": [],
        })

    result = analyze_category_default(
        "db_connection", "how DB connections are obtained",
        str(tmp_path), ["db/session.py"], run_cli=fake_cli,
    )
    assert len(calls) == 2  # one narrow call, one synthesis call
    assert result["summary"] == "Uses get_session()."
```

Add `import json` to the top of `tests/test_patterns.py` (used by these new tests).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_patterns.py -v`
Expected: FAIL/ERROR on the three new tests — functions not defined yet.

- [ ] **Step 3: Append implementation to patterns.py**

```python
from pathlib import Path


def synthesize_pattern(
    category: str, description: str, candidate_contents: dict, run_cli=run_claude_cli
) -> dict:
    if not candidate_contents:
        return {
            "category": category,
            "summary": "No candidate files found for this pattern.",
            "example": None,
            "consistency": "unknown",
            "exceptions": [],
            "files_examined": [],
        }
    files_block = "\n\n".join(
        f"--- {path} ---\n{content}" for path, content in candidate_contents.items()
    )
    prompt = (
        f"Given these files from a code repository, describe {description}.\n"
        "Respond with ONLY a JSON object with these keys: "
        '"summary" (string), "example" (object with "file" and "snippet"), '
        '"consistency" (one of "consistent", "mostly_consistent", "inconsistent"), '
        '"exceptions" (array of strings).\n\n' + files_block
    )
    output = run_cli(prompt)
    try:
        parsed = _extract_json(output)
    except (ValueError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "category": category,
        "summary": parsed.get("summary", ""),
        "example": parsed.get("example"),
        "consistency": parsed.get("consistency", "unknown"),
        "exceptions": parsed.get("exceptions", []),
        "files_examined": list(candidate_contents.keys()),
    }


def _read_files(repo_path: str, paths: list[str]) -> dict:
    root = Path(repo_path)
    contents = {}
    for p in paths:
        try:
            contents[p] = (root / p).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return contents


def analyze_category_default(
    category: str, description: str, repo_path: str, file_paths: list[str], run_cli=run_claude_cli
) -> dict:
    candidates = narrow_candidates(category, description, file_paths, run_cli=run_cli)
    contents = _read_files(repo_path, candidates)
    return synthesize_pattern(category, description, contents, run_cli=run_cli)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_patterns.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add patterns.py tests/test_patterns.py
git commit -m "feat: add pattern synthesis and default-mode category analysis"
```

---

### Task 9: patterns.py — full-repo mode, dispatcher, architecture summary

**Files:**
- Modify: `patterns.py`
- Modify: `tests/test_patterns.py`

**Interfaces:**
- Produces: `merge_batch_results(results)`, `describe_category(category)`, `analyze_category(category, repo_path, file_paths, full_repo_mode=False, batch_size=150, run_cli=run_claude_cli)`, `summarize_architecture(repo_path, file_paths, run_cli=run_claude_cli)` — see Shared Interfaces Reference.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_patterns.py`:
```python
from patterns import (
    analyze_category,
    describe_category,
    merge_batch_results,
    summarize_architecture,
)


def test_describe_category_known_category_uses_named_description():
    assert "database connection" in describe_category("db_connection")


def test_describe_category_unknown_category_falls_back_to_generic_text():
    assert describe_category("custom_thing") == "how this codebase handles custom thing"


def test_merge_batch_results_unions_files_and_exceptions_takes_worst_consistency():
    results = [
        {
            "category": "db_connection", "summary": "uses get_session()",
            "example": {"file": "a.py", "snippet": "..."},
            "consistency": "consistent", "exceptions": [], "files_examined": ["a.py"],
        },
        {
            "category": "db_connection", "summary": "uses get_session()",
            "example": {"file": "a.py", "snippet": "..."},
            "consistency": "inconsistent", "exceptions": ["b.py opens raw connection"],
            "files_examined": ["b.py"],
        },
    ]
    merged = merge_batch_results(results)
    assert merged["consistency"] == "inconsistent"
    assert merged["files_examined"] == ["a.py", "b.py"]
    assert merged["exceptions"] == ["b.py opens raw connection"]


def test_merge_batch_results_when_nothing_found_returns_first_result():
    results = [
        {"category": "logging", "summary": "", "example": None,
         "consistency": "unknown", "exceptions": [], "files_examined": []},
    ]
    assert merge_batch_results(results) == results[0]


def test_analyze_category_default_mode_delegates_to_narrow_and_synthesize(tmp_path):
    (tmp_path / "a.py").write_text("import logging", encoding="utf-8")
    calls = []

    def fake_cli(prompt):
        calls.append(prompt)
        return '["a.py"]' if len(calls) == 1 else '{"summary": "uses logging", "example": null, "consistency": "consistent", "exceptions": []}'

    result = analyze_category("logging", str(tmp_path), ["a.py"], run_cli=fake_cli)
    assert result["summary"] == "uses logging"


def test_analyze_category_full_mode_batches_and_merges(tmp_path):
    for i in range(4):
        (tmp_path / f"f{i}.py").write_text("import logging", encoding="utf-8")
    file_paths = [f"f{i}.py" for i in range(4)]

    def fake_cli(prompt):
        # Narrow calls return the batch's own files; synthesis calls return a fixed pattern.
        if "Respond with ONLY a JSON array" in prompt:
            return json.dumps([p for p in file_paths if p in prompt])
        return '{"summary": "uses logging", "example": null, "consistency": "consistent", "exceptions": []}'

    result = analyze_category(
        "logging", str(tmp_path), file_paths, full_repo_mode=True, batch_size=2, run_cli=fake_cli
    )
    assert result["consistency"] == "consistent"
    assert len(result["files_examined"]) == 4


def test_analyze_category_catches_claude_cli_error_per_category():
    def failing_cli(prompt):
        raise ClaudeCLIError("boom")

    result = analyze_category("logging", "/unused", ["a.py"], run_cli=failing_cli)
    assert result == {"category": "logging", "error": "boom"}


def test_summarize_architecture_returns_cli_output_stripped():
    result = summarize_architecture("/unused", ["a.py", "b.py"], run_cli=lambda p: "  Some summary.  \n")
    assert result == "Some summary."


def test_summarize_architecture_handles_cli_error_gracefully():
    def failing_cli(prompt):
        raise ClaudeCLIError("boom")

    result = summarize_architecture("/unused", ["a.py"], run_cli=failing_cli)
    assert "unavailable" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_patterns.py -v`
Expected: FAIL/ERROR on the nine new tests — functions not defined yet.

- [ ] **Step 3: Append implementation to patterns.py**

```python
CATEGORY_DESCRIPTIONS = {
    "date_handling": "how date/time objects are created and manipulated",
    "db_connection": "how a database connection is obtained before running a query",
    "queue_access": "how the code talks to a message queue",
    "logging": "how a logger is obtained and configured",
    "error_handling": "custom exception types and try/except conventions",
    "config_loading": "how settings and environment variables are read into the app",
}


def describe_category(category: str) -> str:
    return CATEGORY_DESCRIPTIONS.get(
        category, f"how this codebase handles {category.replace('_', ' ')}"
    )


def _batch(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def merge_batch_results(results: list[dict]) -> dict:
    found = [r for r in results if r.get("files_examined")]
    if not found:
        return results[0]
    order = {"consistent": 0, "mostly_consistent": 1, "inconsistent": 2, "unknown": 0}
    worst = max(found, key=lambda r: order.get(r.get("consistency", "unknown"), 0))
    merged_exceptions: list = []
    merged_files: list = []
    for r in found:
        for exc in r.get("exceptions", []):
            if exc not in merged_exceptions:
                merged_exceptions.append(exc)
        for f in r.get("files_examined", []):
            if f not in merged_files:
                merged_files.append(f)
    return {
        "category": found[0]["category"],
        "summary": found[0]["summary"],
        "example": found[0]["example"],
        "consistency": worst["consistency"],
        "exceptions": merged_exceptions,
        "files_examined": merged_files,
    }


def analyze_category_full(
    category: str,
    description: str,
    repo_path: str,
    file_paths: list[str],
    batch_size: int = 150,
    run_cli=run_claude_cli,
) -> dict:
    batches = _batch(file_paths, batch_size)
    results = [
        analyze_category_default(category, description, repo_path, batch, run_cli=run_cli)
        for batch in batches
    ]
    return merge_batch_results(results)


def analyze_category(
    category: str,
    repo_path: str,
    file_paths: list[str],
    full_repo_mode: bool = False,
    batch_size: int = 150,
    run_cli=run_claude_cli,
) -> dict:
    description = describe_category(category)
    try:
        if full_repo_mode:
            return analyze_category_full(
                category, description, repo_path, file_paths,
                batch_size=batch_size, run_cli=run_cli,
            )
        return analyze_category_default(category, description, repo_path, file_paths, run_cli=run_cli)
    except ClaudeCLIError as e:
        return {"category": category, "error": str(e)}


def summarize_architecture(repo_path: str, file_paths: list[str], run_cli=run_claude_cli) -> str:
    prompt = (
        "Here is a repository's file list. In plain English, describe what each "
        "top-level module/directory is responsible for, in a few sentences per module.\n\n"
        + "\n".join(file_paths)
    )
    try:
        return run_cli(prompt).strip()
    except ClaudeCLIError as e:
        return f"(architecture summary unavailable: {e})"
```

Note: `analyze_category`/`summarize_architecture` only catch `ClaudeCLIError` — a bare `FileNotFoundError` (claude not on PATH) is left to propagate, so `analyze.py` (Task 11) can catch it once at the top level and skip L2 entirely, per spec.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_patterns.py -v`
Expected: PASS (18 passed)

- [ ] **Step 5: Commit**

```bash
git add patterns.py tests/test_patterns.py
git commit -m "feat: add full-repo batching, category dispatcher, architecture summary"
```

---

### Task 10: report.py — Markdown renderer

**Files:**
- Create: `report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: the `metrics` dict shape produced by `analyze.py` (Tasks 6 & 11) — built directly from fixture dicts in this task's tests, no import of `analyze.py` needed.
- Produces: `render_markdown(metrics)` — see Shared Interfaces Reference.

- [ ] **Step 1: Write the failing tests**

`tests/test_report.py`:
```python
from report import render_markdown


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report.py -v`
Expected: FAIL/ERROR — `report` module does not exist yet.

- [ ] **Step 3: Implement report.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add report.py tests/test_report.py
git commit -m "feat: add Markdown report renderer"
```

---

### Task 11: analyze.py — L2 wiring, final CLI, README

**Files:**
- Modify: `analyze.py`
- Modify: `tests/test_analyze.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `analyze_category`, `summarize_architecture` (Task 9), `render_markdown` (Task 10).
- Produces: `collect_l2_patterns(repo_path, files, config)` — see Shared Interfaces Reference. `main()` now writes both `metrics.json` and `metrics.md`, and runs L2 when `claude` is available.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_analyze.py`:
```python
import analyze


def test_main_writes_metrics_md_alongside_json(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        analyze, "collect_l2_patterns", lambda repo_path, files, config: None
    )
    exit_code = main([str(repo), "--out", str(out_path)])
    assert exit_code == 0
    md_path = out_path.with_suffix(".md")
    assert md_path.exists()
    assert "# Codebase Report" in md_path.read_text(encoding="utf-8")


def test_main_includes_l2_patterns_when_claude_cli_succeeds(tmp_path, monkeypatch):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)

    fake_l2 = {
        "mode": "default",
        "categories": {"logging": {"category": "logging", "summary": "uses logging",
                                    "example": None, "consistency": "consistent",
                                    "exceptions": [], "files_examined": []}},
        "architecture_summary": "A simple repo.",
    }
    monkeypatch.setattr(
        analyze, "collect_l2_patterns", lambda repo_path, files, config: fake_l2
    )
    exit_code = main([str(repo), "--out", str(out_path)])
    assert exit_code == 0
    metrics = json.loads(out_path.read_text(encoding="utf-8"))
    assert metrics["l2_patterns"] == fake_l2


def test_main_omits_l2_patterns_when_claude_cli_missing(tmp_path, monkeypatch, capsys):
    repo = _make_minimal_repo(tmp_path)
    out_path = tmp_path / "metrics.json"
    monkeypatch.chdir(tmp_path)

    def raise_missing(repo_path, files, config):
        raise FileNotFoundError("no claude on PATH")

    monkeypatch.setattr(analyze, "collect_l2_patterns_raw", raise_missing, raising=False)
    monkeypatch.setattr(analyze, "_run_l2_or_none", lambda repo_path, files, config: None)
    exit_code = main([str(repo), "--out", str(out_path)])
    assert exit_code == 0
    metrics = json.loads(out_path.read_text(encoding="utf-8"))
    assert "l2_patterns" not in metrics
```

Add `import json` and `from analyze import main, parse_args` already present at top of `tests/test_analyze.py`; add `import analyze` alongside it for the `monkeypatch.setattr(analyze, ...)` calls above.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analyze.py -v`
Expected: FAIL — `md_path.exists()` is False (no `.md` written yet), and `analyze.collect_l2_patterns`/`_run_l2_or_none` don't exist yet.

- [ ] **Step 3: Rewrite analyze.py's L2 wiring and main()**

Add these imports to the top of `analyze.py`:
```python
from patterns import analyze_category, summarize_architecture
from report import render_markdown
```

Add, after `collect_l1_stats`:
```python
def collect_l2_patterns(repo_path: str, files: list, config: dict) -> dict:
    """Raises FileNotFoundError if the claude CLI isn't on PATH — caller decides
    what that means (analyze.py's main() skips L2 entirely and warns)."""
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
```

Replace the body of `main()` from the `metrics = {...}` line onward with:
```python
    l1_stats = collect_l1_stats(args.repo_path, files)
    l2_patterns = _run_l2_or_none(args.repo_path, files, config)

    metrics = {
        "repo_path": str(Path(args.repo_path).resolve()),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "l1_stats": l1_stats,
    }
    if l2_patterns is not None:
        metrics["l2_patterns"] = l2_patterns

    output_path = Path(args.out or config["output_path"])
    output_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    output_path.with_suffix(".md").write_text(render_markdown(metrics), encoding="utf-8")
    print(f"wrote {output_path} and {output_path.with_suffix('.md')}")
    return 0
```

Note: the two tests that reference `analyze.collect_l2_patterns` and `analyze._run_l2_or_none` directly (rather than importing them from `patterns`) confirm `main()` calls through these module-level names — which is why `monkeypatch.setattr(analyze, "collect_l2_patterns", ...)` in the first L2 test works to stub out the whole L2 path without needing a real `claude` binary.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analyze.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across every module, ~45 total)

- [ ] **Step 6: Write README.md**

```markdown
# codebase-insights

Understand a brownfield codebase quickly: deterministic stats (L1) plus
LLM-detected conventions and patterns (L2).

## Usage

```bash
pip install -r requirements.txt
python analyze.py /path/to/some/repo
```

This writes `metrics.json` (machine-readable) and `metrics.md` (human-readable
report) into the current directory.

Options:

- `--config config.yaml` — override excludes, language allowlist, pattern
  categories, mode, batch size, output path. See `config.example.yaml` for the
  full set of options and their defaults.
- `--full` — exhaustive full-repo pattern coverage (chunks the whole file list
  into batches instead of narrowing to a handful of candidates). Slower, more
  thorough.
- `--out metrics.json` — override the output path (also determines the
  `.md` report's path, e.g. `--out foo.json` writes `foo.json` + `foo.md`).

L2 (pattern detection) requires the `claude` CLI to be installed and on
`PATH`. If it isn't found, L1 stats still run and are written normally; L2 is
skipped with a warning on stderr.

## Development

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Manual end-to-end validation

Before considering a change done, run the tool once against a real
downloaded open-source repository (not this repo, and never the team's own internal platform codebase —
see the design spec's constraints) and confirm `metrics.json`/`metrics.md`
look sane. This is a manual sanity check, not an automated test — the L2
Claude CLI calls are non-deterministic and not something to assert on in CI.

## Design

See `docs/superpowers/specs/2026-08-13-codebase-insights-design.md` for the
full design rationale, and `docs/superpowers/plans/2026-08-13-codebase-insights-implementation.md`
for the implementation plan this was built from.
```

- [ ] **Step 7: Commit**

```bash
git add analyze.py tests/test_analyze.py README.md
git commit -m "feat: wire L2 pattern detection into main(), write metrics.md, add README"
```

---

## Self-Review

**Spec coverage:**
- L1 stats (file/language counts, LOC, tests, manifests, config files, git metadata, commit convention, branch strategy, PR templates) → Tasks 3–6. ✅
- L2 pattern detection, both modes, default category set, architecture summary → Tasks 7–9, wired in Task 11. ✅
- Config-driven categories/excludes/mode, built-in excludes always applied → Task 1, consumed in Task 6/11. ✅
- Per-category output shape (summary/example/consistency/exceptions/files_examined) → Task 8. ✅
- Output schema (`metrics.json` + `metrics.md`) → Tasks 6, 10, 11. ✅
- Error handling (CLI missing → skip L2 with warning; per-category CLI failure isolated; malformed config fails fast; unreadable/binary files silently skipped) → Tasks 1 (config), 3 (LOC skip), 9 (per-category), 11 (CLI-missing skip). ✅
- Testing approach (fixture-based L1 tests, mocked-CLI L2 tests, manual e2e check) → every task's tests + README's manual-validation note. ✅
- Out-of-scope items (code-quality metrics, broader category menu, folding into a larger internal platform's tooling) → intentionally has no task; called out in README/spec instead. ✅

**Placeholder scan:** No TBD/TODO/"add appropriate error handling" phrasing anywhere above — every step has literal code or a literal shell command.

**Type consistency:** `WalkedFile(path, language)` used identically in `file_walker.py`, `stats.py`, and `analyze.py`. `run_cli` parameter name and default (`run_claude_cli`) consistent across `patterns.py`'s `narrow_candidates`, `synthesize_pattern`, `analyze_category_default`, `analyze_category_full`, `analyze_category`, `summarize_architecture`. The per-category dict shape (`category`, `summary`, `example`, `consistency`, `exceptions`, `files_examined`) is produced once in `synthesize_pattern` (Task 8) and consumed identically in `merge_batch_results` (Task 9) and `render_markdown` (Task 10) — checked for matching key names in each.
