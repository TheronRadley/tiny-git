"""Regression tests: reference name validation (audit "Fix first" #1).

A branch name is joined to ``.tinygit/refs/heads/`` to produce a filesystem
path. Before validation, an absolute name or one containing ``..`` escaped that
directory, so `init -b /abs/path/victim` followed by a commit overwrote an
unrelated file with a commit hash.
"""

from pathlib import Path

import pytest

from tinygit.errors import InvalidReferenceError
from tinygit.refs import validate_ref_name
from tinygit.repository import Repository


@pytest.mark.parametrize(
    "bad_name",
    [
        "/tmp/evil",
        "/etc/passwd",
        "a/../../escape",
        "../../escape",
        "..",
        ".",
        "",
        "   ",
        " leading",
        "trailing ",
        "feat//double",
        "feat/",
        "/feat",
        ".hidden",
        "hidden.",
        "x.lock",
        "feat/x.lock",
        "a~b",
        "a^b",
        "a:b",
        "a?b",
        "a*b",
        "a[b",
        "a\\b",
        "HEAD",
        "@",
        "a@{b",
        "refs/heads/x",
        "new\nline",
        "nul\x00byte",
        "del\x7fchar",
    ],
)
def test_malicious_branch_names_are_rejected(bad_name: str):
    with pytest.raises(InvalidReferenceError):
        validate_ref_name(bad_name)


@pytest.mark.parametrize("good_name", ["main", "feat/x", "release/1.0", "a-b_c.d", "X", "0", "deep/a/b/c"])
def test_legitimate_branch_names_are_accepted(good_name: str):
    assert validate_ref_name(good_name) == good_name


def test_create_branch_cannot_write_outside_the_repository(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("IMPORTANT DATA", encoding="utf-8")

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = Repository.init(repo_dir)

    with pytest.raises(InvalidReferenceError):
        repo.refs.create_branch(str(victim), "a" * 40)

    assert victim.read_text(encoding="utf-8") == "IMPORTANT DATA"
    assert not victim.parent.joinpath(victim.name).is_dir()


def test_create_branch_cannot_traverse_out_of_refs_heads(tmp_path: Path):
    repo = Repository.init(tmp_path)
    with pytest.raises(InvalidReferenceError):
        repo.refs.create_branch("a/../../escape.txt", "a" * 40)
    assert not (tmp_path / ".tinygit" / "refs" / "escape.txt").exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_init_with_malicious_branch_does_not_overwrite_external_file(tmp_path: Path):
    """The reported exploit: `init -b <absolute path>` then commit."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("IMPORTANT DATA", encoding="utf-8")

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    with pytest.raises(InvalidReferenceError):
        Repository.init(repo_dir, default_branch=str(victim))

    assert victim.read_text(encoding="utf-8") == "IMPORTANT DATA"


def test_init_with_malicious_branch_then_commit_is_still_safe(tmp_path: Path):
    """Even if HEAD somehow holds a bad name, committing must not write through it."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("IMPORTANT DATA", encoding="utf-8")

    repo = Repository.init(tmp_path / "repo")
    (repo.repo_root / "f.txt").write_text("hi", encoding="utf-8")
    repo.add(["f.txt"])

    # Simulate a HEAD written by an older version that did not validate.
    repo.refs.head_path.write_text(f"ref: refs/heads/{victim}\n", encoding="utf-8")

    with pytest.raises(InvalidReferenceError):
        repo.commit("evil commit")
    assert victim.read_text(encoding="utf-8") == "IMPORTANT DATA"


def test_init_with_legitimate_nested_branch_works(tmp_path: Path):
    repo = Repository.init(tmp_path, default_branch="release/1.0")
    (tmp_path / "f.txt").write_text("hi", encoding="utf-8")
    repo.add(["f.txt"])
    sha = repo.commit("c1")

    assert repo.refs.get_current_branch() == "release/1.0"
    assert repo.refs.get_head_commit() == sha


def test_update_branch_rejects_non_commit_target(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("hi", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("c1")

    with pytest.raises(InvalidReferenceError):
        repo.refs.update_branch("main", "not-a-sha")
    with pytest.raises(InvalidReferenceError):
        repo.refs.update_branch("main", "A" * 40)


def test_detached_head_rejects_non_sha(tmp_path: Path):
    repo = Repository.init(tmp_path)
    with pytest.raises(InvalidReferenceError):
        repo.refs.set_head_to_commit("../../../etc/passwd")
    assert repo.refs.get_head_target() == "ref: refs/heads/main"
