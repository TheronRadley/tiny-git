"""Unit tests for commit creation and history chaining."""

from pathlib import Path

import pytest

from tinygit.errors import NothingToCommitError
from tinygit.repository import Repository


def test_commit_chaining_and_empty_refusal(tmp_path: Path):
    repo = Repository.init(tmp_path)

    with pytest.raises(NothingToCommitError):
        repo.commit("Empty commit without allow_empty")

    c1 = repo.commit("Allow empty commit", allow_empty=True)
    assert c1
    assert repo.refs.get_head_commit() == c1

    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    repo.add(["a.txt"])
    c2 = repo.commit("Add a.txt")
    assert c2 != c1

    c2_obj = repo.store.read_commit(c2)
    assert c2_obj.parents == [c1]
    assert repo.refs.get_head_commit() == c2

    # Attempting to commit without new staged changes should raise NothingToCommitError
    with pytest.raises(NothingToCommitError):
        repo.commit("No new changes")
