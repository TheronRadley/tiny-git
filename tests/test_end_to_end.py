"""End-to-end tests covering complete repository workflows and CLI commands."""

import os
from pathlib import Path

from tinygit.cli import main
from tinygit.repository import Repository


def test_full_workflow_api(tmp_path: Path):
    os.chdir(tmp_path)
    try:
        # 1. init
        repo = Repository.init(tmp_path)

        # 2. add & commit
        f1 = tmp_path / "hello.txt"
        f1.write_text("hello\n", encoding="utf-8")
        repo.add(["hello.txt"])
        c1 = repo.commit("Initial commit")

        # 3. status
        st = repo.status()
        assert st.is_clean()
        assert st.branch == "main"

        # 4. branch & checkout
        repo.branch("feature")
        repo.checkout("feature")
        assert repo.refs.get_current_branch() == "feature"

        # 5. modify, add, commit on feature
        f1.write_text("hello world\n", encoding="utf-8")
        repo.add(["hello.txt"])
        c2 = repo.commit("Update greeting")

        # 6. log
        logs = repo.log()
        assert len(logs) == 2
        assert logs[0].commit_sha == c2
        assert logs[1].commit_sha == c1

        # 7. checkout main
        repo.checkout("main")
        assert f1.read_text(encoding="utf-8") == "hello\n"

        # 8. merge feature into main -> fast-forward
        merge_res = repo.merge("feature")
        assert merge_res.is_success()
        assert merge_res.status == "fast-forward"
        assert f1.read_text(encoding="utf-8") == "hello world\n"
    finally:
        pass


def test_full_workflow_cli(tmp_path: Path, capsys):
    orig_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        # init
        assert main(["init"]) == 0
        out, _ = capsys.readouterr()
        assert "Initialized empty Tiny Git repository" in out

        # config
        assert main(["config", "user.name", "Test User"]) == 0
        assert main(["config", "user.name"]) == 0
        out, _ = capsys.readouterr()
        assert "Test User" in out

        # add & commit
        (tmp_path / "main.py").write_text("print(1)\n", encoding="utf-8")
        assert main(["status"]) == 0
        out, _ = capsys.readouterr()
        assert "Untracked files:" in out
        assert "main.py" in out

        assert main(["add", "."]) == 0
        assert main(["diff", "--cached"]) == 0
        out, _ = capsys.readouterr()
        assert "+print(1)" in out

        assert main(["commit", "-m", "First commit"]) == 0
        out, _ = capsys.readouterr()
        assert "First commit" in out

        # branch & checkout
        assert main(["branch", "dev"]) == 0
        assert main(["checkout", "dev"]) == 0
        out, _ = capsys.readouterr()
        assert "Switched to branch 'dev'" in out

        # modify & commit on dev
        (tmp_path / "main.py").write_text("print(2)\n", encoding="utf-8")
        assert main(["diff"]) == 0
        out, _ = capsys.readouterr()
        assert "-print(1)" in out
        assert "+print(2)" in out

        assert main(["add", "main.py"]) == 0
        assert main(["commit", "-m", "Second commit"]) == 0

        # checkout main & branch another branch for 3-way merge
        assert main(["checkout", "main"]) == 0
        assert main(["branch", "hotfix"]) == 0
        assert main(["checkout", "hotfix"]) == 0
        (tmp_path / "README.md").write_text("# Doc\n", encoding="utf-8")
        assert main(["add", "README.md"]) == 0
        assert main(["commit", "-m", "Add docs"]) == 0

        # checkout main, merge hotfix, then merge dev -> 3-way clean merge
        assert main(["checkout", "main"]) == 0
        assert main(["merge", "hotfix"]) == 0
        assert main(["merge", "dev"]) == 0

        # log
        assert main(["log", "--oneline"]) == 0
        out, _ = capsys.readouterr()
        lines = [line for line in out.strip().splitlines() if line]
        assert len(lines) >= 3
    finally:
        os.chdir(orig_cwd)
