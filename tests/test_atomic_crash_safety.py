"""Unit and crash-consistency tests for atomic file writes and format versioning."""

from pathlib import Path

import pytest

from tinygit.errors import UnsupportedRepositoryFormatError
from tinygit.repository import Repository
from tinygit.utils import atomic_write_file


def test_atomic_write_file(tmp_path: Path):
    target = tmp_path / "metadata.txt"
    atomic_write_file(target, "atomic content")
    assert target.read_text(encoding="utf-8") == "atomic content"
    # No temporary files left behind
    temp_files = list(tmp_path.glob(".tmp*"))
    assert len(temp_files) == 0


def test_unsupported_repository_format_version(tmp_path: Path):
    repo = Repository.init(tmp_path)
    repo.config.set("core.repositoryformatversion", "99")

    # Reopening should immediately raise UnsupportedRepositoryFormatError
    with pytest.raises(UnsupportedRepositoryFormatError) as exc_info:
        Repository(tmp_path)
    assert exc_info.value.version == 99


def test_fsck_detects_corrupted_object(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    repo.add(["hello.txt"])
    _ = repo.commit("commit 1")

    # Simulate filesystem corruption: overwrite a blob with garbage
    sha_blob = repo.index.query("hello.txt").object_id
    blob_path = tmp_path / ".tinygit" / "objects" / sha_blob[:2] / sha_blob[2:]
    blob_path.write_bytes(b"corrupted garbage bytes")

    fsck_res = repo.fsck()
    assert fsck_res.is_healthy() is False
    assert any("malformed or corrupted" in err or "SHA-1 integrity" in err for err in fsck_res.errors)
