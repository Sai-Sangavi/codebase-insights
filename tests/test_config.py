import pytest

from codebase_insights.config import ConfigError, DEFAULT_CONFIG, get_effective_excludes, load_config


def test_load_config_with_no_path_returns_defaults():
    config = load_config(None)
    assert config == DEFAULT_CONFIG


def test_load_config_merges_overrides(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("output_path: custom.json\n", encoding="utf-8")
    config = load_config(str(config_file))
    assert config["output_path"] == "custom.json"
    assert config["pattern_categories"] == DEFAULT_CONFIG["pattern_categories"]


def test_load_config_missing_file_raises_config_error():
    with pytest.raises(ConfigError):
        load_config("/nonexistent/config.yaml")


def test_load_config_malformed_yaml_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("exclude: [unterminated\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_unknown_key_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("nonexistent_key: true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_get_effective_excludes_includes_builtin_defaults():
    config = load_config(None)
    excludes = get_effective_excludes(config)
    assert "node_modules/**" in excludes


def test_load_config_falsy_scalar_top_level_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("false\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_null_exclude_value_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("exclude:\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_null_pattern_categories_value_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("pattern_categories:\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_wrong_type_value_raises_config_error(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text('batch_size: "oops"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(config_file))


def test_load_config_empty_file_still_returns_defaults(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("", encoding="utf-8")
    assert load_config(str(config_file)) == DEFAULT_CONFIG


def test_load_config_accepts_shipped_example_config():
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "config.example.yaml"
    config = load_config(str(example))
    assert "vendor/**" in config["exclude"]
