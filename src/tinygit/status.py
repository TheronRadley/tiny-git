"""Status service comparing HEAD -> INDEX -> WORKING TREE."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tinygit.index import Index
from tinygit.objects import ObjectStore
from tinygit.refs import ReferenceManager
from tinygit.working_tree import WorkingTree


@dataclass
class StatusResult:
    """The result of a status comparison across HEAD, Index, and Working Tree."""

    branch: str | None = "main"
    head_commit: str | None = None
    staged_added: list[str] = field(default_factory=list)
    staged_modified: list[str] = field(default_factory=list)
    staged_deleted: list[str] = field(default_factory=list)
    unstaged_modified: list[str] = field(default_factory=list)
    unstaged_deleted: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    merge_head: str | None = None
    merge_branch: str | None = None
    unmerged_paths: list[str] = field(default_factory=list)

    def is_clean(self) -> bool:
        """Return True if there are no staged, unstaged, unmerged, or untracked changes."""
        return not (
            self.staged_added
            or self.staged_modified
            or self.staged_deleted
            or self.unstaged_modified
            or self.unstaged_deleted
            or self.unmerged_paths
            or self.untracked
        )

    def has_staged_changes(self) -> bool:
        """Return True if there are any staged changes."""
        return bool(self.staged_added or self.staged_modified or self.staged_deleted)

    def has_unstaged_changes(self) -> bool:
        """Return True if there are any unstaged changes."""
        return bool(self.unstaged_modified or self.unstaged_deleted)

    def format(self) -> str:
        """Format the status report in a clear Git-like human-readable format."""
        lines = []
        if self.branch:
            lines.append(f"On branch {self.branch}")
        elif self.head_commit:
            lines.append(f"Detached HEAD at {self.head_commit[:7]}")
        else:
            lines.append("On branch main (unborn)")

        if not self.head_commit and self.branch:
            lines.append("No commits yet")

        if self.merge_head:
            lines.append("")
            lines.append(f"You are currently merging {self.merge_branch or self.merge_head[:7]}.")

        if self.unmerged_paths:
            lines.append("")
            lines.append("Unmerged paths:")
            for p in sorted(self.unmerged_paths):
                lines.append(f"  both modified:   {p}")

        if self.has_staged_changes():
            lines.append("")
            lines.append("Changes to be committed:")
            for p in sorted(self.staged_added):
                lines.append(f"  new file:   {p}")
            for p in sorted(self.staged_modified):
                lines.append(f"  modified:   {p}")
            for p in sorted(self.staged_deleted):
                lines.append(f"  deleted:    {p}")

        if self.has_unstaged_changes():
            lines.append("")
            lines.append("Changes not staged for commit:")
            for p in sorted(self.unstaged_modified):
                lines.append(f"  modified:   {p}")
            for p in sorted(self.unstaged_deleted):
                lines.append(f"  deleted:    {p}")

        if self.untracked:
            lines.append("")
            lines.append("Untracked files:")
            for p in sorted(self.untracked):
                lines.append(f"  {p}")

        if self.is_clean():
            lines.append("")
            lines.append("nothing to commit, working tree clean")

        return "\n".join(lines)

    def porcelain_codes(self) -> dict[str, str]:
        """Map each changed path to its two-character porcelain status code.

        The first character is the index (staged) state, the second the working
        tree state, matching `git status --porcelain`. A path can carry both,
        e.g. `MM` for staged and unstaged modifications to the same file.
        """
        codes: dict[str, list[str]] = {}
        unmerged = set(self.unmerged_paths)

        def put(path: str, x: str | None = None, y: str | None = None) -> None:
            slot = codes.setdefault(path, [" ", " "])
            if x is not None:
                slot[0] = x
            if y is not None:
                slot[1] = y

        # A conflicted path has no stage-0 entry, so nothing else in this method
        # would claim it. Lay the U code down first and skip the untracked pass
        # for these paths, so the merge stays visible in the output.
        for path in self.unmerged_paths:
            put(path, "U", "U")
        for path in self.staged_added:
            put(path, x="A")
        for path in self.staged_modified:
            put(path, x="M")
        for path in self.staged_deleted:
            put(path, x="D")
        for path in self.unstaged_modified:
            put(path, y="M")
        for path in self.unstaged_deleted:
            put(path, y="D")
        for path in self.untracked:
            if path not in unmerged:
                put(path, "?", "?")

        return {path: "".join(xy) for path, xy in codes.items()}

    def format_porcelain(self) -> str:
        """Machine-readable status, one `XY <path>` line per changed path."""
        codes = self.porcelain_codes()
        if not codes:
            return ""
        return "\n".join(f"{codes[p]} {p}" for p in sorted(codes))

    def format_short(self) -> str:
        """Compact human-readable status (`git status --short`)."""
        lines = []
        if self.branch:
            lines.append(f"## {self.branch}")
        elif self.head_commit:
            lines.append(f"## HEAD (detached at {self.head_commit[:7]})")
        else:
            lines.append("## No commits yet")

        codes = self.porcelain_codes()
        lines.extend(f"{codes[p]} {p}" for p in sorted(codes))

        if self.unmerged_paths:
            lines.append("")
            lines.append("Unmerged paths: commit the resolution or run 'tiny-git merge --abort'.")
        elif self.merge_head:
            lines.append("")
            lines.append(f"Merging {self.merge_branch or self.merge_head[:7]}.")
        elif len(lines) == 1:
            lines = [f"## {lines[0][3:]}", ""]
        return "\n".join(lines)


class StatusService:
    """Service for computing StatusResult across HEAD -> Index -> Working Tree."""

    @staticmethod
    def get_status(
        repo_root: Path,
        refs: ReferenceManager,
        index: Index,
        wt: WorkingTree,
        store: ObjectStore,
    ) -> StatusResult:
        branch = refs.get_current_branch()
        head_commit = refs.get_head_commit()

        head_map: dict[str, tuple[str, str]] = {}
        if head_commit:
            commit_obj = store.read_commit(head_commit)
            head_map = wt.get_tree_entries_flat(commit_obj.tree_id, store)

        index_map: dict[str, tuple[str, str]] = {
            entry.path: (entry.object_id, entry.mode) for entry in index.list_stage0_entries()
        }

        res = StatusResult(branch=branch, head_commit=head_commit)
        res.unmerged_paths = index.get_unmerged_paths()

        merge_head_path = repo_root / ".tinygit" / "MERGE_HEAD"
        merge_mode_path = repo_root / ".tinygit" / "MERGE_MODE"
        if merge_head_path.exists():
            try:
                res.merge_head = merge_head_path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        if merge_mode_path.exists():
            try:
                res.merge_branch = merge_mode_path.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        # 1. Compare HEAD -> INDEX for normal entries (stage 0).
        # The mode is part of the comparison: toggling the executable bit with no
        # edit to the bytes is a real staged change, and comparing object ids
        # alone makes it invisible.
        for path, staged_val in index_map.items():
            if path in res.unmerged_paths:
                continue
            if path not in head_map:
                res.staged_added.append(path)
            elif staged_val != head_map[path]:
                res.staged_modified.append(path)

        for path in head_map:
            # index_map holds stage-0 entries only, so a conflicted path is
            # absent from it. That absence is the conflict, not a staged
            # deletion -- the unmerged guard keeps the two distinguishable.
            if path not in index_map and path not in res.unmerged_paths:
                res.staged_deleted.append(path)

        # 2. Compare INDEX -> WORKING TREE
        disk_files = set(wt.list_files(always_include=index_map.keys()))
        for path, index_val in index_map.items():
            if path not in disk_files:
                res.unstaged_deleted.append(path)
            else:
                disk_state = wt.get_file_state(path)
                if disk_state is not None and disk_state != index_val:
                    res.unstaged_modified.append(path)

        unmerged = set(res.unmerged_paths)
        for path in sorted(disk_files):
            if path not in index_map and path not in unmerged:
                res.untracked.append(path)

        return res
