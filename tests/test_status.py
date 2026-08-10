"""Unit tests for the status comparison engine."""

from pathlib import Path

from tinygit.index import Index
from tinygit.objects import Blob, Commit, ObjectStore
from tinygit.refs import ReferenceManager
from tinygit.status import StatusService
from tinygit.working_tree import WorkingTree


def test_status_clean_unborn(tmp_path: Path):
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    index = Index(tmp_path)
    wt = WorkingTree(tmp_path)
    store = ObjectStore(tmp_path)

    res = StatusService.get_status(tmp_path, refs, index, wt, store)
    assert res.is_clean()
    assert "On branch main" in res.format()
    assert "No commits yet" in res.format()


def test_status_staged_unstaged_untracked(tmp_path: Path):
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    index = Index(tmp_path)
    wt = WorkingTree(tmp_path)
    store = ObjectStore(tmp_path)

    # 1. Create a commit with README.md = "old"
    b1 = Blob(b"old")
    sha1 = store.write_object(b1)
    index.add("README.md", sha1, "100644", size=3)
    tree_sha = wt.build_tree_from_index(index, store)
    c1 = Commit(tree_id=tree_sha, message="Init")
    commit_sha = store.write_object(c1)
    refs.update_head_commit(commit_sha)

    # 2. Add new file to disk and stage it -> staged_added
    b2 = Blob(b"staged content")
    sha2 = store.write_object(b2)
    wt.write_file("new_file.py", b"staged content")
    index.add("new_file.py", sha2, "100644", size=14)

    # 3. Modify README.md on disk without staging -> unstaged_modified
    wt.write_file("README.md", b"new unstaged content")

    # 4. Add an untracked file to disk
    wt.write_file("notes.txt", b"random notes")

    res = StatusService.get_status(tmp_path, refs, index, wt, store)

    assert "new_file.py" in res.staged_added
    assert "README.md" in res.unstaged_modified
    assert "notes.txt" in res.untracked
    assert res.is_clean() is False
    formatted = res.format()
    assert "Changes to be committed:" in formatted
    assert "Changes not staged for commit:" in formatted
    assert "Untracked files:" in formatted
