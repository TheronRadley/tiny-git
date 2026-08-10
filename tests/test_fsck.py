"""Unit tests for repository integrity checker (tiny-git fsck)."""

from pathlib import Path

from tinygit.fsck import IntegrityChecker
from tinygit.index import Index
from tinygit.objects import Commit, ObjectStore
from tinygit.refs import ReferenceManager
from tinygit.repository import Repository


def test_fsck_clean_repo(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")
    repo.add(["hello.txt"])
    repo.commit("c1")

    res = IntegrityChecker.check(tmp_path, repo.store, repo.refs, repo.index)
    assert res.is_healthy()
    assert res.objects_checked >= 3  # blob, tree, commit
    assert res.refs_checked == 1
    assert res.head_valid is True
    assert res.index_valid is True
    assert res.commit_graph_valid is True

    formatted = res.format()
    assert "Checking repository..." in formatted
    assert "Repository is healthy." in formatted


def test_fsck_detects_missing_commit_parent_and_corrupt_ref(tmp_path: Path):
    _ = Repository.init(tmp_path)
    store = ObjectStore(tmp_path)
    refs = ReferenceManager(tmp_path)
    index = Index(tmp_path)

    # Create commit referencing nonexistent parent
    c = Commit(
        tree_id="a" * 40,
        parents=["0" * 40],
        message="Corrupt commit",
    )
    c_sha = store.write_object(c)
    refs.set_head_to_commit(c_sha)

    res = IntegrityChecker.check(tmp_path, store, refs, index)
    assert res.is_healthy() is False
    assert any("references missing object" in err for err in res.errors)
