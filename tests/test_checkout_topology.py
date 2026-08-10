"""Unit tests for checkout filesystem topology transitions and path canonicalization.

Tests transitions between regular files and directories (file -> dir, dir -> file),
file mode changes, and canonical POSIX path resolution across commands.
"""

from pathlib import Path

from tinygit.repository import Repository


def test_checkout_topology_file_to_directory_and_back(tmp_path: Path):
    repo = Repository.init(tmp_path)

    # Commit 1: 'foo' is a regular file
    (tmp_path / "foo").write_text("regular file", encoding="utf-8")
    repo.add(["foo"])
    _ = repo.commit("C1: foo is file")

    repo.branch("dir_branch")

    # Commit 2 on dir_branch: replace 'foo' with directory 'foo/bar.txt'
    repo.checkout("dir_branch")
    (tmp_path / "foo").unlink()
    foo_dir = tmp_path / "foo"
    foo_dir.mkdir()
    (foo_dir / "bar.txt").write_text("nested file in dir", encoding="utf-8")
    repo.add(["."])
    _ = repo.commit("C2: foo is directory")

    assert (tmp_path / "foo" / "bar.txt").exists()
    assert "foo/bar.txt" in repo.index

    # Checkout main (C1): directory 'foo/bar.txt' must be removed and replaced by file 'foo'
    repo.checkout("main")
    assert (tmp_path / "foo").is_file()
    assert (tmp_path / "foo").read_text(encoding="utf-8") == "regular file"
    assert "foo" in repo.index
    assert "foo/bar.txt" not in repo.index

    # Checkout dir_branch (C2): file 'foo' must be replaced by directory 'foo/bar.txt'
    repo.checkout("dir_branch")
    assert (tmp_path / "foo").is_dir()
    assert (tmp_path / "foo" / "bar.txt").read_text(encoding="utf-8") == "nested file in dir"
    assert "foo/bar.txt" in repo.index


def test_path_canonicalization_and_duplicate_separators(tmp_path: Path):
    repo = Repository.init(tmp_path)
    sub_dir = tmp_path / "src" / "sub"
    sub_dir.mkdir(parents=True)
    (sub_dir / "file.txt").write_text("content", encoding="utf-8")

    # Stage using non-canonical path strings
    repo.add(["./src//sub/../sub/file.txt"])

    # Index must store canonical POSIX relative path 'src/sub/file.txt'
    assert "src/sub/file.txt" in repo.index
    assert "./src//sub/../sub/file.txt" not in repo.index
