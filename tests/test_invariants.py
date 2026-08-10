"""Property and invariant testing for Tiny Git core data models and operations."""

from pathlib import Path

from tinygit.objects import Blob, Commit, ObjectStore
from tinygit.repository import Repository


def test_invariant_object_identity_and_mutation(tmp_path: Path):
    store = ObjectStore(tmp_path)
    b1 = Blob(b"invariant content")
    b2 = Blob(b"invariant content")
    b3 = Blob(b"mutated content")

    sha1 = store.write_object(b1)
    sha2 = store.write_object(b2)
    sha3 = store.write_object(b3)

    # Same content -> same object ID
    assert sha1 == sha2
    # Different content -> different object ID
    assert sha1 != sha3


def test_invariant_commit_identity(tmp_path: Path):
    store = ObjectStore(tmp_path)
    c1 = Commit(
        tree_id="a" * 40,
        parents=[],
        author_name="Ron",
        author_email="ron@example.com",
        timestamp="2026-08-09 10:00:00",
        message="Message A",
    )
    c2 = Commit(
        tree_id="a" * 40,
        parents=[],
        author_name="Ron",
        author_email="ron@example.com",
        timestamp="2026-08-09 10:00:00",
        message="Message B",
    )
    sha1 = store.write_object(c1)
    sha2 = store.write_object(c2)

    # Changing message -> different commit ID
    assert sha1 != sha2


def test_invariant_branch_isolation(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("base", encoding="utf-8")
    repo.add(["f.txt"])
    c1 = repo.commit("c1")

    # Branch feature off main
    repo.branch("feature")

    # Commit on main
    (tmp_path / "f.txt").write_text("main update", encoding="utf-8")
    repo.add(["f.txt"])
    c_main = repo.commit("main update")

    # Creating and committing on main must not mutate feature ref!
    assert repo.refs.get_ref_commit("feature") == c1
    assert repo.refs.get_ref_commit("main") == c_main

    # Checkout feature and verify state
    repo.checkout("feature")
    assert repo.refs.get_head_commit() == c1
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "base"

    # Commit on feature must not mutate main ref!
    (tmp_path / "f.txt").write_text("feature update", encoding="utf-8")
    repo.add(["f.txt"])
    c_feat = repo.commit("feature update")
    assert repo.refs.get_ref_commit("main") == c_main
    assert repo.refs.get_ref_commit("feature") == c_feat


def test_invariant_checkout_reproduces_snapshot(tmp_path: Path):
    repo = Repository.init(tmp_path)
    # Snapshot A: file_a = "1", file_b = "1"
    (tmp_path / "file_a.txt").write_text("1", encoding="utf-8")
    (tmp_path / "file_b.txt").write_text("1", encoding="utf-8")
    repo.add(["."])
    c_a = repo.commit("Snapshot A")

    # Snapshot B: file_a = "2", file_c = "3" (file_b deleted)
    (tmp_path / "file_a.txt").write_text("2", encoding="utf-8")
    (tmp_path / "file_b.txt").unlink()
    (tmp_path / "file_c.txt").write_text("3", encoding="utf-8")
    repo.add(["."])
    c_b = repo.commit("Snapshot B")

    # Checking out Snapshot A must reproduce exact Snapshot A on disk and index
    repo.checkout(c_a)
    assert (tmp_path / "file_a.txt").read_text(encoding="utf-8") == "1"
    assert (tmp_path / "file_b.txt").read_text(encoding="utf-8") == "1"
    assert not (tmp_path / "file_c.txt").exists()
    assert "file_a.txt" in repo.index
    assert "file_b.txt" in repo.index
    assert "file_c.txt" not in repo.index

    # Checking out Snapshot B must reproduce exact Snapshot B on disk and index
    repo.checkout(c_b)
    assert (tmp_path / "file_a.txt").read_text(encoding="utf-8") == "2"
    assert not (tmp_path / "file_b.txt").exists()
    assert (tmp_path / "file_c.txt").read_text(encoding="utf-8") == "3"


def test_invariant_clean_merge_union_of_changes(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "base.txt").write_text("common", encoding="utf-8")
    repo.add(["base.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    # Commit on b1: add a.txt
    repo.checkout("b1")
    (tmp_path / "a.txt").write_text("from b1", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("Add a.txt")

    # Commit on b2: add b.txt
    repo.checkout("b2")
    (tmp_path / "b.txt").write_text("from b2", encoding="utf-8")
    repo.add(["b.txt"])
    repo.commit("Add b.txt")

    # Merge b1 into b2
    res = repo.merge("b1")
    assert res.is_success()

    # The clean merge must contain the union of non-conflicting changes from both branches
    assert (tmp_path / "base.txt").read_text(encoding="utf-8") == "common"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "from b1"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "from b2"
    assert len(repo.index) == 3
