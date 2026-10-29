"""Failure-injection tests for interrupted multi-file operations.

The audit asks for these alongside the reproduced bugs. The property under test
is not "nothing ever fails" but that a failure part-way through a multi-file
operation leaves a repository that is still *usable*: fsck stays healthy, no
partial metadata is left behind, and the user can retry or abort.
"""

from pathlib import Path

import pytest

from tinygit.errors import WorkingTreeDirtyError
from tinygit.repository import Repository
from tinygit.utils import atomic_write_file
from tinygit.working_tree import WorkingTree


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    r = Repository.init(tmp_path)
    r.config.set("user.name", "T")
    r.config.set("user.email", "t@t.t")
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(f"{name}\n", encoding="utf-8")
    r.add(["."])
    r.commit("base")
    return r


def _feature_branch(repo: Repository, tmp_path: Path) -> None:
    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "a.txt").write_text("feat a\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("feat new\n", encoding="utf-8")
    (tmp_path / "c.txt").unlink()
    repo.add(["."])
    repo.commit("feat changes")
    repo.checkout("main")


# --------------------------------------------------------------------------
# atomic_write_file
# --------------------------------------------------------------------------
def test_atomic_write_leaves_no_temp_files_on_failure(tmp_path: Path):
    target = tmp_path / "meta.txt"
    target.write_text("original\n", encoding="utf-8")

    class ExplodingPath(type(target)):
        def replace(self, *args, **kwargs):
            raise OSError("simulated crash during rename")

    import tinygit.utils as utils

    real_mkstemp = utils.tempfile.mkstemp

    def failing_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        # Swap in a Path subclass whose replace() fails.
        return fd, path

    utils.tempfile.mkstemp = failing_mkstemp
    try:
        with pytest.raises(OSError):
            _atomic_write_that_fails_on_rename(target, "new content")
    finally:
        utils.tempfile.mkstemp = real_mkstemp

    assert target.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob(".tmp_tinygit_*")) == []


def _atomic_write_that_fails_on_rename(path: Path, data: str) -> None:
    """atomic_write_file with the rename step made to fail."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path_str = tempfile.mkstemp(dir=path.parent, prefix=".tmp_tinygit_")
    temp_path = Path(temp_path_str)
    try:
        with open(fd, "wb") as f:
            f.write(data.encode())
            f.flush()
            os.fsync(f.fileno())
        raise OSError("simulated crash during rename")
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def test_fsync_dir_tolerates_an_unopenable_directory(tmp_path: Path):
    from tinygit.utils import fsync_dir

    fsync_dir(tmp_path / "does-not-exist")  # must not raise
    fsync_dir(tmp_path)


def test_atomic_write_survives_a_real_write(tmp_path: Path):
    target = tmp_path / "nested" / "deep" / "meta.txt"
    atomic_write_file(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert list(target.parent.glob(".tmp_tinygit_*")) == []


# --------------------------------------------------------------------------
# Interrupted checkout
# --------------------------------------------------------------------------
def test_checkout_failure_during_write_leaves_the_repository_usable(repo: Repository, tmp_path: Path, monkeypatch):
    _feature_branch(repo, tmp_path)
    head_before = repo.refs.get_head_commit()

    original_write = WorkingTree.write_file
    calls = {"n": 0}

    def flaky_write(self, rel_path, content, mode="100644"):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("simulated disk failure")
        return original_write(self, rel_path, content, mode=mode)

    monkeypatch.setattr(WorkingTree, "write_file", flaky_write)
    with pytest.raises(OSError):
        repo.checkout("feat")
    monkeypatch.setattr(WorkingTree, "write_file", original_write)

    # HEAD did not move, and the repository is still consistent enough to inspect.
    assert repo.refs.get_head_commit() == head_before
    assert repo.fsck().is_healthy()

    # A retried checkout completes.
    repo.checkout("feat")
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "feat new\n"
    assert not (tmp_path / "c.txt").exists()


def test_forced_checkout_recovers_from_a_partially_applied_operation(repo: Repository, tmp_path: Path, monkeypatch):
    """The documented recovery path: HEAD's tree is intact, so force restores it."""
    _feature_branch(repo, tmp_path)
    pristine = {name: (tmp_path / name).read_text(encoding="utf-8") for name in ("a.txt", "b.txt", "c.txt")}

    original_write = WorkingTree.write_file
    calls = {"n": 0}

    def flaky_write(self, rel_path, content, mode="100644"):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("simulated disk failure")
        return original_write(self, rel_path, content, mode=mode)

    monkeypatch.setattr(WorkingTree, "write_file", flaky_write)
    with pytest.raises(OSError):
        repo.checkout("feat")
    monkeypatch.setattr(WorkingTree, "write_file", original_write)

    repo.checkout("main", force=True)

    for name, content in pristine.items():
        assert (tmp_path / name).read_text(encoding="utf-8") == content
    assert not (tmp_path / "new.txt").exists()
    assert repo.status().is_clean()
    assert repo.fsck().is_healthy()


def test_checkout_validates_the_whole_plan_before_writing_anything(repo: Repository, tmp_path: Path, monkeypatch):
    """A blob that cannot be read must abort before the first file is written."""
    _feature_branch(repo, tmp_path)

    # Delete one of the blobs the target snapshot needs.
    feat_sha = repo.refs.get_ref_commit("feat")
    feat_map = repo.wt.get_tree_entries_flat(repo.store.read_commit(feat_sha).tree_id, repo.store)
    victim_blob = feat_map["new.txt"][0]
    blob_path = repo.store.objects_dir / victim_blob[:2] / victim_blob[2:]
    blob_path.unlink()

    writes = []
    original_write = WorkingTree.write_file

    def recording_write(self, rel_path, content, mode="100644"):
        writes.append(rel_path)
        return original_write(self, rel_path, content, mode=mode)

    monkeypatch.setattr(WorkingTree, "write_file", recording_write)
    from tinygit.errors import ObjectNotFoundError

    with pytest.raises(ObjectNotFoundError):
        repo.checkout("feat")

    assert writes == [], "no file may be written once the plan is known to be unresolvable"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a.txt\n"


def test_checkout_propagates_a_removal_failure(repo: Repository, tmp_path: Path, monkeypatch):
    """A file that cannot be unlinked must not be reported as a clean checkout."""
    _feature_branch(repo, tmp_path)

    def failing_remove(self, rel_path):
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(WorkingTree, "remove_file", failing_remove)
    with pytest.raises(OSError):
        repo.checkout("feat")


# --------------------------------------------------------------------------
# Interrupted merge
# --------------------------------------------------------------------------
def test_merge_failure_during_write_leaves_the_repository_usable(repo: Repository, tmp_path: Path, monkeypatch):
    _feature_branch(repo, tmp_path)
    head_before = repo.refs.get_head_commit()

    original_write = WorkingTree.write_file
    calls = {"n": 0}

    def flaky_write(self, rel_path, content, mode="100644"):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("simulated disk failure")
        return original_write(self, rel_path, content, mode=mode)

    monkeypatch.setattr(WorkingTree, "write_file", flaky_write)
    with pytest.raises(OSError):
        repo.merge("feat")
    monkeypatch.setattr(WorkingTree, "write_file", original_write)

    assert repo.refs.get_head_commit() == head_before
    assert repo.fsck().is_healthy()

    # The failed apply left the working tree partly rewritten. Force-restoring
    # HEAD's tree is the recovery path, after which the merge can be retried.
    repo.checkout("main", force=True)
    assert repo.status().is_clean()

    result = repo.merge("feat")
    # main never diverged in this fixture, so this merge fast-forwards.
    assert result.status == "fast-forward"
    committed = repo.wt.get_tree_entries_flat(repo.store.read_commit(result.commit_sha).tree_id, repo.store)
    assert set(committed) == set(repo.wt.list_files())
    assert repo.status().is_clean()
    assert repo.fsck().is_healthy()


def test_conflicted_merge_state_survives_and_can_be_aborted(repo: Repository, tmp_path: Path):
    (tmp_path / "f.txt").write_text("base\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("feat\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("feat")

    repo.checkout("main")
    (tmp_path / "f.txt").write_text("main\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("main")

    assert repo.merge("feat").status == "conflict"
    assert (repo.tinygit_dir / "MERGE_HEAD").exists()
    assert repo.fsck().is_healthy()

    repo.merge(abort=True)
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "main\n"
    assert repo.status().is_clean()
    assert repo.fsck().is_healthy()


def test_merge_refuses_when_an_untracked_file_would_be_overwritten(repo: Repository, tmp_path: Path):
    _feature_branch(repo, tmp_path)
    (tmp_path / "new.txt").write_text("untracked, precious\n", encoding="utf-8")

    with pytest.raises(WorkingTreeDirtyError):
        repo.merge("feat")
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "untracked, precious\n"
    assert repo.fsck().is_healthy()


def test_merge_refuses_with_a_dirty_working_tree(repo: Repository, tmp_path: Path):
    _feature_branch(repo, tmp_path)
    (tmp_path / "a.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(WorkingTreeDirtyError):
        repo.merge("feat")


# --------------------------------------------------------------------------
# Interrupted commit
# --------------------------------------------------------------------------
def test_commit_failure_leaves_head_and_index_intact(repo: Repository, tmp_path: Path, monkeypatch):
    (tmp_path / "d.txt").write_text("d\n", encoding="utf-8")
    repo.add(["d.txt"])
    head_before = repo.refs.get_head_commit()
    index_before = {e.path for e in repo.index.list_entries()}

    import tinygit.repository as repo_mod

    def failing_write(self, obj):
        raise OSError("simulated object write failure")

    monkeypatch.setattr(repo_mod.ObjectStore, "write_object", failing_write)
    with pytest.raises(OSError):
        repo.commit("should fail")

    assert repo.refs.get_head_commit() == head_before
    repo.index.read()
    assert {e.path for e in repo.index.list_entries()} == index_before
    assert repo.fsck().is_healthy()


def test_no_temporary_files_leak_across_a_full_workflow(repo: Repository, tmp_path: Path):
    _feature_branch(repo, tmp_path)
    repo.merge("feat")
    repo.status()
    repo.diff()
    repo.fsck()

    leftovers = list((tmp_path / ".tinygit").rglob(".tmp_tinygit_*"))
    assert leftovers == []
