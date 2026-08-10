"""Unit tests for content-addressable object storage."""

from pathlib import Path

import pytest

from tinygit.errors import ObjectNotFoundError
from tinygit.objects import Blob, Commit, ObjectStore, Tree, TreeEntry, hash_object


def test_hash_object_blob():
    data = b"hello world\n"
    sha, raw = hash_object("blob", data)
    assert sha  # 40 hex chars
    assert len(sha) == 40
    assert raw.startswith(b"blob 12\0hello world\n")


def test_blob_deduplication_and_immutability(tmp_path: Path):
    store = ObjectStore(tmp_path)
    b1 = Blob(b"hello world")
    b2 = Blob(b"hello world")
    b3 = Blob(b"different content")

    sha1 = store.write_object(b1)
    sha2 = store.write_object(b2)
    sha3 = store.write_object(b3)

    assert sha1 == sha2
    assert sha1 != sha3

    # Check that reading returns identical blob
    loaded = store.read_blob(sha1)
    assert loaded.data == b"hello world"
    assert loaded == b1


def test_tree_serialization_and_parsing(tmp_path: Path):
    entries = [
        TreeEntry(mode="100644", name="b.txt", object_id="a" * 40),
        TreeEntry(mode="040000", name="a_dir", object_id="b" * 40),
    ]
    tree = Tree(entries)
    # Tree should automatically sort by name
    assert tree.entries[0].name == "a_dir"
    assert tree.entries[1].name == "b.txt"

    store = ObjectStore(tmp_path)
    sha = store.write_object(tree)

    loaded_tree = store.read_tree(sha)
    assert len(loaded_tree.entries) == 2
    assert loaded_tree.entries[0].name == "a_dir"
    assert loaded_tree.entries[0].mode == "040000"
    assert loaded_tree.entries[1].name == "b.txt"
    assert loaded_tree.entries[1].mode == "100644"


def test_commit_identity_and_invariants(tmp_path: Path):
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

    # Changing message must change commit ID
    c2 = Commit(
        tree_id=c1.tree_id,
        parents=c1.parents,
        author_name=c1.author_name,
        author_email=c1.author_email,
        timestamp=c1.timestamp,
        message="Modified message",
    )
    sha2 = store.write_object(c2)
    assert sha1 != sha2

    # Changing tree must change commit ID
    c3 = Commit(
        tree_id="b" * 40,
        parents=c1.parents,
        author_name=c1.author_name,
        author_email=c1.author_email,
        timestamp=c1.timestamp,
        message="Initial commit",
    )
    sha3 = store.write_object(c3)
    assert sha1 != sha3

    # Changing parent must change commit ID
    c4 = Commit(
        tree_id=c1.tree_id,
        parents=["c" * 40],
        author_name=c1.author_name,
        author_email=c1.author_email,
        timestamp=c1.timestamp,
        message="Initial commit",
    )
    sha4 = store.write_object(c4)
    assert sha1 != sha4


def test_commit_multiple_parents_for_merge():
    c = Commit(
        tree_id="d" * 40,
        parents=["p" * 40, "q" * 40],
        author_name="Ron",
        author_email="ron@example.com",
        timestamp="2026-08-09 13:00:00",
        message="Merge branch 'feature'",
    )
    data = c.serialize()
    loaded = Commit.parse(data)
    assert len(loaded.parents) == 2
    assert loaded.parents == ["p" * 40, "q" * 40]
    assert loaded.message == "Merge branch 'feature'"
    assert loaded.author_name == "Ron"
    assert loaded.author_email == "ron@example.com"
    assert loaded.timestamp == "2026-08-09 13:00:00"


def test_resolve_prefix(tmp_path: Path):
    store = ObjectStore(tmp_path)
    b = Blob(b"test prefix resolution")
    sha = store.write_object(b)

    short_sha = sha[:7]
    resolved = store.resolve_prefix(short_sha)
    assert resolved == sha

    with pytest.raises(ObjectNotFoundError):
        store.resolve_prefix("0000000")
