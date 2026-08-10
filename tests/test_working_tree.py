"""Unit tests for working tree operations, tree building, and checkout safety."""

from pathlib import Path

import pytest

from tinygit.errors import WorkingTreeDirtyError
from tinygit.index import Index
from tinygit.objects import Blob, ObjectStore
from tinygit.working_tree import WorkingTree


def test_build_tree_from_index_and_flatten(tmp_path: Path):
    store = ObjectStore(tmp_path)
    b1 = Blob(b"hello")
    b2 = Blob(b"print('world')")
    sha1 = store.write_object(b1)
    sha2 = store.write_object(b2)

    index = Index(tmp_path)
    index.add("README.md", sha1, "100644", size=5)
    index.add("src/main.py", sha2, "100644", size=14)

    tree_sha = WorkingTree.build_tree_from_index(index, store)
    assert tree_sha

    flat = WorkingTree.get_tree_entries_flat(tree_sha, store)
    assert len(flat) == 2
    assert flat["README.md"] == (sha1, "100644")
    assert flat["src/main.py"] == (sha2, "100644")


def test_checkout_tree_restores_files_and_index(tmp_path: Path):
    store = ObjectStore(tmp_path)
    wt = WorkingTree(tmp_path)
    index = Index(tmp_path)

    b = Blob(b"snapshot content")
    sha = store.write_object(b)
    index.add("test.txt", sha, "100644", size=16)
    tree_sha = WorkingTree.build_tree_from_index(index, store)

    # Perform checkout of tree_sha
    wt.checkout_tree(tree_sha, head_tree_sha=None, index=index, store=store)

    assert (tmp_path / "test.txt").read_bytes() == b"snapshot content"
    assert "test.txt" in index


def test_checkout_safety_prevents_overwrite_of_uncommitted_work(tmp_path: Path):
    store = ObjectStore(tmp_path)
    wt = WorkingTree(tmp_path)
    index = Index(tmp_path)

    # Commit 1 (HEAD) has hello.txt = "hello"
    b1 = Blob(b"hello")
    sha1 = store.write_object(b1)
    index.add("hello.txt", sha1, "100644", size=5)
    tree1 = WorkingTree.build_tree_from_index(index, store)

    # Commit 2 (target) has hello.txt = "foo"
    b2 = Blob(b"foo")
    sha2 = store.write_object(b2)
    index.add("hello.txt", sha2, "100644", size=3)
    tree2 = WorkingTree.build_tree_from_index(index, store)

    # Setup working tree to match tree1
    wt.checkout_tree(tree1, None, index, store, force=True)

    # Now modify hello.txt in the working directory without staging
    wt.write_file("hello.txt", b"hello world - unstaged")

    # Attempting to checkout tree2 should raise WorkingTreeDirtyError!
    with pytest.raises(WorkingTreeDirtyError) as exc_info:
        wt.checkout_tree(tree2, head_tree_sha=tree1, index=index, store=store)

    assert "would be overwritten" in str(exc_info.value)
    # File content must remain unmodified!
    assert (tmp_path / "hello.txt").read_bytes() == b"hello world - unstaged"
