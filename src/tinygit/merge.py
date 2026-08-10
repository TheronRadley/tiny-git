"""Three-way merge engine for Tiny Git.

Implements:
  - Lowest Common Ancestor (LCA) graph search
  - Fast-forward merge detection
  - True 3-way file and line-level merge with conflict detection
  - Git-like conflict markers (<<<<<<< HEAD ... ======= ... >>>>>>> branch)
  - Merge commit creation with multiple parents
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from tinygit.errors import InvalidReferenceError, WorkingTreeDirtyError
from tinygit.index import Index
from tinygit.objects import Blob, Commit, ObjectStore
from tinygit.refs import ReferenceManager
from tinygit.status import StatusService
from tinygit.utils import atomic_write_file, get_timestamp, is_binary_bytes
from tinygit.working_tree import WorkingTree


@dataclass
class Conflict:
    """Represents a merge conflict in a single file."""

    path: str
    reason: str
    head_content: bytes | None = None
    target_content: bytes | None = None


@dataclass
class MergeResult:
    """Result of a merge operation."""

    status: str  # 'up-to-date', 'fast-forward', 'clean', 'conflict'
    commit_sha: str | None = None
    message: str = ""
    conflicts: list[Conflict] = field(default_factory=list)

    def is_success(self) -> bool:
        return self.status in ("up-to-date", "fast-forward", "clean")


class MergeEngine:
    """Engine for performing three-way merges between branches."""

    @staticmethod
    def find_lca(commit_sha1: str, commit_sha2: str, store: ObjectStore) -> str | None:
        """Find the Lowest Common Ancestor (LCA) commit of two commits."""
        if commit_sha1 == commit_sha2:
            return commit_sha1

        # Collect all ancestors of sha1 with BFS
        ancestors_1: dict[str, int] = {}
        queue: list[tuple[str, int]] = [(commit_sha1, 0)]
        while queue:
            curr, depth = queue.pop(0)
            if curr in ancestors_1:
                continue
            ancestors_1[curr] = depth
            try:
                obj = store.read_commit(curr)
                for p in obj.parents:
                    queue.append((p, depth + 1))
            except Exception:
                pass

        # BFS from sha2 to find first commit in ancestors_1
        queue2: list[tuple[str, int]] = [(commit_sha2, 0)]
        visited_2: set[str] = set()
        best_lca: str | None = None
        best_depth = float("inf")

        while queue2:
            curr, depth = queue2.pop(0)
            if curr in visited_2:
                continue
            visited_2.add(curr)

            if curr in ancestors_1:
                tot_depth = depth + ancestors_1[curr]
                if tot_depth < best_depth:
                    best_depth = tot_depth
                    best_lca = curr
                continue

            try:
                obj = store.read_commit(curr)
                for p in obj.parents:
                    queue2.append((p, depth + 1))
            except Exception:
                pass

        return best_lca

    @classmethod
    def _merge_3way_lines(
        cls, a_lines: list[str], b_lines: list[str], c_lines: list[str], target_branch: str
    ) -> tuple[list[str], bool]:
        """Line-by-line 3-way merge of text lines using edit regions."""
        sm_b = difflib.SequenceMatcher(None, a_lines, b_lines)
        sm_c = difflib.SequenceMatcher(None, a_lines, c_lines)

        opcodes_b = sm_b.get_opcodes()
        opcodes_c = sm_c.get_opcodes()

        # Build edit intervals in A for B and C
        edits_b = []
        for tag, i1, i2, j1, j2 in opcodes_b:
            if tag != "equal":
                edits_b.append((i1, i2, j1, j2))

        edits_c = []
        for tag, i1, i2, k1, k2 in opcodes_c:
            if tag != "equal":
                edits_c.append((i1, i2, k1, k2))

        # Merge overlapping intervals across B and C
        events = []
        for i1, i2, j1, j2 in edits_b:
            events.append((i1, i2, "B", j1, j2))
        for i1, i2, k1, k2 in edits_c:
            events.append((i1, i2, "C", k1, k2))

        events.sort(key=lambda x: (x[0], x[1]))

        merged_blocks = []
        i = 0
        while i < len(events):
            start_a = events[i][0]
            end_a = events[i][1]
            block_events = [events[i]]
            j = i + 1
            while j < len(events) and events[j][0] <= end_a:
                end_a = max(end_a, events[j][1])
                block_events.append(events[j])
                j += 1
            merged_blocks.append((start_a, end_a, block_events))
            i = j

        result_lines = []
        has_conflict = False
        last_a = 0

        for start_a, end_a, block_events in merged_blocks:
            # Copy unchanged lines from A before this block
            if start_a > last_a:
                result_lines.extend(a_lines[last_a:start_a])

            has_b = any(e[2] == "B" for e in block_events)
            has_c = any(e[2] == "C" for e in block_events)

            if has_b and not has_c:
                # Only B edited this region
                for e in block_events:
                    result_lines.extend(b_lines[e[3] : e[4]])
            elif has_c and not has_b:
                # Only C edited this region
                for e in block_events:
                    result_lines.extend(c_lines[e[3] : e[4]])
            else:
                # Both edited this region
                b_slice = []
                c_slice = []
                for e in block_events:
                    if e[2] == "B":
                        b_slice.extend(b_lines[e[3] : e[4]])
                    elif e[2] == "C":
                        c_slice.extend(c_lines[e[3] : e[4]])

                if b_slice == c_slice:
                    result_lines.extend(b_slice)
                else:
                    has_conflict = True
                    result_lines.append("<<<<<<< HEAD\n")
                    result_lines.extend(b_slice)
                    result_lines.append("=======\n")
                    result_lines.extend(c_slice)
                    result_lines.append(f">>>>>>> {target_branch}\n")

            last_a = max(last_a, end_a)

        if last_a < len(a_lines):
            result_lines.extend(a_lines[last_a:])

        return result_lines, has_conflict

    @classmethod
    def merge_3way_text(
        cls, a_bytes: bytes | None, b_bytes: bytes | None, c_bytes: bytes | None, target_branch: str
    ) -> tuple[bytes, bool]:
        """Three-way merge of file bytes, returning (merged_bytes, has_conflict)."""
        if b_bytes == c_bytes:
            return (b_bytes or b"", False)

        if a_bytes == b_bytes:
            return (c_bytes or b"", False)

        if a_bytes == c_bytes:
            return (b_bytes or b"", False)

        # One side deleted, one side modified
        if b_bytes is None and c_bytes is not None:
            c_text = c_bytes.decode("utf-8", errors="replace")
            conflict_str = f"<<<<<<< HEAD\n=======\n{c_text}>>>>>>> {target_branch}\n"
            return (conflict_str.encode("utf-8"), True)

        if c_bytes is None and b_bytes is not None:
            b_text = b_bytes.decode("utf-8", errors="replace")
            conflict_str = f"<<<<<<< HEAD\n{b_text}=======\n>>>>>>> {target_branch}\n"
            return (conflict_str.encode("utf-8"), True)

        if is_binary_bytes(b_bytes or b"") or is_binary_bytes(c_bytes or b""):
            # Cannot inline text conflict markers into binary files
            return (b_bytes or b"", True)

        a_lines = (a_bytes or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        b_lines = (b_bytes or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        c_lines = (c_bytes or b"").decode("utf-8", errors="replace").splitlines(keepends=True)

        res_lines, has_conflict = cls._merge_3way_lines(a_lines, b_lines, c_lines, target_branch)
        return ("".join(res_lines).encode("utf-8"), has_conflict)

    @classmethod
    def merge(
        cls,
        target_branch: str,
        refs: ReferenceManager,
        index: Index,
        wt: WorkingTree,
        store: ObjectStore,
        author_name: str = "Ron",
        author_email: str = "ron@example.com",
        timestamp: str | None = None,
    ) -> MergeResult:
        """Perform a three-way merge of target_branch into current HEAD."""
        if timestamp is None:
            timestamp = get_timestamp()

        # 1. Safety check: ensure working tree and index have no uncommitted modifications
        status_res = StatusService.get_status(wt.repo_root, refs, index, wt, store)
        if status_res.has_staged_changes() or status_res.has_unstaged_changes() or status_res.unmerged_paths:
            raise WorkingTreeDirtyError("Working tree has uncommitted changes. Cannot merge safely.")

        head_commit_sha = refs.get_head_commit()
        if not head_commit_sha:
            raise InvalidReferenceError("Cannot merge into unborn branch")

        target_commit_sha = refs.get_ref_commit(target_branch)
        if not target_commit_sha:
            raise InvalidReferenceError(target_branch)

        # 2. Find Lowest Common Ancestor
        lca_sha = cls.find_lca(head_commit_sha, target_commit_sha, store)
        if head_commit_sha == target_commit_sha or lca_sha == target_commit_sha:
            # Already up to date
            return MergeResult(
                status="up-to-date",
                commit_sha=head_commit_sha,
                message="Already up to date.",
            )

        if lca_sha == head_commit_sha:
            # Fast-forward merge
            wt.checkout_tree(
                store.read_commit(target_commit_sha).tree_id,
                head_tree_sha=store.read_commit(head_commit_sha).tree_id,
                index=index,
                store=store,
            )
            refs.update_head_commit(target_commit_sha)
            return MergeResult(
                status="fast-forward",
                commit_sha=target_commit_sha,
                message=f"Fast-forward merge to {target_commit_sha[:7]}",
            )

        # 3. Three-way merge
        lca_tree_sha = store.read_commit(lca_sha).tree_id if lca_sha else None
        head_tree_sha = store.read_commit(head_commit_sha).tree_id
        target_tree_sha = store.read_commit(target_commit_sha).tree_id

        lca_map = wt.get_tree_entries_flat(lca_tree_sha, store)
        head_map = wt.get_tree_entries_flat(head_tree_sha, store)
        target_map = wt.get_tree_entries_flat(target_tree_sha, store)

        all_paths = sorted(set(lca_map.keys()) | set(head_map.keys()) | set(target_map.keys()))

        conflicts: list[Conflict] = []
        merged_map: dict[str, tuple[str, str]] = {}

        for path in all_paths:
            lca_val = lca_map.get(path)
            head_val = head_map.get(path)
            target_val = target_map.get(path)

            if head_val == target_val:
                if head_val is not None:
                    merged_map[path] = head_val
                continue

            if head_val == lca_val:
                # Took target's change
                if target_val is not None:
                    merged_map[path] = target_val
                continue

            if target_val == lca_val:
                # Took HEAD's change
                if head_val is not None:
                    merged_map[path] = head_val
                continue

            # Both changed differently
            lca_bytes = store.read_blob(lca_val[0]).data if lca_val else None
            head_bytes = store.read_blob(head_val[0]).data if head_val else None
            target_bytes = store.read_blob(target_val[0]).data if target_val else None

            merged_bytes, has_conflict = cls.merge_3way_text(lca_bytes, head_bytes, target_bytes, target_branch)

            mode = head_val[1] if head_val else (target_val[1] if target_val else "100644")

            if has_conflict:
                conflicts.append(
                    Conflict(
                        path=path,
                        reason="content conflict",
                        head_content=head_bytes,
                        target_content=target_bytes,
                    )
                )
                # Write conflict markers to disk and stage them with conflict stages (1, 2, 3)
                blob = Blob(merged_bytes)
                new_sha = store.write_object(blob)
                merged_map[path] = (new_sha, mode)
                index.add(path, lca_val[0] if lca_val else ("0" * 40), mode=mode, stage=1)
                index.add(path, head_val[0] if head_val else ("0" * 40), mode=mode, stage=2)
                index.add(path, target_val[0] if target_val else ("0" * 40), mode=mode, stage=3)
            else:
                if merged_bytes or (head_val or target_val):
                    blob = Blob(merged_bytes)
                    new_sha = store.write_object(blob)
                    merged_map[path] = (new_sha, mode)

        # Verify no untracked files will be overwritten by incoming merged files
        for path in sorted(merged_map.keys()):
            if path not in head_map:
                full_path = wt.repo_root / path
                if full_path.exists() and path not in index:
                    raise WorkingTreeDirtyError(f"Untracked working tree file '{path}' would be overwritten by merge.")

        # Update working directory and index with merged results (including conflict markers if any)
        # Remove files that are not in merged_map
        for path in sorted(head_map.keys()):
            if path not in merged_map:
                wt.remove_file(path)

        # Write merged files to disk
        for path, (sha, mode) in merged_map.items():
            blob_data = store.read_blob(sha).data
            wt.write_file(path, blob_data, mode=mode)

        # Rebuild index for clean entries (stage 0)
        for path, (sha, mode) in sorted(merged_map.items()):
            if any(c.path == path for c in conflicts):
                continue
            full_path = wt.repo_root / path
            size = full_path.stat().st_size if full_path.exists() else 0
            mtime = full_path.stat().st_mtime if full_path.exists() else 0.0
            index.add(path, sha, mode=mode, size=size, mtime=mtime, stage=0)
        index.write()

        if conflicts:
            # Write MERGE_HEAD and MERGE_MODE to record merge state
            atomic_write_file(wt.repo_root / ".tinygit" / "MERGE_HEAD", f"{target_commit_sha}\n")
            atomic_write_file(wt.repo_root / ".tinygit" / "MERGE_MODE", f"{target_branch}\n")
            return MergeResult(
                status="conflict",
                commit_sha=None,
                conflicts=conflicts,
                message="Automatic merge failed; fix conflicts and then commit the result.",
            )

        # Clean merge: create merge commit with 2 parents
        new_tree_sha = wt.build_tree_from_index(index, store)
        merge_commit = Commit(
            tree_id=new_tree_sha,
            parents=[head_commit_sha, target_commit_sha],
            author_name=author_name,
            author_email=author_email,
            timestamp=timestamp,
            message=f"Merge branch '{target_branch}'",
        )
        merge_commit_sha = store.write_object(merge_commit)
        refs.update_head_commit(merge_commit_sha)

        return MergeResult(
            status="clean",
            commit_sha=merge_commit_sha,
            message=f"Merge made by 3-way merge: {merge_commit_sha[:7]}",
        )
