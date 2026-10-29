"""Tests for the additions: .tinygitignore, the HEAD reflog, and porcelain status."""

import os
from pathlib import Path

import pytest

from tinygit import cli
from tinygit.repository import Repository
from tinygit.utils import is_path_ignored, load_ignore_patterns


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    r = Repository.init(tmp_path)
    r.config.set("user.name", "T")
    r.config.set("user.email", "t@t.t")
    return r


# --------------------------------------------------------------------------
# .tinygitignore
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "pattern, path, expected",
    [
        ("*.pyc", "mod.pyc", True),
        ("*.pyc", "pkg/mod.pyc", True),
        ("*.pyc", "mod.py", False),
        ("build/", "build/out.log", True),
        ("build/", "build/nested/out.log", True),
        ("build/", "src/build.py", False),
        ("/root.txt", "root.txt", True),
        ("/root.txt", "sub/root.txt", False),
        ("docs/*.md", "docs/a.md", True),
        ("docs/*.md", "docs/sub/a.md", False),
        ("secret.txt", "secret.txt", True),
        # `**` crosses directory separators where `*` does not.
        ("docs/**.md", "docs/sub/a.md", True),
        ("**/node_modules", "a/b/node_modules", True),
        ("**/node_modules", "node_modules", True),
        # A bare pattern matches a directory and everything below it.
        ("build/", "a/b/build/x", True),
    ],
)
def test_ignore_pattern_matching(pattern: str, path: str, expected: bool):
    assert is_path_ignored(path, [pattern]) is expected


def test_last_matching_pattern_wins_for_negations():
    """Negations only cancel rules that come before them, as documented."""
    assert is_path_ignored("keep.log", ["*.log", "!keep.log"]) is False
    assert is_path_ignored("keep.log", ["!keep.log", "*.log"]) is True


def test_ignore_negation_re_includes_a_path():
    assert is_path_ignored("keep.log", ["*.log", "!keep.log"]) is False
    assert is_path_ignored("drop.log", ["*.log", "!keep.log"]) is True


def test_no_patterns_ignores_nothing():
    assert is_path_ignored("anything.txt", []) is False


def test_load_ignore_patterns_skips_comments_and_blanks(tmp_path: Path):
    (tmp_path / ".tinygitignore").write_text("# a comment\n\n  \n*.pyc\nbuild/\n", encoding="utf-8")
    assert load_ignore_patterns(tmp_path) == ["*.pyc", "build/"]


def test_missing_ignore_file_is_not_an_error(tmp_path: Path):
    assert load_ignore_patterns(tmp_path) == []


def test_add_dot_skips_ignored_files(repo: Repository, tmp_path: Path):
    (tmp_path / ".tinygitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("k\n", encoding="utf-8")
    (tmp_path / "noise.log").write_text("n\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.log").write_text("o\n", encoding="utf-8")

    staged = repo.add(["."])

    assert "keep.txt" in staged
    assert "noise.log" not in staged
    assert "build/out.log" not in staged


def test_status_does_not_list_ignored_files_as_untracked(repo: Repository, tmp_path: Path):
    (tmp_path / ".tinygitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("k\n", encoding="utf-8")
    (tmp_path / "noise.log").write_text("n\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("c1")

    status = repo.status()
    assert status.untracked == []
    assert ".tinygitignore" not in status.untracked


def test_already_tracked_file_is_not_untracked_by_a_later_ignore_rule(repo: Repository, tmp_path: Path):
    """The explicit tracked-file behaviour: ignoring a committed file must not delete it."""
    (tmp_path / "data.log").write_text("committed content\n", encoding="utf-8")
    repo.add(["data.log"])
    repo.commit("c1")

    # Now ignore it.
    (tmp_path / ".tinygitignore").write_text("*.log\n", encoding="utf-8")

    # add . must stage the modification, not a deletion.
    (tmp_path / "data.log").write_text("updated content\n", encoding="utf-8")
    repo.add(["."])
    assert "data.log" in repo.index
    assert repo.index.query("data.log").object_id != "0" * 40

    status = repo.status()
    assert "data.log" not in status.staged_deleted
    assert "data.log" not in status.unstaged_deleted
    assert "data.log" in status.staged_modified

    sha = repo.commit("update tracked-but-ignored")
    committed = repo.wt.get_tree_entries_flat(repo.store.read_commit(sha).tree_id, repo.store)
    assert "data.log" in committed
    assert (tmp_path / "data.log").exists()


def test_naming_an_ignored_file_explicitly_is_refused_not_silently_skipped(repo: Repository, tmp_path: Path):
    """A silent skip would make `add <file>` look like it worked while staging nothing."""
    from tinygit.errors import IgnoredPathError

    (tmp_path / ".tinygitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "a.log").write_text("a\n", encoding="utf-8")

    with pytest.raises(IgnoredPathError, match="a.log"):
        repo.add(["a.log"])
    assert "a.log" not in repo.index


def test_add_force_overrides_the_ignore_rule(repo: Repository, tmp_path: Path):
    (tmp_path / ".tinygitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "a.log").write_text("a\n", encoding="utf-8")

    assert repo.add(["a.log"], force=True) == ["a.log"]
    assert "a.log" in repo.index


def test_add_force_cli_flag(tmp_path: Path, monkeypatch, capsys):
    Repository.init(tmp_path)
    (tmp_path / ".tinygitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "a.log").write_text("a\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Without --force the CLI reports the refusal rather than exiting quietly.
    def staged() -> set[str]:
        idx = Repository(tmp_path).index
        idx.read()
        return {e.path for e in idx.list_entries()}

    assert cli.main(["add", "a.log"]) == 1
    assert "ignored by .tinygitignore" in capsys.readouterr().err
    assert "a.log" not in staged()

    assert cli.main(["add", "--force", "a.log"]) == 0
    assert "a.log" in staged()


def test_checkout_still_restores_a_tracked_ignored_file(repo: Repository, tmp_path: Path):
    (tmp_path / "keep.log").write_text("k\n", encoding="utf-8")
    repo.add(["keep.log"])
    committed = repo.commit("c1")
    (tmp_path / ".tinygitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "keep.log").unlink()

    repo.checkout(committed)
    assert (tmp_path / "keep.log").read_text(encoding="utf-8") == "k\n"


# --------------------------------------------------------------------------
# Reflog
# --------------------------------------------------------------------------
def test_reflog_records_commits_and_checkouts(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    first = repo.commit("c1")

    repo.branch("feat")
    repo.checkout("feat")
    repo.checkout("main")

    entries = repo.reflog()
    assert len(entries) >= 3
    assert any("moving to feat" in e.message for e in entries)
    assert any("moving to main" in e.message for e in entries)
    assert any(e.new_sha == first for e in entries)


def test_reflog_entries_have_both_endpoints(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    first = repo.commit("c1")
    (tmp_path / "a.txt").write_text("b\n", encoding="utf-8")
    repo.add(["a.txt"])
    second = repo.commit("c2")

    entries = repo.reflog()
    move = [e for e in entries if e.new_sha == second][-1]
    assert move.old_sha == first
    assert "c" in move.format()


def test_reflog_max_count_limits_to_the_newest(repo: Repository, tmp_path: Path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text(f"{i}\n", encoding="utf-8")
        repo.add([f"f{i}.txt"])
        repo.commit(f"c{i}")

    assert len(repo.reflog(max_count=2)) == 2
    assert len(repo.reflog()) >= 5


def test_reflog_survives_a_repository_reopen(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    reopened = Repository(tmp_path)
    assert len(reopened.reflog()) >= 1


def test_reflog_can_recover_a_commit_after_a_branch_is_moved(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    (tmp_path / "a.txt").write_text("important\n", encoding="utf-8")
    repo.add(["a.txt"])
    important = repo.commit("important work")

    # Simulate a bad reset: point main back at the first commit.
    first = next(e.new_sha for e in repo.reflog() if e.new_sha != "0" * 40)
    repo.refs.update_branch("main", first)
    assert repo.refs.get_head_commit() != important

    # The commit is still findable through the reflog.
    recorded = [e.new_sha for e in repo.reflog()]
    assert important in recorded

    repo.checkout(important)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "important\n"


def test_reflog_cli_prints_entries(tmp_path: Path, monkeypatch, capsys):
    repo = Repository.init(tmp_path)
    repo.config.set("user.name", "T")
    repo.config.set("user.email", "t@t.t")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    monkeypatch.chdir(tmp_path)
    assert cli.main(["reflog"]) == 0
    out = capsys.readouterr().out
    assert "moving to" in out or "commit on" in out


def test_reflog_cli_on_a_fresh_repository(tmp_path: Path, monkeypatch, capsys):
    Repository.init(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["reflog"]) == 0
    assert "No reflog entries yet." in capsys.readouterr().out


def test_reflog_failure_does_not_break_the_operation(repo: Repository, tmp_path: Path):
    """The reflog is a recovery aid, never part of correctness.

    Making `.tinygit/logs` a regular file makes the mkdir inside append_reflog
    raise FileExistsError (an OSError); the commit must still succeed.
    """
    logs = tmp_path / ".tinygit" / "logs"
    if logs.is_dir():
        logs.rmdir()
    logs.write_text("not a directory\n", encoding="utf-8")

    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    sha = repo.commit("still works")

    assert repo.store.read_commit(sha).message == "still works"
    assert repo.reflog() == []


# --------------------------------------------------------------------------
# status --short / --porcelain
# --------------------------------------------------------------------------
def test_porcelain_codes_for_each_change_kind(repo: Repository, tmp_path: Path):
    (tmp_path / "tracked.txt").write_text("t\n", encoding="utf-8")
    (tmp_path / "gone.txt").write_text("g\n", encoding="utf-8")
    repo.add(["."])
    repo.commit("c1")

    (tmp_path / "new.txt").write_text("n\n", encoding="utf-8")
    repo.add(["new.txt"])
    (tmp_path / "tracked.txt").write_text("modified\n", encoding="utf-8")
    repo.add(["tracked.txt"])
    (tmp_path / "gone.txt").unlink()
    repo.add(["gone.txt"])
    (tmp_path / "untracked.txt").write_text("u\n", encoding="utf-8")

    codes = repo.status().porcelain_codes()
    assert codes["new.txt"] == "A "
    assert codes["tracked.txt"] == "M "
    assert codes["gone.txt"] == "D "
    assert codes["untracked.txt"] == "??"


def test_porcelain_reports_staged_and_unstaged_modification(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")

    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    repo.add(["a.txt"])
    (tmp_path / "a.txt").write_text("three\n", encoding="utf-8")

    assert repo.status().porcelain_codes()["a.txt"] == "MM"


def test_porcelain_output_is_line_oriented(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    output = repo.status().format_porcelain()
    assert output == "A  a.txt"
    for line in output.splitlines():
        assert len(line.split(" ", 1)) == 2
        assert len(line[:2]) == 2


def test_porcelain_is_empty_on_a_clean_tree(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    assert repo.status().format_porcelain() == ""


def test_short_status_has_a_branch_header(repo: Repository, tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    repo.add(["a.txt"])
    repo.commit("c1")
    text = repo.status().format_short()
    assert text.startswith("## main")


def test_status_cli_flags(tmp_path: Path, monkeypatch, capsys):
    repo = Repository.init(tmp_path)
    repo.config.set("user.name", "T")
    repo.config.set("user.email", "t@t.t")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["add", "a.txt"]) == 0
    assert cli.main(["status", "--porcelain"]) == 0
    assert capsys.readouterr().out.strip() == "A  a.txt"

    assert cli.main(["status", "--short"]) == 0
    assert "A  a.txt" in capsys.readouterr().out

    assert cli.main(["status"]) == 0
    assert "Changes to be committed" in capsys.readouterr().out


def test_porcelain_marks_unmerged_paths(repo: Repository, tmp_path: Path):
    (tmp_path / "f.txt").write_text("base\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("base")
    repo.branch("feat")
    repo.checkout("feat")
    (tmp_path / "f.txt").write_text("feat\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("feat")
    repo.checkout("main")
    (tmp_path / "f.txt").write_text("main\n", encoding="utf-8")
    repo.add(["f.txt"])
    repo.commit("main")

    assert repo.merge("feat").status == "conflict"
    status = repo.status()
    # The index is compared stage-0-only, so a conflicted path is absent from it.
    # Without the unmerged guard it would surface as untracked (hiding the merge)
    # and as a staged deletion (a lie). Locks in both halves.
    assert status.porcelain_codes()["f.txt"] == "UU"
    assert status.unmerged_paths == ["f.txt"]
    assert "f.txt" not in status.untracked
    assert "f.txt" not in status.staged_deleted
    assert not status.is_clean()


def test_mode_change_appears_in_porcelain(repo: Repository, tmp_path: Path):
    (tmp_path / "run.sh").write_text("echo\n", encoding="utf-8")
    repo.add(["run.sh"])
    repo.commit("c1")
    os.chmod(tmp_path / "run.sh", 0o755)
    assert repo.status().porcelain_codes()["run.sh"] == " M"
