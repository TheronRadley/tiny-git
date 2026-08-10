"""Staging area (index) implementation for Tiny Git.

The index stores the proposed next commit snapshot as a structured list of entries
mapping POSIX relative file paths to content-addressed Blob SHA-1 IDs and file modes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from tinygit.errors import InvalidObjectError, InvalidPathError
from tinygit.utils import atomic_write_file


@dataclass
class IndexEntry:
    """An entry in the staging area (index)."""

    path: str
    object_id: str
    mode: str = "100644"
    stat_size: int = 0
    stat_mtime: float = 0.0
    stage: int = 0

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "path": self.path,
            "object_id": self.object_id,
            "mode": self.mode,
            "stat_size": self.stat_size,
            "stat_mtime": self.stat_mtime,
            "stage": self.stage,
        }

    @classmethod
    def from_dict(cls, d: dict[str, str | int | float]) -> IndexEntry:
        return cls(
            path=str(d["path"]),
            object_id=str(d["object_id"]),
            mode=str(d.get("mode", "100644")),
            stat_size=int(d.get("stat_size", 0)),
            stat_mtime=float(d.get("stat_mtime", 0.0)),
            stage=int(d.get("stage", 0)),
        )

    def validate(self) -> None:
        """Validate index entry invariants."""
        if not self.path or "/" in self.path[:1] or "\\" in self.path:
            raise InvalidObjectError("index", f"Invalid path in index: {self.path}")
        parts = self.path.split("/")
        if ".tinygit" in parts or ".." in parts or "." in parts:
            raise InvalidObjectError("index", f"Disallowed path component in index: {self.path}")
        if self.mode not in ("100644", "100755", "040000"):
            raise InvalidObjectError("index", f"Invalid file mode in index: {self.mode}")
        if not re.match(r"^[0-9a-fA-F]{40}$", self.object_id):
            raise InvalidObjectError("index", f"Invalid object SHA-1 in index: {self.object_id}")
        if self.stage not in (0, 1, 2, 3):
            raise InvalidObjectError("index", f"Invalid stage {self.stage} in index for path: {self.path}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IndexEntry):
            return False
        return (
            self.path == other.path
            and self.object_id == other.object_id
            and self.mode == other.mode
            and self.stage == other.stage
        )


class Index:
    """Manages the staging area (.tinygit/index).

    Supports add, remove, update, query, write, and read operations,
    enforcing normalized relative paths, uniqueness, stage (0..3) for merges,
    and atomic writes.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.index_path = repo_root / ".tinygit" / "index"
        self._entries: dict[tuple[str, int], IndexEntry] = {}

    def read(self) -> None:
        """Read the index from disk into memory."""
        self._entries.clear()
        if not self.index_path.exists():
            return
        try:
            with open(self.index_path, encoding="utf-8") as f:
                data = json.load(f)
            for entry_dict in data:
                entry = IndexEntry.from_dict(entry_dict)
                entry.validate()
                self._entries[(entry.path, entry.stage)] = entry
        except Exception as e:
            raise InvalidObjectError("index", f"Corrupted index file: {e}") from e

    def write(self) -> None:
        """Write current index entries atomically to disk."""
        for entry in self._entries.values():
            entry.validate()
        sorted_entries = [self._entries[key].to_dict() for key in sorted(self._entries.keys())]
        json_str = json.dumps(sorted_entries, indent=2) + "\n"
        atomic_write_file(self.index_path, json_str)

    def add(
        self,
        path: str,
        object_id: str,
        mode: str = "100644",
        size: int = 0,
        mtime: float = 0.0,
        stage: int = 0,
    ) -> None:
        """Add or update a file entry in the index at a specific stage (0=normal, 1-3=conflict)."""
        posix_path = Path(path).as_posix()
        if posix_path.startswith("/") or ".tinygit" in posix_path.split("/") or ".." in posix_path.split("/"):
            raise InvalidPathError(path, "Disallowed path in index staging")
        entry = IndexEntry(
            path=posix_path,
            object_id=object_id,
            mode=mode,
            stat_size=size,
            stat_mtime=mtime,
            stage=stage,
        )
        entry.validate()
        # Adding a normal stage 0 entry clears any conflicting entries (stage 1, 2, 3) for that path
        if stage == 0:
            for st in (1, 2, 3):
                self._entries.pop((posix_path, st), None)
        self._entries[(posix_path, stage)] = entry

    def remove(self, path: str, stage: int | None = None) -> bool:
        """Remove a file entry from the index. If stage is None, removes all stages for path."""
        posix_path = Path(path).as_posix()
        removed = False
        if stage is None:
            for st in (0, 1, 2, 3):
                if (posix_path, st) in self._entries:
                    del self._entries[(posix_path, st)]
                    removed = True
        else:
            if (posix_path, stage) in self._entries:
                del self._entries[(posix_path, stage)]
                removed = True
        return removed

    def update(
        self,
        path: str,
        object_id: str,
        mode: str = "100644",
        size: int = 0,
        mtime: float = 0.0,
        stage: int = 0,
    ) -> None:
        """Update an entry in the index."""
        self.add(path, object_id, mode=mode, size=size, mtime=mtime, stage=stage)

    def query(self, path: str, stage: int = 0) -> IndexEntry | None:
        """Query for an entry by path and stage (default stage=0)."""
        posix_path = Path(path).as_posix()
        return self._entries.get((posix_path, stage))

    def list_entries(self) -> list[IndexEntry]:
        """Return all staged entries sorted by (path, stage)."""
        return [self._entries[key] for key in sorted(self._entries.keys())]

    def has_unmerged_paths(self) -> bool:
        """Check if any entries are unmerged (stage > 0)."""
        return any(key[1] > 0 for key in self._entries.keys())

    def get_unmerged_paths(self) -> list[str]:
        """Return sorted list of distinct paths that have entries with stage > 0."""
        return sorted({key[0] for key in self._entries.keys() if key[1] > 0})

    def clear(self) -> None:
        """Clear all staged entries in the index."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, path: str) -> bool:
        posix_path = Path(path).as_posix()
        return any(key[0] == posix_path for key in self._entries.keys())
