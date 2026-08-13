# codebase-insights

Understand a brownfield codebase quickly: deterministic stats (L1) plus
LLM-detected conventions and patterns (L2).

## Usage

```bash
pip install -e .
python -m codebase_insights /path/to/some/repo
```

By default this writes into **codebase-insights itself**, under
`output/<category>/json/<repo-name>-metrics.json` and
`output/<category>/md/<repo-name>-metrics.md` (named after whatever repo
you pointed it at), so every run's results are archived in one place,
committed to this repo, rather than scattered wherever you happened to run
the command from. `<category>` is picked automatically:

- **`full-analysis`** — the output actually contains L2 pattern findings
  (the normal case for a default run with the `claude` CLI available).
- **`basic-stats`** — no real L2 content (L2 was skipped/empty via config,
  or the `claude` CLI was unavailable) — deterministic stats only.

Options:

- `--config config.yaml` — override excludes, language allowlist, pattern
  categories, mode, batch size, output path. See `config.example.yaml` for the
  full set of options and their defaults. Two ready-made partial-run configs:
  - `config-l1-only.yaml` — L1 stats only, zero LLM calls, instant.
  - `config-l2-only.yaml` — L2 pattern detection only, `l1_stats` omitted.
- `--full` — exhaustive full-repo pattern coverage (chunks the whole file list
  into batches instead of narrowing to a handful of candidates). Slower, more
  thorough.
- `--out metrics.json` — override the output path with a single fixed
  location instead of the `output/<category>/` default (also determines
  the `.md` report's path, e.g. `--out foo.json` writes `foo.json` +
  `foo.md`). Same effect as setting `output_path` in `config.yaml`.

L2 (pattern detection) requires the `claude` CLI to be installed and on
`PATH`. If it isn't found, L1 stats still run and are written normally; L2 is
skipped with a warning on stderr.

## Project layout

Follows the same shape as `bnts-arc`'s standalone tools (e.g.
`tools/quality`): one importable package with its own `pyproject.toml`,
a thin `cli.py` (argument parsing only) separate from `runner.py`
(orchestration), and a `__main__.py` for `python -m` invocation.

```
pyproject.toml
codebase_insights/
  __main__.py      # python -m codebase_insights -> cli.main()
  cli.py           # argument parsing only, delegates to runner.run()
  runner.py        # orchestration: load config, walk repo, compute L1+L2, write outputs
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
Code CLI for L2. `config.py` and `report.py` stay at the package root
since they're genuinely cross-cutting — config holds settings for both
levels, and report renders both levels' output.

## Development

```bash
pip install -e ".[dev]"
pytest -v
```

## Manual end-to-end validation

Before considering a change done, run the tool once against a real
downloaded open-source repository (not this repo, and not `bnts-arc` —
see the design spec's constraints) and confirm the output looks sane. This
is a manual sanity check, not an automated test — the L2 Claude CLI calls
are non-deterministic and not something to assert on in CI. Past runs are
archived under `output/full-analysis/` and `output/basic-stats/` (e.g.
`microblog-metrics.*` and `express-mongoose-es6-rest-api-metrics.*` from
validation runs against real repos in different stacks) as reference
examples of real output.

## Design

See `docs/superpowers/specs/2026-08-13-codebase-insights-design.md` for the
full design rationale, and `docs/superpowers/plans/2026-08-13-codebase-insights-implementation.md`
for the implementation plan this was built from.
