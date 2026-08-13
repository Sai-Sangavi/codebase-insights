# codebase-insights — Design Spec

**Date:** 2026-08-13
**Status:** Approved (pending write-up), design phase
**Origin:** An action item assigned during a team meeting (2026-08-12) to build a
codebase-understanding tool. Verified against the meeting notes prior to
brainstorming this design — see the verification the assistant performed at the
start of this thread for line-by-line traceability of what was actually requested
vs. what's an open design decision.

## Goal

Given an arbitrary codebase — specifically a "brownfield" project a team has been
working on for 2–5 years — understand it quickly and as completely as possible,
without a human reading through it file by file. This is deliberately separate from
a teammate's parallel work (a structural code-relationship graph via
Graphify/Code Graph); this tool is the **stats + conventions layer**, not the
code-relationship-graph layer.

Two levels, as originally framed:

- **L1 — basic stats.** Deterministic, no LLM. "Think of what are stats that can be
  simply calculated from the source code itself."
- **L2 — patterns.** The conventions a mature codebase has already settled on, even
  where nobody wrote them down — e.g. "whenever you create a date object, you use
  dateutil.now," or "whenever you connect to a database and invoke a query, this is
  how you get the connection." May need an LLM.

Everything beyond the originally-named examples (file counts, test counts, date
handling, DB connection, queue access) is this project's own design decision, made
explicit throughout this document — the ask was explicitly not an exhaustively
pre-enumerated checklist; discovering what counts as a pattern in a given repo is
part of the point.

## Constraints (from the original ask, non-negotiable)

- Must be tested against a downloaded open-source repository — explicitly **not**
  the team's own internal platform codebase.
- Must stay general-purpose; anything that varies per-project comes from
  configuration, not hardcoded logic.
- Language: Python (a suggestion, not a mandate — "most likely Python scripts,
  maybe shell script, whatever").

## Decisions made during brainstorming (not specified in the original ask)

- **Location:** standalone project (this repo), not folded into any other internal
  codebase, for now — kept general enough to fold into a larger platform's tooling
  later without a rewrite if it graduates into a product feature.
- **Structure:** one command (`python analyze.py <repo_path>`), code split across a
  few small, single-purpose files rather than one large file or a full package.
- **LLM access:** shells out to the Claude Code CLI (`claude`) as a subprocess,
  rather than calling the Anthropic API directly — no separate API key/billing
  needed beyond an existing Claude Code auth.
- **Output:** `metrics.json` (machine-readable) + `metrics.md` (human-readable
  report rendered from the JSON) — mirrors a JSON-source-of-truth +
  friendly-renderer split discussed elsewhere in the same meeting for a related
  implementation-plan-rendering idea.

## Architecture

```
codebase-insights/
  analyze.py            # entrypoint: python analyze.py <repo_path> [--config config.yaml] [--full] [--out metrics.json]
  file_walker.py         # enumerate files, apply excludes, classify by language/extension
  stats.py               # L1: all deterministic stats
  patterns.py            # L2: narrowing (default or --full mode), Claude CLI calls, synthesis
  report.py              # renders metrics.json -> metrics.md
  config.py              # loads optional YAML config, applies defaults
  config.example.yaml    # documented example config
  docs/superpowers/specs/  # this doc
```

Single command, single run, both L1 and L2 execute in sequence (L1 first — it's
fast and needed as an input to L2's narrowing anyway; then L2).

## L1 — Basic stats (no LLM)

All computed via filesystem walk (`file_walker.py`), manifest parsing, and `git`
subprocess calls. Zero LLM calls in this phase.

- File counts by language/extension (an originally-named example)
- Lines of code (LOC) per language
- Test case counts + detected test framework (an originally-named example: "test cases")
- Dependency manifest inventory (requirements.txt/pyproject.toml/package.json/etc.),
  parsed dependency counts
- Config file inventory (Dockerfile, CI workflow files, linter configs, etc.)
- Git metadata: commit count, contributor count, repo age in days
- Commit message convention detection (e.g. Conventional Commits, via regex over
  `git log`)
- Branching strategy signal (from `git branch -a` / merge history shape)
- PR/issue template presence (`.github/PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/`)

Deliberately excluded from v1 (would scope-creep into what a general code-quality
gate/linter runner already does): largest-files-by-LOC, cyclomatic complexity, or
any other code-quality-flavored metric.

## L2 — Pattern detection (needs an LLM)

### Categories

Config-driven (`pattern_categories` in `config.yaml`), not hardcoded — a project can
add/remove categories without touching code. Default starter set:

- `date_handling` (an originally-named example)
- `db_connection` (an originally-named example)
- `queue_access` (an originally-named example)
- `logging`
- `error_handling`
- `config_loading`

Plus a separate, differently-shaped pass:

- `architecture_summary` (boolean flag) — a plain-English "what does each top-level
  module do" narrative, not tied to a single convention.

A much broader menu of candidate categories (migration_pattern, http_client,
auth_check, validation, serialization, dependency_injection, retry_backoff,
test_fixtures, secrets_management, tenant_scoping, and more — organized by axis:
data/persistence, external communication, cross-cutting concerns, application
structure, testing, frontend-only, concurrency/time, domain modeling, API design,
security, observability, docs/release) was explored during brainstorming and is
**intentionally not all shipped as defaults**. It's documented as commented-out
examples in `config.example.yaml` so it's discoverable and any project can opt in,
without bloating what runs by default. Continuing to hand-enumerate categories
indefinitely works against the actual point of the original ask — that discovering
what counts as a pattern in a given repo is itself part of the job, not a fixed
checklist to author upfront.

### Narrowing strategy — two modes

**Default mode** (per the original suggestion): per category, enumerate the
file-path list only (no content), ask Claude CLI to narrow to a handful of
candidates purely from path/filename structure — betting that "somebody who worked
on the project would have named them meaningfully" — then read only those
candidates' content and ask Claude CLI to synthesize the pattern. One narrowing
call + one synthesis call per category.

**`--full` mode** (opt-in flag, for when a user wants exhaustive coverage instead of
speed): skip narrowing-to-a-handful. Instead split the full file list into batches
(default 150 files/batch, configurable via `batch_size`), run the same
narrow+read+synthesize pass per batch per category, then merge per-batch findings
into one final answer per category (e.g. "found in batches 3 and 7, consistent
across both," or surfaces exceptions found in either). More LLM calls, but no file
is structurally excluded from consideration.

### Per-category output shape

Beyond just naming a category, someone exploring an unfamiliar repo actually wants:
a plain-English summary, a real example, and — something only an LLM pass can
surface — whether the convention is actually followed consistently or has drifted:

```json
{
  "category": "db_connection",
  "summary": "DB connections are obtained via get_session() in db/session.py, used as a context manager everywhere.",
  "example": {
    "file": "db/session.py",
    "snippet": "with get_session() as session:\n    ..."
  },
  "consistency": "consistent",
  "exceptions": ["legacy/importer.py opens a raw connection directly"],
  "files_examined": ["db/session.py", "api/routes/users.py"]
}
```

`consistency` is one of `consistent | mostly_consistent | inconsistent`.

## Config shape (`config.yaml`, fully optional — sensible defaults if omitted)

```yaml
# --- L1 scope ---
exclude:                      # glob patterns, merged with built-in defaults
  - node_modules/**
  - .venv/**
  - venv/**
  - dist/**
  - build/**
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
architecture_summary: true

full_repo_mode: false         # true = chunk+cover-everything instead of narrow-to-handful
batch_size: 150               # files per batch, only used when full_repo_mode: true
# The --full CLI flag, if passed, overrides full_repo_mode: true regardless of this
# config value; the config key exists so a project can default to full mode without
# needing the flag on every invocation.

# --- output ---
output_path: metrics.json
```

Built-in excludes (node_modules, venv, .venv, dist, build, common VCS/cache dirs)
always apply even with zero config, matching "leaving aside things like node
modules and VM" from the original ask.

## Output schema

`metrics.json`:

```json
{
  "repo_path": "/path/to/analyzed-repo",
  "analyzed_at": "2026-08-13T00:00:00Z",
  "l1_stats": {
    "file_counts_by_language": {"python": 342, "javascript": 58},
    "loc_by_language": {"python": 48213, "javascript": 6210},
    "test_counts": {"total": 512, "framework": "pytest"},
    "dependency_manifests": [{"file": "requirements.txt", "count": 34}],
    "config_files": ["Dockerfile", ".github/workflows/ci.yml"],
    "git_metadata": {"commit_count": 4821, "contributors": 23, "repo_age_days": 1460},
    "commit_convention": {"detected": "conventional_commits", "confidence": "high"},
    "branch_strategy": {"signal": "trunk_based | gitflow | unclear"},
    "pr_templates_present": true
  },
  "l2_patterns": {
    "mode": "default | full_repo",
    "categories": {
      "db_connection": { "...": "per-category shape above" }
    },
    "architecture_summary": "This repo is organized into..."
  }
}
```

`l1_stats` is always populated (no LLM dependency, always runs). `l2_patterns` is
only present if Claude CLI was actually invoked successfully.

`metrics.md` is a rendered Markdown version of the same data — headings, tables for
L1 stats, a subsection per pattern category with its summary/example/consistency —
generated by `report.py`, meant to be read directly (editor preview, terminal,
GitHub) rather than parsed.

## Error handling

- **Claude CLI missing/not on PATH:** L1 still runs and writes `metrics.json` in
  full; L2 is skipped with a warning to stderr (`l2_patterns` omitted, or set to
  `{"skipped": "claude CLI not found"}`) — not a hard failure. L1 output alone is
  still useful.
- **Claude CLI call fails/times out for one category:** that category's slot gets
  `{"error": "..."}`; other categories still proceed independently.
- **Unreadable/binary files during the file walk:** silently skipped, not counted
  as source, not an error.
- **Malformed `config.yaml`:** fail fast with a clear error message before doing any
  work — don't silently fall back to defaults for a config a user clearly tried to
  customize.

## Testing approach

- **L1 (`stats.py`, `file_walker.py`):** unit tests against a small, checked-in
  fixture directory tree (a handful of fake files across a couple of languages, a
  fake `.git`, a fake `requirements.txt`) — fully deterministic, no mocking needed.
- **L2 (`patterns.py`):** unit tests mock the Claude CLI subprocess call (fake
  `subprocess.run` returning canned JSON), so tests never actually shell out or
  spend tokens — verifies narrowing/synthesis logic and error handling (CLI
  missing, CLI errors, timeout) without needing live Claude access in CI.
- **`report.py`:** unit test that a known `metrics.json` fixture renders to the
  expected Markdown structure.
- **End-to-end validation:** manually run the whole tool once against a real
  downloaded open-source repo (never the team's own internal platform codebase) as
  a one-time manual sanity check before calling this done — not an automated test.

## Out of scope for v1

- Any code-quality-flavored metric (complexity, largest files) — that's a general
  code-quality gate runner's territory, not this tool's.
- The ~25-category broader pattern menu explored during brainstorming — documented
  as opt-in config examples, not shipped as defaults.
- Folding this into a larger internal platform's tooling as an actual workspace
  package — explicitly deferred until/unless it graduates from standalone tool to
  adopted product feature.
