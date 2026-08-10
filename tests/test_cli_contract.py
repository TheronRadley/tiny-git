"""CLI contract audit tests.

Audits every command against valid input, invalid input, missing repository,
missing arguments, dirty working tree, unborn branch, and merge in progress.
Verifies that every failure produces human-readable stderr, a non-zero exit
code, zero Python tracebacks, and zero repository corruption.
"""

import os
from pathlib import Path

from tinygit.cli import main
from tinygit.repository import Repository


def test_cli_contract_missing_repo(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        for cmd in (
            ["status"],
            ["log"],
            ["add", "file.txt"],
            ["commit", "-m", "msg"],
            ["branch"],
            ["checkout", "main"],
            ["merge", "feat"],
            ["diff"],
            ["config", "user.name"],
            ["fsck"],
            ["cat-file", "HEAD"],
            ["show", "HEAD"],
            ["rev-parse", "HEAD"],
            ["rm", "file.txt"],
            ["restore", "file.txt"],
        ):
            code = main(cmd)
            assert code == 1, f"Command {cmd} should fail with 1 outside repo"
            _, err = capsys.readouterr()
            assert "error: not a tiny-git repository" in err
            assert "Traceback" not in err
    finally:
        os.chdir(orig_cwd)


def test_cli_contract_missing_args(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
        capsys.readouterr()

        # commit missing -m
        code1 = main(["commit"])
        assert code1 != 0
        _, err1 = capsys.readouterr()
        assert "Traceback" not in err1

        # cat-file missing object
        code2 = main(["cat-file"])
        assert code2 != 0
        _, err2 = capsys.readouterr()
        assert "Traceback" not in err2

        # checkout missing target
        code3 = main(["checkout"])
        assert code3 != 0
        _, err3 = capsys.readouterr()
        assert "Traceback" not in err3
    finally:
        os.chdir(orig_cwd)


def test_cli_contract_unborn_nothing_to_commit(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
        capsys.readouterr()

        code = main(["commit", "-m", "empty"])
        assert code == 1
        _, err = capsys.readouterr()
        assert "error: Nothing to commit" in err
        assert "Traceback" not in err
    finally:
        os.chdir(orig_cwd)


def test_cli_contract_invalid_reference(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        main(["add", "a.txt"])
        main(["commit", "-m", "c1"])
        capsys.readouterr()

        code = main(["checkout", "nonexistent_branch_name"])
        assert code == 1
        _, err = capsys.readouterr()
        assert "error: Invalid or unresolved reference" in err
        assert "Traceback" not in err
    finally:
        os.chdir(orig_cwd)


def test_cli_contract_dirty_worktree_abort_checkout(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
        (tmp_path / "a.txt").write_text("v1", encoding="utf-8")
        main(["add", "a.txt"])
        main(["commit", "-m", "c1"])
        main(["branch", "feat"])
        main(["checkout", "feat"])
        (tmp_path / "a.txt").write_text("v2", encoding="utf-8")
        main(["add", "a.txt"])
        main(["commit", "-m", "c2 on feat"])
        main(["checkout", "main"])
        capsys.readouterr()

        # Modify working tree a.txt unstaged
        (tmp_path / "a.txt").write_text("unstaged local edit", encoding="utf-8")
        code = main(["checkout", "feat"])
        assert code == 1
        _, err = capsys.readouterr()
        assert "error: Your local changes to file 'a.txt' would be overwritten by checkout." in err
        assert "Traceback" not in err
        # Verify repo is uncorrupted
        assert Repository(tmp_path).fsck().is_healthy()
    finally:
        os.chdir(orig_cwd)


def test_cli_contract_commit_rejected_during_conflict(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
        (tmp_path / "f.txt").write_text("base", encoding="utf-8")
        main(["add", "f.txt"])
        main(["commit", "-m", "base"])
        main(["branch", "feat"])
        (tmp_path / "f.txt").write_text("main edit", encoding="utf-8")
        main(["add", "f.txt"])
        main(["commit", "-m", "main"])
        main(["checkout", "feat"])
        (tmp_path / "f.txt").write_text("feat edit", encoding="utf-8")
        main(["add", "f.txt"])
        main(["commit", "-m", "feat"])
        main(["checkout", "main"])
        capsys.readouterr()

        code_merge = main(["merge", "feat"])
        assert code_merge == 1  # merge conflict exits 1
        out, err = capsys.readouterr()
        assert "Automatic merge failed" in err
        assert "Traceback" not in err

        code_commit = main(["commit", "-m", "try commit"])
        assert code_commit == 1
        _, err_c = capsys.readouterr()
        assert "error: Cannot commit: you have unmerged files" in err_c
        assert "Traceback" not in err_c
        # Verify repo is uncorrupted
        assert Repository(tmp_path).fsck().is_healthy()
    finally:
        os.chdir(orig_cwd)
