"""Content-addressable object storage for Tiny Git.

Implements SHA-1 content-addressed objects:
  - Blob: file contents
  - Tree: directory structures
  - Commit: repository snapshots with metadata
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from tinygit.errors import InvalidObjectError, ObjectNotFoundError
from tinygit.utils import METADATA_DIR_NAMES, atomic_write_file


class HashAlgorithm(Enum):
    """Supported cryptographic hash algorithms for content-addressable objects.

    V1 Object Format: SHA-1
    Reason:
      - mirrors Git's historical object model
      - keeps the implementation educational
      - is NOT intended to provide modern collision resistance
    """

    SHA1 = "sha1"
    # Architectural extension point: SHA256 = "sha256"


def get_hasher(algorithm: HashAlgorithm = HashAlgorithm.SHA1) -> hashlib._Hash:
    """Get a hash object for the specified cryptographic hash algorithm."""
    if algorithm == HashAlgorithm.SHA1:
        return hashlib.sha1()
    raise NotImplementedError(f"Unsupported hash algorithm: {algorithm}")


def hash_object(
    obj_type: str,
    content: bytes,
    algorithm: HashAlgorithm = HashAlgorithm.SHA1,
) -> tuple[str, bytes]:
    """Create the formatted Git object payload (<type> <size>\\0<content>) and its digest."""
    header = f"{obj_type} {len(content)}\0".encode()
    raw = header + content
    hasher = get_hasher(algorithm)
    hasher.update(raw)
    return hasher.hexdigest(), raw


class GitObject:
    """Base class for all content-addressed Tiny Git objects."""

    type: str

    def serialize(self) -> bytes:
        raise NotImplementedError

    def get_hash(self) -> str:
        sha, _ = hash_object(self.type, self.serialize())
        return sha

    @classmethod
    def parse(cls, data: bytes) -> GitObject:
        raise NotImplementedError


class Blob(GitObject):
    """A blob object representing raw file content."""

    type = "blob"

    def __init__(self, data: bytes) -> None:
        self.data = data

    def serialize(self) -> bytes:
        return self.data

    @classmethod
    def parse(cls, data: bytes) -> Blob:
        return cls(data)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Blob):
            return False
        return self.data == other.data


# Modes a tree entry may carry. Symlinks (120000) and gitlinks (160000) are
# deliberately unsupported in V1; see docs/git-comparison.md.
VALID_TREE_MODES = frozenset({"100644", "100755", "040000"})

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def validate_tree_entry_name(name: str) -> str:
    """Validate a single tree entry name and return it unchanged.

    A tree entry name is one path component, never a path. The tree text format
    is ``<mode> <sha> <name>\n``, so a name containing a newline silently
    corrupts every following entry, and a name containing a separator would let
    a crafted tree write outside the directory it names.
    """
    if not name:
        raise InvalidObjectError("tree", "Empty tree entry name")
    if name in (".", ".."):
        raise InvalidObjectError("tree", f"Traversal tree entry name: {name!r}")
    if "/" in name or "\\" in name:
        raise InvalidObjectError("tree", f"Tree entry name contains a path separator: {name!r}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise InvalidObjectError("tree", f"Tree entry name contains a control character: {name!r}")
    if name in METADATA_DIR_NAMES:
        raise InvalidObjectError("tree", f"Tree entry name is reserved metadata: {name!r}")
    return name


@dataclass(order=True)
class TreeEntry:
    """An entry in a tree object (file or directory)."""

    mode: str
    name: str
    object_id: str

    def validate(self) -> None:
        """Validate this entry's mode, name, and object id."""
        validate_tree_entry_name(self.name)
        if self.mode not in VALID_TREE_MODES:
            raise InvalidObjectError("tree", f"Unsupported tree entry mode: {self.mode!r}")
        if not _SHA1_RE.match(self.object_id):
            raise InvalidObjectError("tree", f"Invalid object id in tree entry {self.name!r}: {self.object_id!r}")


class Tree(GitObject):
    """A tree object representing a directory structure."""

    type = "tree"

    def __init__(self, entries: list[TreeEntry] | None = None) -> None:
        self.entries = sorted(entries or [], key=lambda e: e.name)
        self.validate_entries()

    def validate_entries(self) -> None:
        """Validate every entry and reject duplicate names.

        Duplicates make a tree ambiguous -- two blobs claim the same path -- so
        they are rejected on both construction and parse rather than being
        silently resolved by last-write-wins.
        """
        seen: set[str] = set()
        for entry in self.entries:
            entry.validate()
            if entry.name in seen:
                raise InvalidObjectError("tree", f"Duplicate tree entry name: {entry.name!r}")
            seen.add(entry.name)

    def serialize(self) -> bytes:
        lines = []
        for e in self.entries:
            lines.append(f"{e.mode} {e.object_id} {e.name}\n")
        return "".join(lines).encode("utf-8")

    @classmethod
    def parse(cls, data: bytes) -> Tree:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise InvalidObjectError("tree", f"Tree payload is not valid UTF-8: {e}") from e
        entries = []
        for line in text.splitlines():
            if not line.strip():
                continue
            parts = line.split(" ", 2)
            if len(parts) != 3:
                raise InvalidObjectError("tree", f"Invalid tree entry format: {line}")
            mode, sha, name = parts
            entries.append(TreeEntry(mode=mode, name=name, object_id=sha))
        return cls(entries)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tree):
            return False
        return self.entries == other.entries


@dataclass
class Commit(GitObject):
    """A commit object representing a repository snapshot and its history."""

    tree_id: str
    parents: list[str] = field(default_factory=list)
    author_name: str = "Ron"
    author_email: str = "ron@example.com"
    timestamp: str = "2026-08-09 00:00:00"
    message: str = ""

    type = "commit"

    def serialize(self) -> bytes:
        lines = [f"tree {self.tree_id}"]
        for p in self.parents:
            lines.append(f"parent {p}")
        lines.append(f"author {self.author_name} <{self.author_email}> {self.timestamp}")
        lines.append("")
        lines.append(self.message)
        return "\n".join(lines).encode("utf-8")

    @classmethod
    def parse(cls, data: bytes) -> Commit:
        text = data.decode("utf-8")
        parts = text.split("\n\n", 1)
        headers_block = parts[0]
        message = parts[1] if len(parts) > 1 else ""

        tree_id = ""
        parents = []
        author_name = "Unknown"
        author_email = "unknown@example.com"
        timestamp = ""

        for line in headers_block.splitlines():
            if line.startswith("tree "):
                tree_id = line[5:].strip()
            elif line.startswith("parent "):
                parents.append(line[7:].strip())
            elif line.startswith("author "):
                author_line = line[7:].strip()
                if "<" in author_line and ">" in author_line:
                    left = author_line.index("<")
                    right = author_line.index(">")
                    author_name = author_line[:left].strip()
                    author_email = author_line[left + 1 : right].strip()
                    timestamp = author_line[right + 1 :].strip()
                else:
                    author_name = author_line
        if not tree_id:
            raise InvalidObjectError("unknown", "Commit missing tree header")

        return cls(
            tree_id=tree_id,
            parents=parents,
            author_name=author_name,
            author_email=author_email,
            timestamp=timestamp,
            message=message,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Commit):
            return False
        return (
            self.tree_id == other.tree_id
            and self.parents == other.parents
            and self.author_name == other.author_name
            and self.author_email == other.author_email
            and self.timestamp == other.timestamp
            and self.message == other.message
        )


class ObjectStore:
    """Manages reading and writing content-addressed objects to .tinygit/objects/."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.objects_dir = repo_root / ".tinygit" / "objects"

    def write_object(self, obj: GitObject) -> str:
        """Serialize and write a GitObject to the database. Returns SHA-1."""
        serialized = obj.serialize()
        sha, raw = hash_object(obj.type, serialized)
        prefix = sha[:2]
        filename = sha[2:]
        target_dir = self.objects_dir / prefix
        target_path = target_dir / filename

        if target_path.exists():
            return sha

        atomic_write_file(target_path, raw)
        return sha

    def exists(self, sha: str) -> bool:
        """Check if an object with SHA-1 exists in the database."""
        if len(sha) != 40:
            return False
        path = self.objects_dir / sha[:2] / sha[2:]
        return path.exists()

    def read_object(self, sha: str) -> GitObject:
        """Read and parse an object by its SHA-1 hash."""
        resolved_sha = self.resolve_prefix(sha)
        path = self.objects_dir / resolved_sha[:2] / resolved_sha[2:]
        if not path.exists():
            raise ObjectNotFoundError(resolved_sha)

        with open(path, "rb") as f:
            raw = f.read()

        null_idx = raw.find(b"\0")
        if null_idx == -1:
            raise InvalidObjectError(resolved_sha, "Missing null byte terminator in header")

        header_str = raw[:null_idx].decode("utf-8")
        parts = header_str.split(" ")
        if len(parts) != 2:
            raise InvalidObjectError(resolved_sha, f"Invalid object header: {header_str}")

        obj_type, size_str = parts
        try:
            expected_size = int(size_str)
        except ValueError:
            raise InvalidObjectError(resolved_sha, f"Invalid size in header: {size_str}") from None

        payload = raw[null_idx + 1 :]
        if len(payload) != expected_size:
            raise InvalidObjectError(
                resolved_sha, f"Payload size {len(payload)} does not match header size {expected_size}"
            )

        # Verify SHA-1 integrity
        calc_sha, _ = hash_object(obj_type, payload)
        if calc_sha != resolved_sha:
            raise InvalidObjectError(resolved_sha, "SHA-1 integrity verification failed")

        if obj_type == "blob":
            return Blob.parse(payload)
        elif obj_type == "tree":
            return Tree.parse(payload)
        elif obj_type == "commit":
            return Commit.parse(payload)
        else:
            raise InvalidObjectError(resolved_sha, f"Unknown object type: {obj_type}")

    def read_blob(self, sha: str) -> Blob:
        obj = self.read_object(sha)
        if not isinstance(obj, Blob):
            raise InvalidObjectError(sha, f"Expected blob, got {obj.type}")
        return obj

    def read_tree(self, sha: str) -> Tree:
        obj = self.read_object(sha)
        if not isinstance(obj, Tree):
            raise InvalidObjectError(sha, f"Expected tree, got {obj.type}")
        return obj

    def read_commit(self, sha: str) -> Commit:
        obj = self.read_object(sha)
        if not isinstance(obj, Commit):
            raise InvalidObjectError(sha, f"Expected commit, got {obj.type}")
        return obj

    def resolve_prefix(self, prefix: str) -> str:
        """Resolve a short SHA-1 prefix (4..40 chars) to a full 40-character SHA-1."""
        if len(prefix) == 40:
            if not (self.objects_dir / prefix[:2] / prefix[2:]).exists():
                raise ObjectNotFoundError(prefix)
            return prefix
        if len(prefix) < 4:
            raise ObjectNotFoundError(f"Prefix too short: {prefix}")

        dir_prefix = prefix[:2]
        file_prefix = prefix[2:]
        target_dir = self.objects_dir / dir_prefix
        if not target_dir.exists():
            raise ObjectNotFoundError(prefix)

        matches = []
        for file_path in target_dir.iterdir():
            if file_path.name.startswith(file_prefix):
                matches.append(dir_prefix + file_path.name)

        if not matches:
            raise ObjectNotFoundError(prefix)
        if len(matches) > 1:
            matches_str = ", ".join(sorted(matches)[:4])
            raise InvalidObjectError(prefix, f"Ambiguous revision '{prefix}': matches {matches_str}")
        return matches[0]
