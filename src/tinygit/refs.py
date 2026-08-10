"""Reference management for Tiny Git (branches and HEAD).

Manages symbolic references (HEAD -> refs/heads/<branch>) and direct commit references.
"""

from __future__ import annotations

import re
from pathlib import Path

from tinygit.errors import InvalidReferenceError, ObjectNotFoundError
from tinygit.objects import ObjectStore
from tinygit.utils import atomic_write_file


class ReferenceManager:
    """Manages HEAD and branch references under .tinygit/refs/heads/."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.tinygit_dir = repo_root / ".tinygit"
        self.head_path = self.tinygit_dir / "HEAD"
        self.heads_dir = self.tinygit_dir / "refs" / "heads"
        self.store = ObjectStore(repo_root)

    def init_head(self, default_branch: str = "main") -> None:
        """Initialize HEAD to point to default branch."""
        self.set_head_to_branch(default_branch)

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
            ref_path = self.tinygit_dir / target[5:]
            if not ref_path.exists():
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
        branch_path = self.heads_dir / ref
        if branch_path.exists():
            return branch_path.read_text(encoding="utf-8").strip()

        # Try refs/heads/branch
        if ref.startswith("refs/heads/"):
            full_path = self.tinygit_dir / ref
            if full_path.exists():
                return full_path.read_text(encoding="utf-8").strip()

        # Try as object SHA-1 prefix
        try:
            full_sha = self.store.resolve_prefix(ref)
            obj = self.store.read_object(full_sha)
            if obj.type == "commit":
                return full_sha
        except (ObjectNotFoundError, Exception):
            pass

        return None

    def set_head_to_branch(self, branch: str) -> None:
        """Set HEAD to a symbolic branch reference (ref: refs/heads/<branch>)."""
        atomic_write_file(self.head_path, f"ref: refs/heads/{branch}\n")

    def set_head_to_commit(self, commit_sha: str) -> None:
        """Set HEAD to a detached commit SHA-1."""
        atomic_write_file(self.head_path, f"{commit_sha}\n")

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
        return (self.heads_dir / branch).is_file()

    def _validate_branch_name(self, branch: str) -> None:
        """Validate branch name according to simple git-like reference rules."""
        if not branch or "/" in branch.strip("/") or ".." in branch or "~" in branch or "^" in branch or ":" in branch:
            # For simplicity, allow alphanumeric, hyphens, underscores, dots, and slashes
            if not re.match(r"^[a-zA-Z0-9_\-\.\/]+$", branch):
                raise InvalidReferenceError(branch)
        if branch.startswith(".") or branch.endswith(".") or branch.endswith("/"):
            raise InvalidReferenceError(branch)

    def create_branch(self, branch: str, commit_sha: str) -> None:
        """Create a new branch pointing to commit_sha."""
        self._validate_branch_name(branch)
        if self.branch_exists(branch):
            raise InvalidReferenceError(f"a branch named '{branch}' already exists")
        branch_path = self.heads_dir / branch
        atomic_write_file(branch_path, f"{commit_sha}\n")

    def update_branch(self, branch: str, commit_sha: str) -> None:
        """Update an existing branch (or create it) to point to commit_sha."""
        self._validate_branch_name(branch)
        branch_path = self.heads_dir / branch
        atomic_write_file(branch_path, f"{commit_sha}\n")

    def update_head_commit(self, commit_sha: str) -> None:
        """Update the commit SHA-1 pointed to by current branch or detached HEAD."""
        branch = self.get_current_branch()
        if branch is not None:
            self.update_branch(branch, commit_sha)
        else:
            self.set_head_to_commit(commit_sha)
