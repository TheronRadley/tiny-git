"""Reference management for Tiny Git (branches and HEAD).

Manages symbolic references (HEAD -> refs/heads/<branch>) and direct commit references.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from tinygit.errors import InvalidReferenceError, ObjectNotFoundError, StaleReferenceError
from tinygit.objects import ObjectStore
from tinygit.utils import atomic_write_file, get_timestamp, validate_relative_path

# A single path component of a reference: must start alphanumerically, and may
# contain alphanumerics plus '.', '_' and '-'. This deliberately excludes '/',
# which is handled as a component separator by validate_ref_name.
_REF_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")

# Characters git forbids anywhere in a reference name.
_REF_FORBIDDEN_CHARS = "~^:?*[\\"

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def validate_ref_name(name: str) -> str:
    """Validate a reference name and return it unchanged.

    Mirrors the subset of `git check-ref-format` that matters for a filesystem
    backed ref store. The important guarantee is that a name accepted here can
    never, when joined to ``.tinygit/refs/heads/``, address a path outside that
    directory -- so an absolute name or one containing ``..`` cannot be used to
    write over an unrelated file.

    Raises InvalidReferenceError for anything unsafe.
    """
    if not name:
        raise InvalidReferenceError(name)
    if name != name.strip():
        raise InvalidReferenceError(name)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise InvalidReferenceError(name)
    if any(ch in _REF_FORBIDDEN_CHARS for ch in name):
        raise InvalidReferenceError(name)
    if ".." in name:
        raise InvalidReferenceError(name)
    if "//" in name or name.startswith("/") or name.endswith("/"):
        raise InvalidReferenceError(name)
    if name in ("@", "HEAD") or name.startswith("refs/"):
        raise InvalidReferenceError(name)
    if "@{" in name:
        raise InvalidReferenceError(name)

    for component in name.split("/"):
        if not _REF_COMPONENT_RE.match(component):
            raise InvalidReferenceError(name)
        if component.startswith(".") or component.endswith("."):
            raise InvalidReferenceError(name)
        if component.endswith(".lock"):
            raise InvalidReferenceError(name)

    return name


ZERO_SHA = "0" * 40


@dataclass
class ReflogEntry:
    """One line of `.tinygit/logs/HEAD`."""

    old_sha: str
    new_sha: str
    timestamp: str
    message: str

    def format(self) -> str:
        old = self.old_sha[:7] if self.old_sha != ZERO_SHA else "0000000"
        new = self.new_sha[:7] if self.new_sha != ZERO_SHA else "0000000"
        return f"{old}..{new} {self.timestamp}	{self.message}"


def is_full_sha1(value: str) -> bool:
    """Return True if value is a well-formed lowercase 40-character SHA-1."""
    return bool(_SHA1_RE.match(value))


class ReferenceManager:
    """Manages HEAD and branch references under .tinygit/refs/heads/."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.tinygit_dir = repo_root / ".tinygit"
        self.head_path = self.tinygit_dir / "HEAD"
        self.heads_dir = self.tinygit_dir / "refs" / "heads"
        self.store = ObjectStore(repo_root)

    def init_head(self, default_branch: str = "main") -> None:
        """Initialize HEAD to point to default branch.

        The branch name is validated here as well as in create/update: `init -b`
        reaches this method directly, and an unvalidated name would let a later
        commit write a ref file outside the repository.
        """
        validate_ref_name(default_branch)
        # Written directly rather than through set_head_to_branch: an unborn
        # branch has no commit on either side of the move, and logging it would
        # leave a fresh repository with a meaningless 0000000..0000000 entry.
        atomic_write_file(self.head_path, f"ref: refs/heads/{default_branch}\n")

    def get_head_target(self) -> str:
        """Get the literal content of .tinygit/HEAD."""
        if not self.head_path.exists():
            raise InvalidReferenceError("HEAD")
        return self.head_path.read_text(encoding="utf-8").strip()

    def is_detached_head(self) -> bool:
        """Check if HEAD is detached (points directly to a commit SHA-1)."""
        target = self.get_head_target()
        return not target.startswith("ref: ")

    def get_current_branch(self) -> str | None:
        """Get the current branch name if HEAD is symbolic, else None if detached."""
        target = self.get_head_target()
        if target.startswith("ref: refs/heads/"):
            return target[len("ref: refs/heads/") :]
        return None

    def get_head_commit(self) -> str | None:
        """Resolve HEAD to a 40-character commit SHA-1 hash, or None if unborn branch."""
        target = self.get_head_target()
        if target.startswith("ref: "):
            branch = target[len("ref: refs/heads/") :]
            ref_path = self._ref_path(branch)
            if ref_path is None or not ref_path.exists():
                return None
            return ref_path.read_text(encoding="utf-8").strip()
        else:
            # Detached HEAD
            return target

    def get_ref_commit(self, ref: str) -> str | None:
        """Resolve a branch name, HEAD, or SHA-1 prefix to a full commit SHA-1."""
        if ref == "HEAD":
            return self.get_head_commit()

        # Try branch name
        branch_path = self._ref_path(ref)
        if branch_path is not None and branch_path.exists():
            return branch_path.read_text(encoding="utf-8").strip()

        # Try as object SHA-1 prefix
        try:
            full_sha = self.store.resolve_prefix(ref)
            obj = self.store.read_object(full_sha)
            if obj.type == "commit":
                return full_sha
        except (ObjectNotFoundError, Exception):
            pass

        return None

    def set_head_to_branch(self, branch: str, message: str = "checkout") -> None:
        """Set HEAD to a symbolic branch reference (ref: refs/heads/<branch>)."""
        validate_ref_name(branch)
        old_sha = None
        try:
            old_sha = self.get_head_commit()
        except Exception:
            old_sha = None
        atomic_write_file(self.head_path, f"ref: refs/heads/{branch}\n")
        new_sha = None
        try:
            new_sha = self.get_head_commit()
        except Exception:
            new_sha = None
        self.append_reflog(old_sha, new_sha, f"{message}: moving to {branch}")

    def set_head_to_commit(self, commit_sha: str, message: str = "checkout") -> None:
        """Set HEAD to a detached commit SHA-1."""
        if not is_full_sha1(commit_sha):
            raise InvalidReferenceError(commit_sha)
        try:
            old_sha = self.get_head_commit()
        except Exception:
            old_sha = None
        atomic_write_file(self.head_path, f"{commit_sha}\n")
        self.append_reflog(old_sha, commit_sha, f"{message}: moving to {commit_sha[:7]}")

    def list_branches(self) -> list[str]:
        """List all branch names in sorted order."""
        if not self.heads_dir.exists():
            return []
        branches = []
        for p in self.heads_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.heads_dir).as_posix()
                branches.append(rel)
        return sorted(branches)

    def branch_exists(self, branch: str) -> bool:
        """Check if a branch exists in refs/heads/."""
        path = self._ref_path(branch)
        return path is not None and path.is_file()

    def _ref_path(self, branch: str) -> Path | None:
        """Resolve a branch name to its ref file, or None if the name is unusable.

        Name validation and a resolved-path containment check together guarantee
        the result is a file inside .tinygit/refs/heads/. The containment check
        is defence in depth: if the name rules ever regress, a name that escapes
        the heads directory is still refused instead of writing elsewhere.
        """
        try:
            validate_ref_name(branch)
            validate_relative_path(branch)
        except Exception:
            return None

        candidate = (self.heads_dir / branch).resolve()
        heads_root = self.heads_dir.resolve()
        try:
            candidate.relative_to(heads_root)
        except ValueError:
            return None
        if candidate == heads_root:
            return None
        return candidate

    # ------------------------------------------------------------------
    # Reflog
    # ------------------------------------------------------------------
    @property
    def reflog_path(self) -> Path:
        return self.tinygit_dir / "logs" / "HEAD"

    def append_reflog(self, old_sha: str | None, new_sha: str | None, message: str) -> None:
        """Append one entry to the HEAD reflog.

        Best-effort by design: a reflog is a recovery aid, not part of the
        repository's correctness invariants, so a failure to append must never
        fail the operation that triggered it.
        """
        try:
            path = self.reflog_path
            path.parent.mkdir(parents=True, exist_ok=True)
            line = f"{old_sha or ZERO_SHA} {new_sha or ZERO_SHA} {get_timestamp()}	{message}\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass

    def read_reflog(self) -> list[ReflogEntry]:
        """Read the HEAD reflog, newest last. Malformed lines are skipped."""
        path = self.reflog_path
        if not path.is_file():
            return []
        entries: list[ReflogEntry] = []
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for line in raw.splitlines():
            if not line.strip():
                continue
            head, _, message = line.partition("\t")
            parts = head.split(" ")
            if len(parts) < 3:
                continue
            entries.append(
                ReflogEntry(
                    old_sha=parts[0],
                    new_sha=parts[1],
                    timestamp=" ".join(parts[2:]),
                    message=message,
                )
            )
        return entries

    def create_branch(self, branch: str, commit_sha: str) -> None:
        """Create a new branch pointing to commit_sha."""
        validate_ref_name(branch)
        if not is_full_sha1(commit_sha):
            raise InvalidReferenceError(f"branch '{branch}' target is not a valid commit hash")
        branch_path = self._ref_path(branch)
        if branch_path is None:
            raise InvalidReferenceError(branch)
        if branch_path.is_file():
            raise InvalidReferenceError(f"a branch named '{branch}' already exists")
        atomic_write_file(branch_path, f"{commit_sha}\n")

    def read_branch_raw(self, branch: str) -> str | None:
        """Return the literal stored value of a branch, or None if it does not exist."""
        path = self._ref_path(branch)
        if path is None or not path.is_file():
            return None
        return path.read_text(encoding="utf-8").strip()

    def update_branch(self, branch: str, commit_sha: str, expected: str | None = None) -> None:
        """Update an existing branch (or create it) to point to commit_sha.

        When ``expected`` is supplied the update is guarded: it only proceeds if
        the branch still holds that value. This is the compare-and-swap that
        stops two concurrent commits from both advancing a branch off the same
        parent, silently discarding one of them.
        """
        validate_ref_name(branch)
        if not is_full_sha1(commit_sha):
            raise InvalidReferenceError(f"branch '{branch}' target is not a valid commit hash")
        branch_path = self._ref_path(branch)
        if branch_path is None:
            raise InvalidReferenceError(branch)
        if expected is not None:
            actual = self.read_branch_raw(branch)
            if actual != expected:
                raise StaleReferenceError(branch, expected, actual)
        atomic_write_file(branch_path, f"{commit_sha}\n")

    def update_head_commit(self, commit_sha: str, expected: str | None = None) -> None:
        """Update the commit SHA-1 pointed to by current branch or detached HEAD.

        ``expected`` is the value HEAD resolved to when the caller started; for a
        symbolic HEAD the guard applies to the branch it names.
        """
        branch = self.get_current_branch()
        if branch is not None:
            self.update_branch(branch, commit_sha, expected=expected)
            self.append_reflog(expected, commit_sha, f"commit on {branch}")
        else:
            if expected is not None:
                actual = self.get_head_target()
                if actual != expected:
                    raise StaleReferenceError("HEAD", expected, actual)
            self.set_head_to_commit(commit_sha, message="commit")
