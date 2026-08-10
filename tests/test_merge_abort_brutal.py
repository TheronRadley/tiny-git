"""Brutal verification tests for merge --abort.

Snapshots HEAD, INDEX, WORKTREE, and MERGE_STATE before merge,
executes a conflicting merge, performs user actions, calls merge --abort,
and asserts exact pre-merge state restoration across:
  - untracked files
  - executable modes
  - multiple conflicting files
  - files created during merge
  - directory/file topology changes
"""

import os
from pathlib import Path

from tinygit.repository import Repository


def test_merge_abort_brutal_matrix(tmp_path: Path):
    repo = Repository.init(tmp_path)

    # 1. Base commit: regular file 'a.txt', executable 'exec.sh', file 'foo'
    (tmp_path / "a.txt").write_text("base a\n", encoding="utf-8")
    exec_sh = tmp_path / "exec.sh"
    exec_sh.write_text("echo test\n", encoding="utf-8")
    exec_sh.chmod(0o755)
    (tmp_path / "foo").write_text("file foo\n", encoding="utf-8")

    repo.add(["a.txt", "exec.sh", "foo"])
    _ = repo.commit("Base")

    # 2. Feat branch: modify a.txt, create new.txt, replace 'foo' with directory 'foo/bar.txt'
    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "a.txt").write_text("feat a\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("feat new\n", encoding="utf-8")
    (tmp_path / "foo").unlink()
    foo_dir = tmp_path / "foo"
    foo_dir.mkdir()
    (foo_dir / "bar.txt").write_text("nested foo\n", encoding="utf-8")

    repo.add(["."])
    _ = repo.commit("Feat changes")

    # 3. Main branch: modify a.txt differently, modify exec.sh mode/text
    repo.checkout("main")
    (tmp_path / "a.txt").write_text("main a\n", encoding="utf-8")
    exec_sh.write_text("echo main\n", encoding="utf-8")
    exec_sh.chmod(0o755)
    repo.add(["a.txt", "exec.sh"])
    _ = repo.commit("Main changes")

    # 4. Create untracked file before merge
    untracked_path = tmp_path / "untracked.txt"
    untracked_path.write_text("untracked notes", encoding="utf-8")

    # Snapshot exact pre-merge state
    pre_main_text = (tmp_path / "a.txt").read_text(encoding="utf-8")
    pre_exec_text = (tmp_path / "exec.sh").read_text(encoding="utf-8")
    pre_exec_mode = os.stat(exec_sh).st_mode
    pre_foo_text = (tmp_path / "foo").read_text(encoding="utf-8")
    pre_untracked = untracked_path.read_text(encoding="utf-8")
    pre_head = repo.refs.get_head_commit()
    pre_index_map = {e.path: (e.object_id, e.mode, e.stage) for e in repo.index.list_entries()}

    # 5. Perform conflicting merge
    res = repo.merge("feat")
    assert res.status == "conflict"
    assert (repo.tinygit_dir / "MERGE_HEAD").exists()

    # 6. Call merge --abort
    msg = repo.merge(abort=True)
    assert msg == "Merge aborted."

    # 7. Verify EXACT pre-merge restoration
    assert not (repo.tinygit_dir / "MERGE_HEAD").exists()
    assert not (repo.tinygit_dir / "MERGE_MODE").exists()
    assert repo.refs.get_head_commit() == pre_head

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == pre_main_text
    assert (tmp_path / "exec.sh").read_text(encoding="utf-8") == pre_exec_text
    assert os.stat(exec_sh).st_mode == pre_exec_mode
    assert (tmp_path / "foo").is_file()
    assert (tmp_path / "foo").read_text(encoding="utf-8") == pre_foo_text
    assert not (tmp_path / "new.txt").exists()  # file created by feat must be gone
    assert not (tmp_path / "foo" / "bar.txt").exists()

    # Untracked file must be untouched
    assert untracked_path.exists()
    assert untracked_path.read_text(encoding="utf-8") == pre_untracked

    # Index must match pre-merge index exactly
    post_index_map = {e.path: (e.object_id, e.mode, e.stage) for e in repo.index.list_entries()}
    assert post_index_map == pre_index_map
    assert not repo.status().has_staged_changes() and not repo.status().has_unstaged_changes()
    assert repo.fsck().is_healthy()
