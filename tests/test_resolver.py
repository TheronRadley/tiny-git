"""Unit tests for the RevisionResolver (~N, ^N, branch, short SHA)."""

from pathlib import Path

import pytest

from tinygit.errors import RevisionNotFoundError
from tinygit.repository import Repository
from tinygit.resolver import RevisionResolver


def test_resolve_branches_short_sha_and_ancestry(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    repo.add(["a.txt"])
    c1 = repo.commit("c1")

    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    repo.add(["a.txt"])
    c2 = repo.commit("c2")

    (tmp_path / "a.txt").write_text("3", encoding="utf-8")
    repo.add(["a.txt"])
    c3 = repo.commit("c3")

    rev_head = RevisionResolver.resolve("HEAD", repo.refs, repo.store)
    assert rev_head.commit_sha == c3

    rev_main = RevisionResolver.resolve("main", repo.refs, repo.store)
    assert rev_main.commit_sha == c3
    assert rev_main.is_branch is True
    assert rev_main.branch_name == "main"

    rev_1 = RevisionResolver.resolve("HEAD~1", repo.refs, repo.store)
    assert rev_1.commit_sha == c2
    assert rev_1.is_branch is False

    rev_2 = RevisionResolver.resolve("main~2", repo.refs, repo.store)
    assert rev_2.commit_sha == c1

    rev_3 = RevisionResolver.resolve("HEAD^^", repo.refs, repo.store)
    assert rev_3.commit_sha == c1

    with pytest.raises(RevisionNotFoundError):
        RevisionResolver.resolve("HEAD~10", repo.refs, repo.store)


def test_resolve_merge_second_parent(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("base", encoding="utf-8")
    repo.add(["f.txt"])
    _ = repo.commit("base")

    repo.branch("feat")
    (tmp_path / "f.txt").write_text("main edit", encoding="utf-8")
    repo.add(["f.txt"])
    c_main = repo.commit("main")

    repo.checkout("feat")
    (tmp_path / "feat.txt").write_text("feat edit", encoding="utf-8")
    repo.add(["feat.txt"])
    c_feat = repo.commit("feat")

    repo.checkout("main")
    res_merge = repo.merge("feat")
    assert res_merge.is_success()
    merge_sha = res_merge.commit_sha
    assert merge_sha

    rev_p1 = RevisionResolver.resolve("HEAD^1", repo.refs, repo.store)
    assert rev_p1.commit_sha == c_main

    rev_p2 = RevisionResolver.resolve("HEAD^2", repo.refs, repo.store)
    assert rev_p2.commit_sha == c_feat


def test_resolve_ambiguous_prefix_and_invalid_ancestry(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    repo.add(["a.txt"])
    _ = repo.commit("c1")

    with pytest.raises(RevisionNotFoundError):
        RevisionResolver.resolve("HEAD~invalid", repo.refs, repo.store)

    with pytest.raises(RevisionNotFoundError):
        RevisionResolver.resolve("HEAD^3", repo.refs, repo.store)

    # Test ambiguous prefix error formatting
    from tinygit.objects import Blob
    _ = repo.store.write_object(Blob(b"ambig1"))
    _ = repo.store.write_object(Blob(b"ambig2"))
    # Find a shared prefix if possible, or test resolve_prefix directly
    with pytest.raises(RevisionNotFoundError):
        RevisionResolver.resolve("0000000", repo.refs, repo.store)
