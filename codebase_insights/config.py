"""Load and validate the optional config.yaml, with built-in defaults.

Design rule (per the original ask): keep the tool itself general-purpose.
Anything that varies per-project -- which files to skip, which patterns to
look for, how much of the repo to cover -- lives in this config, not
hardcoded in the analysis code. If you're onboarding a new project and it
needs different excludes/categories, you write a config.yaml; you never
touch stats.py/patterns.py.
"""

import copy

import yaml

# Directories/files every run excludes, regardless of config. These are the
# "obviously not real source" categories (dependency trees, venvs, build
# output, VCS internals) -- a user's config.yaml can ADD to this list
# (see get_effective_excludes below) but never has to re-declare it.
DEFAULT_EXCLUDES = [
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "dist/**",
    "build/**",
    ".git/**",
    "__pycache__/**",
    "*.min.js",
]

# The full set of config keys and what a fresh run does with no config.yaml
# at all -- this dict IS the "zero-config" behavior.
DEFAULT_CONFIG = {
    "exclude": [],  # extra glob patterns, merged with DEFAULT_EXCLUDES above
    "languages": [],  # empty = classify/count every language file_walker recognizes
    "pattern_categories": [  # which L2 conventions to look for -- see llm/patterns.py.
        "date_handling",      # Ashutosh's example #1: "you use dateutil.now"
        "db_connection",      # Ashutosh's example #2: "how do you get the connection"
        "queue_access",       # Ashutosh's example #3: "how do you talk to queues"
        "logging",            # extended by us: same "one seam per concern" idea
        "error_handling",
        "config_loading",
    ],
    "architecture_summary": True,  # also run the "what does each module do" pass
    "full_repo_mode": False,  # False = narrow-to-a-handful per category (fast, default)
                              # True = chunk the whole file list and cover every file (--full)
    "batch_size": 150,  # files per chunk, only used when full_repo_mode is True
    "output_path": None,  # None = use the smart default (output/<category>/json,md); set to
                          # override with a fixed path, same effect as the --out CLI flag.
    "skip_l1": False,  # true = skip deterministic stats entirely, l1_stats omitted from output
                       # (used by config-l2-only.yaml for a pure-L2 run)
}


# Every value in a user's config.yaml gets type-checked against this before
# it's trusted -- see the validation loop in load_config below. This is what
# turns "user typo'd their config" into a clean error message instead of a
# confusing crash three layers deep in file_walker or patterns.py.
_EXPECTED_TYPES = {
    "exclude": list,
    "languages": list,
    "pattern_categories": list,
    "architecture_summary": bool,
    "full_repo_mode": bool,
    "batch_size": int,
    "output_path": str,
    "skip_l1": bool,
}


class ConfigError(Exception):
    """Raised when config.yaml is missing, malformed, or has unknown keys.

    analyze.py's run() catches this once, prints a clean stderr message, and
    exits 1 -- config problems fail fast, before any file-walking or LLM
    calls happen (per the spec's "don't silently proceed on a bad config"
    requirement).
    """


def load_config(config_path: str | None) -> dict:
    # No --config passed at all: just hand back the defaults untouched.
    # copy.deepcopy matters here -- callers (and tests) mutate the returned
    # dict (e.g. `config["full_repo_mode"] = True` for --full), and without
    # the deepcopy that mutation would corrupt the shared DEFAULT_CONFIG
    # object for every future call in the same process.
    config = copy.deepcopy(DEFAULT_CONFIG)
    if config_path is None:
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {config_path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {config_path}: {e}") from e

    # yaml.safe_load returns None for a genuinely empty file -- treat that as
    # "no overrides", same as passing no config file at all.
    if raw is None:
        raw = {}

    # Guards against a config.yaml whose top-level content isn't a mapping at
    # all -- e.g. a file that's just `false` or a bare list. Deliberately
    # checked BEFORE the raw={} substitution above would hide it (a None top
    # level is "empty file", a non-None non-dict top level is "wrong shape").
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping at the top level")

    # Reject any key we don't recognize -- catches typos like
    # "excludes:" (plural) instead of "exclude:" immediately, rather than
    # silently ignoring the typo and running with un-overridden defaults.
    unknown_keys = set(raw) - set(DEFAULT_CONFIG)
    if unknown_keys:
        raise ConfigError(
            f"unknown config key(s) in {config_path}: {', '.join(sorted(unknown_keys))}"
        )

    # Type-check every value the user actually set (not the defaults --
    # those are already correct by construction). Catches things like
    # `batch_size: "oops"` or `exclude: "vendor/**"` (a bare string instead
    # of a one-item list) before they crash deep inside file_walker/patterns.
    for key, value in raw.items():
        expected_type = _EXPECTED_TYPES[key]
        if value is None or not isinstance(value, expected_type):
            raise ConfigError(
                f"config key '{key}' in {config_path} must be a {expected_type.__name__}, "
                f"got {value!r}"
            )

    # Everything validated -- merge the user's overrides on top of defaults.
    config.update(raw)
    return config


def get_effective_excludes(config: dict) -> list[str]:
    """The excludes file_walker actually applies: built-ins + whatever the
    project's config adds. Built-ins always apply -- a project's config.yaml
    only ever ADDS exclusions, it can't remove the defaults."""
    return DEFAULT_EXCLUDES + config["exclude"]
