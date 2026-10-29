"""Regression tests: rm() protection and merge correctness (audit "Fix first" #5, "Correctness" #1-#4).

Covered here:
  * ``rm`` destroyed uncommitted work with no override available.
  * A clean three-way merge deleted a file from disk while the resulting commit
    still contained it, because the index was patched instead of rebuilt.
  * Conflicted paths kept a stage 0 entry alongside stages 1-3, and missing
    sides were recorded as all-zero object ids that broke diff and fsck.
  * Non-UTF-8 bytes were mangled into replacement characters by a merge that
    reported success.
  * ``find_lca`` chose an older common ancestor when a newer one existed.
"""

from pathlib import Path

import pytest

from tinygit.errors import InvalidPathError, WorkingTreeDirtyError
from tinygit.merge import MergeEngine
from tinygit.objects import Commit
from tinygit.repository import Repository


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    r = Repository.init(tmp_path)
    r.config.set("user.name", "T")
    r.config.set("user.email", "t@t.t")
    return r


# --------------------------------------------------------------------------
# rm() protection
# --------------------------------------------------------------------------
def test_rm_refuses_to_destroy_uncommitted_modifications(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("committed\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    (tmp_path / "a.txt").write_text("HOURS OF UNCOMMITTED WORK\n", encoding="utf-8")

    with pytest.raises(WorkingTreeDirtyError) as exc:
        repo.rm(["a.txt"])
    assert "--force" in str(exc.value)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "HOURS OF UNCOMMITTED WORK\n"
    assert "a.txt" in repo.index


def test_rm_refuses_when_staged_content_differs_from_head(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("committed\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    (tmp_path / "a.txt").write_text("staged but uncommitted\n", encoding="utf-8")
    repo.add(["a.txt"])

    with pytest.raises(WorkingTreeDirtyError):
        repo.rm(["a.txt"])
    assert (tmp_path / "a.txt").exists()


def test_rm_force_overrides_the_protection(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("committed\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    (tmp_path / "a.txt").write_text("discard me\n", encoding="utf-8")

    repo.rm(["a.txt"], force=True)

    assert not (tmp_path / "a.txt").exists()
    assert "a.txt" not in repo.index


def test_rm_cached_never_touches_the_working_tree(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("committed\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    (tmp_path / "a.txt").write_text("local edit\n", encoding="utf-8")

    repo.rm(["a.txt"], cached=True)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "local edit\n"
    assert "a.txt" not in repo.index


def test_rm_validates_every_path_before_removing_any(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    repo.add(["a.txt", "b.txt"])
    repo.commit("c1")

    with pytest.raises(InvalidPathError):
        repo.rm(["a.txt", "does-not-exist.txt"])

    # Nothing was removed by the failed call.
    assert (tmp_path / "a.txt").exists()
    assert "a.txt" in repo.index


def test_rm_of_unmodified_committed_file_still_works(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    repo.rm(["a.txt"])
    assert not (tmp_path / "a.txt").exists()


# --------------------------------------------------------------------------
# Merge: index rebuilt from the actual result
# --------------------------------------------------------------------------
def test_clean_merge_removes_deleted_file_from_both_disk_and_commit(repo: Repository, tmp_path: Path):
    (tmp_path / "keep.txt").write_text("keep\n", encoding="utf-8")
    (tmp_path / "gone.txt").write_text("gone\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "feat.txt").write_text("feat work\n", encoding="utf-8")
    repo.add(["feat.txt"])
    repo.commit("feat adds")

    repo.checkout("main")
    (tmp_path / "gone.txt").unlink()
    repo.add(["gone.txt"])
    repo.commit("main deletes gone.txt")

    result = repo.merge("feat")
    assert result.status == "clean"

    committed = repo.wt.get_tree_entries_flat(repo.store.read_commit(result.commit_sha).tree_id, repo.store)
    assert not (tmp_path / "gone.txt").exists()
    assert "gone.txt" not in committed, "commit must not retain a file deleted from disk"
    assert "gone.txt" not in repo.index
    assert sorted(committed) == ["feat.txt", "keep.txt"]
    assert repo.fsck().is_healthy()


def test_merge_result_commit_matches_the_working_tree(repo: Repository, tmp_path: Path):
    for name in ("one.txt", "two.txt", "three.txt"):
        (tmp_path / name).write_text(f"{name}\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "three.txt").unlink()
    (tmp_path / "four.txt").write_text("four\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("feat: drop three, add four")

    repo.checkout("main")
    (tmp_path / "one.txt").write_text("one changed on main\n", encoding="utf-8")
    repo.add(["one.txt"])
    repo.commit("main: edit one")

    result = repo.merge("feat")
    assert result.status == "clean"

    committed = repo.wt.get_tree_entries_flat(repo.store.read_commit(result.commit_sha).tree_id, repo.store)
    on_disk = set(repo.wt.list_files())
    assert set(committed) == on_disk
    assert repo.status().is_clean()


# --------------------------------------------------------------------------
# Merge: conflict stages
# --------------------------------------------------------------------------
def _make_add_add_conflict(repo: Repository, tmp_path: Path):
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    repo.add(["base.txt"])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "shared.txt").write_text("feat side\n", encoding="utf-8")
    repo.add(["shared.txt"])
    repo.commit("feat adds shared")

    repo.checkout("main")
    (tmp_path / "shared.txt").write_text("main side\n", encoding="utf-8")
    repo.add(["shared.txt"])
    repo.commit("main adds shared")

    return repo.merge("feat")


def test_add_add_conflict_omits_the_absent_base_stage(repo: Repository, tmp_path: Path):
    result = _make_add_add_conflict(repo, tmp_path)
    assert result.status == "conflict"

    stages = {e.stage for e in repo.index.list_entries() if e.path == "shared.txt"}
    assert stages == {2, 3}, f"add/add has no base; got stages {sorted(stages)}"


def test_conflicted_path_has_no_stage_zero_entry(repo: Repository, tmp_path: Path):
    _make_add_add_conflict(repo, tmp_path)
    assert repo.index.query("shared.txt") is None
    assert repo.index.get_unmerged_paths() == ["shared.txt"]


def test_no_zero_hash_placeholders_are_written_to_the_index(repo: Repository, tmp_path: Path):
    _make_add_add_conflict(repo, tmp_path)
    for entry in repo.index.list_entries():
        assert entry.object_id != "0" * 40
        assert repo.store.exists(entry.object_id), f"{entry.path} stage {entry.stage} dangles"


def test_conflicted_merge_leaves_fsck_healthy_and_diff_runnable(repo: Repository, tmp_path: Path):
    _make_add_add_conflict(repo, tmp_path)
    assert repo.fsck().is_healthy()
    repo.diff()  # must not raise
    repo.diff(cached=True)


def test_modify_delete_conflict_records_only_existing_sides(repo: Repository, tmp_path: Path):
    (tmp_path / "f.txt").write_text("base\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "f.txt").unlink()
    repo.add(["f.txt"])
    repo.commit("feat deletes f")

    repo.checkout("main")
    (tmp_path / "f.txt").write_text("main modified f\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("main modifies f")

    result = repo.merge("feat")
    assert result.status == "conflict"

    entries = [e for e in repo.index.list_entries() if e.path == "f.txt"]
    stages = {e.stage for e in entries}
    assert 0 not in stages
    for e in entries:
        assert e.object_id != "0" * 40
        assert repo.store.exists(e.object_id)
    assert repo.fsck().is_healthy()


def test_resolving_a_conflict_clears_all_stages(repo: Repository, tmp_path: Path):
    _make_add_add_conflict(repo, tmp_path)
    (tmp_path / "shared.txt").write_text("resolved\n", encoding="utf-8")
    repo.add(["shared.txt"])

    assert repo.index.has_unmerged_paths() is False
    entry = repo.index.query("shared.txt")
    assert entry is not None and entry.stage == 0

    sha = repo.commit("resolve")
    assert len(repo.store.read_commit(sha).parents) == 2
    assert repo.fsck().is_healthy()


# --------------------------------------------------------------------------
# Merge: byte preservation
# --------------------------------------------------------------------------
NON_UTF8 = "café résumé".encode("latin-1")


def test_non_utf8_file_survives_a_merge_untouched(repo: Repository, tmp_path: Path):
    assert NON_UTF8.decode("utf-8", errors="strict") if False else True  # it is not valid UTF-8
    with pytest.raises(UnicodeDecodeError):
        NON_UTF8.decode("utf-8")

    (tmp_path / "data.bin").write_bytes(NON_UTF8)
    (tmp_path / "other.txt").write_text("base\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "other.txt").write_text("feat edit\n", encoding="utf-8")
    repo.add(["other.txt"])
    repo.commit("feat")

    repo.checkout("main")
    (tmp_path / "other.txt").write_text("main edit\n", encoding="utf-8")
    repo.add(["other.txt"])
    repo.commit("main")

    repo.merge("feat")
    assert (tmp_path / "data.bin").read_bytes() == NON_UTF8


def test_merge_takes_a_one_sided_non_utf8_change_verbatim(repo: Repository, tmp_path: Path):
    (tmp_path / "data.bin").write_bytes(b"original\n")
    repo.add(["data.bin"])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "data.bin").write_bytes(NON_UTF8)
    repo.add(["data.bin"])
    repo.commit("feat: non-utf8 content")

    repo.checkout("main")
    (tmp_path / "other.txt").write_text("main work\n", encoding="utf-8")
    repo.add(["other.txt"])
    repo.commit("main: unrelated")

    result = repo.merge("feat")
    assert result.status == "clean"
    assert (tmp_path / "data.bin").read_bytes() == NON_UTF8


def test_conflicting_non_utf8_content_keeps_our_bytes_exactly(repo: Repository, tmp_path: Path):
    other_non_utf8 = "naïve".encode("latin-1")
    (tmp_path / "data.bin").write_bytes(b"base\n")
    repo.add(["data.bin"])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "data.bin").write_bytes(other_non_utf8)
    repo.add(["data.bin"])
    repo.commit("feat")

    repo.checkout("main")
    (tmp_path / "data.bin").write_bytes(NON_UTF8)
    repo.add(["data.bin"])
    repo.commit("main")

    result = repo.merge("feat")
    assert result.status == "conflict"
    assert (tmp_path / "data.bin").read_bytes() == NON_UTF8, "binary conflict keeps HEAD's bytes"


# --------------------------------------------------------------------------
# Merge base selection
# --------------------------------------------------------------------------
def _mk(repo: Repository, parents: list[str], message: str) -> str:
    root_tree = repo.store.read_commit(repo.refs.get_head_commit() or parents[0]).tree_id
    c = Commit(
        tree_id=root_tree,
        parents=parents,
        author_name="T",
        author_email="t@t.t",
        timestamp="2026-01-01 00:00:00",
        message=message,
    )
    return repo.store.write_object(c)


def test_lca_prefers_a_newer_common_ancestor_over_an_older_one(repo: Repository, tmp_path: Path):
    """Minimal reproduction of the distance-based selection bug.

    R is the root; A is a newer common ancestor. TIP1 reaches both in one hop,
    TIP2 reaches R in one hop but A in two. Minimum total distance therefore
    favours the *older* ancestor R, which makes the merge diff against too old a
    base. Ancestry-based selection returns A.
    """
    (tmp_path / "f.txt").write_text("root\n", encoding="utf-8")
    repo.add(["f.txt"])
    root = repo.commit("R")

    a = _mk(repo, [root], "A")
    b1 = _mk(repo, [a], "B1")
    tip1 = _mk(repo, [root, a], "TIP1")
    tip2 = _mk(repo, [b1, root], "TIP2")

    bases = MergeEngine.find_merge_bases(tip1, tip2, repo.store)
    assert bases == [a], f"expected the newer ancestor {a[:7]}, got {[b[:7] for b in bases]}"
    assert MergeEngine.find_lca(tip1, tip2, repo.store) == a
    assert a != root


def test_multiple_merge_bases_are_all_reported(repo: Repository, tmp_path: Path):
    """A criss-cross history has two equally valid merge bases."""
    (tmp_path / "f.txt").write_text("root\n", encoding="utf-8")
    repo.add(["f.txt"])
    root = repo.commit("R")

    left = _mk(repo, [root], "L")
    right = _mk(repo, [root], "Rr")
    m1 = _mk(repo, [left, right], "M1")
    m2 = _mk(repo, [right, left], "M2")

    bases = MergeEngine.find_merge_bases(m1, m2, repo.store)
    assert set(bases) == {left, right}
    assert bases == sorted(bases), "selection must be deterministic across runs"
    assert MergeEngine.find_lca(m1, m2, repo.store) == sorted([left, right])[0]


def test_lca_of_identical_commits_is_that_commit(repo: Repository, tmp_path: Path):
    (tmp_path / "f.txt").write_text("root\n", encoding="utf-8")
    repo.add(["f.txt"])
    sha = repo.commit("R")
    assert MergeEngine.find_merge_bases(sha, sha, repo.store) == [sha]


def test_lca_of_unrelated_histories_is_none(repo: Repository, tmp_path: Path):
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    repo.add(["f.txt"])
    first = repo.commit("first")

    orphan = _mk(repo, [], "orphan")
    assert MergeEngine.find_merge_bases(first, orphan, repo.store) == []
    assert MergeEngine.find_lca(first, orphan, repo.store) is None


def test_merge_base_is_never_a_non_maximal_ancestor(repo: Repository, tmp_path: Path):
    """Whatever the graph, the chosen base must not be an ancestor of another base."""
    (tmp_path / "f.txt").write_text("root\n", encoding="utf-8")
    repo.add(["f.txt"])
    root = repo.commit("R")

    chain = root
    for i in range(4):
        chain = _mk(repo, [chain], f"c{i}")
    side = _mk(repo, [root], "side")
    join = _mk(repo, [chain, side], "join")
    other = _mk(repo, [side], "other")

    bases = MergeEngine.find_merge_bases(join, other, repo.store)
    assert bases == [side]
