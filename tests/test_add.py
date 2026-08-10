"""Unit tests for staging files and deletions (add command)."""

from pathlib import Path

import pytest

from tinygit.errors import InvalidPathError
from tinygit.repository import Repository


def test_add_files_directories_and_deletions(tmp_path: Path):
    repo = Repository.init(tmp_path)

    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("print('test')", encoding="utf-8")

    staged = repo.add(["file.txt", "src"])
    assert "file.txt" in staged
    assert "src/main.py" in staged
    assert len(repo.index) == 2

    # Commit so files are in HEAD
    repo.commit("Init commit")

    # Now modify file.txt and delete src/main.py from disk
    (tmp_path / "file.txt").write_text("hello modified", encoding="utf-8")
    (src_dir / "main.py").unlink()

    staged_mod = repo.add(["."])
    assert "file.txt" in staged_mod
    assert "src/main.py" in staged_mod
    assert "src/main.py" not in repo.index  # deletion staged!
    assert len(repo.index) == 1


def test_add_missing_path_error(tmp_path: Path):
    repo = Repository.init(tmp_path)
    with pytest.raises(InvalidPathError):
        repo.add(["nonexistent.txt"])
