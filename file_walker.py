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
