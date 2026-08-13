"""Load and validate the optional config.yaml, with built-in defaults."""

import copy

import yaml

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

DEFAULT_CONFIG = {
    "exclude": [],
    "languages": [],
    "pattern_categories": [
        "date_handling",
        "db_connection",
        "queue_access",
        "logging",
        "error_handling",
        "config_loading",
    ],
    "architecture_summary": True,
    "full_repo_mode": False,
    "batch_size": 150,
    "output_path": "metrics.json",
}


_EXPECTED_TYPES = {
    "exclude": list,
    "languages": list,
    "pattern_categories": list,
    "architecture_summary": bool,
    "full_repo_mode": bool,
    "batch_size": int,
    "output_path": str,
}


class ConfigError(Exception):
    """Raised when config.yaml is missing, malformed, or has unknown keys."""


def load_config(config_path: str | None) -> dict:
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

    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping at the top level")

    unknown_keys = set(raw) - set(DEFAULT_CONFIG)
    if unknown_keys:
        raise ConfigError(
            f"unknown config key(s) in {config_path}: {', '.join(sorted(unknown_keys))}"
        )

    for key, value in raw.items():
        expected_type = _EXPECTED_TYPES[key]
        if value is None or not isinstance(value, expected_type):
            raise ConfigError(
                f"config key '{key}' in {config_path} must be a {expected_type.__name__}, "
                f"got {value!r}"
            )

    config.update(raw)
    return config


def get_effective_excludes(config: dict) -> list[str]:
    return DEFAULT_EXCLUDES + config["exclude"]
