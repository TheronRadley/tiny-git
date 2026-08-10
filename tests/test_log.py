"""Unit tests for log command and commit history traversal."""

from pathlib import Path

from tinygit.repository import Repository


def test_log_traversal_and_formatting(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    repo.add(["a.txt"])
    c1 = repo.commit("Initial commit")

    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    repo.add(["b.txt"])
    c2 = repo.commit("Add authentication\n\nDetailed description here.")

    logs = repo.log()
    assert len(logs) == 2
    assert logs[0].commit_sha == c2
    assert logs[1].commit_sha == c1

    fmt_normal = logs[0].format(oneline=False)
    assert f"commit {c2}" in fmt_normal
    assert "Author: Ron" in fmt_normal
    assert "Date:   " in fmt_normal
    assert "    Add authentication" in fmt_normal
    assert "    Detailed description here." in fmt_normal

    fmt_oneline = logs[0].format(oneline=True)
    assert fmt_oneline == f"{c2[:7]} Add authentication"
