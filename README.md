# codebase-insights

Understand a brownfield codebase quickly: deterministic stats (L1) plus
LLM-detected conventions and patterns (L2).

## Usage

```bash
pip install -r requirements.txt
python analyze.py /path/to/some/repo
```

This writes `metrics.json` (machine-readable) and `metrics.md` (human-readable
report) into the current directory.

Options:

- `--config config.yaml` — override excludes, language allowlist, pattern
  categories, mode, batch size, output path. See `config.example.yaml` for the
  full set of options and their defaults.
- `--full` — exhaustive full-repo pattern coverage (chunks the whole file list
  into batches instead of narrowing to a handful of candidates). Slower, more
  thorough.
- `--out metrics.json` — override the output path (also determines the
  `.md` report's path, e.g. `--out foo.json` writes `foo.json` + `foo.md`).

L2 (pattern detection) requires the `claude` CLI to be installed and on
`PATH`. If it isn't found, L1 stats still run and are written normally; L2 is
skipped with a warning on stderr.

## Project layout

```
analyze.py       # entrypoint / orchestrator (cross-cutting)
config.py        # config loading for both levels (cross-cutting)
report.py        # renders both levels' output to metrics.md (cross-cutting)
stats/           # L1: deterministic stats, zero LLM dependency
  file_walker.py # file enumeration + exclude/language handling
  stats.py       # the actual stat computations
llm/             # L2: LLM-based pattern detection
  patterns.py    # the only module that shells out to Claude CLI
```

`stats/` groups everything that computes L1's deterministic stats;
`llm/patterns.py` is the sole boundary where the tool talks to the Claude
Code CLI for L2. `analyze.py`, `config.py`, and `report.py` stay at the
root since they're genuinely cross-cutting — config holds settings for
both levels, and report renders both levels' output.

## Development

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Manual end-to-end validation

Before considering a change done, run the tool once against a real
downloaded open-source repository (not this repo, and not `bnts-arc` —
see the design spec's constraints) and confirm `metrics.json`/`metrics.md`
look sane. This is a manual sanity check, not an automated test — the L2
Claude CLI calls are non-deterministic and not something to assert on in CI.

## Design

See `docs/superpowers/specs/2026-08-13-codebase-insights-design.md` for the
full design rationale, and `docs/superpowers/plans/2026-08-13-codebase-insights-implementation.md`
for the implementation plan this was built from.
