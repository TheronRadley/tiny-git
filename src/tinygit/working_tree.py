"""Working directory operations and tree/snapshot conversions for Tiny Git.

Handles scanning the working tree, building tree objects from the index,
restoring snapshots to disk, and protecting uncommitted user work during checkouts.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from tinygit.errors import WorkingTreeDirtyError
from tinygit.index import Index, IndexEntry
from tinygit.objects import ObjectStore, Tree, TreeEntry, hash_object
from tinygit.utils import (
    apply_file_mode,
    get_file_mode,
    is_ignored,
    is_path_ignored,
    load_ignore_patterns,
    validate_path,
    validate_relative_path,
)


class WorkingTree:
    """Manages files in the working directory and snapshot restoration."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def list_files(self, always_include: Iterable[str] = ()) -> list[str]:
        """List all regular files in the working tree as POSIX relative paths.

        Skips version-control metadata and anything matched by `.tinygitignore`.

        ``always_include`` names paths that stay visible even when an ignore
        pattern matches them. Every caller that compares against the index must
        pass the tracked paths here: a file that was committed before its ignore
        rule existed is still tracked, and dropping it from this list would make
        `add .` stage a deletion and `status` report the file as removed.
        """
        ignore_patterns = load_ignore_patterns(self.repo_root)
        keep = set(always_include)
        files = []
        for root, dirs, filenames in os.walk(self.repo_root):
            root_path = Path(root)
            # Filter out ignored directories in-place so os.walk doesn't descend into them
            dirs[:] = [d for d in dirs if not is_ignored(root_path / d, self.repo_root)]

            for filename in filenames:
                file_path = root_path / filename
                if file_path.is_symlink() or is_ignored(file_path, self.repo_root):
                    continue
                try:
                    if file_path.is_file():
                        rel = file_path.relative_to(self.repo_root).as_posix()
                        if rel not in keep and is_path_ignored(rel, ignore_patterns):
                            continue
                        files.append(rel)
                except Exception:
                    pass

        return sorted(files)

    def read_file(self, rel_path: str) -> bytes:
        """Read a file from the working tree after validating its path."""
        target_path = validate_path(rel_path, self.repo_root)
        return target_path.read_bytes()

    def write_file(self, rel_path: str, content: bytes, mode: str = "100644") -> None:
        """Write content to a file in the working tree, creating directories as needed.

        The path is validated as a repository-relative path first, so a tree
        entry naming metadata or traversing upwards can never be materialised.
        """
        validate_relative_path(rel_path)
        target_path = validate_path(rel_path, self.repo_root)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        apply_file_mode(target_path, mode)

    def remove_file(self, rel_path: str) -> bool:
        """Remove a file from the working tree and clean up empty parent directories.

        Returns True if a file was removed. Failures to unlink are propagated:
        silently swallowing them would let a checkout report success while
        leaving the working tree in a state that matches neither snapshot.
        Cleanup of now-empty parent directories stays best-effort.
        """
        validate_relative_path(rel_path)
        target_path = validate_path(rel_path, self.repo_root)
        if not (target_path.exists() and target_path.is_file()):
            return False

        target_path.unlink()

        parent = target_path.parent
        while parent != self.repo_root:
            try:
                parent.rmdir()  # Fails if directory is not empty
            except OSError:
                break
            parent = parent.parent
        return True

    def get_file_sha1(self, rel_path: str) -> str | None:
        """Compute the SHA-1 blob hash of a file currently in the working tree."""
        try:
            target_path = validate_path(rel_path, self.repo_root)
            if not target_path.is_file():
                return None
            data = target_path.read_bytes()
            sha, _ = hash_object("blob", data)
            return sha
        except Exception:
            return None

    def get_file_mode(self, rel_path: str) -> str:
        """Get the mode of a file in the working tree."""
        target_path = validate_path(rel_path, self.repo_root)
        return get_file_mode(target_path)

    def get_file_state(self, rel_path: str) -> tuple[str, str] | None:
        """Return (sha, mode) for a working tree file, or None if it is absent.

        Comparing mode alongside content is what lets a mode-only change -- the
        executable bit toggled with no edit to the bytes -- be detected at all.
        """
        sha = self.get_file_sha1(rel_path)
        if sha is None:
            return None
        try:
            mode = self.get_file_mode(rel_path)
        except Exception:
            mode = "100644"
        return (sha, mode)

    @classmethod
    def build_tree_from_index(cls, index: Index, store: ObjectStore) -> str:
        """Build nested Tree objects from index entries and store them in ObjectStore.

        Returns the root Tree SHA-1.
        """
        entries = {entry.path: entry for entry in index.list_entries() if entry.stage == 0}
        return cls._build_tree_recursive(entries, store)

    @classmethod
    def _build_tree_recursive(cls, entries: dict[str, IndexEntry], store: ObjectStore) -> str:
        """Recursively build trees for a dictionary of relative paths -> IndexEntry."""
        tree_entries: list[TreeEntry] = []
        files_in_dir: dict[str, IndexEntry] = {}
        dirs_in_dir: dict[str, dict[str, IndexEntry]] = {}

        for path, entry in entries.items():
            if "/" not in path:
                files_in_dir[path] = entry
            else:
                top_dir, rest = path.split("/", 1)
                if top_dir not in dirs_in_dir:
                    dirs_in_dir[top_dir] = {}
                dirs_in_dir[top_dir][rest] = entry

        for name, entry in files_in_dir.items():
            tree_entries.append(TreeEntry(mode=entry.mode, name=name, object_id=entry.object_id))

        for dir_name, sub_entries in dirs_in_dir.items():
            sub_tree_sha = cls._build_tree_recursive(sub_entries, store)
            tree_entries.append(TreeEntry(mode="040000", name=dir_name, object_id=sub_tree_sha))

        tree = Tree(tree_entries)
        return store.write_object(tree)

    @classmethod
    def get_tree_entries_flat(
        cls, tree_sha: str | None, store: ObjectStore, prefix: str = ""
    ) -> dict[str, tuple[str, str]]:
        """Recursively flatten a tree object into a mapping of POSIX path -> (blob_sha, mode).

        A missing or corrupt tree raises rather than flattening to an empty
        mapping. An empty mapping means "this snapshot contains no files", which
        for a checkout is an instruction to delete the entire working tree --
        the wrong answer to give when the real problem is an unreadable object.
        Only a genuinely absent tree_sha (an unborn branch) yields {}.
        """
        if not tree_sha:
            return {}
        tree = store.read_tree(tree_sha)

        result: dict[str, tuple[str, str]] = {}
        for entry in tree.entries:
            path_name = f"{prefix}/{entry.name}" if prefix else entry.name
            if entry.mode == "040000":
                sub_res = cls.get_tree_entries_flat(entry.object_id, store, prefix=path_name)
                result.update(sub_res)
            else:
                # Tree.parse validates each entry name; this validates the whole
                # flattened path, so a nested metadata directory is caught too.
                validate_relative_path(path_name)
                result[path_name] = (entry.object_id, entry.mode)
        return result

    def check_safe_checkout(
        self,
        target_tree_sha: str | None,
        head_tree_sha: str | None,
        index: Index,
        store: ObjectStore,
    ) -> None:
        """Verify that checking out target_tree_sha will not overwrite uncommitted work.

        Raises WorkingTreeDirtyError if uncommitted changes would be lost.
        """
        head_map = self.get_tree_entries_flat(head_tree_sha, store)
        target_map = self.get_tree_entries_flat(target_tree_sha, store)
        changing = _changing_paths(head_map, target_map)
        self._check_changing_paths_safe(changing, head_map, target_map, index)

    def _check_changing_paths_safe(
        self,
        changing: set[str],
        head_map: dict[str, tuple[str, str]],
        target_map: dict[str, tuple[str, str]],
        index: Index,
    ) -> None:
        """Refuse if any path about to be rewritten carries uncommitted work."""
        for path in sorted(changing):
            head_val = head_map.get(path)
            target_val = target_map.get(path)
            head_sha = head_val[0] if head_val else None
            target_sha = target_val[0] if target_val else None

            # Check 1: Staged modifications in index
            staged_entry = index.query(path)
            if staged_entry is not None:
                staged_sha = staged_entry.object_id
                if staged_sha != target_sha and (head_sha is None or staged_sha != head_sha):
                    raise WorkingTreeDirtyError(
                        f"Your local changes to staged file '{path}' would be overwritten by checkout."
                    )
            elif head_val is not None and target_val is not None:
                # File was in HEAD, but removed from index (staged deletion)
                # If target branch has this file, checkout would overwrite the staged deletion
                raise WorkingTreeDirtyError(f"Your staged deletion of file '{path}' would be overwritten by checkout.")

            # Check 2: Unstaged modifications (content or mode) or untracked files on disk
            disk_state = self.get_file_state(path)
            if disk_state is not None:
                disk_sha, disk_mode = disk_state
                head_mode = head_val[1] if head_val else None
                content_dirty = disk_sha != target_sha and (head_sha is None or disk_sha != head_sha)
                mode_dirty = (
                    head_mode is not None
                    and disk_mode != head_mode
                    and disk_mode != (target_val[1] if target_val else disk_mode)
                )
                if content_dirty or mode_dirty:
                    if head_sha is None:
                        raise WorkingTreeDirtyError(
                            f"Untracked working tree file '{path}' would be overwritten by checkout."
                        )
                    raise WorkingTreeDirtyError(
                        f"Your local changes to file '{path}' would be overwritten by checkout."
                    )

    def checkout_tree(
        self,
        target_tree_sha: str | None,
        head_tree_sha: str | None,
        index: Index,
        store: ObjectStore,
        force: bool = False,
    ) -> None:
        """Switch working directory and index to match target_tree_sha.

        Validated and applied in two phases. Phase one reads both trees, computes
        the complete mutation plan, resolves every blob it will write, and runs
        the safety check -- all before a single byte on disk changes. Phase two
        applies it. A failure anywhere in phase one therefore leaves the working
        tree, the index, and HEAD exactly as they were.

        Only paths that differ between the two trees are touched. Files that are
        identical in both snapshots keep their working-tree contents and their
        index entry, which is what preserves unstaged edits and newly staged
        files when the target happens to be the branch already checked out.
        """
        # ---- Phase 1: validate and plan. No mutation happens here. ----
        head_map = self.get_tree_entries_flat(head_tree_sha, store)
        target_map = self.get_tree_entries_flat(target_tree_sha, store)

        changing = _changing_paths(head_map, target_map)

        if not force:
            self._check_changing_paths_safe(changing, head_map, target_map, index)

        tracked = set(head_map) | {e.path for e in index.list_entries()}

        if force:
            # Forced means "make the working tree and index match the target
            # exactly", which is the recovery path after a partially applied
            # operation. Every target path is rewritten, not just the ones that
            # differ from HEAD, because the working tree may already have been
            # partly rewritten by whatever failed.
            doomed = tracked - set(target_map)
            to_write_set = set(target_map)
        else:
            # Only paths that differ between the two snapshots are candidates, so
            # a file staged but present in neither snapshot survives.
            doomed = {p for p in changing if p not in target_map}
            # Plus any tracked file that is simply missing from disk: restoring an
            # absent file cannot destroy uncommitted work, and leaving it absent
            # would mean "checked out" does not mean "matches the snapshot".
            missing = {p for p in target_map if not (self.repo_root / p).is_file()}
            to_write_set = {p for p in changing if p in target_map} | missing

        to_remove = sorted(doomed)
        to_write = sorted(to_write_set - doomed)

        # Resolve every payload up front so a missing blob aborts the whole
        # operation instead of leaving a half-written working tree.
        payloads: dict[str, tuple[bytes, str]] = {}
        for path in to_write:
            sha, mode = target_map[path]
            payloads[path] = (store.read_blob(sha).data, mode)

        for path in to_remove + to_write:
            validate_relative_path(path)

        # ---- Phase 2: apply. ----
        for path in to_remove:
            self.remove_file(path)
        for path in to_write:
            data, mode = payloads[path]
            self.write_file(path, data, mode=mode)

        for path in to_remove:
            index.remove(path)
        for path in to_write:
            sha, mode = target_map[path]
            full_path = self.repo_root / path
            size = full_path.stat().st_size if full_path.exists() else 0
            mtime = full_path.stat().st_mtime if full_path.exists() else 0.0
            index.add(path, sha, mode=mode, size=size, mtime=mtime)
        index.write()


def _changing_paths(head_map: dict[str, tuple[str, str]], target_map: dict[str, tuple[str, str]]) -> set[str]:
    """Return the paths whose (blob, mode) differs between two snapshots."""
    return {p for p in set(head_map) | set(target_map) if head_map.get(p) != target_map.get(p)}
