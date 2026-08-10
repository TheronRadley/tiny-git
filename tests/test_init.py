"""Unit tests for repository initialization and detection."""

from pathlib import Path

import pytest

from tinygit.errors import RepositoryAlreadyExistsError, RepositoryNotFoundError
from tinygit.repository import Repository


def test_repository_init_creates_structure(tmp_path: Path):
    _ = Repository.init(tmp_path)
    tinygit_dir = tmp_path / ".tinygit"

    assert tinygit_dir.is_dir()
    assert (tinygit_dir / "objects").is_dir()
    assert (tinygit_dir / "refs" / "heads").is_dir()
    assert (tinygit_dir / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert (tinygit_dir / "index").is_file()
    assert (tinygit_dir / "config").is_file()

    with pytest.raises(RepositoryAlreadyExistsError):
        Repository.init(tmp_path)


def test_find_repo_from_subdir(tmp_path: Path):
    Repository.init(tmp_path)
    sub = tmp_path / "src" / "nested"
    sub.mkdir(parents=True)

    found = Repository.find_repo(sub)
    assert found.repo_root == tmp_path

    with pytest.raises(RepositoryNotFoundError):
        Repository.find_repo(tmp_path.parent)
