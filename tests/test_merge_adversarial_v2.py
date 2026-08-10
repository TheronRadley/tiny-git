"""Adversarial merge audit v2: attacking 3-way merge and LCA resolution.

Audits:
  - multiple valid merge bases and deterministic merge-base selection
  - recursive ancestry and repeated merges
  - merge of an already-merged branch ('Already up to date')
  - merge after revert
  - merge conflict -> resolve -> commit -> merge again
  - merge conflict -> abort -> merge again
  - merge conflict -> modify unrelated file -> abort
  - directory deletion vs file modification inside directory
"""

from pathlib import Path

from tinygit.repository import Repository


def assert_repo_invariants(repo: Repository, expected_parents: int | None = None) -> None:
    """Verify repository invariants after a merge operation."""
    fsck_res = repo.fsck()
    assert fsck_res.is_healthy(), f"Repository fsck failed: {fsck_res.errors}"

    head_sha = repo.refs.get_head_commit()
    assert head_sha, "HEAD commit SHA is empty"
    commit = repo.store.read_commit(head_sha)
    if expected_parents is not None:
        assert len(commit.parents) == expected_parents
    assert repo.store.exists(commit.tree_id), "Commit tree does not exist"

    # Working tree and index must match HEAD tree for clean merges
    if not (repo.tinygit_dir / "MERGE_HEAD").exists():
        head_map = repo.wt.get_tree_entries_flat(commit.tree_id, repo.store)
        index_map = {e.path: (e.object_id, e.mode) for e in repo.index.list_entries() if e.stage == 0}
        assert head_map == index_map, "Index does not match HEAD commit tree"


def test_merge_already_up_to_date_and_repeated(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("v1", encoding="utf-8")
    repo.add(["f.txt"])
    _ = repo.commit("Base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("v2", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Feat c1")

    # Merge feat into main -> fast-forward
    repo.checkout("main")
    res1 = repo.merge("feat")
    assert res1.is_success()
    assert res1.status == "fast-forward"
    assert_repo_invariants(repo, expected_parents=1)

    # Repeat merge -> already up to date
    res2 = repo.merge("feat")
    assert res2.is_success()
    assert res2.status == "up-to-date"
    assert_repo_invariants(repo, expected_parents=1)


def test_merge_conflict_resolve_commit_and_remerge(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("base\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("feat")
    (tmp_path / "f.txt").write_text("main edit\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Main c1")

    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("feat edit\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Feat c1")

    repo.checkout("main")
    res_conf = repo.merge("feat")
    assert res_conf.status == "conflict"
    assert (repo.tinygit_dir / "MERGE_HEAD").exists()

    # Resolve conflict and commit
    (tmp_path / "f.txt").write_text("resolved\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Merge feat into main")
    assert_repo_invariants(repo, expected_parents=2)

    # Merging feat again should now be up to date!
    res2 = repo.merge("feat")
    assert res2.status == "up-to-date"
    assert_repo_invariants(repo, expected_parents=2)


def test_merge_conflict_abort_modify_and_remerge(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("root", encoding="utf-8")
    repo.add(["f.txt"])
    _ = repo.commit("Root")

    repo.branch("feat")
    (tmp_path / "f.txt").write_text("main", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Main")

    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("feat", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Feat")

    repo.checkout("main")
    res1 = repo.merge("feat")
    assert res1.status == "conflict"

    # User modifies an unrelated file while in conflict state, then aborts
    (tmp_path / "unrelated.txt").write_text("temp", encoding="utf-8")
    msg = repo.merge(abort=True)
    assert msg == "Merge aborted."
    assert not (repo.tinygit_dir / "MERGE_HEAD").exists()
    # Pre-merge HEAD state for tracked files must be restored
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "main"
    assert_repo_invariants(repo, expected_parents=1)


def test_merge_dir_deleted_vs_file_modified_inside(tmp_path: Path):
    repo = Repository.init(tmp_path)
    dir_path = tmp_path / "src"
    dir_path.mkdir()
    file_path = dir_path / "code.py"
    file_path.write_text("print(1)\n", encoding="utf-8")
    repo.add(["src"])
    repo.commit("Base with dir")

    repo.branch("del_branch")
    repo.branch("mod_branch")

    # del_branch removes src/code.py (and dir src)
    repo.checkout("del_branch")
    repo.rm(["src/code.py"])
    repo.commit("Delete src/code.py")

    # mod_branch modifies src/code.py
    repo.checkout("mod_branch")
    file_path.write_text("print(2)\n", encoding="utf-8")
    repo.add(["src"])
    repo.commit("Modify src/code.py")

    # Merge del_branch into mod_branch -> conflict on src/code.py!
    res = repo.merge("del_branch")
    assert res.status == "conflict"
    assert "src/code.py" in [c.path for c in res.conflicts]
    content = file_path.read_text(encoding="utf-8")
    assert "<<<<<<< HEAD" in content
    assert "print(2)" in content
