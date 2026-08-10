"""Unit tests for the three-way merge engine, fast-forward merge, and conflict detection."""

from pathlib import Path

import pytest

from tinygit.errors import WorkingTreeDirtyError
from tinygit.index import Index
from tinygit.merge import MergeEngine
from tinygit.objects import Blob, Commit, ObjectStore
from tinygit.refs import ReferenceManager
from tinygit.working_tree import WorkingTree


def test_fast_forward_merge(tmp_path: Path):
    store = ObjectStore(tmp_path)
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    index = Index(tmp_path)
    wt = WorkingTree(tmp_path)

    # Commit 1 on main
    wt.write_file("file.txt", b"v1")
    sha1 = store.write_object(Blob(b"v1"))
    index.add("file.txt", sha1, "100644", size=2)
    t1 = wt.build_tree_from_index(index, store)
    c1 = Commit(tree_id=t1, message="Commit 1")
    c1_sha = store.write_object(c1)
    refs.update_head_commit(c1_sha)

    # Branch feature off main
    refs.create_branch("feature", c1_sha)

    # Commit 2 on feature
    wt.write_file("file.txt", b"v2")
    sha2 = store.write_object(Blob(b"v2"))
    index.add("file.txt", sha2, "100644", size=2)
    t2 = wt.build_tree_from_index(index, store)
    c2 = Commit(tree_id=t2, parents=[c1_sha], message="Commit 2")
    c2_sha = store.write_object(c2)
    refs.update_branch("feature", c2_sha)

    # Reset working tree to main (t1) so main is clean before merge
    wt.checkout_tree(t1, t2, index, store, force=True)

    # Now merge feature into main -> Fast-forward!
    res = MergeEngine.merge("feature", refs, index, wt, store)
    assert res.status == "fast-forward"
    assert res.commit_sha == c2_sha
    assert refs.get_head_commit() == c2_sha
    assert (tmp_path / "file.txt").read_bytes() == b"v2"


def test_clean_3way_merge(tmp_path: Path):
    store = ObjectStore(tmp_path)
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    index = Index(tmp_path)
    wt = WorkingTree(tmp_path)

    # Base commit (LCA) on main
    wt.write_file("common.txt", b"base content")
    sha_base = store.write_object(Blob(b"base content"))
    index.add("common.txt", sha_base, "100644", size=12)
    t0 = wt.build_tree_from_index(index, store)
    c0 = Commit(tree_id=t0, message="Base commit")
    c0_sha = store.write_object(c0)
    refs.update_head_commit(c0_sha)

    # Branch feature
    refs.create_branch("feature", c0_sha)

    # Commit on main: add main.txt
    wt.write_file("main.txt", b"from main")
    sha_main = store.write_object(Blob(b"from main"))
    index.add("main.txt", sha_main, "100644", size=9)
    t_main = wt.build_tree_from_index(index, store)
    c_main = Commit(tree_id=t_main, parents=[c0_sha], message="Main change")
    c_main_sha = store.write_object(c_main)
    refs.update_head_commit(c_main_sha)

    # Commit on feature: add feature.txt
    wt.write_file("feature.txt", b"from feature")
    sha_feat = store.write_object(Blob(b"from feature"))
    index.add("feature.txt", sha_feat, "100644", size=12)
    t_feat = wt.build_tree_from_index(index, store)
    c_feat = Commit(tree_id=t_feat, parents=[c0_sha], message="Feature change")
    c_feat_sha = store.write_object(c_feat)
    refs.update_branch("feature", c_feat_sha)

    # Now checkout main and merge feature -> Clean 3-way merge!
    wt.checkout_tree(t_main, t_feat, index, store, force=True)
    res = MergeEngine.merge("feature", refs, index, wt, store)

    assert res.status == "clean"
    assert res.commit_sha
    merge_c = store.read_commit(res.commit_sha)
    assert len(merge_c.parents) == 2
    assert c_main_sha in merge_c.parents
    assert c_feat_sha in merge_c.parents

    # Verify both files are in working directory
    assert (tmp_path / "main.txt").read_bytes() == b"from main"
    assert (tmp_path / "feature.txt").read_bytes() == b"from feature"
    assert "main.txt" in index
    assert "feature.txt" in index


def test_conflict_3way_merge(tmp_path: Path):
    store = ObjectStore(tmp_path)
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    index = Index(tmp_path)
    wt = WorkingTree(tmp_path)

    # Base commit
    wt.write_file("conflict.txt", b"line 1\nline 2\n")
    sha_base = store.write_object(Blob(b"line 1\nline 2\n"))
    index.add("conflict.txt", sha_base, "100644", size=14)
    t0 = wt.build_tree_from_index(index, store)
    c0 = Commit(tree_id=t0, message="Base")
    c0_sha = store.write_object(c0)
    refs.update_head_commit(c0_sha)

    # Feature branch
    refs.create_branch("feature", c0_sha)

    # Main commit: modify line 1 to "main version"
    wt.write_file("conflict.txt", b"main version\nline 2\n")
    sha_m = store.write_object(Blob(b"main version\nline 2\n"))
    index.add("conflict.txt", sha_m, "100644", size=20)
    t_m = wt.build_tree_from_index(index, store)
    c_m = Commit(tree_id=t_m, parents=[c0_sha], message="Main edit")
    c_m_sha = store.write_object(c_m)
    refs.update_head_commit(c_m_sha)

    # Feature commit: modify line 1 to "feature version"
    wt.write_file("conflict.txt", b"feature version\nline 2\n")
    sha_f = store.write_object(Blob(b"feature version\nline 2\n"))
    index.add("conflict.txt", sha_f, "100644", size=23)
    t_f = wt.build_tree_from_index(index, store)
    c_f = Commit(tree_id=t_f, parents=[c0_sha], message="Feature edit")
    c_f_sha = store.write_object(c_f)
    refs.update_branch("feature", c_f_sha)

    # Reset working tree to main
    wt.checkout_tree(t_m, t_f, index, store, force=True)

    res = MergeEngine.merge("feature", refs, index, wt, store)
    assert res.status == "conflict"
    assert len(res.conflicts) == 1
    assert res.conflicts[0].path == "conflict.txt"

    content = (tmp_path / "conflict.txt").read_bytes().decode("utf-8")
    assert "<<<<<<< HEAD" in content
    assert "main version" in content
    assert "=======" in content
    assert "feature version" in content
    assert ">>>>>>> feature" in content


def test_merge_refused_on_dirty_worktree(tmp_path: Path):
    store = ObjectStore(tmp_path)
    refs = ReferenceManager(tmp_path)
    refs.init_head("main")
    index = Index(tmp_path)
    wt = WorkingTree(tmp_path)

    # Base commit
    wt.write_file("file.txt", b"clean")
    sha1 = store.write_object(Blob(b"clean"))
    index.add("file.txt", sha1, "100644", size=5)
    t0 = wt.build_tree_from_index(index, store)
    c0 = Commit(tree_id=t0, message="Base")
    c0_sha = store.write_object(c0)
    refs.update_head_commit(c0_sha)

    refs.create_branch("feature", c0_sha)

    # Modify working tree without staging
    wt.write_file("file.txt", b"dirty uncommitted")

    with pytest.raises(WorkingTreeDirtyError):
        MergeEngine.merge("feature", refs, index, wt, store)
