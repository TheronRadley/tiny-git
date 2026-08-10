"""Unit tests for symlink policy, binary/non-UTF-8 byte storage, and file modes."""

import os
from pathlib import Path

import pytest

from tinygit.errors import InvalidPathError
from tinygit.repository import Repository


def test_symlink_rejected(tmp_path: Path):
    repo = Repository.init(tmp_path)
    target = tmp_path / "real.txt"
    target.write_text("real", encoding="utf-8")

    link = tmp_path / "link.txt"
    try:
        os.symlink("real.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform/filesystem")

    with pytest.raises(InvalidPathError) as exc_info:
        repo.add(["link.txt"])
    assert "Symlinks are unsupported" in str(exc_info.value)


def test_byte_oriented_storage_non_utf8_and_binary(tmp_path: Path):
    repo = Repository.init(tmp_path)
    raw_bytes = b"\x80\x81\x82\xff\x00\x01\n\r\n"
    (tmp_path / "binary.dat").write_bytes(raw_bytes)

    repo.add(["binary.dat"])
    c_sha = repo.commit("Binary commit")

    # Verify blob data in store matches byte-for-byte
    entry = repo.index.query("binary.dat")
    assert entry is not None
    blob = repo.store.read_blob(entry.object_id)
    assert blob.data == raw_bytes

    # Checkout commit and verify working tree file matches byte-for-byte
    (tmp_path / "binary.dat").unlink()
    repo.checkout(c_sha)
    assert (tmp_path / "binary.dat").read_bytes() == raw_bytes


def test_executable_mode_preservation(tmp_path: Path):
    repo = Repository.init(tmp_path)
    script = tmp_path / "run.sh"
    script.write_text("echo test\n", encoding="utf-8")
    script.chmod(0o755)

    repo.add(["run.sh"])
    repo.commit("Add executable")

    entry = repo.index.query("run.sh")
    assert entry is not None
    assert entry.mode == "100755"

    repo.checkout("main")
    # Verify mode is restored
    st_mode = os.stat(script).st_mode
    assert (st_mode & 0o111) != 0
