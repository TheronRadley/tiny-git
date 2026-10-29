"""Unified diff engine for Tiny Git.

Compares snapshots across:
  - Working Tree <-> Index (tiny-git diff)
  - Index <-> HEAD (tiny-git diff --cached)
  - Tree <-> Tree (arbitrary commit snapshots)
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from tinygit.index import Index
from tinygit.objects import ObjectStore
from tinygit.refs import ReferenceManager
from tinygit.utils import is_binary_bytes
from tinygit.working_tree import WorkingTree


@dataclass
class FileChange:
    """Represents a change to a single file between two snapshots."""

    path: str
    old_sha: str | None
    new_sha: str | None
    old_mode: str | None
    new_mode: str | None
    old_content: bytes | None
    new_content: bytes | None

    @property
    def is_binary(self) -> bool:
        return is_binary_bytes(self.old_content or b"") or is_binary_bytes(self.new_content or b"")

    def to_unified_diff(self) -> str:
        """Format this change as a standard unified diff string."""
        if self.old_content == self.new_content and self.old_mode == self.new_mode:
            return ""

        if self.is_binary:
            old_name = f"a/{self.path}" if self.old_content is not None else "/dev/null"
            new_name = f"b/{self.path}" if self.new_content is not None else "/dev/null"
            return f"Binary files {old_name} and {new_name} differ\n"

        old_lines = (self.old_content or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        new_lines = (self.new_content or b"").decode("utf-8", errors="replace").splitlines(keepends=True)

        fromfile = f"a/{self.path}" if self.old_content is not None else "/dev/null"
        tofile = f"b/{self.path}" if self.new_content is not None else "/dev/null"

        diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile))
        if not diff_lines:
            # Content is identical but the mode is not: a mode-only change has
            # no hunks, so report it the way git does rather than printing
            # nothing and making the change invisible.
            if self.old_mode != self.new_mode and self.old_mode and self.new_mode:
                return f"diff --git a/{self.path} b/{self.path}\nold mode {self.old_mode}\nnew mode {self.new_mode}\n"
            return ""
        # Ensure trailing newline
        diff_str = "".join(diff_lines)
        if not diff_str.endswith("\n"):
            diff_str += "\n"
        return diff_str


class DiffEngine:
    """Service for computing diffs between snapshots."""

    @staticmethod
    def diff_worktree_index(repo_root: Path, index: Index, wt: WorkingTree, store: ObjectStore) -> list[FileChange]:
        """Compute diff between Working Tree and Index (tiny-git diff)."""
        changes = []
        disk_files = set(wt.list_files(always_include=[e.path for e in index.list_stage0_entries()]))

        for entry in index.list_stage0_entries():
            path = entry.path
            old_blob = store.read_blob(entry.object_id)
            old_content = old_blob.data

            if path not in disk_files:
                changes.append(
                    FileChange(
                        path=path,
                        old_sha=entry.object_id,
                        new_sha=None,
                        old_mode=entry.mode,
                        new_mode=None,
                        old_content=old_content,
                        new_content=None,
                    )
                )
            else:
                disk_state = wt.get_file_state(path)
                disk_sha = disk_state[0] if disk_state else None
                if disk_state is not None and disk_state != (entry.object_id, entry.mode):
                    new_content = wt.read_file(path)
                    changes.append(
                        FileChange(
                            path=path,
                            old_sha=entry.object_id,
                            new_sha=disk_sha,
                            old_mode=entry.mode,
                            new_mode=wt.get_file_mode(path),
                            old_content=old_content,
                            new_content=new_content,
                        )
                    )
        return sorted(changes, key=lambda c: c.path)

    @staticmethod
    def diff_index_head(
        repo_root: Path,
        refs: ReferenceManager,
        index: Index,
        wt: WorkingTree,
        store: ObjectStore,
    ) -> list[FileChange]:
        """Compute diff between Index and HEAD (tiny-git diff --cached)."""
        changes = []
        head_commit = refs.get_head_commit()

        head_map: dict[str, tuple[str, str]] = {}
        if head_commit:
            commit_obj = store.read_commit(head_commit)
            head_map = wt.get_tree_entries_flat(commit_obj.tree_id, store)

        index_map: dict[str, tuple[str, str]] = {
            entry.path: (entry.object_id, entry.mode) for entry in index.list_stage0_entries()
        }

        all_paths = set(head_map.keys()) | set(index_map.keys())
        for path in sorted(all_paths):
            head_val = head_map.get(path)
            idx_val = index_map.get(path)

            if head_val == idx_val:
                continue

            old_sha, old_mode = head_val if head_val else (None, None)
            new_sha, new_mode = idx_val if idx_val else (None, None)

            old_content = store.read_blob(old_sha).data if old_sha else None
            new_content = store.read_blob(new_sha).data if new_sha else None

            changes.append(
                FileChange(
                    path=path,
                    old_sha=old_sha,
                    new_sha=new_sha,
                    old_mode=old_mode,
                    new_mode=new_mode,
                    old_content=old_content,
                    new_content=new_content,
                )
            )

        return changes

    @staticmethod
    def diff_trees(
        old_tree_sha: str | None,
        new_tree_sha: str | None,
        wt: WorkingTree,
        store: ObjectStore,
    ) -> list[FileChange]:
        """Compute diff between two arbitrary Tree snapshots."""
        old_map = wt.get_tree_entries_flat(old_tree_sha, store)
        new_map = wt.get_tree_entries_flat(new_tree_sha, store)

        changes = []
        all_paths = sorted(set(old_map.keys()) | set(new_map.keys()))
        for path in all_paths:
            old_val = old_map.get(path)
            new_val = new_map.get(path)

            if old_val == new_val:
                continue

            old_sha, old_mode = old_val if old_val else (None, None)
            new_sha, new_mode = new_val if new_val else (None, None)

            old_content = store.read_blob(old_sha).data if old_sha else None
            new_content = store.read_blob(new_sha).data if new_sha else None

            changes.append(
                FileChange(
                    path=path,
                    old_sha=old_sha,
                    new_sha=new_sha,
                    old_mode=old_mode,
                    new_mode=new_mode,
                    old_content=old_content,
                    new_content=new_content,
                )
            )

        return changes

    @classmethod
    def format_diff(cls, changes: list[FileChange]) -> str:
        """Format a list of FileChange objects into unified diff output string."""
        parts = []
        for change in changes:
            diff_str = change.to_unified_diff()
            if diff_str:
                parts.append(diff_str)
        return "".join(parts).rstrip()
