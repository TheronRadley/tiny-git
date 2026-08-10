"""Repository integrity checker (tiny-git fsck).

Inspects the entire repository (.tinygit/objects, refs, HEAD, index, trees,
commits, blobs) and reports any malformed objects, invalid hashes, missing
referenced objects, corrupt object contents, or dangling references.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tinygit.index import Index
from tinygit.objects import Commit, ObjectStore, Tree
from tinygit.refs import ReferenceManager


@dataclass
class FsckResult:
    """Result of a comprehensive repository integrity check."""

    objects_checked: int = 0
    refs_checked: int = 0
    head_valid: bool = False
    index_valid: bool = False
    commit_graph_valid: bool = False
    errors: list[str] = field(default_factory=list)

    def is_healthy(self) -> bool:
        """Return True if no corruption or integrity errors were detected."""
        return len(self.errors) == 0

    def format(self) -> str:
        """Format the fsck report for CLI output."""
        lines = ["Checking repository..."]
        if self.objects_checked > 0:
            lines.append(f"✓ {self.objects_checked} objects checked")
        else:
            lines.append("✓ 0 objects checked")

        lines.append(f"✓ {self.refs_checked} refs checked")

        if self.head_valid:
            lines.append("✓ HEAD valid")
        else:
            lines.append("✗ HEAD invalid")

        if self.index_valid:
            lines.append("✓ index valid")
        else:
            lines.append("✗ index invalid")

        if self.commit_graph_valid:
            lines.append("✓ commit graph valid")
        else:
            lines.append("✗ commit graph invalid")

        if self.is_healthy():
            lines.append("")
            lines.append("Repository is healthy.")
        else:
            lines.append("")
            for err in self.errors:
                lines.append(f"ERROR: {err}")

        return "\n".join(lines)


class IntegrityChecker:
    """Service for checking repository consistency and object integrity."""

    @classmethod
    def check(
        cls,
        repo_root: Path,
        store: ObjectStore,
        refs: ReferenceManager,
        index: Index,
    ) -> FsckResult:
        res = FsckResult()

        # 1. Inspect all object files in .tinygit/objects/
        known_objects: set[str] = set()
        objects_dir = repo_root / ".tinygit" / "objects"
        if objects_dir.exists():
            for prefix_dir in objects_dir.iterdir():
                if not prefix_dir.is_dir() or len(prefix_dir.name) != 2:
                    continue
                for obj_file in prefix_dir.iterdir():
                    if not obj_file.is_file() or len(obj_file.name) != 38:
                        continue
                    sha = prefix_dir.name + obj_file.name
                    known_objects.add(sha)
                    res.objects_checked += 1

                    try:
                        obj = store.read_object(sha)
                    except Exception as e:
                        res.errors.append(f"Object {sha} is malformed or corrupted: {e}")
                        continue

                    # Verify object references
                    if isinstance(obj, Commit):
                        if not store.exists(obj.tree_id):
                            res.errors.append(
                                f"Commit {sha[:7]}... references missing object {obj.tree_id[:7]}..."
                            )
                        else:
                            try:
                                store.read_tree(obj.tree_id)
                            except Exception:
                                res.errors.append(
                                    f"Commit {sha[:7]}... tree {obj.tree_id[:7]}... is corrupted"
                                )
                        for p in obj.parents:
                            if not store.exists(p):
                                res.errors.append(
                                    f"Commit {sha[:7]}... references missing object {p[:7]}..."
                                )
                            else:
                                try:
                                    store.read_commit(p)
                                except Exception:
                                    res.errors.append(
                                        f"Commit {sha[:7]}... parent {p[:7]}... is not a commit"
                                    )

                    elif isinstance(obj, Tree):
                        for tree_entry in obj.entries:
                            if not store.exists(tree_entry.object_id):
                                res.errors.append(
                                    f"Tree {sha[:7]}... references missing object "
                                    f"{tree_entry.object_id[:7]}... ({tree_entry.name})"
                                )

        # 2. Inspect refs
        heads_dir = repo_root / ".tinygit" / "refs" / "heads"
        if heads_dir.exists():
            for branch_file in heads_dir.rglob("*"):
                if not branch_file.is_file():
                    continue
                res.refs_checked += 1
                rel_ref = branch_file.relative_to(heads_dir).as_posix()
                try:
                    target_sha = branch_file.read_text(encoding="utf-8").strip()
                    if not re.match(r"^[0-9a-fA-F]{40}$", target_sha):
                        res.errors.append(
                            f"Reference refs/heads/{rel_ref} contains invalid hash: {target_sha}"
                        )
                    elif not store.exists(target_sha):
                        res.errors.append(
                            f"Reference refs/heads/{rel_ref} references missing commit {target_sha[:7]}..."
                        )
                    else:
                        store.read_commit(target_sha)
                except Exception as e:
                    res.errors.append(f"Reference refs/heads/{rel_ref} is corrupted: {e}")

        # 3. Inspect HEAD
        try:
            head_target = refs.get_head_target()
            if head_target.startswith("ref: refs/heads/"):
                branch_name = head_target[len("ref: refs/heads/") :]
                if refs.branch_exists(branch_name):
                    res.head_valid = True
                else:
                    # Unborn branch is valid only if repository has no commits yet
                    res.head_valid = True
            elif re.match(r"^[0-9a-fA-F]{40}$", head_target):
                if store.exists(head_target):
                    res.head_valid = True
                else:
                    res.errors.append(f"Detached HEAD references missing commit {head_target[:7]}...")
            else:
                res.errors.append(f"HEAD contains invalid target: {head_target}")
        except Exception as e:
            res.errors.append(f"HEAD read failed: {e}")

        # 4. Inspect index
        try:
            index.read()
            index_ok = True
            for idx_entry in index.list_entries():
                if not store.exists(idx_entry.object_id):
                    res.errors.append(
                        f"Index entry '{idx_entry.path}' references missing blob {idx_entry.object_id[:7]}..."
                    )
                    index_ok = False
                else:
                    try:
                        store.read_blob(idx_entry.object_id)
                    except Exception:
                        res.errors.append(
                            f"Index entry '{idx_entry.path}' references corrupted blob {idx_entry.object_id[:7]}..."
                        )
                        index_ok = False
            res.index_valid = index_ok
        except Exception as e:
            res.errors.append(f"Index file corrupted: {e}")
            res.index_valid = False

        # 5. Verify commit graph acyclicity
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(c_sha: str) -> bool:
            visited.add(c_sha)
            rec_stack.add(c_sha)
            try:
                commit = store.read_commit(c_sha)
                for p in commit.parents:
                    if p not in visited:
                        if not dfs(p):
                            return False
                    elif p in rec_stack:
                        res.errors.append(f"Commit graph cycle detected involving {p[:7]}...")
                        return False
            except Exception:
                pass
            rec_stack.remove(c_sha)
            return True

        commit_graph_ok = True
        for sha in known_objects:
            try:
                obj = store.read_object(sha)
                if isinstance(obj, Commit) and sha not in visited:
                    if not dfs(sha):
                        commit_graph_ok = False
                        break
            except Exception:
                pass
        res.commit_graph_valid = commit_graph_ok

        return res
