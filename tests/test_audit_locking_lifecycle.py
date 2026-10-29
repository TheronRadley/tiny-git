"""Regression tests: operation locking, guarded ref updates, and merge lifecycle rules.

Covers audit items "Add operation locking and guarded ref updates" and "Enforce
merge lifecycle rules".
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tinygit.errors import LockHeldError, StaleReferenceError, WorkingTreeDirtyError
from tinygit.locking import FileLock, LockError, index_lock, operation_lock, ref_lock
from tinygit.repository import Repository


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    r = Repository.init(tmp_path)
    r.config.set("user.name", "T")
    r.config.set("user.email", "t@t.t")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    r.add(["seed.txt"])
    r.commit("seed")
    return r


# --------------------------------------------------------------------------
# FileLock primitives
# --------------------------------------------------------------------------
def test_lock_is_exclusive_and_times_out(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    first = FileLock(lock_path)
    first.acquire()
    try:
        assert lock_path.exists()
        second = FileLock(lock_path)
        with pytest.raises(LockError):
            second.acquire(timeout=0.2)
    finally:
        first.release()

    # After release the lock can be taken again.
    third = FileLock(lock_path)
    third.acquire(timeout=0.2)
    third.release()


def test_lock_records_its_owner_pid(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    lock = FileLock(lock_path)
    lock.acquire()
    try:
        assert lock_path.read_text(encoding="ascii").strip() == str(os.getpid())
    finally:
        lock.release()
    assert not lock_path.exists()


def test_stale_lock_from_a_dead_process_is_broken(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    # A PID that is not running. Pick one high enough to be implausible.
    dead_pid = 2**22 - 1
    lock_path.write_text(f"{dead_pid}\n", encoding="ascii")

    lock = FileLock(lock_path)
    lock.acquire(timeout=1.0)
    try:
        assert lock.held
    finally:
        lock.release()


def test_live_lock_is_not_broken(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    lock_path.write_text(f"{os.getpid()}\n", encoding="ascii")

    lock = FileLock(lock_path)
    with pytest.raises(LockError):
        lock.acquire(timeout=0.2)


def test_release_is_idempotent(tmp_path: Path):
    lock = FileLock(tmp_path / "x.lock")
    lock.acquire()
    lock.release()
    lock.release()  # must not raise


# --------------------------------------------------------------------------
# Context managers used by Repository
# --------------------------------------------------------------------------
def test_index_lock_blocks_a_second_holder(tmp_path: Path):
    with index_lock(tmp_path):
        assert (tmp_path / ".tinygit" / "index.lock").exists()
        with pytest.raises(LockError):
            with index_lock(tmp_path, timeout=0.2):
                pass
    assert not (tmp_path / ".tinygit" / "index.lock").exists()


def test_ref_lock_is_per_branch(tmp_path: Path):
    heads = tmp_path / ".tinygit" / "refs" / "heads"
    heads.mkdir(parents=True, exist_ok=True)
    with ref_lock(tmp_path, "main"):
        # A different branch is unaffected.
        with ref_lock(tmp_path, "feat", timeout=0.2):
            pass
        with pytest.raises(LockError):
            with ref_lock(tmp_path, "main", timeout=0.2):
                pass


def test_operation_lock_releases_on_exception(tmp_path: Path):
    with pytest.raises(RuntimeError):
        with operation_lock(tmp_path):
            raise RuntimeError("boom")
    assert not (tmp_path / ".tinygit" / "index.lock").exists()
    assert not (tmp_path / ".tinygit" / "HEAD.lock").exists()


def test_mutating_command_surfaces_a_held_lock(repo: Repository, tmp_path: Path):
    with operation_lock(tmp_path):
        with pytest.raises(LockHeldError):
            repo.commit("should not run")


# --------------------------------------------------------------------------
# Guarded (compare-and-swap) ref updates
# --------------------------------------------------------------------------
def test_guarded_branch_update_detects_a_concurrent_move(repo: Repository):
    original = repo.refs.get_head_commit()
    new_sha = original  # value is irrelevant; the guard is what is under test

    repo.refs.update_branch("main", new_sha, expected=original)

    with pytest.raises(StaleReferenceError):
        repo.refs.update_branch("main", new_sha, expected="f" * 40)


def test_guarded_update_rejects_when_branch_is_absent(repo: Repository):
    with pytest.raises(StaleReferenceError):
        repo.refs.update_branch("brand-new", "a" * 40, expected="b" * 40)


def test_unguarded_update_still_works(repo: Repository):
    head = repo.refs.get_head_commit()
    repo.refs.update_branch("main", head)
    assert repo.refs.get_head_commit() == head


# --------------------------------------------------------------------------
# Real concurrency: parallel processes must not lose commits
# --------------------------------------------------------------------------
_WORKER = """
import sys, time
sys.path.insert(0, {src!r})
from pathlib import Path
from tinygit.repository import Repository
from tinygit.errors import TinyGitError

root, name = Path(sys.argv[1]), sys.argv[2]
for attempt in range(40):
    try:
        repo = Repository.find_repo(root)
        (root / (name + ".txt")).write_text(name + "\\n")
        repo.add([name + ".txt"])
        repo.commit("commit " + name)
        sys.exit(0)
    except TinyGitError:
        time.sleep(0.03 * (attempt + 1))
sys.exit(1)
"""


def test_parallel_processes_do_not_lose_commits(repo: Repository, tmp_path: Path):
    src = str(Path(__file__).resolve().parents[1] / "src")
    script = tmp_path / "worker.py"
    script.write_text(_WORKER.format(src=src), encoding="utf-8")

    names = [f"w{i}" for i in range(6)]
    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(tmp_path), name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for name in names
    ]
    deadline = time.monotonic() + 120
    for p in procs:
        remaining = max(1.0, deadline - time.monotonic())
        p.wait(timeout=remaining)

    fresh = Repository(tmp_path)
    messages = [e.message for e in fresh.log()]
    missing = [n for n in names if f"commit {n}" not in messages]

    assert not missing, f"lost commits for workers: {missing}"
    fresh.index.read()
    committed = fresh.wt.get_tree_entries_flat(
        fresh.store.read_commit(fresh.refs.get_head_commit()).tree_id, fresh.store
    )
    for name in names:
        assert f"{name}.txt" in committed
    assert fresh.fsck().is_healthy()


def test_no_lock_files_are_left_behind_after_concurrent_work(repo: Repository, tmp_path: Path):
    src = str(Path(__file__).resolve().parents[1] / "src")
    script = tmp_path / "worker.py"
    script.write_text(_WORKER.format(src=src), encoding="utf-8")

    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(tmp_path), f"p{i}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for i in range(4)
    ]
    for p in procs:
        p.wait(timeout=120)

    leftovers = list((tmp_path / ".tinygit").rglob("*.lock"))
    assert leftovers == [], f"stale lock files left behind: {leftovers}"


# --------------------------------------------------------------------------
# Merge lifecycle
# --------------------------------------------------------------------------
def _conflicted_merge(repo: Repository, tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("base\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("feat edit\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("feat")

    repo.checkout("main")
    (tmp_path / "f.txt").write_text("main edit\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("main")

    assert repo.merge("feat").status == "conflict"


def test_checkout_is_refused_while_a_merge_is_pending(repo: Repository, tmp_path: Path):
    _conflicted_merge(repo, tmp_path)
    repo.branch("side")

    with pytest.raises(WorkingTreeDirtyError) as exc:
        repo.checkout("side")
    assert "MERGE_HEAD" in str(exc.value)
    assert (repo.tinygit_dir / "MERGE_HEAD").exists()
    assert repo.refs.get_current_branch() == "main"


def test_a_second_merge_is_refused_while_one_is_pending(repo: Repository, tmp_path: Path):
    _conflicted_merge(repo, tmp_path)
    repo.branch("other")

    with pytest.raises(WorkingTreeDirtyError) as exc:
        repo.merge("other")
    assert "MERGE_HEAD" in str(exc.value)


def test_merge_abort_is_always_available_during_a_merge(repo: Repository, tmp_path: Path):
    _conflicted_merge(repo, tmp_path)
    assert repo.merge(abort=True) == "Merge aborted."
    assert not (repo.tinygit_dir / "MERGE_HEAD").exists()


def test_checkout_is_allowed_after_the_merge_is_committed(repo: Repository, tmp_path: Path):
    _conflicted_merge(repo, tmp_path)
    (tmp_path / "f.txt").write_text("resolved\n", encoding="utf-8")
    repo.add(["f.txt"])
    sha = repo.commit("resolve merge")
    assert len(repo.store.read_commit(sha).parents) == 2

    repo.branch("side")
    assert "Switched to branch 'side'" in repo.checkout("side")


def test_checkout_is_allowed_after_the_merge_is_aborted(repo: Repository, tmp_path: Path):
    _conflicted_merge(repo, tmp_path)
    repo.merge(abort=True)

    repo.branch("side")
    assert "Switched to branch 'side'" in repo.checkout("side")


def test_merge_in_progress_helper_reports_the_pending_commit(repo: Repository, tmp_path: Path):
    assert repo.merge_in_progress() is None
    _conflicted_merge(repo, tmp_path)
    assert repo.merge_in_progress() is not None
    repo.merge(abort=True)
    assert repo.merge_in_progress() is None


def test_status_mentions_the_pending_merge(repo: Repository, tmp_path: Path):
    _conflicted_merge(repo, tmp_path)
    text = repo.status().format()
    assert "You are currently merging feat" in text
    assert "merge --abort" in text or "Unmerged paths" in text
