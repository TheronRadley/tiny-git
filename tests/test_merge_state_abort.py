"""Unit tests for merge state (MERGE_HEAD), index conflict stages (1, 2, 3), and merge --abort."""

from pathlib import Path

import pytest

from tinygit.errors import NothingToCommitError
from tinygit.repository import Repository


def test_merge_state_conflict_status_and_resolution(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("hello\nworld\n", encoding="utf-8")
    repo.add(["f.txt"])
    _ = repo.commit("Base")

    repo.branch("feat")

    # Change on main
    (tmp_path / "f.txt").write_text("hello\nmain world\n", encoding="utf-8")
    repo.add(["f.txt"])
    c_main = repo.commit("Main edit")

    # Change on feat
    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("hello\nfeat world\n", encoding="utf-8")
    repo.add(["f.txt"])
    c_feat = repo.commit("Feat edit")

    repo.checkout("main")
    res = repo.merge("feat")
    assert res.status == "conflict"

    # Verify MERGE_HEAD exists
    merge_head_path = tmp_path / ".tinygit" / "MERGE_HEAD"
    assert merge_head_path.exists()
    assert merge_head_path.read_text(encoding="utf-8").strip() == c_feat

    # Verify status reports merge in progress and unmerged paths
    st = repo.status()
    assert st.merge_head == c_feat
    assert "You are currently merging feat" in st.format()
    assert "Unmerged paths:" in st.format()
    assert "f.txt" in st.unmerged_paths
    assert len(st.staged_modified) == 0

    # Attempting to commit before resolving conflicts must raise NothingToCommitError
    with pytest.raises(NothingToCommitError) as exc_info:
        repo.commit("Premature commit")
    assert "unmerged files" in str(exc_info.value).lower()

    # Resolve conflict: write final text and stage it
    (tmp_path / "f.txt").write_text("hello\nmerged world\n", encoding="utf-8")
    repo.add(["f.txt"])
    assert repo.index.has_unmerged_paths() is False

    # Now commit -> creates multi-parent commit and removes MERGE_HEAD
    merge_c_sha = repo.commit("Merge feat into main")
    merge_obj = repo.store.read_commit(merge_c_sha)
    assert len(merge_obj.parents) == 2
    assert c_main in merge_obj.parents
    assert c_feat in merge_obj.parents
    assert not merge_head_path.exists()
    assert repo.status().is_clean()


def test_merge_abort_restores_state(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "a.txt").write_text("base", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("Base")

    repo.branch("feat")
    (tmp_path / "a.txt").write_text("main version", encoding="utf-8")
    repo.add(["a.txt"])
    c_main = repo.commit("Main edit")

    repo.checkout("feat")
    (tmp_path / "a.txt").write_text("feat version", encoding="utf-8")
    repo.add(["a.txt"])
    _ = repo.commit("Feat edit")

    repo.checkout("main")
    res = repo.merge("feat")
    assert res.status == "conflict"
    assert (tmp_path / ".tinygit" / "MERGE_HEAD").exists()

    # Abort merge
    msg = repo.merge(abort=True)
    assert msg == "Merge aborted."
    assert not (tmp_path / ".tinygit" / "MERGE_HEAD").exists()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "main version"
    assert repo.refs.get_head_commit() == c_main
    assert repo.status().is_clean()
