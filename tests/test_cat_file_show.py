"""Unit tests for cat-file, show, and rev-parse developer inspection commands."""

import os
from pathlib import Path

from tinygit.cli import main
from tinygit.repository import Repository


def test_cat_file_show_rev_parse(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        repo = Repository.init(tmp_path)
        (tmp_path / "hello.txt").write_text("v1", encoding="utf-8")
        repo.add(["hello.txt"])
        c1 = repo.commit("commit 1")

        (tmp_path / "hello.txt").write_text("v2", encoding="utf-8")
        repo.add(["hello.txt"])
        c2 = repo.commit("commit 2")

        # rev-parse
        sha_c1 = repo.rev_parse("HEAD~1")
        assert sha_c1 == c1
        sha_c2 = repo.rev_parse("HEAD")
        assert sha_c2 == c2

        # cat-file --type
        assert repo.cat_file("HEAD", obj_type_only=True) == "commit"
        assert repo.cat_file("HEAD~1", obj_type_only=True) == "commit"

        # cat-file -p commit
        commit_pretty = repo.cat_file("HEAD", pretty=True)
        assert "tree " in commit_pretty
        assert f"parent {c1}" in commit_pretty
        assert "commit 2" in commit_pretty

        # show
        show_out = repo.show("HEAD")
        assert f"commit {c2}" in show_out
        assert "Author: Ron" in show_out
        assert "-v1" in show_out
        assert "+v2" in show_out

        # Test via CLI
        assert main(["rev-parse", "HEAD~1"]) == 0
        out, _ = capsys.readouterr()
        assert c1 in out

        assert main(["cat-file", "-t", "HEAD"]) == 0
        out, _ = capsys.readouterr()
        assert "commit" in out

        assert main(["show", "HEAD"]) == 0
        out, _ = capsys.readouterr()
        assert "-v1" in out
        assert "+v2" in out
    finally:
        os.chdir(orig_cwd)
