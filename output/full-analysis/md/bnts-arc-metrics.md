# Codebase Report: C:\Users\SaiSangavi\bnts-arc

## Stack

| Language | Files | LOC |
|---|---|---|
| css | 3 | 541 |
| html | 24 | 21720 |
| javascript | 3 | 104 |
| markdown | 162 | 43445 |
| python | 419 | 44044 |
| shell | 22 | 1502 |
| typescript | 256 | 43988 |
| yaml | 65 | 13599 |

## Tests

986 tests (pytest)

## Git

734 commits, 4 contributors, 53 days old

## Patterns

### Date Handling
**Consistency:** mostly_consistent

Date/time values are passed around as ISO 8601 strings (from API/event payloads) and converted to native JS Date objects only at the point of use — either via `new Date(iso).getTime()` for arithmetic (durations, 'ago' calculations, sort/compare) or `new Date(iso).toLocaleString(...)` for locale-formatted display. Live-updating UI reads the current time via `Date.now()` inside a `setInterval`-driven React state tick (`useNow`), paired with a `useMounted` guard so locale/timezone-dependent output is deferred past first render to avoid SSR/client hydration mismatches. Two helper files bypass Date entirely and manipulate the ISO string directly via `.slice()` for cheap, timezone-agnostic substring extraction (UTC hour/min/sec, or month-day for chart axis labels).

```
export function durationBetween(startIso?: string, endIso?: string): string {
  if (!startIso || !endIso) return "";
  return fmtDuration(new Date(endIso).getTime() - new Date(startIso).getTime());
}
```
- **Exception:** apps/web/src/features/runs/timeline.ts: fmtTime(iso) extracts HH:MM:SS via `iso.slice(11, 19)` instead of constructing a Date object, relying on the ISO string always being UTC-formatted rather than using Date/Intl.
- **Exception:** apps/web/src/features/analytics/utils.ts: toMonthDay(iso) uses `iso.slice(5)` string slicing rather than Date parsing/formatting.
- **Exception:** apps/web/src/lib/format.ts and apps/web/src/features/runs/run-time.tsx use different toLocaleString locale arguments (explicit "en-GB" vs. the runtime-default `[]`), so date display formatting isn't uniform across the app.
- **Exception:** No shared date-parsing/formatting utility module is used across features — each file (format.ts, run-time.tsx, timeline.ts, node-visits.ts) reimplements its own new Date(...) arithmetic and formatting rather than centralizing it.

### Db Connection
**Consistency:** mostly_consistent

Every adapter receives a single shared `psycopg_pool.AsyncConnectionPool` instance via constructor injection from the composition root (build_container in runtime/container.py, per ADR-0017) — no adapter ever constructs its own pool. Before running a query, the adapter acquires a connection from that shared pool with `async with self._pool.connection() as conn:` (or `conn, cur = ...` when a cursor is needed), runs `conn.execute(...)`, and the context manager returns the connection to the pool on exit. A `tools/quality` lint check (pg_pool_singleton.py) enforces this at CI time: `AsyncConnectionPool(...)` may only be constructed in runtime/container.py, and direct `psycopg.AsyncConnection.connect()` calls are disallowed everywhere except one documented exception.

```
async def get(self, scope: ConfigScope, key: str) -> ConfigEntry | None:
    async with self._pool.connection() as conn:
        cur = await conn.execute(
            "SELECT scope, tenant_id, project_id, workflow_id, key, value, strategy, updated_at"
            " FROM arc_config"
            " WHERE scope = %s AND tenant_id = %s AND project_id = %s"
            "   AND workflow_id = %s AND key = %s",
            (scope.level.value, scope.tenant_id, scope.project_id, scope.workflow_id, key),
        )
        row = await cur.fetchone()
    return _row_to_entry(row) if row is not None else None
```
- **Exception:** apps/api/src/arc_api/capabilities/events/pg_event_store.py: subscribe() calls psycopg.AsyncConnection.connect() directly (bypassing the pool) to hold a long-lived LISTEN/NOTIFY connection, since pooled connections can't retain LISTEN state — this is the one intentional, lint-allowlisted exception (see tools/quality/arc_quality/checks/devloop/pg_pool_singleton.py).

### Queue Access
**Consistency:** mostly_consistent

There is no traditional broker (Kafka/RabbitMQ/SQS) here — 'messaging' is built from two distinct mechanisms layered on Postgres and Temporal. (1) Durable pub/sub: PgEventStore.record() inserts an event row into the append-only `arc_events` table inside a transaction, then issues `pg_notify('arc_events', 'tenant:project:seq')` — a lightweight pointer, never the payload (NOTIFY's ~8KB cap). A single dedicated LISTEN connection per API process picks up notifications; subscribe() matches the tenant/project in the payload, re-fetches the actual row(s) via since(), and yields them. This feeds a scope-filtered, multiplexed SSE endpoint (GET /api/events) that the Next.js app proxies and a client EventBusProvider consumes via one EventSource, demultiplexing frames by `topic` for any surface to react to. Reconnects resume via Last-Event-ID/`since(after_seq)` replay against the durable table, so Postgres — not the notify channel — is the source of truth; a bounded per-subscriber asyncio.Queue provides backpressure (oldest dropped, client reconnects and replays). The in-memory adapter swaps Postgres LISTEN/NOTIFY for a plain in-process asyncio.Queue fan-out behind the same EventStore port, for tests/mock-mode. (2) Separately, Temporal provides an actual task-queue abstraction (`task_queue='arc-runs'`): the orchestrator starts durable ArcRunWorkflow executions and an in-process Worker polls that queue to execute `run_task`/`record_node_event` Activities, with retries/timeouts/heartbeats and crash-resume — this is work dispatch, not event notification, and is entirely independent of the arc_events/NOTIFY path (though its activities call back into EventStore.record to emit lifecycle events).

```
await cur.execute(
    "SELECT pg_notify(%s, %s)",
    (_CHANNEL, f"{scope.tenant_id}:{scope.project_id}:{seq}"),
)
```
- **Exception:** InMemoryEventStore replaces Postgres LISTEN/NOTIFY with a plain asyncio.Queue-per-subscriber fan-out (no DB), used when ARC_DATABASE_URL is unset and in tests/mock-mode.
- **Exception:** Temporal's task_queue ('arc-runs') is a second, unrelated queueing mechanism used purely for dispatching Activities to workers — it does not go through arc_events/NOTIFY at all.
- **Exception:** NOTIFY messages carry only a 'tenant:project:seq' pointer, never the event body, so the notify channel alone is not a complete message queue — the row must be re-fetched from arc_events.
- **Exception:** High-frequency ephemeral signals (per-message agent events, task_output ticks) are pushed through the same EventStore.record/NOTIFY path but are explicitly documented as best-effort/non-replayable, unlike the durable lifecycle events.
- **Exception:** The Next.js API route (apps/web/src/app/api/events/route.ts) is a pure byte-pipe proxy with no queue semantics of its own — it just forwards the upstream SSE stream and Last-Event-ID header.

### Logging
**Consistency:** mostly_consistent

Python modules that need a logger obtain it via the stdlib `logging` module using the standard `logging.getLogger(__name__)` call, bound once to a module-level constant named `_LOG` right after the imports. There is no central logging-config module in these files; each module fetches its own logger against its `__name__`, relying on whatever root logging config the process (uvicorn) sets up. Only two of the given files actually log this way (container.py, app.py) — the rest either do no logging (local.py, langfuse.py, settings.py, __main__.py), use plain `print()` for user-facing CLI output (runner.py, cli.py), or use `console.error`/`process.stderr.write` in the TypeScript sidecar file.

```
import logging
...
_LOG = logging.getLogger(__name__)
...
_LOG.info("CLI-agent executor: DockerSandbox image=%s (ADR-0008)", image)
```
- **Exception:** apps/api/src/arc_api/capabilities/tracing/local.py, langfuse.py, apps/api/src/arc_api/runtime/settings.py, apps/api/src/arc_api/__main__.py — no logger is created or used at all
- **Exception:** tools/quality/arc_quality/runner.py, cli.py — use plain print() statements instead of the logging module for user-facing output
- **Exception:** apps/desktop/src/sidecar.ts — TypeScript file uses console.error/process.stderr.write, not a logging framework, and isn't part of the Python logging convention

### Error Handling
**Consistency:** mostly_consistent

This codebase defines no custom exception classes of its own in the sampled files — it relies entirely on stdlib and third-party library exceptions (ValueError, TimeoutError, ProcessLookupError, OSError, json.JSONDecodeError, jwt.ExpiredSignatureError/InvalidTokenError, argon2's VerifyMismatchError/VerificationError/InvalidHashError). The convention is to catch narrow, specific exception tuples where the failure mode is well understood (e.g. process-already-dead races, malformed JSON, password-verify failures) and to fall back to a safe default rather than propagate. Broader `except Exception` blocks appear at true I/O/subprocess boundaries (git diff, docker container run) specifically to convert any unexpected failure into a degraded-but-safe result (empty string, exit_code=-1) instead of crashing the caller. Domain-level validation errors (bad git URLs, malformed PR links, unsupported platforms) are raised as plain `ValueError` with descriptive, actionable messages rather than dedicated exception types. try/finally is used deliberately in async subprocess code to guarantee cleanup (killing process groups, cancelling drain tasks) even when a CancelledError bypasses the except clauses.

```
except TimeoutError:
    _LOG.warning("CLI agent timed out after %ds: %s", timeout, argv[0])
    if stderr_task is not None:
        stderr_task.cancel()
    if proc is not None:
        _kill_process_group(proc)
    ...
finally:
    # CancelledError (e.g. Temporal workflow termination) bypasses the except
    # TimeoutError branch — this finally ensures the subprocess is always reaped.
    if stderr_task is not None and not stderr_task.done():
        stderr_task.cancel()
    if proc is not None and proc.returncode is None:
        _kill_process_group(proc)
```
- **Exception:** ValueError (git_platforms/adapter.py — raised with descriptive messages for unparseable URLs/unsupported platforms, no custom subclass)
- **Exception:** TimeoutError (asyncio) — caught explicitly in process_runner.py and docker_sandbox.py to trigger cleanup and mark timed_out=True
- **Exception:** json.JSONDecodeError — caught narrowly in output_parsers.py, malformed lines logged at debug and skipped rather than failing the whole parse
- **Exception:** argon2.exceptions.{VerifyMismatchError, VerificationError, InvalidHashError} — caught together in auth/_service.py to normalize any verify failure to False/None
- **Exception:** jwt.ExpiredSignatureError / jwt.InvalidTokenError — not caught locally; documented in decode_token's docstring as expected to propagate to the caller
- **Exception:** (ProcessLookupError, OSError) — caught together in _kill_process_group for benign already-dead-process races
- **Exception:** bare except Exception — used at hard I/O/subprocess boundaries (_git_diff, DockerSandbox.run) to convert any unexpected error into a safe default ("" or exit_code=-1) instead of propagating

### Config Loading
**Consistency:** mostly_consistent

Backend process config lives in one place: apps/api/src/arc_api/runtime/settings.py defines a frozen Settings dataclass whose from_env() classmethod is the single canonical entry point, reading os.environ.get(...) for every field with an explicit default, coercing types (int(), float()) where needed, and OR-chaining legacy/alias env var names (e.g. ARC_GIT_PLATFORM_TOKEN || ARC_GITHUB_TOKEN || GH_TOKEN || GITHUB_TOKEN) for backward compatibility. Settings.from_env() is called once at process startup and the resulting Settings instance is threaded through the composition root (runtime/container.py's build_container), which builds all adapters/ports from it and is exposed to FastAPI handlers as a Container via dependency injection (runtime/deps.py) — handlers never touch os.environ directly. .env.example files (apps/api/.env.example, infra/docker/env.prod.example) document the same variable names/defaults for local dev and prod deployment (the latter populated by a secrets-refresh script from SSM). The Next.js frontend (apps/web) follows an analogous but separate pattern for its own runtime: next.config.ts reads process.env directly (ARC_API_URL, ARC_ALLOWED_ORIGINS) to build rewrites/config since Next config files execute in Node at build/start time, not through a shared settings object. Separately, packages/core's ConfigResolver/ConfigStore is a distinct, DB-backed hierarchical config layer (system→tenant→project→workflow, REPLACE/MERGE) for runtime-mutable application config exposed via HTTP routes — this is not environment-variable driven and is orthogonal to process bootstrap Settings.

```
provider=os.environ.get("ARC_PROVIDER", "litellm"),
database_url=os.environ.get("ARC_DATABASE_URL") or None,
allow_ephemeral=os.environ.get("ARC_ALLOW_EPHEMERAL", "") not in ("", "0", "false"),
git_platform_cache_ttl=float(os.environ.get("ARC_GIT_PLATFORM_CACHE_TTL", "300")),
```
- **Exception:** container.py's _build_cli_agent_executor reads os.environ.get('ARC_CLI_SANDBOX', 'auto') and os.environ.get('ARC_SANDBOX_IMAGE') directly at build time rather than going through Settings/from_env, so these two knobs bypass the single-source-of-truth pattern.
- **Exception:** apps/web/next.config.ts reads process.env.ARC_API_URL and process.env.ARC_ALLOWED_ORIGINS directly (no shared settings module) since it's a Node-side Next.js build/runtime file, not the Python API process.
- **Exception:** packages/core/src/arc_core/services/config_resolver.py + domain/config.py implement a completely separate, database-backed hierarchical config mechanism (system/tenant/project/workflow scopes with REPLACE/MERGE) for dynamic application config — unrelated to process environment variables and not read via os.environ at all.
- **Exception:** docker_ready/mode logic (ARC_CLI_SANDBOX/ARC_SANDBOX_IMAGE) is only ever consulted inside the composition root at container-build time, so it isn't part of the frozen Settings snapshot that the rest of the app depends on.

## Architecture

# Repository Overview

This is **ARC** (based on naming conventions like `arc_api`, `arc_core`, `ARC-STORY-*`) — an autonomous SDLC/agent orchestration platform that runs AI agents through workflows (plan → implement → review → verify → PR) with human gates, tracing, and a web cockpit for oversight.

## Top-level config/docs files
- **`.editorconfig`, `.gitignore`, `.markdownlint.json`, `.pre-commit-config.yaml`** — standard editor/formatting/linting/git hygiene config.
- **`.importlinter`** — enforces Python import boundaries (architectural layering rules) across the monorepo.
- **`CLAUDE.md`** — instructions for Claude Code when working in this repo.
- **`HANDOFF.md`, `LEARNINGS.md`, `TODOs.md`** — running notes: handoff context between sessions, accumulated lessons, and outstanding work items.
- **`README.md`** — top-level project introduction.
- **`deps-pins.toml`** — pinned dependency versions across the workspace.
- **`justfile`** — task runner recipes (build/test/lint shortcuts), an alternative to Makefile.
- **`package.json` / `package-lock.json` / `pnpm-lock.yaml` / `pnpm-workspace.yaml`** — JS/TS workspace management (pnpm monorepo for the web/desktop apps).
- **`pyproject.toml` / `uv.lock` / `pyrightconfig.json`** — Python workspace config, dependency lock (via `uv`), and type-checking config for the Python packages.

## `.github/workflows/`
CI/CD pipeline definitions: `ci.yml` (main test/build pipeline), `deploy.yml` (deployment), `nightly.yml` (nightly jobs — likely mutation testing, dependency drift, security scans), `quality.yml` (code quality gates).

## `apps/`
The deployable applications:
- **`apps/api`** — the core backend (`arc_api`), a FastAPI service implementing the orchestration engine. Organized by **capabilities** (git platform adapters, execution/process running, sandboxing, tracing, prompts, event stores) and **features** (auth, projects, work items, runs, workflows, teams, personas, analytics, alerts, config) — each feature has routes + repository adapters (in-memory and Postgres), plus a `runtime/` composition root and Temporal-based durable execution (`features/runs/adapters/temporal/`). Extensive test suite under `tests/`.
- **`apps/desktop`** — an Electron desktop wrapper that packages the app with a sidecar process, local web server, and port management.
- **`apps/desktop-tauri`** — a spike/exploration of a Tauri-based alternative desktop packaging (not yet built out).
- **`apps/web`** — the Next.js frontend: pages for cockpit, runs, backlog, projects, workflows (with a visual workflow designer), analytics dashboards, docs viewer, and design catalog. Organized into `components/` (shared UI, charts, app-shell) and `features/` (one folder per domain area: runs, work, workflows, projects, personas, analytics, user-settings), plus `mocks/` for MSW-based test mocking.

## `docs/`
Project documentation: architecture (`ARCHITECTURE.md`, `DOMAIN-MODEL.md`, diagrams), a full set of numbered **Architecture Decision Records** (`decisions/ADR-0001` through `ADR-0028`), roadmaps, PRD, design guidelines/prototypes (`design/`), pitch/status decks (HTML), and `superpowers/` (plans and specs written using the Superpowers skill system for past feature work).

## `harness/`
Operator/CLI tooling for driving the system outside the web UI — scripts to import tickets from Jira, clone/create work items, commit changes, raise PRs, run quality gates, provision users, monitor health, and migrate data. This is the "human/ops harness" around the agent platform.

## `infra/`
Infrastructure-as-code and deployment: Docker Compose files (local + prod), and an `aws/` subtree with OpenTofu (Terraform fork) modules for networking, compute, load balancer, DNS, ECR, IAM/OIDC, and secrets, plus shell scripts for bootstrapping, deploying, migrating databases, and managing a GitHub Actions self-hosted runner on EC2.

## `packages/`
Shared Python libraries consumed by `apps/api`:
- **`packages/core`** (`arc_core`) — the domain model (work, workflow, project, persona, session, etc.) and **ports** (interfaces) for completion, storage, orchestration, tracing, etc. — the hexagonal-architecture core with no framework dependencies.
- **`packages/theme-sdlc`** (`arc_theme_sdlc`) — SDLC-specific workflow definitions (implement story, address PR feedback, merge story, rebase branch, UX design) and criteria/taxonomy logic for the software-delivery domain.

## `prompts/`
YAML prompt templates used by the SDLC workflows (implement, review, verify, refine acceptance criteria, UX design, PR feedback, rebase).

## `skills/`
A distributable Claude Code plugin (`bnts-arc-sdlc-plugin`) packaging this repo's SDLC skills (commit, coordinator, epic, implement, plan, raise-pr, review, setup-worktree, story, verify-acs, verify-tests) for reuse in other repos/marketplaces.

## `tools/quality/`
A custom quality-gate tool (`arc_quality`) that runs categorized checks — **CI** checks (tests, dead code, duplication, SAST, license, type overlap), **devloop** checks (fast local checks: lint, formatting, complexity, secrets, import boundaries, banned patterns), and **nightly** checks (mutation testing, container scanning, semgrep, sonar, dependency drift).

## `tracker/`
A filesystem-based work-tracking system (an alternative/interim to Jira) organizing work as `epic → story → slice`, each with YAML metadata, markdown descriptions, progress notes, and design/UX artifacts. Mirrors the actual product backlog for this repo's own development (dogfooding).
