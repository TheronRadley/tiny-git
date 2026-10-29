"""Regression tests: tree entry validation and checkout safety (audit "Fix first" #2-#4).

Three defects are covered here:

1. Tree entry names were not validated, so a crafted tree could materialise an
   executable ``.tinygit/hooks/post-checkout``. Worse, the checkout *raised*
   partway through, after the hook had already been written and the working tree
   had already been emptied.
2. ``checkout_tree`` rewrote every file in the target snapshot, including files
   identical in both snapshots, destroying unstaged edits and deleting newly
   staged files when the target was the branch already checked out.
3. An unreadable tree flattened to an empty mapping, which reads as "this
   snapshot has no files" -- so checking out a commit with a missing tree deleted
   every tracked file and then moved HEAD onto the broken commit.
"""

from pathlib import Path

import pytest

from tinygit.errors import InvalidObjectError, ObjectNotFoundError
from tinygit.objects import Blob, Tree, TreeEntry, hash_object
from tinygit.repository import Repository
from tinygit.utils import atomic_write_file


def _raw_tree(repo: Repository, entries: list[tuple[str, str, str]]) -> str:
    """Write a raw tree object straight to disk, bypassing Tree validation."""
    payload = "".join(f"{mode} {sha} {name}\n" for mode, sha, name in entries).encode("utf-8")
    sha, raw = hash_object("tree", payload)
    atomic_write_file(repo.store.objects_dir / sha[:2] / sha[2:], raw)
    return sha


def _raw_commit(repo: Repository, tree_sha: str) -> str:
    payload = f"tree {tree_sha}\nauthor T <t@t.t> 2026-01-01 00:00:00\n\ncrafted\n".encode()
    sha, raw = hash_object("commit", payload)
    atomic_write_file(repo.store.objects_dir / sha[:2] / sha[2:], raw)
    return sha


def _repo_with_commit(tmp_path: Path) -> Repository:
    repo = Repository.init(tmp_path)
    repo.config.set("user.name", "T")
    repo.config.set("user.email", "t@t.t")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    return repo


# --------------------------------------------------------------------------
# 1. Tree entry validation
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_name",
    [
        ".tinygit/hooks/post-checkout",
        ".git/hooks/post-checkout",
        "sub/../../.tinygit/config",
        "a/b",
        "a\\b",
        "",
        ".",
        "..",
        "evil\nname",
        "tab\tname",
        "nul\x00name",
    ],
)
def test_tree_rejects_unsafe_entry_names(bad_name: str):
    with pytest.raises(InvalidObjectError):
        Tree([TreeEntry(mode="100644", name=bad_name, object_id="a" * 40)])


def test_tree_rejects_duplicate_entries():
    with pytest.raises(InvalidObjectError):
        Tree(
            [
                TreeEntry(mode="100644", name="dup.txt", object_id="a" * 40),
                TreeEntry(mode="100644", name="dup.txt", object_id="b" * 40),
            ]
        )


def test_tree_rejects_unsupported_mode_and_bad_id():
    with pytest.raises(InvalidObjectError):
        Tree([TreeEntry(mode="120000", name="link", object_id="a" * 40)])
    with pytest.raises(InvalidObjectError):
        Tree([TreeEntry(mode="100644", name="f", object_id="not-a-sha")])


@pytest.mark.parametrize(
    "crafted_name",
    [".tinygit/hooks/post-checkout", ".tinygit/config", "sub/../../.tinygit/x", "", "..", "a/b"],
)
def test_crafted_tree_cannot_plant_files_on_checkout(tmp_path: Path, crafted_name: str):
    """A malicious tree written directly to the object store must not materialise."""
    repo = _repo_with_commit(tmp_path)
    blob_sha = repo.store.write_object(Blob(b"#!/bin/sh\necho PWNED\n"))
    tree_sha = _raw_tree(repo, [("100755", blob_sha, crafted_name)])
    crafted_commit = _raw_commit(repo, tree_sha)

    hook_path = repo.tinygit_dir / "hooks" / "post-checkout"
    head_before = repo.refs.get_head_commit()

    with pytest.raises((InvalidObjectError, ObjectNotFoundError)):
        repo.checkout(crafted_commit)

    # Nothing planted, nothing destroyed, HEAD unmoved.
    assert not hook_path.exists()
    assert (tmp_path / "a.txt").exists()
    assert repo.refs.get_head_commit() == head_before
    assert (repo.tinygit_dir / "config").read_text(encoding="utf-8").startswith("[core]")


# --------------------------------------------------------------------------
# 2. checkout_tree preserves uncommitted work
# --------------------------------------------------------------------------
def test_checkout_of_current_branch_preserves_unstaged_edits(tmp_path: Path):
    repo = _repo_with_commit(tmp_path)
    (tmp_path / "a.txt").write_text("MY UNSTAGED EDIT\n", encoding="utf-8")

    repo.checkout(repo.refs.get_current_branch())

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "MY UNSTAGED EDIT\n"


def test_checkout_of_current_branch_keeps_newly_staged_file(tmp_path: Path):
    repo = _repo_with_commit(tmp_path)
    (tmp_path / "new.txt").write_text("brand new\n", encoding="utf-8")
    repo.add(["new.txt"])

    repo.checkout(repo.refs.get_current_branch())

    assert (tmp_path / "new.txt").exists()
    assert "new.txt" in repo.index


def test_checkout_restores_tracked_file_deleted_from_disk(tmp_path: Path):
    """Preserving local edits must not mean leaving a deleted file deleted."""
    repo = _repo_with_commit(tmp_path)
    committed = repo.refs.get_head_commit()
    (tmp_path / "a.txt").unlink()

    repo.checkout(committed)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a\n"


def test_checkout_refuses_to_clobber_unstaged_edits_on_branch_switch(tmp_path: Path):
    from tinygit.errors import WorkingTreeDirtyError

    repo = _repo_with_commit(tmp_path)
    (tmp_path / "a.txt").write_text("main edit\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("main edit")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "a.txt").write_text("feat edit\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("feat edit")

    repo.checkout("main")
    (tmp_path / "a.txt").write_text("UNCOMMITTED\n", encoding="utf-8")

    with pytest.raises(WorkingTreeDirtyError):
        repo.checkout("feat")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "UNCOMMITTED\n"


# --------------------------------------------------------------------------
# 3. Unreadable trees are not empty snapshots
# --------------------------------------------------------------------------
def test_checkout_of_commit_with_missing_tree_is_refused(tmp_path: Path):
    repo = _repo_with_commit(tmp_path)
    head_before = repo.refs.get_head_commit()
    broken_commit = _raw_commit(repo, "d" * 40)

    with pytest.raises(ObjectNotFoundError):
        repo.checkout(broken_commit)

    assert (tmp_path / "a.txt").exists(), "tracked file must not be deleted"
    assert repo.refs.get_head_commit() == head_before, "HEAD must not move to the broken commit"
    assert "a.txt" in repo.index


def test_flattening_an_unreadable_tree_raises(tmp_path: Path):
    from tinygit.working_tree import WorkingTree

    repo = _repo_with_commit(tmp_path)
    wt = WorkingTree(repo.repo_root)
    with pytest.raises(ObjectNotFoundError):
        wt.get_tree_entries_flat("d" * 40, repo.store)


def test_flattening_an_absent_tree_is_empty(tmp_path: Path):
    """An unborn branch legitimately has no tree; that is not an error."""
    from tinygit.working_tree import WorkingTree

    repo = Repository.init(tmp_path)
    assert WorkingTree(repo.repo_root).get_tree_entries_flat(None, repo.store) == {}


# --------------------------------------------------------------------------
# Phase separation: a failed checkout mutates nothing
# --------------------------------------------------------------------------
def test_failed_checkout_leaves_working_tree_and_index_untouched(tmp_path: Path):
    """Validation must complete before the first byte on disk changes."""
    repo = _repo_with_commit(tmp_path)
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    repo.add(["b.txt"])
    repo.commit("c2")

    good_blob = repo.store.write_object(Blob(b"ok\n"))
    # Second entry points at an object that does not exist.
    tree_sha = _raw_tree(
        repo,
        [("100644", good_blob, "a.txt"), ("100644", "e" * 40, "zzz.txt")],
    )
    crafted = _raw_commit(repo, tree_sha)

    index_before = {e.path for e in repo.index.list_entries()}
    with pytest.raises(ObjectNotFoundError):
        repo.checkout(crafted)

    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()
    assert {e.path for e in repo.index.list_entries()} == index_before
