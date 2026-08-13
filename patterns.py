"""L2 pattern detection: shells out to the Claude Code CLI per category."""

import json
import shutil
import subprocess
from pathlib import Path


class ClaudeCLIError(Exception):
    """Raised when the claude CLI is present but the call fails or times out."""


def run_claude_cli(prompt: str, timeout: int = 120) -> str:
    """Invoke the claude CLI with the prompt on stdin.

    The executable is resolved via shutil.which because subprocess.run only
    appends .exe to a bare name on Windows, where the installed CLI is
    claude.CMD. Raises FileNotFoundError if it can't be resolved — callers
    (analyze.py) depend on that propagating uncaught.
    """
    claude_path = shutil.which("claude")
    if claude_path is None:
        raise FileNotFoundError("claude CLI not found on PATH")
    try:
        result = subprocess.run(
            [claude_path, "-p"], input=prompt, capture_output=True, text=True, timeout=timeout
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
    if not results:
        return {
            "category": None,
            "summary": "No candidate files found for this pattern.",
            "example": None,
            "consistency": "unknown",
            "exceptions": [],
            "files_examined": [],
        }
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
    if not batches:
        return synthesize_pattern(category, description, {}, run_cli=run_cli)
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
