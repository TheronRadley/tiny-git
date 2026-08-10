"""Unit tests for the staging area (index)."""

from pathlib import Path

from tinygit.index import Index


def test_index_add_remove_query(tmp_path: Path):
    index = Index(tmp_path)
    index.add("src/main.py", "a" * 40, "100644", size=120)
    index.add("README.md", "b" * 40, "100644", size=50)

    assert len(index) == 2
    assert "src/main.py" in index
    assert index.query("README.md").object_id == "b" * 40

    assert index.remove("README.md") is True
    assert "README.md" not in index
    assert len(index) == 1


def test_index_write_and_read(tmp_path: Path):
    index1 = Index(tmp_path)
    index1.add("b.txt", "1" * 40, "100644", size=10)
    index1.add("a/c.txt", "2" * 40, "100644", size=20)
    index1.write()

    index2 = Index(tmp_path)
    index2.read()
    assert len(index2) == 2
    entries = index2.list_entries()
    assert entries[0].path == "a/c.txt"
    assert entries[1].path == "b.txt"
    assert entries[0].object_id == "2" * 40
    assert entries[1].object_id == "1" * 40


def test_index_clear(tmp_path: Path):
    index = Index(tmp_path)
    index.add("file.txt", "f" * 40)
    index.clear()
    assert len(index) == 0
