from file_walker import WalkedFile, classify_language, walk_files


def _make_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "src" / "app.js").write_text("console.log('hi')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("// vendored\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_classify_language_known_extensions():
    assert classify_language("src/main.py") == "python"
    assert classify_language("src/app.js") == "javascript"
    assert classify_language("README.md") == "markdown"


def test_classify_language_unknown_extension_returns_none():
    assert classify_language("image.png") is None


def test_walk_files_finds_all_non_excluded_files(tmp_path):
    repo = _make_repo(tmp_path)
    files = walk_files(str(repo), exclude=["node_modules/**"])
    paths = {f.path for f in files}
    assert "src/main.py" in paths
    assert "src/app.js" in paths
    assert "README.md" in paths
    assert "image.png" in paths  # walked, just language=None
    assert not any(p.startswith("node_modules/") for p in paths)


def test_walk_files_classifies_language_per_file(tmp_path):
    repo = _make_repo(tmp_path)
    files = walk_files(str(repo), exclude=["node_modules/**"])
    by_path = {f.path: f for f in files}
    assert by_path["src/main.py"] == WalkedFile(path="src/main.py", language="python")
    assert by_path["image.png"].language is None


def test_walk_files_language_allowlist_filters_results(tmp_path):
    repo = _make_repo(tmp_path)
    files = walk_files(str(repo), exclude=["node_modules/**"], languages=["python"])
    paths = {f.path for f in files}
    assert paths == {"src/main.py"}
