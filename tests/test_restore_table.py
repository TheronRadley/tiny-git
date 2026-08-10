"""Truth-table verification tests for restore and restore --staged.

Verifies deterministic behavior across all permutations of:
  HEAD (A) x INDEX (B) x WORKTREE (C)
"""

from pathlib import Path

from tinygit.repository import Repository


def test_restore_truth_table_permutations(tmp_path: Path):
    repo = Repository.init(tmp_path)
    file_path = tmp_path / "f.txt"

    # Set HEAD = A
    file_path.write_text("A", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("A")

    # Set INDEX = B, WORKTREE = C
    file_path.write_text("B", encoding="utf-8")
    repo.add(["f.txt"])
    file_path.write_text("C", encoding="utf-8")

    # Verify state: HEAD=A, INDEX=B, WORKTREE=C
    st1 = repo.status()
    assert "f.txt" in st1.staged_modified
    assert "f.txt" in st1.unstaged_modified

    # Case 1: restore f.txt (without --staged)
    # Expected: WORKTREE is restored from INDEX (becomes B); INDEX remains B
    repo.restore(["f.txt"], staged=False)
    assert file_path.read_text(encoding="utf-8") == "B"
    st2 = repo.status()
    assert "f.txt" in st2.staged_modified
    assert "f.txt" not in st2.unstaged_modified

    # Reset to HEAD=A, INDEX=B, WORKTREE=C
    file_path.write_text("C", encoding="utf-8")

    # Case 2: restore --staged f.txt
    # Expected: INDEX is restored from HEAD (becomes A); WORKTREE remains C
    repo.restore(["f.txt"], staged=True)
    assert file_path.read_text(encoding="utf-8") == "C"
    st3 = repo.status()
    assert "f.txt" not in st3.staged_modified
    assert "f.txt" in st3.unstaged_modified

    # Case 3: restore f.txt when INDEX=A, WORKTREE=C
    # Expected: WORKTREE is restored from INDEX (A)
    repo.restore(["f.txt"], staged=False)
    assert file_path.read_text(encoding="utf-8") == "A"
    assert repo.status().is_clean()
