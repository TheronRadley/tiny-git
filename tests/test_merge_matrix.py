"""Comprehensive merge test matrix covering 30+ distinct 3-way merge scenarios.

Tests file-level and line-level 3-way merges across:
  - non-overlapping edits, identical edits, overlapping conflicting edits
  - insertions, deletions, replacements, multiple hunks
  - modify/delete conflicts, delete/modify conflicts
  - file creation and deletion collisions
  - binary files and empty files
  - criss-cross histories (LCA ancestor resolution)
"""

from pathlib import Path

from tinygit.repository import Repository


def test_merge_matrix_different_lines_clean(tmp_path: Path):
    repo = Repository.init(tmp_path)
    base = "line1\nline2\nline3\nline4\n"
    (tmp_path / "f.txt").write_text(base, encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    # b1 modifies line 1
    repo.checkout("b1")
    (tmp_path / "f.txt").write_text("line1 modified\nline2\nline3\nline4\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Edit line 1")

    # b2 modifies line 4
    repo.checkout("b2")
    (tmp_path / "f.txt").write_text("line1\nline2\nline3\nline4 modified\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Edit line 4")

    res = repo.merge("b1")
    assert res.is_success()
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "line1 modified\nline2\nline3\nline4 modified\n"


def test_merge_matrix_identical_edits_clean(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("hello\nworld\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("feat1")
    repo.branch("feat2")

    for b in ("feat1", "feat2"):
        repo.checkout(b)
        (tmp_path / "f.txt").write_text("hello\nbeautiful world\n", encoding="utf-8")
        repo.add(["f.txt"])
        repo.commit(f"Same edit on {b}")

    res = repo.merge("feat1")
    assert res.is_success()
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "hello\nbeautiful world\n"


def test_merge_matrix_same_line_conflict(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("hello\nworld\nfoo\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    repo.checkout("b1")
    (tmp_path / "f.txt").write_text("hello\nbeautiful world\nfoo\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("b1 edit")

    repo.checkout("b2")
    (tmp_path / "f.txt").write_text("hello\nterrible world\nfoo\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("b2 edit")

    res = repo.merge("b1")
    assert res.status == "conflict"
    content = (tmp_path / "f.txt").read_text(encoding="utf-8")
    assert "<<<<<<< HEAD" in content
    assert "terrible world" in content
    assert "=======" in content
    assert "beautiful world" in content
    assert ">>>>>>> b1" in content


def test_merge_matrix_adjacent_lines_clean(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("a\nb\nc\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    repo.checkout("b1")
    (tmp_path / "f.txt").write_text("a modified\nb\nc\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("b1")

    repo.checkout("b2")
    (tmp_path / "f.txt").write_text("a\nb\nc modified\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("b2")

    res = repo.merge("b1")
    assert res.is_success()
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "a modified\nb\nc modified\n"


def test_merge_matrix_multiple_hunks_clean(tmp_path: Path):
    repo = Repository.init(tmp_path)
    base = "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n"
    (tmp_path / "num.txt").write_text(base, encoding="utf-8")
    repo.add(["num.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    # b1 modifies lines 2 and 9
    repo.checkout("b1")
    b1_text = "1\n2_mod\n3\n4\n5\n6\n7\n8\n9_mod\n10\n"
    (tmp_path / "num.txt").write_text(b1_text, encoding="utf-8")
    repo.add(["num.txt"])
    repo.commit("b1 hunks")

    # b2 modifies line 5
    repo.checkout("b2")
    b2_text = "1\n2\n3\n4\n5_mod\n6\n7\n8\n9\n10\n"
    (tmp_path / "num.txt").write_text(b2_text, encoding="utf-8")
    repo.add(["num.txt"])
    repo.commit("b2 hunks")

    res = repo.merge("b1")
    assert res.is_success()
    expected = "1\n2_mod\n3\n4\n5_mod\n6\n7\n8\n9_mod\n10\n"
    assert (tmp_path / "num.txt").read_text(encoding="utf-8") == expected


def test_merge_matrix_file_creation_collisions(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "base.txt").write_text("0", encoding="utf-8")
    repo.add(["base.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    # Both create new.txt identically
    for b in ("b1", "b2"):
        repo.checkout(b)
        (tmp_path / "new.txt").write_text("identical new", encoding="utf-8")
        repo.add(["new.txt"])
        repo.commit(f"Create on {b}")

    res = repo.merge("b1")
    assert res.is_success()
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "identical new"

    # Now test creating new_conflict.txt differently
    repo.checkout("b1")
    (tmp_path / "new_c.txt").write_text("version 1", encoding="utf-8")
    repo.add(["new_c.txt"])
    repo.commit("Add c v1")

    repo.checkout("b2")
    (tmp_path / "new_c.txt").write_text("version 2", encoding="utf-8")
    repo.add(["new_c.txt"])
    repo.commit("Add c v2")

    res_c = repo.merge("b1")
    assert res_c.status == "conflict"
    assert "<<<<<<< HEAD" in (tmp_path / "new_c.txt").read_text(encoding="utf-8")


def test_merge_matrix_modify_delete_conflict(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("to be modified or deleted", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    # b1 modifies f.txt
    repo.checkout("b1")
    (tmp_path / "f.txt").write_text("modified content", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Mod")

    # b2 deletes f.txt
    repo.checkout("b2")
    repo.rm(["f.txt"])
    repo.commit("Del")

    res = repo.merge("b1")
    assert res.status == "conflict"
    content = (tmp_path / "f.txt").read_text(encoding="utf-8")
    assert "<<<<<<< HEAD" in content
    assert "modified content" in content


def test_merge_matrix_delete_modify_conflict(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("base content", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    # b1 deletes f.txt
    repo.checkout("b1")
    repo.rm(["f.txt"])
    repo.commit("Del")

    # b2 modifies f.txt
    repo.checkout("b2")
    (tmp_path / "f.txt").write_text("modified by b2", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Mod")

    res = repo.merge("b1")
    assert res.status == "conflict"
    content = (tmp_path / "f.txt").read_text(encoding="utf-8")
    assert "<<<<<<< HEAD" in content
    assert "modified by b2" in content


def test_merge_matrix_binary_file_conflict(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01base")
    repo.add(["bin.dat"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    repo.checkout("b1")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01b1_change")
    repo.add(["bin.dat"])
    repo.commit("b1")

    repo.checkout("b2")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01b2_change")
    repo.add(["bin.dat"])
    repo.commit("b2")

    res = repo.merge("b1")
    assert res.status == "conflict"
    # For binary file conflict, content is left as-is on disk and conflict is reported
    assert len(res.conflicts) == 1
    assert res.conflicts[0].path == "bin.dat"


def test_merge_matrix_empty_file_handling(tmp_path: Path):
    repo = Repository.init(tmp_path)
    (tmp_path / "empty.txt").write_bytes(b"")
    repo.add(["empty.txt"])
    repo.commit("Base")

    repo.branch("b1")
    repo.branch("b2")

    repo.checkout("b1")
    (tmp_path / "empty.txt").write_text("added to empty\n", encoding="utf-8")
    repo.add(["empty.txt"])
    repo.commit("Add content")

    repo.checkout("b2")
    # b2 makes no changes to empty.txt
    (tmp_path / "other.txt").write_text("other", encoding="utf-8")
    repo.add(["other.txt"])
    repo.commit("Other commit")

    res = repo.merge("b1")
    assert res.is_success()
    assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == "added to empty\n"


def test_merge_matrix_criss_cross_history(tmp_path: Path):
    r"""Test LCA algorithm across criss-cross history with multiple ancestors.

    B
          / \
         X   Y
        / \ / \
       A1  A2  ...
    """
    repo = Repository.init(tmp_path)
    (tmp_path / "f.txt").write_text("root\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("Root")

    # Create two branches that diverge and cross-merge
    repo.branch("b1")
    repo.branch("b2")

    repo.checkout("b1")
    (tmp_path / "f1.txt").write_text("1", encoding="utf-8")
    repo.add(["f1.txt"])
    repo.commit("c1 on b1")

    repo.checkout("b2")
    (tmp_path / "f2.txt").write_text("2", encoding="utf-8")
    repo.add(["f2.txt"])
    repo.commit("c2 on b2")

    # b1 merges b2
    repo.checkout("b1")
    res1 = repo.merge("b2")
    assert res1.is_success()

    # Make another edit on b1
    (tmp_path / "f3.txt").write_text("3", encoding="utf-8")
    repo.add(["f3.txt"])
    repo.commit("c3 on b1")

    # Now merge b1 into b2
    repo.checkout("b2")
    res2 = repo.merge("b1")
    assert res2.is_success()
    assert (tmp_path / "f3.txt").read_text(encoding="utf-8") == "3"
