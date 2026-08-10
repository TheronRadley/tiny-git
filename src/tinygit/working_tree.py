"""Working directory operations and tree/snapshot conversions for Tiny Git.

Handles scanning the working tree, building tree objects from the index,
restoring snapshots to disk, and protecting uncommitted user work during checkouts.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from tinygit.errors import WorkingTreeDirtyError
from tinygit.index import Index, IndexEntry
from tinygit.objects import ObjectStore, Tree, TreeEntry, hash_object
from tinygit.utils import get_file_mode, is_ignored, validate_path


class WorkingTree:
    """Manages files in the working directory and snapshot restoration."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def list_files(self) -> list[str]:
        """List all tracked/unignored regular files in the working tree as POSIX relative paths."""
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
                        files.append(rel)
                except Exception:
                    pass

        return sorted(files)

    def read_file(self, rel_path: str) -> bytes:
        """Read a file from the working tree after validating its path."""
        target_path = validate_path(rel_path, self.repo_root)
        return target_path.read_bytes()

    def write_file(self, rel_path: str, content: bytes, mode: str = "100644") -> None:
        """Write content to a file in the working tree, creating directories as needed."""
        target_path = validate_path(rel_path, self.repo_root)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

        if mode == "100755":
            try:
                st = os.stat(target_path)
                os.chmod(target_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except Exception:
                pass

    def remove_file(self, rel_path: str) -> bool:
        """Remove a file from the working tree and clean up empty parent directories."""
        try:
            target_path = validate_path(rel_path, self.repo_root)
            if target_path.exists() and target_path.is_file():
                target_path.unlink()
                # Clean up empty parent directories up to repo_root
                parent = target_path.parent
                while parent != self.repo_root:
                    try:
                        parent.rmdir()  # Fails if directory is not empty
                        parent = parent.parent
                    except Exception:
                        break
                return True
        except Exception:
            pass
        return False

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

    @classmethod
    def build_tree_from_index(cls, index: Index, store: ObjectStore) -> str:
        """Build nested Tree objects from index entries and store them in ObjectStore.

        Returns the root Tree SHA-1.
        """
        entries = {entry.path: entry for entry in index.list_entries()}
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
        """Recursively flatten a tree object into a mapping of POSIX path -> (blob_sha, mode)."""
        if not tree_sha:
            return {}
        try:
            tree = store.read_tree(tree_sha)
        except Exception:
            return {}

        result: dict[str, tuple[str, str]] = {}
        for entry in tree.entries:
            path_name = f"{prefix}/{entry.name}" if prefix else entry.name
            if entry.mode == "040000":
                sub_res = cls.get_tree_entries_flat(entry.object_id, store, prefix=path_name)
                result.update(sub_res)
            else:
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

        all_changing_paths = set(head_map.keys()) | set(target_map.keys())
        for path in sorted(all_changing_paths):
            head_val = head_map.get(path)
            target_val = target_map.get(path)

            if head_val == target_val:
                continue

            head_sha = head_val[0] if head_val else None
            target_sha = target_val[0] if target_val else None

            # Check 1: Staged modifications in index
            staged_entry = index.query(path)
            if staged_entry is not None:
                staged_sha = staged_entry.object_id
                # If staged content differs from target AND differs from HEAD
                if staged_sha != target_sha and (head_sha is None or staged_sha != head_sha):
                    raise WorkingTreeDirtyError(
                        f"Your local changes to staged file '{path}' would be overwritten by checkout."
                    )
            elif head_val is not None and target_val is not None:
                # File was in HEAD, but removed from index (staged deletion)
                # If target branch has this file, checkout would overwrite the staged deletion
                raise WorkingTreeDirtyError(
                    f"Your staged deletion of file '{path}' would be overwritten by checkout."
                )

            # Check 2: Unstaged modifications or untracked files on disk
            disk_sha = self.get_file_sha1(path)
            if disk_sha is not None:
                # If disk content differs from target AND (file was untracked in HEAD OR differs from HEAD)
                if disk_sha != target_sha and (head_sha is None or disk_sha != head_sha):
                    if head_sha is None:
                        raise WorkingTreeDirtyError(
                            f"Untracked working tree file '{path}' would be overwritten by checkout."
                        )
                    else:
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
        """Safely switch working directory and index to match target_tree_sha."""
        if not force:
            self.check_safe_checkout(target_tree_sha, head_tree_sha, index, store)

        head_map = self.get_tree_entries_flat(head_tree_sha, store)
        target_map = self.get_tree_entries_flat(target_tree_sha, store)

        # 1. Remove files that were tracked in HEAD or index but are not in target_map
        current_tracked = {e.path for e in index.list_entries()} | set(head_map.keys())
        for path in sorted(current_tracked):
            if path not in target_map:
                self.remove_file(path)

        # 2. Write all files from target_map to the working tree
        for path, (sha, mode) in target_map.items():
            blob = store.read_blob(sha)
            self.write_file(path, blob.data, mode=mode)

        # 3. Rebuild the index to match target_map
        index.clear()
        for path, (sha, mode) in sorted(target_map.items()):
            full_path = self.repo_root / path
            size = full_path.stat().st_size if full_path.exists() else 0
            mtime = full_path.stat().st_mtime if full_path.exists() else 0.0
            index.add(path, sha, mode=mode, size=size, mtime=mtime)
        index.write()
