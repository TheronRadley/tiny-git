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


class ConfigurationError(TinyGitError):
    """Raised when configuration is missing or invalid."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Missing or invalid configuration for key: {key}")
        self.key = key


class UnsupportedRepositoryFormatError(TinyGitError):
    """Raised when opening a repository with a format version newer than supported."""

    def __init__(self, version: int) -> None:
        super().__init__(f"Unsupported Tiny Git repository format version: {version} (this version supports up to 1)")
        self.version = version


class RevisionNotFoundError(TinyGitError):
    """Raised when a revision expression (e.g. HEAD~1, short SHA, or branch) cannot be resolved."""

    def __init__(self, rev: str) -> None:
        super().__init__(f"Unknown revision or reference: '{rev}'")
        self.rev = rev


class CorruptRepositoryError(TinyGitError):
    """Raised when repository fsck detects corruption or missing objects."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Repository corruption detected: {message}")

