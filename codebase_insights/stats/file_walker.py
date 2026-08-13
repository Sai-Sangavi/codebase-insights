"""Enumerate repo files, applying excludes and language classification.

This is the L1 layer's foundation: every stats.py function and (via the
narrow-then-read strategy in llm/patterns.py) the L2 layer too, operate on
the file list this module produces. Zero LLM involvement here -- pure
filesystem walking + extension matching.
"""

import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

# Extension -> language name. Deliberately a flat, hardcoded table (not
# config-driven) -- unlike excludes/pattern-categories, "what language does
# .py mean" isn't something that varies per project, so it doesn't belong in
# config.yaml.
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

# Inverted for O(1) lookup by extension: ".py" -> "python", etc.
_EXT_TO_LANGUAGE = {ext: lang for lang, exts in LANGUAGE_EXTENSIONS.items() for ext in exts}


@dataclass(frozen=True)
class WalkedFile:
    """One file found by walk_files. `language` is None for anything not in
    LANGUAGE_EXTENSIONS (images, binaries, lockfiles, ...) -- the file still
    gets walked and counted, it's just excluded from per-language stats."""
    path: str          # POSIX-style, relative to the repo root (e.g. "src/app.py")
    language: str | None


def classify_language(path: str) -> str | None:
    """Extension -> language name, or None if we don't recognize it."""
    return _EXT_TO_LANGUAGE.get(Path(path).suffix.lower())


def _is_excluded(rel_path: str, exclude_patterns: list[str]) -> bool:
    """True if rel_path matches any exclude glob (directly, or nested)."""
    posix_path = rel_path.replace("\\", "/")  # normalize Windows paths for fnmatch
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
    """Walk repo_path, returning every non-excluded file as a WalkedFile.

    Uses os.walk (not Path.rglob) specifically so excluded directories can be
    PRUNED before descending into them -- for a repo with a huge
    node_modules/ or .venv/, this is the difference between "instant" and
    "walks tens of thousands of vendored files just to throw them away".
    """
    exclude = exclude or []
    root = Path(repo_path)
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()  # deterministic traversal order, not load-bearing otherwise

        # Mutating dirnames in place is the actual pruning mechanism: os.walk
        # reads this list back after we return it and only descends into
        # what's left. Anything filtered out here is never visited at all --
        # this is NOT the same as walking everything and filtering the
        # result afterward (that was an earlier, slower version of this code).
        pruned = []
        for d in dirnames:
            rel_dir = (Path(dirpath) / d).relative_to(root).as_posix()
            # Check both "node_modules" and "node_modules/" -- a pattern like
            # "node_modules/**" only matches the trailing-slash form via fnmatch.
            if _is_excluded(rel_dir, exclude) or _is_excluded(rel_dir + "/", exclude):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for filename in sorted(filenames):
            rel = (Path(dirpath) / filename).relative_to(root).as_posix()
            if _is_excluded(rel, exclude):
                continue
            lang = classify_language(rel)
            # languages allowlist (config's "languages" key): empty/None means
            # "keep everything"; otherwise drop anything not in the list,
            # including unclassified (lang=None) files.
            if languages and lang not in languages:
                continue
            results.append(WalkedFile(path=rel, language=lang))
    return results
