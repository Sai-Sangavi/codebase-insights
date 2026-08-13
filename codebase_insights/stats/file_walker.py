"""Enumerate repo files, applying excludes and language classification."""

import os
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
    for pattern in exclude_patterns:
        if fnmatch(posix_path, pattern):
            return True
        # A directory pattern like "node_modules/**" is anchored at the repo root,
        # but vendored/cache dirs nest arbitrarily deep in real monorepos
        # (packages/web/node_modules/...), so also match at any depth.
        if pattern.endswith("/**") and fnmatch(posix_path, "**/" + pattern):
            return True
    return False


def walk_files(
    repo_path: str,
    exclude: list[str] | None = None,
    languages: list[str] | None = None,
) -> list[WalkedFile]:
    exclude = exclude or []
    root = Path(repo_path)
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        pruned = []
        for d in dirnames:
            rel_dir = (Path(dirpath) / d).relative_to(root).as_posix()
            if _is_excluded(rel_dir, exclude) or _is_excluded(rel_dir + "/", exclude):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for filename in sorted(filenames):
            rel = (Path(dirpath) / filename).relative_to(root).as_posix()
            if _is_excluded(rel, exclude):
                continue
            lang = classify_language(rel)
            if languages and lang not in languages:
                continue
            results.append(WalkedFile(path=rel, language=lang))
    return results
