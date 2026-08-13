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
