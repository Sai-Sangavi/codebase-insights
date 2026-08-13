import pytest

from config import ConfigError, DEFAULT_CONFIG, get_effective_excludes, load_config


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
