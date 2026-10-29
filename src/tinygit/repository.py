"""Central Repository facade connecting all Tiny Git subsystems.

Provides high-level repository operations (init, add, commit, status, log,
branch, checkout, merge, diff, config) and enforces safety invariants.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from tinygit.config import ConfigManager
from tinygit.diff import DiffEngine, FileChange
from tinygit.errors import (
    IgnoredPathError,
    InvalidPathError,
    InvalidReferenceError,
    LockHeldError,
    NothingToCommitError,
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
    UnsupportedRepositoryFormatError,
    WorkingTreeDirtyError,
)
from tinygit.fsck import FsckResult, IntegrityChecker
from tinygit.index import Index
from tinygit.locking import LockError, operation_lock
from tinygit.merge import MergeEngine, MergeResult
from tinygit.objects import Blob, Commit, ObjectStore, Tree
from tinygit.refs import ReferenceManager, ReflogEntry
from tinygit.resolver import RevisionResolver
from tinygit.status import StatusResult, StatusService
from tinygit.utils import (
    format_log_date,
    get_timestamp,
    is_path_ignored,
    load_ignore_patterns,
)
from tinygit.working_tree import WorkingTree


@dataclass
class CommitLogEntry:
    """Represents a single commit entry in the repository log."""

    commit_sha: str
    author_name: str
    author_email: str
    date: str
    message: str

    def format(self, oneline: bool = False) -> str:
        """Format the commit log entry."""
        if oneline:
            first_line = self.message.splitlines()[0] if self.message else ""
            return f"{self.commit_sha[:7]} {first_line}"

        lines = [
            f"commit {self.commit_sha}",
            f"Author: {self.author_name}",
            f"Date:   {format_log_date(self.date)}",
            "",
        ]
        for msg_line in self.message.splitlines():
            lines.append(f"    {msg_line}")
        if not self.message.splitlines():
            lines.append("    ")
        return "\n".join(lines)


_T = TypeVar("_T")


def _serialized(fn: Callable[..., _T]) -> Callable[..., _T]:
    """Serialise a mutating repository operation against other tiny-git processes.

    Each of these methods reads metadata, mutates it in memory, and writes it
    back. Without a lock held across all three steps, two concurrent commands
    each write their own version of the index or a branch and one of the updates
    is silently lost.
    """

    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> _T:
        try:
            with operation_lock(self.repo_root):
                return fn(self, *args, **kwargs)
        except LockError as e:
            raise LockHeldError(e.lock_path) from e

    return wrapper


class Repository:
    """High-level repository manager representing a Tiny Git repository (.tinygit/)."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.tinygit_dir = self.repo_root / ".tinygit"
        self.config = ConfigManager(self.repo_root)
        self._validate_format_version()
        self.store = ObjectStore(self.repo_root)
        self.index = Index(self.repo_root)
        self.refs = ReferenceManager(self.repo_root)
        self.wt = WorkingTree(self.repo_root)

    def _validate_format_version(self) -> None:
        version_str = self.config.get("core.repositoryformatversion", "1")
        if version_str is None:
            return
        try:
            version = int(version_str)
        except ValueError:
            # A malformed version is not the same as version 1. Silently
            # treating it as supported would let a truncated or hand-edited
            # config open a repository whose layout this code cannot interpret.
            raise UnsupportedRepositoryFormatError(version_str) from None
        if version > 1:
            raise UnsupportedRepositoryFormatError(version)

    @classmethod
    def init(cls, path: Path | str = ".", default_branch: str = "main") -> Repository:
        """Initialize a new Tiny Git repository."""
        repo_root = Path(path).resolve()
        tinygit_dir = repo_root / ".tinygit"
        if tinygit_dir.exists():
            raise RepositoryAlreadyExistsError(str(repo_root))

        # Create standard directory layout
        (tinygit_dir / "objects").mkdir(parents=True, exist_ok=True)
        (tinygit_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)

        repo = cls(repo_root)
        repo.refs.init_head(default_branch)

        # Initialize empty index
        repo.index.write()

        # Initialize default config
        repo.config.set("core.repositoryformatversion", "1")
        repo.config.set("user.name", "Ron")
        repo.config.set("user.email", "ron@example.com")

        return repo

    @classmethod
    def find_repo(cls, start_path: Path | str = ".") -> Repository:
        """Find the containing Tiny Git repository by traversing upwards."""
        curr = Path(start_path).resolve()
        while True:
            if (curr / ".tinygit").is_dir():
                return cls(curr)
            if curr.parent == curr:
                break
            curr = curr.parent
        raise RepositoryNotFoundError(str(start_path))

    @_serialized
    def add(self, paths: list[str], force: bool = False) -> list[str]:
        """Stage file changes (additions, modifications, and deletions) in the index."""
        self.index.read()
        # Tracked files stay visible even if .tinygitignore now matches them, so
        # that `add .` updates them instead of silently staging a deletion.
        tracked = {e.path for e in self.index.list_entries()}
        disk_files = set(self.wt.list_files(always_include=tracked))
        ignore_patterns = load_ignore_patterns(self.repo_root)
        head_commit_sha = self.refs.get_head_commit()
        head_map: dict[str, tuple[str, str]] = {}
        if head_commit_sha:
            head_commit = self.store.read_commit(head_commit_sha)
            head_map = self.wt.get_tree_entries_flat(head_commit.tree_id, self.store)

        staged_paths = []

        for p in paths:
            if p == "." or p == "":
                # Stage all current disk files
                for f in sorted(disk_files):
                    self._stage_file(f)
                    staged_paths.append(f)
                # Stage deletions for files in index that are missing on disk
                for idx_path in list(self.index.list_entries()):
                    if idx_path.path not in disk_files:
                        self.index.remove(idx_path.path)
                        staged_paths.append(idx_path.path)
            else:
                raw_target = self.repo_root / p
                if raw_target.is_symlink():
                    raise InvalidPathError(p, "Symlinks are unsupported for security and determinism")
                target_path = raw_target.resolve()
                try:
                    rel_prefix = target_path.relative_to(self.repo_root).as_posix()
                except ValueError:
                    raise InvalidPathError(p, "Path is outside repository") from None

                if target_path.is_dir():
                    matched_any = False
                    prefix_slash = rel_prefix if rel_prefix.endswith("/") else f"{rel_prefix}/"
                    for f in sorted(disk_files):
                        if f == rel_prefix or f.startswith(prefix_slash):
                            self._stage_file(f)
                            staged_paths.append(f)
                            matched_any = True
                    for idx_entry in list(self.index.list_entries()):
                        if (
                            idx_entry.path == rel_prefix or idx_entry.path.startswith(prefix_slash)
                        ) and idx_entry.path not in disk_files:
                            self.index.remove(idx_entry.path)
                            staged_paths.append(idx_entry.path)
                            matched_any = True
                    if not matched_any and not disk_files:
                        pass
                else:
                    # Regular file path
                    posix_p = rel_prefix
                    if posix_p in disk_files:
                        self._stage_file(posix_p)
                        staged_paths.append(posix_p)
                    elif target_path.is_file() and is_path_ignored(posix_p, ignore_patterns):
                        # Present on disk, untracked, and matched by
                        # .tinygitignore. A silent skip would look like success.
                        if not force:
                            raise IgnoredPathError(posix_p)
                        self._stage_file(posix_p)
                        staged_paths.append(posix_p)
                    elif posix_p in self.index or posix_p in head_map:
                        self.index.remove(posix_p)
                        staged_paths.append(posix_p)
                    else:
                        raise InvalidPathError(p, "File does not exist")

        self.index.write()
        return sorted(set(staged_paths))

    def _stage_file(self, rel_path: str) -> str:
        """Helper to hash and stage a single existing working tree file."""
        content = self.wt.read_file(rel_path)
        sha = self.store.write_object(Blob(content))
        mode = self.wt.get_file_mode(rel_path)
        full_p = self.repo_root / rel_path
        size = full_p.stat().st_size if full_p.exists() else len(content)
        mtime = full_p.stat().st_mtime if full_p.exists() else 0.0
        self.index.add(rel_path, sha, mode=mode, size=size, mtime=mtime)
        return sha

    @_serialized
    def commit(self, message: str, allow_empty: bool = False) -> str:
        """Create a new commit from the staging area (index)."""
        if not message.strip():
            raise NothingToCommitError()

        self.index.read()
        if self.index.has_unmerged_paths():
            raise NothingToCommitError(
                "Cannot commit: you have unmerged files. Resolve conflicts and stage with 'tiny-git add'."
            )

        head_commit_sha = self.refs.get_head_commit()
        parents = [head_commit_sha] if head_commit_sha else []
        merge_head_path = self.tinygit_dir / "MERGE_HEAD"
        merge_mode_path = self.tinygit_dir / "MERGE_MODE"
        if merge_head_path.exists():
            try:
                merge_parent = merge_head_path.read_text(encoding="utf-8").strip()
                if merge_parent and merge_parent not in parents:
                    parents.append(merge_parent)
            except Exception:
                pass

        if not allow_empty and not merge_head_path.exists():
            if not head_commit_sha and len(self.index) == 0:
                raise NothingToCommitError()
            if head_commit_sha:
                head_commit = self.store.read_commit(head_commit_sha)
                head_map = self.wt.get_tree_entries_flat(head_commit.tree_id, self.store)
                index_map = {e.path: (e.object_id, e.mode) for e in self.index.list_entries()}
                if head_map == index_map:
                    raise NothingToCommitError()

        tree_sha = self.wt.build_tree_from_index(self.index, self.store)

        name, email = self.config.get_user_info()
        ts = get_timestamp()

        c = Commit(
            tree_id=tree_sha,
            parents=parents,
            author_name=name,
            author_email=email,
            timestamp=ts,
            message=message.strip(),
        )
        commit_sha = self.store.write_object(c)
        # Guarded: if another process moved HEAD between the read above and now,
        # fail instead of overwriting its commit.
        self.refs.update_head_commit(commit_sha, expected=head_commit_sha)

        if merge_head_path.exists():
            try:
                merge_head_path.unlink()
            except Exception:
                pass
        if merge_mode_path.exists():
            try:
                merge_mode_path.unlink()
            except Exception:
                pass

        return commit_sha

    def reflog(self, max_count: int | None = None) -> list[ReflogEntry]:
        """Return HEAD reflog entries, newest last, optionally limited to the last N."""
        entries = self.refs.read_reflog()
        if max_count is not None and max_count > 0:
            return entries[-max_count:]
        return entries

    def status(self) -> StatusResult:
        """Get repository status comparing HEAD -> INDEX -> WORKING TREE."""
        self.index.read()
        return StatusService.get_status(self.repo_root, self.refs, self.index, self.wt, self.store)

    def log(self, max_count: int | None = None, oneline: bool = False) -> list[CommitLogEntry]:
        """Traverse commit parent chain and return log entries."""
        head_commit_sha = self.refs.get_head_commit()
        if not head_commit_sha:
            return []

        entries = []
        queue = [head_commit_sha]
        visited = set()

        while queue:
            curr_sha = queue.pop(0)
            if curr_sha in visited:
                continue
            visited.add(curr_sha)

            try:
                commit = self.store.read_commit(curr_sha)
                entries.append(
                    CommitLogEntry(
                        commit_sha=curr_sha,
                        author_name=commit.author_name,
                        author_email=commit.author_email,
                        date=commit.timestamp,
                        message=commit.message,
                    )
                )
                if max_count and len(entries) >= max_count:
                    break
                for p in commit.parents:
                    if p not in visited:
                        queue.append(p)
            except Exception:
                break

        return entries

    @_serialized
    def branch(self, name: str | None = None) -> list[tuple[str, bool]] | str:
        """List branches or create a new branch."""
        if name is None:
            branches = self.refs.list_branches()
            current = self.refs.get_current_branch()
            return [(b, b == current) for b in branches]
        else:
            head_commit_sha = self.refs.get_head_commit()
            if not head_commit_sha:
                raise InvalidReferenceError("Cannot create branch: no commits yet")
            self.refs.create_branch(name, head_commit_sha)
            return name

    def merge_in_progress(self) -> str | None:
        """Return the MERGE_HEAD commit sha if a merge is underway, else None."""
        merge_head_path = self.tinygit_dir / "MERGE_HEAD"
        if not merge_head_path.exists():
            return None
        try:
            value = merge_head_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def _assert_no_merge_in_progress(self, action: str) -> None:
        """Refuse to start a new operation while an unresolved merge is pending.

        MERGE_HEAD is the only record that the next commit has two parents. An
        operation that moves HEAD or starts a second merge while it exists
        silently discards that record, leaving a commit that looks like an
        ordinary one-parent commit even though a merge was in flight.
        """
        if self.merge_in_progress() is not None:
            raise WorkingTreeDirtyError(
                f"You have not concluded your merge (MERGE_HEAD exists). "
                f"Commit it with 'tiny-git commit' or discard it with "
                f"'tiny-git merge --abort' before running {action}."
            )

    @_serialized
    def checkout(self, target: str, force: bool = False) -> str:
        """Checkout a branch or commit after ensuring working tree safety.

        With ``force``, the safety check is skipped and the working tree and
        index are made to match the target exactly. This is the recovery path
        for an operation that failed part-way through its apply phase: the
        snapshot it was aiming at is still intact in the object store, so
        re-materialising HEAD's tree always gets back to a known state. It
        destroys uncommitted work and must never be the default.
        """
        self.index.read()
        if not force:
            self._assert_no_merge_in_progress("checkout")
        target_commit_sha = self.refs.get_ref_commit(target)
        if not target_commit_sha:
            raise InvalidReferenceError(target)

        target_commit = self.store.read_commit(target_commit_sha)
        head_commit_sha = self.refs.get_head_commit()
        head_tree_sha = None
        if head_commit_sha:
            head_commit = self.store.read_commit(head_commit_sha)
            head_tree_sha = head_commit.tree_id

        self.wt.checkout_tree(target_commit.tree_id, head_tree_sha, self.index, self.store, force=force)

        if self.refs.branch_exists(target):
            self.refs.set_head_to_branch(target)
            return f"Switched to branch '{target}'"
        else:
            self.refs.set_head_to_commit(target_commit_sha)
            return f"Note: switching to '{target_commit_sha[:7]}'.\nYou are in 'detached HEAD' state."

    @_serialized
    def merge(self, target_branch: str | None = None, abort: bool = False) -> MergeResult | str:
        """Merge target_branch into current HEAD branch using 3-way merge, or abort current merge."""
        self.index.read()
        merge_head_path = self.tinygit_dir / "MERGE_HEAD"
        merge_mode_path = self.tinygit_dir / "MERGE_MODE"

        if abort:
            if not merge_head_path.exists():
                raise InvalidReferenceError("There is no merge to abort")
            head_commit_sha = self.refs.get_head_commit()
            head_tree_sha = None
            if head_commit_sha:
                head_tree_sha = self.store.read_commit(head_commit_sha).tree_id
            self.wt.checkout_tree(head_tree_sha, None, self.index, self.store, force=True)
            if merge_head_path.exists():
                merge_head_path.unlink()
            if merge_mode_path.exists():
                merge_mode_path.unlink()
            return "Merge aborted."

        if not target_branch:
            raise InvalidReferenceError("No branch specified for merge")

        self._assert_no_merge_in_progress("another merge")

        name, email = self.config.get_user_info()
        res = MergeEngine.merge(target_branch, self.refs, self.index, self.wt, self.store, name, email)
        return res

    def diff(self, cached: bool = False) -> list[FileChange]:
        """Compute unified diff for unstaged or staged changes."""
        self.index.read()
        if cached:
            return DiffEngine.diff_index_head(self.repo_root, self.refs, self.index, self.wt, self.store)
        else:
            return DiffEngine.diff_worktree_index(self.repo_root, self.index, self.wt, self.store)

    def fsck(self) -> FsckResult:
        """Check repository integrity and report any corruption or broken references."""
        return IntegrityChecker.check(self.repo_root, self.store, self.refs, self.index)

    def rev_parse(self, rev: str) -> str:
        """Resolve arbitrary revision expression to full 40-character SHA-1."""
        resolved = RevisionResolver.resolve(rev, self.refs, self.store)
        return resolved.commit_sha

    def cat_file(
        self,
        target: str,
        pretty: bool = True,
        obj_type_only: bool = False,
        size_only: bool = False,
    ) -> str:
        """Inspect a raw object in the database by SHA-1 or revision expression."""
        sha = None
        if len(target) >= 4:
            try:
                sha = self.store.resolve_prefix(target)
            except Exception:
                pass
        if not sha:
            sha = self.rev_parse(target)

        obj = self.store.read_object(sha)
        if obj_type_only:
            return obj.type
        if size_only:
            return str(len(obj.serialize()))
        if pretty:
            if isinstance(obj, Blob):
                return obj.data.decode("utf-8", errors="replace")
            elif isinstance(obj, Commit):
                return obj.serialize().decode("utf-8", errors="replace")
            elif isinstance(obj, Tree):
                lines = []
                for entry in obj.entries:
                    try:
                        sub_obj = self.store.read_object(entry.object_id)
                        sub_type = sub_obj.type
                    except Exception:
                        sub_type = "unknown"
                    lines.append(f"{entry.mode} {sub_type} {entry.object_id} {entry.name}")
                return "\n".join(lines)
        return obj.serialize().decode("utf-8", errors="replace")

    def show(self, rev: str = "HEAD") -> str:
        """Show commit metadata and its diff against its first parent."""
        sha = self.rev_parse(rev)
        commit = self.store.read_commit(sha)

        parent_tree_sha = None
        if commit.parents:
            try:
                parent_commit = self.store.read_commit(commit.parents[0])
                parent_tree_sha = parent_commit.tree_id
            except Exception:
                pass

        changes = DiffEngine.diff_trees(parent_tree_sha, commit.tree_id, self.wt, self.store)
        diff_str = DiffEngine.format_diff(changes)

        lines = [
            f"commit {sha}",
            f"Author: {commit.author_name} <{commit.author_email}>",
            f"Date:   {commit.timestamp}",
            "",
        ]
        for msg_line in commit.message.splitlines():
            lines.append(f"    {msg_line}")
        if not commit.message.splitlines():
            lines.append("    ")
        if diff_str:
            lines.append("")
            lines.append(diff_str)
        return "\n".join(lines)

    @_serialized
    def rm(self, paths: list[str], cached: bool = False, force: bool = False) -> list[str]:
        """Remove files from the index (staged deletion), optionally deleting from disk.

        Without ``force``, refuses to delete a working tree file that carries
        work not present in HEAD -- either staged content that differs from
        HEAD, or local modifications. Such a deletion is unrecoverable: the
        bytes exist nowhere else. ``--cached`` only touches the index, so it is
        never destructive and needs no override.

        Every path is validated before anything is removed, so a bad argument
        cannot leave a partial removal behind.
        """
        self.index.read()

        head_sha = self.refs.get_head_commit()
        head_map: dict[str, tuple[str, str]] = {}
        if head_sha:
            head_map = self.wt.get_tree_entries_flat(self.store.read_commit(head_sha).tree_id, self.store)

        planned = [(original, Path(original).as_posix()) for original in paths]

        # ---- Validate the whole plan first. ----
        for original, posix_p in planned:
            if posix_p not in self.index:
                raise InvalidPathError(original, "Path is not in index")

        if not cached and not force:
            for _original, posix_p in planned:
                head_sha_for_path = head_map[posix_p][0] if posix_p in head_map else None
                entry = self.index.query(posix_p)
                if entry is not None and entry.object_id != head_sha_for_path:
                    raise WorkingTreeDirtyError(
                        f"file '{posix_p}' has staged content different from HEAD (use --force to remove it anyway)"
                    )
                disk_state = self.wt.get_file_state(posix_p)
                if disk_state is not None and disk_state[0] != head_sha_for_path:
                    raise WorkingTreeDirtyError(
                        f"file '{posix_p}' has local modifications (use --force to remove it anyway)"
                    )

        # ---- Apply. ----
        removed = []
        for _original, posix_p in planned:
            self.index.remove(posix_p)
            removed.append(posix_p)
            if not cached:
                self.wt.remove_file(posix_p)
        self.index.write()
        return sorted(removed)

    @_serialized
    def restore(self, paths: list[str], staged: bool = False) -> list[str]:
        """Restore working tree files from index (or unstage index files from HEAD)."""
        self.index.read()
        head_sha = self.refs.get_head_commit()
        head_map: dict[str, tuple[str, str]] = {}
        if head_sha:
            commit_obj = self.store.read_commit(head_sha)
            head_map = self.wt.get_tree_entries_flat(commit_obj.tree_id, self.store)

        restored = []
        for p in paths:
            posix_p = Path(p).as_posix()
            if staged:
                if posix_p in head_map:
                    sha, mode = head_map[posix_p]
                    full_p = self.repo_root / posix_p
                    size = full_p.stat().st_size if full_p.exists() else 0
                    mtime = full_p.stat().st_mtime if full_p.exists() else 0.0
                    self.index.add(posix_p, sha, mode=mode, size=size, mtime=mtime)
                else:
                    self.index.remove(posix_p)
                restored.append(posix_p)
            else:
                if posix_p in self.index:
                    entry = self.index.query(posix_p)
                    assert entry is not None
                    blob = self.store.read_blob(entry.object_id)
                    self.wt.write_file(posix_p, blob.data, mode=entry.mode)
                    restored.append(posix_p)
                elif posix_p in head_map:
                    sha, mode = head_map[posix_p]
                    blob = self.store.read_blob(sha)
                    self.wt.write_file(posix_p, blob.data, mode=mode)
                    restored.append(posix_p)
                else:
                    raise InvalidPathError(p, "Path not in index or HEAD")

        if staged:
            self.index.write()
        return sorted(restored)
