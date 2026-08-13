from file_walker import WalkedFile
from stats import count_files_by_language, count_loc_by_language, count_tests


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
