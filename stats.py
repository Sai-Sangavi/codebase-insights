"""L1 deterministic stats: no LLM involved anywhere in this module."""

import json
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
        data = json.loads(text)
    except json.JSONDecodeError:
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
