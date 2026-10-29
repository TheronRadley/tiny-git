"""Command-line interface for Tiny Git (`tiny-git`).

Provides a clean, human-readable CLI with structured error handling
and non-zero exit codes on failure without dumping tracebacks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tinygit.diff import DiffEngine
from tinygit.errors import InvalidPathError, TinyGitError
from tinygit.repository import Repository


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="tiny-git",
        description="Tiny Git: A small educational content-addressed version-control system inspired by Git.",
    )
    subparsers = parser.add_subparsers(dest="command", title="commands", required=True)

    # init
    init_parser = subparsers.add_parser("init", help="Initialize an empty Tiny Git repository")
    init_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to initialize (default: current directory)",
    )
    init_parser.add_argument(
        "-b",
        "--initial-branch",
        default="main",
        help="Initial branch name (default: main)",
    )

    # add
    add_parser = subparsers.add_parser("add", help="Add file contents to the index (staging area)")
    add_parser.add_argument("files", nargs="+", help="Files or directories to stage (use '.' for all)")
    add_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow adding a file explicitly named but matched by .tinygitignore",
    )

    # commit
    commit_parser = subparsers.add_parser("commit", help="Record changes to the repository")
    commit_parser.add_argument("-m", "--message", required=True, help="Commit message")
    commit_parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow creating a commit with no changes",
    )

    # status
    status_parser = subparsers.add_parser("status", help="Show the working tree status")
    status_parser.add_argument(
        "-s", "--short", dest="short", action="store_true", help="Show a compact two-column summary"
    )
    status_parser.add_argument(
        "--porcelain",
        action="store_true",
        help="Show machine-readable `XY <path>` output suitable for scripts",
    )

    # log
    log_parser = subparsers.add_parser("log", help="Show commit logs")
    log_parser.add_argument("--oneline", action="store_true", help="Show each commit on a single line")
    log_parser.add_argument("-n", "--max-count", type=int, default=None, help="Limit number of commits to output")

    # branch
    branch_parser = subparsers.add_parser("branch", help="List or create branches")
    branch_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Name of branch to create (if omitted, lists branches)",
    )

    # checkout
    checkout_parser = subparsers.add_parser("checkout", help="Switch branches or restore working tree files")
    checkout_parser.add_argument("target", help="Branch name or commit SHA-1 prefix to checkout")
    checkout_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Discard local changes and make the working tree match the target exactly",
    )

    # merge
    merge_parser = subparsers.add_parser("merge", help="Join two or more development histories together")
    merge_parser.add_argument("branch", nargs="?", default=None, help="Branch to merge into current branch")
    merge_parser.add_argument(
        "--abort",
        action="store_true",
        help="Abort the current conflicted merge and restore pre-merge state",
    )

    # diff
    diff_parser = subparsers.add_parser(
        "diff",
        help="Show changes between commits, commit and working tree, etc",
    )
    diff_parser.add_argument(
        "--cached",
        "--staged",
        dest="cached",
        action="store_true",
        help="Show changes staged for next commit",
    )

    # config
    config_parser = subparsers.add_parser("config", help="Get and set repository or global options")
    config_parser.add_argument("key", help="Configuration key (e.g., user.name)")
    config_parser.add_argument("value", nargs="?", default=None, help="Value to set")

    # reflog
    reflog_parser = subparsers.add_parser("reflog", help="Show the HEAD reference log, for recovering from bad resets")
    reflog_parser.add_argument("-n", "--max-count", type=int, default=None, help="Limit to the most recent N entries")

    # fsck
    subparsers.add_parser("fsck", help="Check repository integrity and object consistency")

    # cat-file
    cat_file_parser = subparsers.add_parser(
        "cat-file",
        help="Provide content or type and size information for repository objects",
    )
    cat_file_parser.add_argument("object", help="The object SHA-1 or revision to display")
    cat_file_parser.add_argument("-t", "--type", dest="show_type", action="store_true", help="Show object type")
    cat_file_parser.add_argument("-s", "--size", dest="show_size", action="store_true", help="Show object size")
    cat_file_parser.add_argument(
        "-p",
        "--pretty",
        dest="pretty",
        action="store_true",
        default=True,
        help="Pretty-print object content",
    )

    # show
    show_parser = subparsers.add_parser("show", help="Show commit metadata and diff against parent")
    show_parser.add_argument("revision", nargs="?", default="HEAD", help="Revision to show (default: HEAD)")

    # rev-parse
    rev_parse_parser = subparsers.add_parser("rev-parse", help="Resolve revision expression to full SHA-1")
    rev_parse_parser.add_argument("revision", help="Revision expression (e.g., HEAD~1, main, short SHA)")

    # rm
    rm_parser = subparsers.add_parser("rm", help="Remove files from index and working tree")
    rm_parser.add_argument("files", nargs="+", help="Files to remove")
    rm_parser.add_argument(
        "--cached",
        action="store_true",
        help="Only remove from index, leave working tree file",
    )
    rm_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Discard uncommitted changes to the removed files instead of refusing",
    )

    # restore
    restore_parser = subparsers.add_parser("restore", help="Restore working tree files or unstage from index")
    restore_parser.add_argument("files", nargs="+", help="Files to restore")
    restore_parser.add_argument(
        "--staged",
        action="store_true",
        help="Restore index from HEAD (unstage changes)",
    )

    return parser


def _to_repo_paths(user_paths: list[str], repo: Repository) -> list[str]:
    """Translate caller-supplied paths into repository-relative POSIX paths.

    The user's paths are relative to their shell's working directory, which is
    not necessarily the repository root. Without this translation, running
    `tiny-git add notes.txt` from `docs/` looks for `<repo>/notes.txt` instead
    of `<repo>/docs/notes.txt`.

    A bare "." keeps its meaning -- everything under the caller's directory --
    by becoming that directory's repository-relative path.
    """
    resolved: list[str] = []
    for raw in user_paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            rel = candidate.resolve().relative_to(repo.repo_root).as_posix()
        except ValueError:
            raise InvalidPathError(raw, "Path is outside repository") from None
        resolved.append(rel if rel else ".")
    return resolved


def run_command(args: argparse.Namespace) -> int:
    """Execute the command handler and return an exit code."""
    cmd = args.command

    if cmd == "init":
        repo = Repository.init(args.path, default_branch=args.initial_branch)
        print(f"Initialized empty Tiny Git repository in {repo.tinygit_dir}")
        return 0

    # For all other commands, locate the repository upwards
    repo = Repository.find_repo(Path("."))

    if cmd == "add":
        _ = repo.add(_to_repo_paths(args.files, repo), force=args.force)
        return 0

    elif cmd == "commit":
        sha = repo.commit(args.message, allow_empty=args.allow_empty)
        branch_name = repo.refs.get_current_branch() or "detached HEAD"
        first_line = args.message.splitlines()[0]
        print(f"[{branch_name} {sha[:7]}] {first_line}")
        return 0

    elif cmd == "status":
        res = repo.status()
        if args.porcelain:
            output = res.format_porcelain()
            if output:
                print(output)
        elif args.short:
            print(res.format_short())
        else:
            print(res.format())
        return 0

    elif cmd == "reflog":
        reflog_entries = repo.reflog(max_count=args.max_count)
        if not reflog_entries:
            print("No reflog entries yet.")
            return 0
        for reflog_entry in reflog_entries:
            print(reflog_entry.format())
        return 0

    elif cmd == "log":
        entries = repo.log(max_count=args.max_count, oneline=args.oneline)
        for i, entry in enumerate(entries):
            print(entry.format(oneline=args.oneline))
            if not args.oneline and i < len(entries) - 1:
                print()
        return 0

    elif cmd == "branch":
        branch_res = repo.branch(args.name)
        if isinstance(branch_res, list):
            for name, is_current in branch_res:
                prefix = "* " if is_current else "  "
                print(f"{prefix}{name}")
        else:
            print(f"Created branch '{branch_res}'")
        return 0

    elif cmd == "checkout":
        msg = repo.checkout(args.target, force=args.force)
        print(msg)
        return 0

    elif cmd == "merge":
        if args.abort:
            abort_msg = repo.merge(abort=True)
            print(abort_msg)
            return 0
        if not args.branch:
            print("error: No branch specified for merge", file=sys.stderr)
            return 1
        merge_res = repo.merge(args.branch)
        if not isinstance(merge_res, str) and not merge_res.is_success():
            print(merge_res.message, file=sys.stderr)
            return 1
        print(merge_res.message if not isinstance(merge_res, str) else merge_res)
        return 0

    elif cmd == "diff":
        changes = repo.diff(cached=args.cached)
        output = DiffEngine.format_diff(changes)
        if output:
            print(output)
        return 0

    elif cmd == "config":
        if args.value is not None:
            repo.config.set(args.key, args.value)
            return 0
        else:
            val = repo.config.get(args.key)
            if val is None:
                print(f"Configuration key not found: {args.key}", file=sys.stderr)
                return 1
            print(val)
            return 0

    elif cmd == "fsck":
        fsck_res = repo.fsck()
        print(fsck_res.format())
        return 0 if fsck_res.is_healthy() else 1

    elif cmd == "cat-file":
        out = repo.cat_file(
            args.object,
            pretty=args.pretty and not args.show_type and not args.show_size,
            obj_type_only=args.show_type,
            size_only=args.show_size,
        )
        print(out)
        return 0

    elif cmd == "show":
        out = repo.show(args.revision)
        print(out)
        return 0

    elif cmd == "rev-parse":
        sha = repo.rev_parse(args.revision)
        print(sha)
        return 0

    elif cmd == "rm":
        removed = repo.rm(_to_repo_paths(args.files, repo), cached=args.cached, force=args.force)
        for p in removed:
            print(f"rm '{p}'")
        return 0

    elif cmd == "restore":
        _ = repo.restore(_to_repo_paths(args.files, repo), staged=args.staged)
        return 0

    return 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()

    try:
        args = parser.parse_args(argv)
        return run_command(args)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    except TinyGitError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
