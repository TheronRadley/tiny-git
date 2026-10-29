"""Regression tests: executable modes, path handling, is_ignored, and fsck hardening.

Covers audit items "Fix executable modes across status, diff, merge, checkout,
and restore", "Reject unsupported filenames before staging", "Fix is_ignored()",
"Resolve CLI paths relative to the caller's directory", and "Strengthen fsck and
format validation".
"""

import os
import stat
from pathlib import Path

import pytest

from tinygit import cli
from tinygit.errors import InvalidPathError, UnsupportedRepositoryFormatError
from tinygit.fsck import IntegrityChecker
from tinygit.objects import Blob, hash_object
from tinygit.repository import Repository
from tinygit.utils import atomic_write_file, is_ignored


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    r = Repository.init(tmp_path)
    r.config.set("user.name", "T")
    r.config.set("user.email", "t@t.t")
    return r


def _is_executable(path: Path) -> bool:
    return bool(os.stat(path).st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


# --------------------------------------------------------------------------
# Executable modes
# --------------------------------------------------------------------------
def test_staging_records_the_executable_bit(repo: Repository, tmp_path: Path):
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    os.chmod(tmp_path / "run.sh", 0o755)
    repo.add(["run.sh"])
    assert repo.index.query("run.sh").mode == "100755"


def test_status_reports_a_mode_only_change(repo: Repository, tmp_path: Path):
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    repo.add(["run.sh"])
    repo.commit("c1")

    os.chmod(tmp_path / "run.sh", 0o755)
    status = repo.status()
    assert "run.sh" in status.unstaged_modified, "mode-only change must be visible to status"


def test_status_reports_a_staged_mode_only_change(repo: Repository, tmp_path: Path):
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    repo.add(["run.sh"])
    repo.commit("c1")

    os.chmod(tmp_path / "run.sh", 0o755)
    repo.add(["run.sh"])
    assert "run.sh" in repo.status().staged_modified


def test_diff_reports_a_mode_only_change(repo: Repository, tmp_path: Path):
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    repo.add(["run.sh"])
    repo.commit("c1")

    os.chmod(tmp_path / "run.sh", 0o755)
    output = cli.DiffEngine.format_diff(repo.diff())
    assert "old mode 100644" in output
    assert "new mode 100755" in output


def test_restore_clears_the_executable_bit(repo: Repository, tmp_path: Path):
    """Restoring a 100644 entry over an executable file must drop the bit."""
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    repo.add(["run.sh"])
    repo.commit("c1")
    assert repo.index.query("run.sh").mode == "100644"

    os.chmod(tmp_path / "run.sh", 0o755)
    assert _is_executable(tmp_path / "run.sh")

    repo.restore(["run.sh"])
    assert not _is_executable(tmp_path / "run.sh")


def test_checkout_restores_the_executable_bit(repo: Repository, tmp_path: Path):
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    os.chmod(tmp_path / "run.sh", 0o755)
    repo.add(["run.sh"])
    repo.commit("c1")

    os.chmod(tmp_path / "run.sh", 0o644)
    (tmp_path / "run.sh").unlink()
    repo.checkout(repo.refs.get_head_commit())

    assert _is_executable(tmp_path / "run.sh")


def test_checkout_clears_a_stale_executable_bit(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    repo.branch("feat")
    repo.checkout("feat")
    os.chmod(tmp_path / "a.txt", 0o755)
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("feat: make executable and edit")

    repo.checkout("main")
    assert not _is_executable(tmp_path / "a.txt")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\n"


def test_merge_carries_a_mode_change_from_the_incoming_branch(repo: Repository, tmp_path: Path):
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("o\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("base")

    repo.branch("feat")
    repo.checkout("feat")
    os.chmod(tmp_path / "run.sh", 0o755)
    (tmp_path / "feat.txt").write_text("f\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("feat: chmod +x run.sh")

    repo.checkout("main")
    (tmp_path / "other.txt").write_text("main\n", encoding="utf-8")
    repo.add(["other.txt"])
    repo.commit("main: edit other")

    result = repo.merge("feat")
    assert result.status == "clean"
    assert repo.index.query("run.sh").mode == "100755"
    assert _is_executable(tmp_path / "run.sh")


# --------------------------------------------------------------------------
# Unsupported filenames
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["bad\nname.txt", "bad\rname.txt", "bad\tname.txt", "a\\b.txt", "../x.txt"])
def test_unsupported_filenames_are_rejected_before_staging(repo: Repository, bad: str):
    with pytest.raises(InvalidPathError):
        repo.index.add(bad, "a" * 40)


def test_add_of_a_file_with_a_newline_is_rejected(repo: Repository, tmp_path: Path):
    (tmp_path / "ok.txt").write_text("ok\n", encoding="utf-8")
    with pytest.raises(InvalidPathError):
        repo.add(["ok.txt\ninjected"])
    assert repo.index.query("ok.txt") is None


# --------------------------------------------------------------------------
# is_ignored
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rel, expected",
    [
        (".gitignore", False),
        (".github/workflows/ci.yml", False),
        (".gitattributes", False),
        (".gitkeep", False),
        (".gitlab-ci.yml", False),
        ("src/main.py", False),
        (".tinygit/config", True),
        (".tinygit/objects/ab/cdef", True),
        (".git/config", True),
        ("nested/.git/x", True),
    ],
)
def test_is_ignored_matches_metadata_directories_only(tmp_path: Path, rel: str, expected: bool):
    assert is_ignored(tmp_path / rel, tmp_path) is expected


def test_add_dot_picks_up_gitignore_and_dot_github(repo: Repository, tmp_path: Path):
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "ci.yml").write_text("jobs: {}\n", encoding="utf-8")
    (tmp_path / "real.txt").write_text("x\n", encoding="utf-8")

    staged = repo.add(["."])
    assert ".gitignore" in staged
    assert ".github/ci.yml" in staged
    assert "real.txt" in staged


def test_status_never_lists_metadata_as_untracked(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    assert repo.status().untracked == []


# --------------------------------------------------------------------------
# CLI path resolution
# --------------------------------------------------------------------------
def test_cli_resolves_paths_relative_to_the_callers_directory(tmp_path: Path, monkeypatch):
    repo = Repository.init(tmp_path)
    repo.config.set("user.name", "T")
    repo.config.set("user.email", "t@t.t")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.txt").write_text("from subdir\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path / "notes")
    assert cli.main(["add", "a.txt"]) == 0

    repo.index.read()
    assert repo.index.query("notes/a.txt") is not None, "path must be repo-relative, not root-relative"
    assert repo.index.query("a.txt") is None


def test_cli_dot_in_a_subdirectory_stages_that_subdirectory(tmp_path: Path, monkeypatch):
    repo = Repository.init(tmp_path)
    repo.config.set("user.name", "T")
    repo.config.set("user.email", "t@t.t")
    (tmp_path / "root.txt").write_text("r\n", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.txt").write_text("a\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path / "notes")
    assert cli.main(["add", "."]) == 0

    repo.index.read()
    assert repo.index.query("notes/a.txt") is not None


def test_cli_rejects_a_path_outside_the_repository(tmp_path: Path, monkeypatch):
    Repository.init(tmp_path / "repo")
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path / "repo")
    assert cli.main(["add", str(outside)]) == 1


def test_cli_rm_supports_force(tmp_path: Path, monkeypatch, capsys):
    repo = Repository.init(tmp_path)
    repo.config.set("user.name", "T")
    repo.config.set("user.email", "t@t.t")
    (tmp_path / "a.txt").write_text("committed\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    (tmp_path / "a.txt").write_text("uncommitted\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert cli.main(["rm", "a.txt"]) == 1
    assert "--force" in capsys.readouterr().err
    assert (tmp_path / "a.txt").exists()

    assert cli.main(["rm", "--force", "a.txt"]) == 0
    assert not (tmp_path / "a.txt").exists()


# --------------------------------------------------------------------------
# fsck hardening and format validation
# --------------------------------------------------------------------------
def _write_raw(repo: Repository, obj_type: str, payload: bytes) -> str:
    sha, raw = hash_object(obj_type, payload)
    atomic_write_file(repo.store.objects_dir / sha[:2] / sha[2:], raw)
    return sha


def test_fsck_flags_a_tree_entry_pointing_at_the_wrong_type(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    blob_sha = repo.index.query("a.txt").object_id
    # mode 040000 says "directory" but the referent is a blob.
    tree_sha = _write_raw(repo, "tree", f"040000 {blob_sha} wrong\n".encode())
    _write_raw(repo, "commit", f"tree {tree_sha}\nauthor T <t@t.t> 2026-01-01 00:00:00\n\nx\n".encode())

    result = repo.fsck()
    assert not result.is_healthy()
    assert any("expected a tree" in e for e in result.errors)


def test_fsck_flags_a_file_entry_pointing_at_a_tree(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    head_tree = repo.store.read_commit(repo.refs.get_head_commit()).tree_id
    tree_sha = _write_raw(repo, "tree", f"100644 {head_tree} wrong\n".encode())
    _write_raw(repo, "commit", f"tree {tree_sha}\nauthor T <t@t.t> 2026-01-01 00:00:00\n\nx\n".encode())

    result = repo.fsck()
    assert any("expected a blob" in e for e in result.errors)


def test_fsck_flags_duplicate_tree_entries(repo: Repository, tmp_path: Path):
    """Duplicates are rejected when the tree is parsed, so fsck reports it as malformed."""
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    blob = repo.index.query("a.txt").object_id

    dup_sha = _write_raw(repo, "tree", f"100644 {blob} dup\n100644 {blob} dup\n".encode())
    result = repo.fsck()
    assert not result.is_healthy()
    assert any(dup_sha in e and "Duplicate tree entry name" in e for e in result.errors)


def test_duplicate_tree_cannot_be_checked_out(repo: Repository, tmp_path: Path):
    from tinygit.errors import InvalidObjectError
    from tinygit.objects import Tree, TreeEntry

    with pytest.raises(InvalidObjectError):
        Tree(
            [
                TreeEntry(mode="100644", name="dup", object_id="a" * 40),
                TreeEntry(mode="100644", name="dup", object_id="b" * 40),
            ]
        )


def test_fsck_flags_a_detached_head_pointing_at_a_blob(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    blob_sha = repo.index.query("a.txt").object_id
    repo.refs.set_head_to_commit(blob_sha)

    result = repo.fsck()
    assert not result.head_valid
    assert any("expected a commit" in e for e in result.errors)


def test_fsck_flags_index_stage_inconsistency(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    sha = repo.commit("c1")
    blob = repo.index.query("a.txt").object_id

    # Hand-craft an index holding stage 0 and stage 2 for the same path.
    import json

    entries = [
        {"path": "a.txt", "object_id": blob, "mode": "100644", "stat_size": 2, "stat_mtime": 0.0, "stage": 0},
        {"path": "a.txt", "object_id": blob, "mode": "100644", "stat_size": 2, "stat_mtime": 0.0, "stage": 2},
    ]
    (tmp_path / ".tinygit" / "index").write_text(json.dumps(entries), encoding="utf-8")

    result = repo.fsck()
    assert not result.index_valid
    assert any("both resolved" in e for e in result.errors)
    assert sha  # keep the commit referenced


def test_fsck_flags_a_malformed_repository_format_version(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / ".tinygit" / "config").write_text("[core]\nrepositoryformatversion = not-a-number\n", encoding="utf-8")
    result = IntegrityChecker.check(repo.repo_root, repo.store, repo.refs, repo.index)
    assert any("Malformed core.repositoryformatversion" in e for e in result.errors)


def test_opening_a_repository_with_a_malformed_version_is_refused(tmp_path: Path):
    Repository.init(tmp_path)
    (tmp_path / ".tinygit" / "config").write_text("[core]\nrepositoryformatversion = banana\n", encoding="utf-8")
    with pytest.raises(UnsupportedRepositoryFormatError):
        Repository(tmp_path)


def test_opening_a_repository_with_a_newer_version_is_refused(tmp_path: Path):
    Repository.init(tmp_path)
    (tmp_path / ".tinygit" / "config").write_text("[core]\nrepositoryformatversion = 99\n", encoding="utf-8")
    with pytest.raises(UnsupportedRepositoryFormatError):
        Repository(tmp_path)


def test_fsck_is_healthy_on_a_normal_repository(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("c1")
    result = repo.fsck()
    assert result.is_healthy(), result.errors
    assert Blob(b"a\n")  # sanity: Blob import still used
