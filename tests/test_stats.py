import json

from file_walker import WalkedFile
from stats import count_files_by_language, count_loc_by_language, count_tests, inventory_config_files, inventory_dependency_manifests


def test_count_files_by_language_ignores_unclassified_files():
    files = [
        WalkedFile(path="a.py", language="python"),
        WalkedFile(path="b.py", language="python"),
        WalkedFile(path="c.js", language="javascript"),
        WalkedFile(path="d.png", language=None),
    ]
    assert count_files_by_language(files) == {"python": 2, "javascript": 1}


def test_count_loc_by_language_sums_lines_per_language(tmp_path):
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("line1\n", encoding="utf-8")
    files = [
        WalkedFile(path="a.py", language="python"),
        WalkedFile(path="b.py", language="python"),
    ]
    assert count_loc_by_language(str(tmp_path), files) == {"python": 4}


def test_count_loc_by_language_skips_undecodable_files(tmp_path):
    (tmp_path / "a.py").write_bytes(b"\xff\xfe\x00\x01")
    files = [WalkedFile(path="a.py", language="python")]
    assert count_loc_by_language(str(tmp_path), files) == {}


def test_count_tests_detects_python_pytest_functions(tmp_path):
    (tmp_path / "test_thing.py").write_text(
        "def test_one():\n    assert True\n\n"
        "def test_two():\n    assert True\n",
        encoding="utf-8",
    )
    files = [WalkedFile(path="test_thing.py", language="python")]
    result = count_tests(str(tmp_path), files)
    assert result == {"total": 2, "framework": "pytest"}


def test_count_tests_with_no_test_files_returns_zero():
    files = [WalkedFile(path="main.py", language="python")]
    result = count_tests("/unused", files)
    assert result == {"total": 0, "framework": None}


def test_count_tests_detects_jest_style_functions(tmp_path):
    (tmp_path / "thing.test.js").write_text(
        "describe('suite', () => {\n"
        "  it('does a thing', () => { expect(1).toBe(1); });\n"
        "  test('does another', () => { expect(2).toBe(2); });\n"
        "});\n",
        encoding="utf-8",
    )
    files = [WalkedFile(path="thing.test.js", language="javascript")]
    result = count_tests(str(tmp_path), files)
    assert result == {"total": 2, "framework": "jest"}


def test_is_test_file_rejects_filenames_with_test_as_mid_word_substring():
    from stats import _is_test_file
    assert _is_test_file("contest_winners.py") is False
    assert _is_test_file("latest_data.py") is False
    assert _is_test_file("attestation_service.py") is False


def test_is_test_file_accepts_standard_test_naming_conventions():
    from stats import _is_test_file
    assert _is_test_file("test_thing.py") is True
    assert _is_test_file("thing_test.py") is True
    assert _is_test_file("foo.test.js") is True
    assert _is_test_file("foo.spec.js") is True


def test_count_tests_does_not_count_regex_test_method_calls(tmp_path):
    (tmp_path / "thing.test.js").write_text(
        "const isValid = someRegex.test(input);\n"
        "test('a real test', () => { expect(isValid).toBe(true); });\n",
        encoding="utf-8",
    )
    files = [WalkedFile(path="thing.test.js", language="javascript")]
    result = count_tests(str(tmp_path), files)
    assert result == {"total": 1, "framework": "jest"}


def test_inventory_dependency_manifests_parses_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\nrequests==2.31\npyyaml\n\n", encoding="utf-8"
    )
    result = inventory_dependency_manifests(str(tmp_path))
    assert {"file": "requirements.txt", "count": 2} in result


def test_inventory_dependency_manifests_parses_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18"}, "devDependencies": {"jest": "^29"}}),
        encoding="utf-8",
    )
    result = inventory_dependency_manifests(str(tmp_path))
    assert {"file": "package.json", "count": 2} in result


def test_inventory_dependency_manifests_skips_absent_files(tmp_path):
    result = inventory_dependency_manifests(str(tmp_path))
    assert result == []


def test_inventory_config_files_finds_known_files(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "workflows").mkdir()
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    result = inventory_config_files(str(tmp_path))
    assert "Dockerfile" in result
    assert ".github/workflows/ci.yml" in result


def test_inventory_dependency_manifests_skips_malformed_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{ this is not valid json", encoding="utf-8")
    result = inventory_dependency_manifests(str(tmp_path))
    assert result == []


def test_count_pyproject_toml_single_line_array():
    from stats import _count_pyproject_toml
    text = 'dependencies = ["requests>=2.31", "click>=8"]\nclassifiers = ["A", "B", "C"]\n'
    assert _count_pyproject_toml(text) == 2


def test_count_pyproject_toml_multi_line_array():
    from stats import _count_pyproject_toml
    text = (
        "dependencies = [\n"
        '    "requests>=2.31",\n'
        '    "click>=8",\n'
        "]\n"
    )
    assert _count_pyproject_toml(text) == 2


def test_count_pyproject_toml_poetry_style_table():
    from stats import _count_pyproject_toml
    text = (
        "[tool.poetry.dependencies]\n"
        'python = "^3.12"\n'
        'requests = "^2.31"\n'
        'click = "^8.0"\n'
        "\n"
        "[tool.poetry.dev-dependencies]\n"
        'pytest = "^7.4"\n'
    )
    assert _count_pyproject_toml(text) == 2  # python excluded, dev-dependencies section not counted
