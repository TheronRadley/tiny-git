"""Utility functions and security validation for Tiny Git."""

from __future__ import annotations

import datetime
import os
import stat
import tempfile
from pathlib import Path

from tinygit.errors import InvalidPathError


def atomic_write_file(path: Path, data: bytes | str, mode: int | None = None) -> None:
    """Write a file atomically using a temporary file, fsync, and atomic rename.

    Guarantees that interrupted operations or process crashes never leave
    partial or corrupted metadata files on disk.
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
            try:
                os.chmod(temp_path, mode)
            except Exception:
                pass
        temp_path.replace(path)
    except Exception:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        raise


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

        try:
            target_path.relative_to(resolved_root)
        except ValueError:
            raise InvalidPathError(str(path), "Path traversal outside repository bounds") from None

        return target_path
    except Exception as e:
        if isinstance(e, InvalidPathError):
            raise
        raise InvalidPathError(str(path), f"Failed to resolve path: {e}") from e


def get_relative_path(path: Path, repo_root: Path) -> str:
    """Get the relative path string using POSIX forward slashes."""
    rel = path.relative_to(repo_root)
    return rel.as_posix()


def is_ignored(path: Path, repo_root: Path) -> bool:
    """Check if a path should be ignored (e.g., .tinygit directory)."""
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
        parts = rel.parts
        return ".tinygit" in parts or any(p.startswith(".git") for p in parts)
    except ValueError:
        return True


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
    """Determine if a byte sequence is binary by checking for NUL bytes."""
    return b"\x00" in data[:8192]
