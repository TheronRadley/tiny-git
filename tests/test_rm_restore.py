"""Unit tests for rm and restore commands (working tree and index modifications)."""

import os
from pathlib import Path

from tinygit.cli import main
from tinygit.repository import Repository


def test_rm_and_rm_cached(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    repo.add(["a.txt", "b.txt"])
    repo.commit("c1")

    # rm --cached b.txt -> removed from index, remains on disk
    removed = repo.rm(["b.txt"], cached=True)
    assert removed == ["b.txt"]
    assert "b.txt" not in repo.index
    assert (tmp_path / "b.txt").exists()

    # rm a.txt -> removed from index AND disk
    removed_a = repo.rm(["a.txt"], cached=False)
    assert removed_a == ["a.txt"]
    assert "a.txt" not in repo.index
    assert not (tmp_path / "a.txt").exists()


def test_restore_and_restore_staged(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("initial", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("c1")

    # Modify f.txt and stage it
    (tmp_path / "f.txt").write_text("staged edit", encoding="utf-8")
    repo.add(["f.txt"])
    assert repo.index.query("f.txt").object_id != repo.refs.get_head_commit()

    # restore --staged f.txt -> unstage change (index matches HEAD again)
    repo.restore(["f.txt"], staged=True)
    st = repo.status()
    assert len(st.staged_modified) == 0
    assert "f.txt" in st.unstaged_modified

    # restore f.txt -> restore disk from index
    repo.restore(["f.txt"], staged=False)
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "initial"
    assert repo.status().is_clean()


def test_rm_restore_cli(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        Repository.init(tmp_path)
        (tmp_path / "test.txt").write_text("v1", encoding="utf-8")
        assert main(["add", "test.txt"]) == 0
        assert main(["commit", "-m", "init"]) == 0

        assert main(["rm", "--cached", "test.txt"]) == 0
        out, _ = capsys.readouterr()
        assert "rm 'test.txt'" in out
        assert (tmp_path / "test.txt").exists()

        assert main(["restore", "--staged", "test.txt"]) == 0
        assert main(["restore", "test.txt"]) == 0
    finally:
        os.chdir(orig_cwd)
