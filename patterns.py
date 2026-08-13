"""L2 pattern detection: shells out to the Claude Code CLI per category."""

import json
import subprocess
from pathlib import Path


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
