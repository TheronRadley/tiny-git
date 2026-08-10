"""Unit tests for checkout command and branch switching."""

from pathlib import Path

import pytest

from tinygit.errors import WorkingTreeDirtyError
from tinygit.repository import Repository


def test_checkout_branch_and_detached_head(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("v1", encoding="utf-8")
    repo.add(["f.txt"])
    _ = repo.commit("commit 1")

    repo.branch("feature")
    repo.checkout("feature")
    assert repo.refs.get_current_branch() == "feature"

    (tmp_path / "f.txt").write_text("v2", encoding="utf-8")
    repo.add(["f.txt"])
    c2 = repo.commit("commit 2 on feature")

    # Checkout back to main
    repo.checkout("main")
    assert repo.refs.get_current_branch() == "main"
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "v1"

    # Checkout commit SHA -> detached HEAD
    repo.checkout(c2[:7])
    assert repo.refs.is_detached_head() is True
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "v2"


def test_checkout_abort_on_dirty_worktree(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    repo.branch("feature")
    repo.checkout("feature")
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c2")

    repo.checkout("main")
    # Modify a.txt in working tree without committing
    (tmp_path / "a.txt").write_text("unstaged edit", encoding="utf-8")

    with pytest.raises(WorkingTreeDirtyError):
        repo.checkout("feature")

    # Verify user edit was not destroyed
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "unstaged edit"
