"""Known test vectors and Git compatibility verification tests.

Verifies that SHA-1 digests for known standard blob contents and tree/commit
payloads match known reference values deterministically.
"""

from tinygit.objects import Commit, Tree, TreeEntry, hash_object


def test_git_compatibility_known_blob_vectors():
    # Standard Git empty blob SHA-1
    sha_empty, raw_empty = hash_object("blob", b"")
    assert sha_empty == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert raw_empty == b"blob 0\0"

    # Standard Git "hello\n" blob SHA-1
    sha_hello, raw_hello = hash_object("blob", b"hello\n")
    assert sha_hello == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert raw_hello == b"blob 6\0hello\n"

    # Standard Git "test content\n" blob SHA-1
    sha_test, _ = hash_object("blob", b"test content\n")
    assert sha_test == "d670460b4b4aece5915caf5c68d12f560a9fe3e4"


def test_git_compatibility_tree_and_commit_determinism():
    entries = [
        TreeEntry("100644", "hello.txt", "ce013625030ba8dba906f756967f9e9ca394464a"),
        TreeEntry("040000", "src", "4b825dc642cb6eb9a060e54bf8d69288fbee4904"),
    ]
    tree = Tree(entries)
    sha_t1, _ = hash_object("tree", tree.serialize())

    # Hashing the same entries in reverse input order must produce the identical SHA-1
    tree2 = Tree(list(reversed(entries)))
    sha_t2, _ = hash_object("tree", tree2.serialize())
    assert sha_t1 == sha_t2

    c = Commit(
        tree_id=sha_t1,
        parents=["ce013625030ba8dba906f756967f9e9ca394464a"],
        author_name="Ron",
        author_email="ron@example.com",
        timestamp="2026-08-10 12:00:00",
        message="Deterministic commit test\n",
    )
    sha_c1, raw_c1 = hash_object("commit", c.serialize())
    sha_c2, _ = hash_object("commit", c.serialize())
    assert sha_c1 == sha_c2
    assert b"tree " in raw_c1
    assert b"parent " in raw_c1
    assert b"author Ron <ron@example.com> 2026-08-10 12:00:00" in raw_c1
