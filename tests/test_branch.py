"""Unit tests for branch and HEAD reference management."""

from pathlib import Path

import pytest

from tinygit.errors import InvalidReferenceError
from tinygit.objects import Commit, ObjectStore
from tinygit.refs import ReferenceManager


def test_reference_manager_init_and_unborn_branch(tmp_path: Path):
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")

    assert refs.get_current_branch() == "main"
    assert refs.is_detached_head() is False
    assert refs.get_head_commit() is None
    assert refs.list_branches() == []


def test_create_list_and_resolve_branches(tmp_path: Path):
    store = ObjectStore(tmp_path)
    c1 = Commit(
        tree_id="a" * 40,
        parents=[],
        author_name="Ron",
        author_email="ron@example.com",
        timestamp="2026-08-09 12:00:00",
        message="Initial commit",
    )
    sha1 = store.write_object(c1)

    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    refs.update_head_commit(sha1)

    assert refs.get_head_commit() == sha1
    assert refs.list_branches() == ["main"]
    assert refs.get_ref_commit("main") == sha1

    # Create new branch
    refs.create_branch("feature", sha1)
    assert sorted(refs.list_branches()) == ["feature", "main"]
    assert refs.get_ref_commit("feature") == sha1

    with pytest.raises(InvalidReferenceError):
        refs.create_branch("feature", sha1)


def test_detached_head(tmp_path: Path):
    store = ObjectStore(tmp_path)
    c1 = Commit(
        tree_id="b" * 40,
        parents=[],
        author_name="Ron",
        author_email="ron@example.com",
        timestamp="2026-08-09 13:00:00",
        message="Detached test",
    )
    sha1 = store.write_object(c1)

    refs = ReferenceManager(tmp_path)
    refs.set_head_to_commit(sha1)

    assert refs.is_detached_head() is True
    assert refs.get_current_branch() is None
    assert refs.get_head_commit() == sha1
