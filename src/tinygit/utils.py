"""Utility functions and security validation for Tiny Git."""

from __future__ import annotations

import datetime
import os
import re
import stat
import tempfile
from pathlib import Path

from tinygit.errors import InvalidPathError

# Directory names that hold version-control metadata. A working tree may never
# contain a path component equal to one of these, and a tree object may never
# name an entry that would materialise one.
#
# This must be an exact match, not a prefix match: `.gitignore`, `.github` and
# `.gitattributes` are legitimate project files that a startswith() test would
# silently exclude from `add .` and `status`.
METADATA_DIR_NAMES = frozenset({".git", ".tinygit"})


def atomic_write_file(path: Path, data: bytes | str, mode: int | None = None) -> None:
    """Write a file atomically using a temporary file, fsync, and atomic rename.

    Guarantees that interrupted operations or process crashes never leave
    partial or corrupted metadata files on disk. The containing directory is
    fsync'd after the rename so the rename itself survives a crash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode("utf-8") if isinstance(data, str) else data

    # Create temporary file in the same directory to guarantee atomic rename across filesystems
    fd, temp_path_str = tempfile.mkstemp(dir=path.parent, prefix=".tmp_tinygit_")
    temp_path = Path(temp_path_str)
    try:
        with open(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(temp_path, mode)
        temp_path.replace(path)
    except Exception:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        raise
    fsync_dir(path.parent)


def fsync_dir(directory: Path) -> None:
    """fsync a directory so a rename inside it is durable across a crash.

    Silently ignored on platforms that cannot open a directory for reading as a
    file descriptor (Windows), where the filesystem journals the rename.
    """
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except (OSError, ValueError):
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def validate_path(path: str | Path, repo_root: Path) -> Path:
    """Validate that a path is within the repository boundaries and is not a symlink.

    Prevents path traversal attacks (e.g., '../../important-file') and symlink escapes.
    """
    try:
        resolved_root = repo_root.resolve()
        raw_path = Path(path)
        if not raw_path.is_absolute():
            raw_path = repo_root / raw_path

        # Ensure no symlinks are followed or staged BEFORE resolve()
        if raw_path.is_symlink() or any(p.is_symlink() for p in raw_path.parents if p != repo_root):
            raise InvalidPathError(str(path), "Symlinks are unsupported for security and determinism")

        target_path = raw_path.resolve()

        # The repository root itself is a directory, not a file target. Treating
        # it as a valid path lets an empty entry name address the repo root.
        if target_path == resolved_root:
            raise InvalidPathError(str(path), "Empty or repository-root path is not a valid file target")

        try:
            target_path.relative_to(resolved_root)
        except ValueError:
            raise InvalidPathError(str(path), "Path traversal outside repository bounds") from None

        return target_path
    except Exception as e:
        if isinstance(e, InvalidPathError):
            raise
        raise InvalidPathError(str(path), f"Failed to resolve path: {e}") from e


def validate_relative_path(rel_path: str) -> str:
    """Validate a repository-relative POSIX path without touching the filesystem.

    Rejects empty names, absolute paths, traversal components, backslashes,
    control characters, and version-control metadata directories. This is the
    single choke point for anything that will later be joined to the repository
    root, so a value accepted here can never escape it.
    """
    if not rel_path:
        raise InvalidPathError(rel_path, "Empty path is not permitted")
    if rel_path != rel_path.strip():
        raise InvalidPathError(rel_path, "Path may not have leading or trailing whitespace")
    if "\\" in rel_path:
        raise InvalidPathError(rel_path, "Backslash is not a path separator in tiny-git")
    if rel_path.startswith("/"):
        raise InvalidPathError(rel_path, "Absolute paths are not permitted")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in rel_path):
        raise InvalidPathError(rel_path, "Control characters are not permitted in paths")

    parts = rel_path.split("/")
    for part in parts:
        if not part:
            raise InvalidPathError(rel_path, "Empty path component is not permitted")
        if part in (".", ".."):
            raise InvalidPathError(rel_path, "Path traversal component is not permitted")
        if part in METADATA_DIR_NAMES:
            raise InvalidPathError(rel_path, f"'{part}' is reserved for version-control metadata")
    return rel_path


def get_relative_path(path: Path, repo_root: Path) -> str:
    """Get the relative path string using POSIX forward slashes."""
    rel = path.relative_to(repo_root)
    return rel.as_posix()


def is_ignored(path: Path, repo_root: Path) -> bool:
    """Check if a path is version-control metadata that must never be staged.

    Only exact metadata directory names are ignored. `.gitignore`, `.github`,
    `.gitattributes` and friends are ordinary project files and are tracked.
    """
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return True
    return any(part in METADATA_DIR_NAMES for part in rel.parts)


IGNORE_FILE_NAME = ".tinygitignore"


def load_ignore_patterns(repo_root: Path) -> list[str]:
    """Read `.tinygitignore` from the repository root.

    A deliberately small subset of gitignore: one pattern per line, `#` starts a
    comment, blank lines are skipped, and whitespace is not significant. Missing
    file means no patterns.
    """
    path = repo_root / IGNORE_FILE_NAME
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    patterns = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _translate_glob(pattern: str) -> str:
    """Translate one gitignore glob to a regex fragment.

    `*` and `?` deliberately do not cross a `/`; only an explicit `**` does.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def is_path_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Test a repository-relative POSIX path against loaded ignore patterns.

    A small, documented subset of gitignore, in order:
      * a pattern with no slash matches the basename at any depth (`*.pyc`)
      * a pattern containing a slash (other than a trailing one) is anchored to
        the repository root (`docs/*.md`, `/root.txt`)
      * a trailing slash restricts the match to a directory and everything below it
      * `*` does not cross a directory separator; `**` does
      * a leading `!` re-includes a path an earlier pattern excluded, so
        ordering matters and the last matching pattern wins
    """
    if not patterns:
        return False

    ignored = False
    for raw in patterns:
        negate = raw.startswith("!")
        pattern = raw[1:] if negate else raw
        if not pattern:
            continue

        directory_only = pattern.endswith("/")
        if directory_only:
            pattern = pattern[:-1]
        if not pattern:
            continue

        # `**/foo` means "foo in any directory", which includes the repository
        # root itself, so it behaves like an unanchored `foo`.
        if pattern.startswith("**/"):
            pattern = pattern[3:]
            anchored = False
        else:
            # A leading slash, or any slash remaining in the pattern, anchors it
            # to the repository root. Without one, it may match at any depth.
            anchored = pattern.startswith("/") or "/" in pattern
            pattern = pattern.lstrip("/")

        body = _translate_glob(pattern)
        if anchored:
            regex = f"^{body}"
        else:
            regex = f"^(?:.*/)?{body}"
        if directory_only:
            regex += "/.*$"
        else:
            regex += "(?:/.*)?$"

        if re.fullmatch(regex, rel_path):
            ignored = not negate
    return ignored


def get_file_mode(path: Path) -> str:
    """Get Git-compatible mode string for a file ('100644' or '100755')."""
    try:
        st_mode = os.stat(path).st_mode
        if stat.S_ISDIR(st_mode):
            return "040000"
        if st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            return "100755"
        return "100644"
    except Exception:
        return "100644"


def apply_file_mode(path: Path, mode: str) -> None:
    """Set a file's permission bits to match a Git mode string.

    `100755` sets the executable bits; every other mode clears them. Clearing
    matters as much as setting: restoring or checking out a `100644` entry over
    a file that is already executable must drop the bit, otherwise a mode-only
    change can never round-trip.
    """
    try:
        st_mode = os.stat(path).st_mode
        if mode == "100755":
            os.chmod(path, st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            os.chmod(path, st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except OSError:
        pass


def get_timestamp() -> str:
    """Get current timestamp in ISO-like string format (YYYY-MM-DD HH:MM:SS)."""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


def format_log_date(timestamp: str) -> str:
    """Format a timestamp for log output (YYYY-MM-DD)."""
    if len(timestamp) >= 10:
        return timestamp[:10]
    return timestamp


def is_binary_bytes(data: bytes) -> bool:
    """Determine if a byte sequence is binary.

    A payload is binary if it contains a NUL byte in the leading 8 KiB, or if it
    is not valid UTF-8. The second test matters: content such as Latin-1 text
    has no NUL byte but cannot be decoded, and treating it as text corrupts it.
    """
    if b"\x00" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False
