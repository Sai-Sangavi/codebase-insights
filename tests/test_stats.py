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


import subprocess

from stats import (
    check_pr_templates,
    detect_branch_strategy,
    detect_commit_convention,
    git_metadata,
)


def _init_git_repo(path, commit_messages):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    for i, message in enumerate(commit_messages):
        (path / f"file{i}.txt").write_text(str(i), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=path, check=True, capture_output=True)


def test_git_metadata_reports_commit_count_and_contributors(tmp_path):
    _init_git_repo(tmp_path, ["feat: first", "fix: second"])
    result = git_metadata(str(tmp_path))
    assert result["commit_count"] == 2
    assert result["contributors"] == 1
    assert result["repo_age_days"] >= 0


def test_detect_commit_convention_high_confidence_when_mostly_conventional(tmp_path):
    _init_git_repo(tmp_path, ["feat: a", "fix: b", "chore: c", "random message"])
    result = detect_commit_convention(str(tmp_path))
    assert result == {"detected": "conventional_commits", "confidence": "high"}


def test_detect_commit_convention_none_when_not_conventional(tmp_path):
    _init_git_repo(tmp_path, ["did a thing", "did another thing"])
    result = detect_commit_convention(str(tmp_path))
    assert result == {"detected": "none", "confidence": "high"}


def test_detect_branch_strategy_trunk_based_with_single_branch(tmp_path):
    _init_git_repo(tmp_path, ["feat: first"])
    result = detect_branch_strategy(str(tmp_path))
    assert result == {"signal": "trunk_based"}


def test_check_pr_templates_true_when_present(tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("template", encoding="utf-8")
    assert check_pr_templates(str(tmp_path)) is True


def test_check_pr_templates_false_when_absent(tmp_path):
    assert check_pr_templates(str(tmp_path)) is False


def test_git_metadata_repo_age_uses_oldest_commit_not_newest(tmp_path):
    import os
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)

    old_env = {**os.environ, "GIT_AUTHOR_DATE": "2020-01-01T00:00:00", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"}
    (tmp_path / "old.txt").write_text("old", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "old commit"], cwd=tmp_path, check=True, capture_output=True, env=old_env)

    (tmp_path / "new.txt").write_text("new", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "new commit"], cwd=tmp_path, check=True, capture_output=True)

    result = git_metadata(str(tmp_path))
    assert result["repo_age_days"] > 365 * 4  # measured from the 2020 commit, not "now"


def test_detect_branch_strategy_does_not_falsely_match_similar_branch_names(tmp_path):
    _init_git_repo(tmp_path, ["feat: first"])
    subprocess.run(["git", "branch", "developer-notes"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "branch", "release-checklist"], cwd=tmp_path, check=True, capture_output=True)
    result = detect_branch_strategy(str(tmp_path))
    assert result["signal"] != "gitflow"


def test_run_git_returns_empty_string_when_repo_path_does_not_exist():
    from stats import _run_git
    result = _run_git("/this/path/does/not/exist", ["log"])
    assert result == ""
