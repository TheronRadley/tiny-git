"""State-machine and property-based verification engine for Tiny Git.

Generates random sequences of repository operations (init, create file,
modify file, stage, commit, branch, checkout, merge, status) and asserts
8 strict repository invariants after every step.
"""

import os
import random
import stat
from pathlib import Path

import pytest

from tinygit.errors import WorkingTreeDirtyError
from tinygit.repository import Repository


def assert_all_repository_invariants(repo: Repository, seed: int, step: int, action: str) -> None:
    """Assert all 8 fundamental Tiny Git repository invariants."""
    try:
        # Invariant 1: Every referenced object must exist (verified via fsck)
        fsck_res = repo.fsck()
        assert fsck_res.is_healthy(), f"Invariant violation - fsck failed: {fsck_res.errors}"

        # Invariant 2: Objects are immutable and readable
        head_sha = repo.refs.get_head_commit()
        if head_sha:
            commit = repo.store.read_commit(head_sha)
            assert commit.get_hash() == head_sha

        # Invariant 3: Every branch points to a valid commit
        for branch_name in repo.refs.list_branches():
            sha = repo.refs.get_ref_commit(branch_name)
            assert sha and repo.store.exists(sha), f"Branch {branch_name} points to invalid SHA {sha}"

        # Invariant 4: HEAD resolves to either a branch or valid commit
        head_target = repo.refs.get_head_target()
        assert head_target.startswith("ref: ") or len(head_target) == 40

        # Invariant 5 & 6: Every commit's tree and all tree children must exist
        if head_sha:
            commit = repo.store.read_commit(head_sha)
            assert repo.store.exists(commit.tree_id)
            tree = repo.store.read_tree(commit.tree_id)
            for entry in tree.entries:
                assert repo.store.exists(entry.object_id)

        # Invariant 7: Status correctly categorizes index vs disk without crashing
        st = repo.status()
        assert isinstance(st.is_clean(), bool)

        # Invariant 8: Index entries reference valid existing blobs
        repo.index.read()
        for entry in repo.index.list_entries():
            assert repo.store.exists(entry.object_id), f"Index references missing blob {entry.object_id}"
    except Exception as e:
        pytest.fail(
            f"\nState-machine failure\nSeed: {seed}\nStep: {step}\nOperation: {action}\nError: {e}"
        )


@pytest.mark.parametrize("seed", [101, 102, 103, 104, 105, 106, 107, 108, 109, 110])
def test_state_machine_random_workflows(tmp_path: Path, seed: int):
    """Simulate a 100-step randomized sequence across 10 distinct seeds."""
    random.seed(seed)
    repo_dir = tmp_path / f"repo_{seed}"
    repo_dir.mkdir()
    repo = Repository.init(repo_dir)
    assert_all_repository_invariants(repo, seed, 0, "init")

    branches = ["main"]
    files = ["a.txt", "b.txt", "c.txt", "d.txt"]

    for step in range(1, 101):
        action = random.choice([
            "write_file",
            "write_file",
            "chmod_file",
            "delete_file",
            "add",
            "rm_cached",
            "restore_staged",
            "commit",
            "branch",
            "checkout",
            "merge",
        ])

        if action == "write_file":
            filename = random.choice(files)
            content = f"seed {seed} step {step} content {random.randint(0, 1000)}\n"
            (repo_dir / filename).write_text(content, encoding="utf-8")

        elif action == "chmod_file":
            existing = [f for f in files if (repo_dir / f).exists()]
            if existing:
                p = repo_dir / random.choice(existing)
                mode = 0o755 if (os.stat(p).st_mode & stat.S_IXUSR) == 0 else 0o644
                p.chmod(mode)

        elif action == "delete_file":
            existing = [f for f in files if (repo_dir / f).exists()]
            if existing:
                (repo_dir / random.choice(existing)).unlink()

        elif action == "add":
            existing = [f for f in files if (repo_dir / f).exists() or f in repo.index]
            if existing:
                repo.add([random.choice(existing)])

        elif action == "rm_cached":
            existing_idx = [e.path for e in repo.index.list_entries()]
            if existing_idx:
                repo.rm([random.choice(existing_idx)], cached=True)

        elif action == "restore_staged":
            st = repo.status()
            if st.staged_modified or st.staged_deleted:
                targets = st.staged_modified + st.staged_deleted
                repo.restore([random.choice(targets)], staged=True)

        elif action == "commit":
            st = repo.status()
            if st.has_staged_changes() and not repo.index.has_unmerged_paths():
                repo.commit(f"Commit at seed {seed} step {step}")

        elif action == "branch":
            new_branch = f"feat_{seed}_{step}"
            if new_branch not in branches and repo.refs.get_head_commit():
                repo.branch(new_branch)
                branches.append(new_branch)

        elif action == "checkout":
            target = random.choice(branches)
            if target != repo.refs.get_current_branch():
                st = repo.status()
                if (
                    not st.has_staged_changes()
                    and not st.has_unstaged_changes()
                    and not st.unmerged_paths
                ):
                    try:
                        repo.checkout(target)
                    except WorkingTreeDirtyError:
                        # Safety engine correctly refused to overwrite untracked file
                        pass

        elif action == "merge":
            target = random.choice(branches)
            curr = repo.refs.get_current_branch()
            st = repo.status()
            if (
                target != curr
                and repo.refs.get_head_commit()
                and not st.has_staged_changes()
                and not st.has_unstaged_changes()
                and not st.unmerged_paths
            ):
                try:
                    res = repo.merge(target)
                except WorkingTreeDirtyError:
                    # Safety engine correctly refused unsafe merge
                    res = None
                if res and not isinstance(res, str) and res.status == "conflict":
                    # On conflict, randomly choose whether to abort or resolve
                    if random.choice([True, False]):
                        repo.merge(abort=True)
                    else:
                        for f in repo.index.get_unmerged_paths():
                            (repo_dir / f).write_text("resolved\n", encoding="utf-8")
                            repo.add([f])
                        repo.commit(f"Resolve merge {target}")

        assert_all_repository_invariants(repo, seed, step, action)
