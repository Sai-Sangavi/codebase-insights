"""Argument parsing for: python -m codebase_insights <repo_path> [--config config.yaml] [--full] [--out metrics.json]"""

import argparse

from .runner import run


def parse_args(argv=None) -> argparse.Namespace:
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
    args = parse_args(argv)
    return run(args.repo_path, config_path=args.config, full=args.full, out=args.out)
