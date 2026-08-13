"""L2 pattern detection: shells out to the Claude Code CLI per category.

This is the ONE module in the whole tool that talks to an LLM -- everything
in stats/ is deterministic. The core idea (from the original ask) is:
don't dump a whole repo's file content at an LLM. Instead, for each
"pattern category" (date handling, DB connections, logging, ...):

  1. narrow_candidates()   -- send Claude only the file PATH list (no
                               content at all), betting that a codebase's
                               own naming is informative enough to guess
                               where a convention lives.
  2. _read_files()          -- read just the handful of files Claude picked.
  3. synthesize_pattern()   -- send Claude those files' actual content, ask
                               it to describe the convention + flag any
                               files that deviate from it.

analyze_category_default() chains those three steps. analyze_category_full()
is the --full/full_repo_mode alternative: instead of narrowing to a handful,
it runs that same three-step pipeline over every batch of the file list and
merges the results, so no file is structurally excluded -- slower and more
thorough, for when narrowing might miss something.
"""

import json
import shutil
import subprocess
from pathlib import Path


class ClaudeCLIError(Exception):
    """Raised when the claude CLI is present but the call fails or times out
    (as opposed to FileNotFoundError, raised when it's missing entirely --
    see run_claude_cli below). This distinction matters to callers:
    analyze_category() catches ClaudeCLIError per-category (so one broken
    category doesn't take down the other five), while FileNotFoundError is
    left to propagate all the way up to runner.py, which catches it ONCE
    and skips L2 entirely with a single warning."""


def run_claude_cli(prompt: str, timeout: int = 120) -> str:
    """Invoke the claude CLI with the prompt on stdin.

    The executable is resolved via shutil.which because subprocess.run only
    appends .exe to a bare name on Windows, where the installed CLI is
    claude.CMD -- a bare ["claude", ...] call silently never resolves there,
    which meant L2 was completely non-functional on this project's own dev
    machine until this was caught by a real end-to-end run. Raises
    FileNotFoundError if it can't be resolved — callers (runner.py) depend
    on that propagating uncaught.

    The prompt is passed via stdin (input=...), NOT as a command-line
    argument -- an earlier version embedded the whole file-path list or
    file contents in argv, which silently hits OS argv-length limits on
    real (thousands-of-files) repos and fails in a way indistinguishable
    from "claude isn't installed". stdin has no such limit.

    encoding="utf-8" is explicit and load-bearing: without it, Python falls
    back to the OS's locale codec (cp1252 on this Windows machine), which
    raises UnicodeEncodeError on any repo containing non-Latin-1 source
    text (CJK comments, emoji, Cyrillic, ...) -- a real bug found by a
    second-pass review after this file's first version shipped.
    """
    claude_path = shutil.which("claude")
    if claude_path is None:
        raise FileNotFoundError("claude CLI not found on PATH")
    try:
        result = subprocess.run(
            [claude_path, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude CLI timed out after {timeout}s") from e
    if result.returncode != 0:
        raise ClaudeCLIError(f"claude CLI exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def _extract_json(text: str):
    """Claude's CLI output is often "Sure, here you go:\n[...]\nhope that
    helps" rather than pure JSON -- this pulls out the JSON payload by
    finding the first opening bracket/brace and the last closing one and
    parsing just that slice. Naive (doesn't handle brackets inside string
    literals in the surrounding prose), but callers always fall back to a
    safe default when this fails to parse, so a fooled slice just means a
    skipped result, never a crash."""
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
    """Step 1 of the pipeline: ask Claude which file PATHS (never content)
    are most likely to show this category's convention. `run_cli` is a
    dependency-injection seam -- tests pass a fake in here so they never
    actually shell out to a real claude process.

    The result is filtered against `valid = set(file_paths)` before being
    returned -- never trust the LLM's output blindly; if it hallucinates a
    path that was never in the input list, it's silently dropped rather
    than passed along to be read from disk.
    """
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
    """Step 3 of the pipeline: given the actual CONTENT of the narrowed
    candidate files, ask Claude to describe the convention as one
    structured result. This exact six-key shape (category/summary/example/
    consistency/exceptions/files_examined) is produced ONLY here and is
    then consumed identically by merge_batch_results (full_repo_mode) and
    report.py's render_markdown -- if you ever change these keys, both of
    those need to change too.

    `consistency` is the interesting field: it's not just "what's the
    convention" but "is it actually followed everywhere, or are there
    exceptions" -- that's the kind of judgment call only an LLM pass (not a
    mechanical count) can make.

    No candidates at all (empty dict) short-circuits to a fixed "nothing
    found" shape without even calling the CLI -- saves a wasted call, and
    gives full_repo_mode's merge logic something inert-but-valid to ignore.
    """
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
        # files_examined comes from what WE actually sent, not from
        # anything Claude reported back -- can't be spoofed or wrong.
        "files_examined": list(candidate_contents.keys()),
    }


def _read_files(repo_path: str, paths: list[str]) -> dict:
    """Step 2 of the pipeline: read the narrowed candidates' actual
    content. Same silent-skip-on-decode-failure behavior as stats.py --
    an unreadable file just doesn't make it into the dict, no error."""
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
    """The default (fast) mode: narrow -> read -> synthesize, exactly the
    three-step pipeline described at the top of this file. One narrowing
    CLI call + one synthesis CLI call per category."""
    candidates = narrow_candidates(category, description, file_paths, run_cli=run_cli)
    contents = _read_files(repo_path, candidates)
    return synthesize_pattern(category, description, contents, run_cli=run_cli)


# What each built-in category actually means, phrased as a question for the
# LLM prompts above. Config-driven categories (a project's config.yaml can
# list ANY category name, not just these six) fall through to
# describe_category's generic fallback below -- this dict is just the
# human-friendly phrasing for the ones we ship by default.
CATEGORY_DESCRIPTIONS = {
    "date_handling": "how date/time objects are created and manipulated",
    "db_connection": "how a database connection is obtained before running a query",
    "queue_access": "how the code talks to a message queue",
    "logging": "how a logger is obtained and configured",
    "error_handling": "custom exception types and try/except conventions",
    "config_loading": "how settings and environment variables are read into the app",
}


def describe_category(category: str) -> str:
    """Known category -> its phrasing above; unknown (project-specific,
    config-driven) category -> a generic "how this codebase handles X"
    phrasing derived from the category name itself. This is what makes
    pattern_categories genuinely open-ended instead of a fixed enum -- a
    project's config.yaml can invent a category we've never heard of and
    it still produces a sensible prompt."""
    return CATEGORY_DESCRIPTIONS.get(
        category, f"how this codebase handles {category.replace('_', ' ')}"
    )


def _batch(items: list, size: int) -> list[list]:
    """Split a list into size-sized chunks, last chunk possibly smaller.
    Used only by full_repo_mode to cover every file across multiple
    narrow+synthesize passes instead of one narrowed handful."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def merge_batch_results(results: list[dict]) -> dict:
    """Combine one category's per-batch results (from full_repo_mode) into
    a single answer, matching synthesize_pattern's six-key shape.

    - consistency: takes the WORST across all batches (consistent <
      mostly_consistent < inconsistent) -- if even one batch found an
      exception, the honest overall answer is "not fully consistent",
      not an average.
    - exceptions / files_examined: unioned across all batches, de-duped.
    - summary / example: taken from the first batch that found anything --
      a known simplification (see the comment on the empty-results guard
      below); the interesting signal (consistency + exceptions) is still
      combined correctly even though only one batch's prose survives.

    The `if not results: return {...}` guard exists because
    analyze_category_full can theoretically call this with zero batches
    (an empty file_paths list) -- but in practice that path is now
    short-circuited earlier (see analyze_category_full), so this is a
    defensive fallback for any other caller, not the normal flow.
    """
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
    """The --full/full_repo_mode alternative to analyze_category_default:
    instead of narrowing to one handful of candidates, chunk the ENTIRE
    file list into batches and run the full narrow+read+synthesize pipeline
    on every batch, then merge. No file is structurally excluded from
    consideration -- more thorough, more LLM calls, slower.

    The `if not batches` short-circuit (file_paths is empty -- a tiny or
    fully-excluded repo) reuses synthesize_pattern's own empty-candidates
    branch rather than ever calling merge_batch_results with zero results --
    this is what a real bug report caught: merge_batch_results([]) used to
    be reachable here and raised an uncaught IndexError.
    """
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
    """Top-level entry point runner.py calls once per pattern_categories
    entry: picks default vs. full mode, and is the ONE place that catches
    ClaudeCLIError (CLI present but a call failed/timed out) and turns it
    into an inert {"category": ..., "error": ...} result instead of letting
    it blow up the whole run -- one bad category doesn't take down the
    other five. Note this does NOT catch FileNotFoundError (claude
    missing entirely) -- that's intentionally left to propagate up to
    runner.py, which handles the "no claude installed at all" case once,
    globally, rather than per-category."""
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
    """The `architecture_summary` pass: a different SHAPE of L2 output than
    the per-category findings above -- a free-text narrative rather than a
    structured summary/consistency/exceptions record, since "what does each
    module do" isn't really a "convention" with a consistency verdict, just
    a description. Same narrow-first spirit as the rest of L2: sends only
    the file path list, never content -- a good file/directory structure is
    often enough on its own to describe what a module is for."""
    prompt = (
        "Here is a repository's file list. In plain English, describe what each "
        "top-level module/directory is responsible for, in a few sentences per module.\n\n"
        + "\n".join(file_paths)
    )
    try:
        return run_cli(prompt).strip()
    except ClaudeCLIError as e:
        return f"(architecture summary unavailable: {e})"
