"""Unit tests for the diff engine."""

from pathlib import Path

from tinygit.diff import DiffEngine, FileChange
from tinygit.index import Index
from tinygit.objects import Blob, Commit, ObjectStore
from tinygit.refs import ReferenceManager
from tinygit.working_tree import WorkingTree


def test_unified_diff_text_and_binary():
    c1 = FileChange(
        path="hello.txt",
        old_sha="a" * 40,
        new_sha="b" * 40,
        old_mode="100644",
        new_mode="100644",
        old_content=b"hello\n",
        new_content=b"hello world\n",
    )
    diff_text = c1.to_unified_diff()
    assert "--- a/hello.txt" in diff_text
    assert "+++ b/hello.txt" in diff_text
    assert "-hello" in diff_text
    assert "+hello world" in diff_text

    c2 = FileChange(
        path="bin.dat",
        old_sha="c" * 40,
        new_sha="d" * 40,
        old_mode="100644",
        new_mode="100644",
        old_content=b"\x00old",
        new_content=b"\x00new",
    )
    diff_bin = c2.to_unified_diff()
    assert diff_bin == "Binary files a/bin.dat and b/bin.dat differ\n"


def test_diff_worktree_and_cached(tmp_path: Path):
    store = ObjectStore(tmp_path)
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    index = Index(tmp_path)
    wt = WorkingTree(tmp_path)

    # 1. Commit with f.txt = "line1\n"
    b1 = Blob(b"line1\n")
    sha1 = store.write_object(b1)
    index.add("f.txt", sha1, "100644", size=6)
    wt.write_file("f.txt", b"line1\n")
    tree_sha = wt.build_tree_from_index(index, store)
    c = Commit(tree_id=tree_sha, message="commit 1")
    commit_sha = store.write_object(c)
    refs.update_head_commit(commit_sha)

    # 2. Modify f.txt on disk without staging -> diff_worktree_index has change
    wt.write_file("f.txt", b"line1\nline2\n")
    wt_changes = DiffEngine.diff_worktree_index(tmp_path, index, wt, store)
    assert len(wt_changes) == 1
    assert wt_changes[0].path == "f.txt"
    assert "+line2" in wt_changes[0].to_unified_diff()

    # Cached diff should be empty (nothing staged)
    cached_changes = DiffEngine.diff_index_head(tmp_path, refs, index, wt, store)
    assert len(cached_changes) == 0

    # 3. Stage the modification -> cached diff has change, worktree diff empty
    b2 = Blob(b"line1\nline2\n")
    sha2 = store.write_object(b2)
    index.add("f.txt", sha2, "100644", size=12)

    cached_changes2 = DiffEngine.diff_index_head(tmp_path, refs, index, wt, store)
    assert len(cached_changes2) == 1
    assert cached_changes2[0].path == "f.txt"
    assert "+line2" in cached_changes2[0].to_unified_diff()

    wt_changes2 = DiffEngine.diff_worktree_index(tmp_path, index, wt, store)
    assert len(wt_changes2) == 0
