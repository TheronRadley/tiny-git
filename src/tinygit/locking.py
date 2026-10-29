"""Advisory file locks for concurrent tiny-git processes.

Every mutating command reads metadata, changes it in memory, and writes it back.
Two commands doing that at once lose one of the updates: the second write simply
overwrites the first. These locks make the read-modify-write sequence exclusive.

The mechanism is `O_CREAT | O_EXCL` on a `.lock` sibling file, which is the same
primitive git uses. It is atomic on every platform tiny-git runs on and leaves a
visible artifact when something crashes, which is what makes stale-lock recovery
possible.
"""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tinygit.errors import TinyGitError

# How long to wait for a contended lock before giving up.
DEFAULT_TIMEOUT_SECONDS = 10.0

# A lock whose owner process is gone is stale. If the owner cannot be
# identified at all, fall back to age.
STALE_LOCK_AGE_SECONDS = 300.0

POLL_INTERVAL_SECONDS = 0.02


class LockError(TinyGitError):
    """Raised when a lock cannot be acquired because another process holds it."""

    def __init__(self, lock_path: str, reason: str = "held by another tiny-git process") -> None:
        super().__init__(f"Unable to create '{lock_path}': {reason}")
        self.lock_path = lock_path


def _pid_is_alive(pid: int) -> bool:
    """Best-effort check for whether a process id is still running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, but owned by someone else.
        return True
    except OSError:
        return False
    return True


class FileLock:
    """An exclusive, self-identifying file lock."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        """Block until the lock is held, or raise LockError after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            conflict = False
            try:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                conflict = True
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                conflict = True

            if not conflict:
                try:
                    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
                    os.fsync(fd)
                except OSError:
                    # The lock is still exclusive even if the owner tag fails to
                    # write; losing the tag only weakens stale detection.
                    pass
                self._fd = fd
                return

            if self._break_stale_lock():
                continue
            if time.monotonic() >= deadline:
                raise LockError(str(self.lock_path))
            time.sleep(POLL_INTERVAL_SECONDS)

    def _break_stale_lock(self) -> bool:
        """Remove a lock left behind by a process that no longer exists.

        Returns True if the lock file was removed and acquisition should be
        retried. A lock is considered stale when its recorded owner is dead, or
        when the owner is unreadable and the file is old enough that no plausible
        operation is still running.
        """
        pid = 0
        try:
            raw = self.lock_path.read_text(encoding="ascii").strip()
            pid = int(raw) if raw else 0
        except (OSError, ValueError):
            pid = 0

        if pid and _pid_is_alive(pid):
            return False
        if not pid:
            try:
                age = time.time() - self.lock_path.stat().st_mtime
            except OSError:
                return False
            if age < STALE_LOCK_AGE_SECONDS:
                return False

        try:
            self.lock_path.unlink()
        except OSError:
            return False
        return True

    def release(self) -> None:
        """Drop the lock. Safe to call more than once."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self.lock_path.unlink()
        except OSError:
            pass

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


@contextmanager
def index_lock(repo_root: Path, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold `.tinygit/index.lock` for the duration of an index read-modify-write."""
    lock = FileLock(repo_root / ".tinygit" / "index.lock")
    lock.acquire(timeout)
    try:
        yield
    finally:
        lock.release()


@contextmanager
def ref_lock(repo_root: Path, branch: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold `.tinygit/refs/heads/<branch>.lock` while updating one branch."""
    lock = FileLock(repo_root / ".tinygit" / "refs" / "heads" / f"{branch}.lock")
    lock.acquire(timeout)
    try:
        yield
    finally:
        lock.release()


@contextmanager
def head_lock(repo_root: Path, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold `.tinygit/HEAD.lock` while repointing HEAD."""
    lock = FileLock(repo_root / ".tinygit" / "HEAD.lock")
    lock.acquire(timeout)
    try:
        yield
    finally:
        lock.release()


@contextmanager
def operation_lock(repo_root: Path, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Iterator[None]:
    """Serialise a whole mutating command against other tiny-git processes.

    Commands that rewrite several files -- commit, checkout, merge -- need to
    hold the index and HEAD locks together, otherwise another process can slip
    in between the two writes and observe a repository whose index belongs to
    one commit and whose HEAD belongs to another.
    """
    locks = [
        FileLock(repo_root / ".tinygit" / "index.lock"),
        FileLock(repo_root / ".tinygit" / "HEAD.lock"),
    ]
    acquired: list[FileLock] = []
    try:
        for lock in locks:
            lock.acquire(timeout)
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()
