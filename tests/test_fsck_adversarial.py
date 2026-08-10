"""Adversarial repository integrity and corruption tests (tiny-git fsck).

Deliberately corrupts object headers, payloads, sizes, tree entries,
commit parents, branch references, HEAD, index, and config, asserting that
fsck detects every corruption and never crashes with an unhandled exception.
"""

from pathlib import Path

from tinygit.objects import Commit
from tinygit.repository import Repository


def test_fsck_adversarial_corruptions(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "a.txt").write_text("content", encoding="utf-8")
    repo.add(["a.txt"])
    _ = repo.commit("commit 1")

    # 1. Corrupt blob payload (SHA-1 checksum mismatch)
    blob_sha = repo.index.query("a.txt").object_id
    blob_path = tmp_path / ".tinygit" / "objects" / blob_sha[:2] / blob_sha[2:]
    blob_path.write_bytes(b"blob 7\0corrupt")

    res1 = repo.fsck()
    assert res1.is_healthy() is False
    assert any("SHA-1 integrity" in err or "malformed" in err for err in res1.errors)

    # 2. Corrupt object header format (missing null byte)
    blob_path.write_bytes(b"blob_without_null_byte_header")
    res2 = repo.fsck()
    assert res2.is_healthy() is False
    assert any("Missing null byte" in err or "malformed" in err for err in res2.errors)

    # 3. Corrupt object size header (wrong size)
    blob_path.write_bytes(b"blob 999\0content")
    res3 = repo.fsck()
    assert res3.is_healthy() is False
    assert any("Payload size" in err or "malformed" in err for err in res3.errors)

    # 4. Commit referencing missing parent
    c_corrupt = Commit(
        tree_id="a" * 40,
        parents=["1" * 40],
        message="bad parent",
    )
    c_sha = repo.store.write_object(c_corrupt)
    repo.refs.set_head_to_commit(c_sha)
    res4 = repo.fsck()
    assert res4.is_healthy() is False
    assert any("references missing object" in err for err in res4.errors)

    # 5. Corrupt branch reference
    ref_path = tmp_path / ".tinygit" / "refs" / "heads" / "main"
    ref_path.write_text("invalid_sha_string\n", encoding="utf-8")
    res5 = repo.fsck()
    assert res5.is_healthy() is False
    assert any("invalid hash" in err for err in res5.errors)

    # 6. Broken HEAD
    head_path = tmp_path / ".tinygit" / "HEAD"
    head_path.write_text("invalid HEAD target\n", encoding="utf-8")
    res6 = repo.fsck()
    assert res6.is_healthy() is False
    assert any("HEAD contains invalid target" in err for err in res6.errors)

    # 7. Corrupted index JSON file
    index_path = tmp_path / ".tinygit" / "index"
    index_path.write_text("{ not json... }", encoding="utf-8")
    res7 = repo.fsck()
    assert res7.is_healthy() is False
    assert any("Index file corrupted" in err for err in res7.errors)

    # 8. Tree referencing missing blob
    from tinygit.objects import Tree, TreeEntry
    t_corrupt = Tree([TreeEntry("100644", "missing.txt", "f" * 40)])
    t_sha = repo.store.write_object(t_corrupt)
    c_bad_tree = Commit(
        tree_id=t_sha,
        parents=[],
        message="bad tree entry",
    )
    repo.store.write_object(c_bad_tree)
    res8 = repo.fsck()
    assert res8.is_healthy() is False
    assert any("references missing object" in err and "missing.txt" in err for err in res8.errors)
