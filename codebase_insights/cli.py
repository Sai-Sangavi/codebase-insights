"""Argument parsing for: python -m codebase_insights <repo_path> [--config config.yaml] [--full] [--out metrics.json]

Deliberately does ONLY argv parsing + handing off to runner.run() -- no
orchestration logic lives here. This split (cli.py = parsing, runner.py =
doing) mirrors bnts-arc's tools/quality package convention: it means
runner.run() can be called directly (e.g. from tests, or from other Python
code) with plain keyword arguments, without going through argv at all.
"""

import argparse

from .runner import run


def parse_args(argv=None) -> argparse.Namespace:
    """Just the argparse definition -- one positional (repo_path) and three
    optional flags, matching the config keys they override (--config,
    --full -> full_repo_mode, --out -> output_path)."""
    parser = argparse.ArgumentParser(
        prog="codebase_insights",
        description="Understand a codebase quickly: deterministic stats + LLM-detected patterns.",
    )
    parser.add_argument("repo_path", help="Path to the repository to analyze")
    parser.add_argument("--config", default=None, help="Path to an optional config.yaml")
    parser.add_argument(
        "--full", action="store_true", help="Use exhaustive full-repo pattern coverage"
    )
    parser.add_argument("--out", default=None, help="Override output_path from config")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """The public entrypoint -- __main__.py calls this. Parse argv, then
    hand the parsed values straight to runner.run() as plain keyword
    arguments. Nothing else happens in this function on purpose."""
    args = parse_args(argv)
    return run(args.repo_path, config_path=args.config, full=args.full, out=args.out)
