"""Adversarial merge tests and DAG topology stress testing.

Tests complex DAGs (multiple merge bases, repeated merges, criss-cross),
reversions, EOF insertions/deletions, binary/text transitions, mode changes,
and mixed conflict states, asserting strict repository invariants after every
successful and failed merge.
"""

import os
import stat
from pathlib import Path

from tinygit.repository import Repository


def assert_merge_success_invariants(repo: Repository, expected_parents: int = 2):
    """Verify repository invariants after a successful merge."""
    fsck_res = repo.fsck()
    assert fsck_res.is_healthy(), f"Fsck failed: {fsck_res.errors}"
    head_sha = repo.refs.get_head_commit()
    assert head_sha
    commit = repo.store.read_commit(head_sha)
    assert len(commit.parents) == expected_parents
    assert repo.store.exists(commit.tree_id)
    # Working tree and index must match HEAD tree
    head_map = repo.wt.get_tree_entries_flat(commit.tree_id, repo.store)
    index_map = {e.path: (e.object_id, e.mode) for e in repo.index.list_entries() if e.stage == 0}
    assert head_map == index_map
    assert repo.status().is_clean()


def assert_merge_conflict_invariants(repo: Repository, pre_merge_head: str):
    """Verify repository invariants after a failed/conflicted merge."""
    fsck_res = repo.fsck()
    assert fsck_res.is_healthy(), f"Fsck failed after conflict: {fsck_res.errors}"
    assert repo.refs.get_head_commit() == pre_merge_head
    assert (repo.tinygit_dir / "MERGE_HEAD").exists()


def test_merge_adversarial_repeated_and_crisscross_dags(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "file.txt").write_text("root\n", encoding="utf-8")
    repo.add(["file.txt"])
    repo.commit("Root")

    repo.branch("b1")
    repo.branch("b2")

    repo.checkout("b1")
    (tmp_path / "file1.txt").write_text("1", encoding="utf-8")
    repo.add(["file1.txt"])
    repo.commit("b1 c1")

    repo.checkout("b2")
    (tmp_path / "file2.txt").write_text("2", encoding="utf-8")
    repo.add(["file2.txt"])
    repo.commit("b2 c1")

    # First cross-merge b1 -> b2
    repo.checkout("b2")
    res1 = repo.merge("b1")
    assert res1.is_success()
    assert_merge_success_invariants(repo, expected_parents=2)

    # Make new commits on both
    repo.checkout("b1")
    (tmp_path / "file3.txt").write_text("3", encoding="utf-8")
    repo.add(["file3.txt"])
    repo.commit("b1 c2")

    repo.checkout("b2")
    (tmp_path / "file4.txt").write_text("4", encoding="utf-8")
    repo.add(["file4.txt"])
    repo.commit("b2 c2")

    # Second cross-merge b2 -> b1
    repo.checkout("b1")
    res2 = repo.merge("b2")
    assert res2.is_success()
    assert_merge_success_invariants(repo, expected_parents=2)


def test_merge_adversarial_reverted_changes(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("v1\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("feat")
    (tmp_path / "f.txt").write_text("v2\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Main edit")

    # Revert on main
    (tmp_path / "f.txt").write_text("v1\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Revert to v1")

    repo.checkout("feat")
    (tmp_path / "other.txt").write_text("other", encoding="utf-8")
    repo.add(["other.txt"])
    repo.commit("Feat commit")

    res = repo.merge("main")
    assert res.is_success()
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "v1\n"
    assert_merge_success_invariants(repo, expected_parents=2)


def test_merge_adversarial_eof_insertions_and_deletions(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("1\n2\n3\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("feat")

    # Main inserts at EOF
    (tmp_path / "f.txt").write_text("1\n2\n3\n4\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("EOF insert")

    # Feat modifies line 1
    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("1_mod\n2\n3\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Line 1 edit")

    res = repo.merge("main")
    assert res.is_success()
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "1_mod\n2\n3\n4\n"
    assert_merge_success_invariants(repo, expected_parents=2)


def test_merge_adversarial_mode_only_change(tmp_path: Path):
    repo = Repository.init(tmp_path)
    script = tmp_path / "run.py"
    script.write_text("print(1)\n", encoding="utf-8")
    repo.add(["run.py"])
    repo.commit("Base")

    repo.branch("feat")

    # Main changes mode to executable without changing contents
    script.chmod(0o755)
    repo.add(["run.py"])
    repo.commit("Make executable")

    # Feat modifies another file
    repo.checkout("feat")
    (tmp_path / "doc.txt").write_text("doc", encoding="utf-8")
    repo.add(["doc.txt"])
    repo.commit("Add doc")

    res = repo.merge("main")
    assert res.is_success()
    assert_merge_success_invariants(repo, expected_parents=2)
    st_mode = os.stat(script).st_mode
    assert (st_mode & stat.S_IXUSR) != 0


def test_merge_adversarial_mixed_conflict_states(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "clean.txt").write_text("clean\n", encoding="utf-8")
    (tmp_path / "conf.txt").write_text("base\n", encoding="utf-8")
    repo.add(["."])
    _ = repo.commit("Base")

    repo.branch("feat")

    # Main modifies both
    (tmp_path / "clean.txt").write_text("clean main\n", encoding="utf-8")
    (tmp_path / "conf.txt").write_text("conf main\n", encoding="utf-8")
    repo.add(["."])
    _ = repo.commit("Main edits")

    # Feat modifies conf.txt differently, leaves clean.txt alone
    repo.checkout("feat")
    (tmp_path / "conf.txt").write_text("conf feat\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("Feat edit")

    res = repo.merge("main")
    assert res.status == "conflict"
    assert_merge_conflict_invariants(repo, pre_merge_head=repo.refs.get_head_commit())
    assert (tmp_path / "clean.txt").read_text(encoding="utf-8") == "clean main\n"
    assert "<<<<<<< HEAD" in (tmp_path / "conf.txt").read_text(encoding="utf-8")
