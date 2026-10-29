"""Structured exceptions for Tiny Git."""

from __future__ import annotations


class TinyGitError(Exception):
    """Base class for all structured Tiny Git exceptions."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RepositoryNotFoundError(TinyGitError):
    """Raised when a Tiny Git repository (.tinygit/) cannot be found."""

    def __init__(self, path: str = ".") -> None:
        super().__init__(f"not a tiny-git repository (or any of the parent directories): .tinygit in '{path}'")


class RepositoryAlreadyExistsError(TinyGitError):
    """Raised when attempting to initialize a repository where one already exists."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Cannot reinitialize existing Tiny Git repository in {path}")


class InvalidRepositoryError(TinyGitError):
    """Raised when the repository structure is corrupted or invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Invalid Tiny Git repository: {reason}")


class ObjectNotFoundError(TinyGitError):
    """Raised when a content-addressed object cannot be found in the database."""

    def __init__(self, object_id: str) -> None:
        super().__init__(f"Object not found: {object_id}")
        self.object_id = object_id


class InvalidObjectError(TinyGitError):
    """Raised when an object is corrupted or cannot be parsed."""

    def __init__(self, object_id: str, reason: str) -> None:
        super().__init__(f"Invalid object {object_id}: {reason}")
        self.object_id = object_id


class InvalidReferenceError(TinyGitError):
    """Raised when a branch or reference name is invalid or cannot be resolved."""

    def __init__(self, ref_name: str) -> None:
        super().__init__(f"Invalid or unresolved reference: {ref_name}")
        self.ref_name = ref_name


class WorkingTreeDirtyError(TinyGitError):
    """Raised when an operation is aborted because the working tree or index has uncommitted changes."""

    def __init__(
        self,
        message: str = "Working tree has uncommitted changes. Aborting operation to prevent data loss.",
    ) -> None:
        super().__init__(message)


class MergeConflictError(TinyGitError):
    """Raised when a merge encounters conflicts that must be resolved manually."""

    def __init__(self, conflicts: list[str]) -> None:
        file_list = ", ".join(conflicts)
        super().__init__(f"Automatic merge failed; fix conflicts and then commit the result: {file_list}")
        self.conflicts = conflicts


class NothingToCommitError(TinyGitError):
    """Raised when attempting to commit with no staged changes or with unresolved conflicts."""

    def __init__(
        self,
        message: str = "Nothing to commit (working tree clean or no changes staged)",
    ) -> None:
        super().__init__(message)


class InvalidPathError(TinyGitError):
    """Raised when a path is invalid, outside the repository, or attempts path traversal."""

    def __init__(self, path: str, reason: str = "path is outside repository boundaries") -> None:
        super().__init__(f"Invalid path '{path}': {reason}")
        self.path = path


class IgnoredPathError(TinyGitError):
    """Raised when an explicitly named path is matched by .tinygitignore.

    Silently skipping the path would make `add <file>` look like it worked while
    staging nothing, so the refusal is explicit and names the file to retry with
    --force.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(
            f"The following path is ignored by .tinygitignore: {path}\n"
            "Use 'tiny-git add --force' if you really mean to track it."
        )


class ConfigurationError(TinyGitError):
    """Raised when configuration is missing or invalid."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Missing or invalid configuration for key: {key}")
        self.key = key


class UnsupportedRepositoryFormatError(TinyGitError):
    """Raised when opening a repository whose format version is unsupported or malformed."""

    def __init__(self, version: int | str) -> None:
        if isinstance(version, int):
            detail = f"version: {version} (this version supports up to 1)"
        else:
            detail = f"version is malformed: {version!r}"
        super().__init__(f"Unsupported Tiny Git repository format {detail}")
        self.version = version


class RevisionNotFoundError(TinyGitError):
    """Raised when a revision expression (e.g. HEAD~1, short SHA, or branch) cannot be resolved."""

    def __init__(self, rev: str) -> None:
        super().__init__(f"Unknown revision or reference: '{rev}'")
        self.rev = rev


class StaleReferenceError(TinyGitError):
    """Raised when a guarded reference update finds the ref changed underneath it."""

    def __init__(self, ref_name: str, expected: str | None, actual: str | None) -> None:
        super().__init__(
            f"Reference '{ref_name}' changed while it was being updated "
            f"(expected {expected or 'absent'}, found {actual or 'absent'})"
        )
        self.ref_name = ref_name


class LockHeldError(TinyGitError):
    """Raised when a repository lock is held by another tiny-git process."""

    def __init__(self, lock_path: str) -> None:
        super().__init__(
            f"Unable to create '{lock_path}': another tiny-git process is running. "
            f"If no other process is running, delete the stale lock file."
        )
        self.lock_path = lock_path


class CorruptRepositoryError(TinyGitError):
    """Raised when repository fsck detects corruption or missing objects."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Repository corruption detected: {message}")
