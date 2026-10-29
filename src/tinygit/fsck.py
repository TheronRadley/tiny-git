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
from tinygit.objects import VALID_TREE_MODES, Commit, ObjectStore, Tree
from tinygit.refs import ReferenceManager
from tinygit.utils import METADATA_DIR_NAMES

_SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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

        cls._check_objects(repo_root, store, res)
        cls._check_refs(repo_root, store, res)
        cls._check_head(repo_root, store, refs, res)
        cls._check_index(store, index, res)
        cls._check_repository_format(repo_root, res)
        cls._check_commit_graph(store, res)

        return res

    # ------------------------------------------------------------------
    # Objects
    # ------------------------------------------------------------------
    @classmethod
    def _check_objects(cls, repo_root: Path, store: ObjectStore, res: FsckResult) -> None:
        """Inspect every loose object: payload integrity, schema, and references."""
        objects_dir = repo_root / ".tinygit" / "objects"
        if not objects_dir.exists():
            return

        for prefix_dir in objects_dir.iterdir():
            if not prefix_dir.is_dir() or len(prefix_dir.name) != 2:
                continue
            for obj_file in prefix_dir.iterdir():
                if not obj_file.is_file() or len(obj_file.name) != 38:
                    continue
                sha = prefix_dir.name + obj_file.name
                res.objects_checked += 1

                try:
                    obj = store.read_object(sha)
                except Exception as e:
                    res.errors.append(f"Object {sha} is malformed or corrupted: {e}")
                    continue

                if isinstance(obj, Commit):
                    cls._check_commit_refs(sha, obj, store, res)
                elif isinstance(obj, Tree):
                    cls._check_tree(sha, obj, store, res)

    @classmethod
    def _check_commit_refs(cls, sha: str, obj: Commit, store: ObjectStore, res: FsckResult) -> None:
        if not store.exists(obj.tree_id):
            res.errors.append(f"Commit {sha[:7]}... references missing object {obj.tree_id[:7]}...")
        else:
            try:
                store.read_tree(obj.tree_id)
            except Exception as e:
                res.errors.append(f"Commit {sha[:7]}... tree {obj.tree_id[:7]}... is not a valid tree: {e}")

        for p in obj.parents:
            if not store.exists(p):
                res.errors.append(f"Commit {sha[:7]}... references missing object {p[:7]}...")
            else:
                try:
                    store.read_commit(p)
                except Exception:
                    res.errors.append(f"Commit {sha[:7]}... parent {p[:7]}... is not a commit")

    @classmethod
    def _check_tree(cls, sha: str, obj: Tree, store: ObjectStore, res: FsckResult) -> None:
        """Validate a tree's entry names, modes, duplicates, and referent types.

        Unsafe names and duplicate entries are rejected when the tree is parsed,
        so a tree that reaches this method has already passed those checks --
        ``_check_objects`` reports the parse failure as a malformed object. The
        name checks below stay as defence in depth for a Tree built in memory
        rather than read from disk.

        The referent-type check is the one only fsck performs: a directory entry
        pointing at a blob, or a file entry pointing at a tree, is a structurally
        valid object that no command can check out.
        """
        for entry in obj.entries:
            short = sha[:7]
            if not entry.name or entry.name in (".", ".."):
                res.errors.append(f"Tree {short}... has an unsafe entry name: {entry.name!r}")
            elif "/" in entry.name or "\\" in entry.name:
                res.errors.append(f"Tree {short}... entry name contains a path separator: {entry.name!r}")
            elif any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in entry.name):
                res.errors.append(f"Tree {short}... entry name contains a control character: {entry.name!r}")
            elif entry.name in METADATA_DIR_NAMES:
                res.errors.append(f"Tree {short}... entry name is reserved metadata: {entry.name!r}")

            if entry.mode not in VALID_TREE_MODES:
                res.errors.append(f"Tree {short}... entry {entry.name!r} has unsupported mode {entry.mode}")

            if not store.exists(entry.object_id):
                res.errors.append(f"Tree {short}... references missing object {entry.object_id[:7]}... ({entry.name})")
                continue

            try:
                referent = store.read_object(entry.object_id)
            except Exception as e:
                res.errors.append(
                    f"Tree {short}... entry {entry.name!r} references unreadable object {entry.object_id[:7]}...: {e}"
                )
                continue

            expected = "tree" if entry.mode == "040000" else "blob"
            if referent.type != expected:
                res.errors.append(
                    f"Tree {short}... entry {entry.name!r} (mode {entry.mode}) points to a "
                    f"{referent.type}, expected a {expected}"
                )

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------
    @classmethod
    def _check_refs(cls, repo_root: Path, store: ObjectStore, res: FsckResult) -> None:
        heads_dir = repo_root / ".tinygit" / "refs" / "heads"
        if not heads_dir.exists():
            return
        for branch_file in heads_dir.rglob("*"):
            if not branch_file.is_file():
                continue
            res.refs_checked += 1
            rel_ref = branch_file.relative_to(heads_dir).as_posix()
            try:
                target_sha = branch_file.read_text(encoding="utf-8").strip()
                if not _SHA1_RE.match(target_sha):
                    res.errors.append(f"Reference refs/heads/{rel_ref} contains invalid hash: {target_sha}")
                elif not store.exists(target_sha):
                    res.errors.append(f"Reference refs/heads/{rel_ref} references missing commit {target_sha[:7]}...")
                else:
                    store.read_commit(target_sha)
            except Exception as e:
                res.errors.append(f"Reference refs/heads/{rel_ref} is corrupted: {e}")

    @classmethod
    def _check_head(cls, repo_root: Path, store: ObjectStore, refs: ReferenceManager, res: FsckResult) -> None:
        """Validate HEAD's shape and that it resolves to a commit.

        A detached HEAD holding a well-formed hash that names a blob or a tree
        passes an existence check but breaks every command that reads history,
        so the referent's type is verified too.
        """
        try:
            head_target = refs.get_head_target()
        except Exception as e:
            res.errors.append(f"HEAD read failed: {e}")
            return

        try:
            if head_target.startswith("ref: "):
                if not head_target.startswith("ref: refs/heads/"):
                    res.errors.append(f"HEAD points outside refs/heads: {head_target}")
                    return
                branch_name = head_target[len("ref: refs/heads/") :]
                if not branch_name:
                    res.errors.append("HEAD points to an empty branch name")
                    return
                ref_path = repo_root / ".tinygit" / "refs" / "heads" / branch_name
                if not ref_path.exists():
                    # An unborn branch is a valid state for a fresh repository.
                    res.head_valid = True
                    return
                target_sha = ref_path.read_text(encoding="utf-8").strip()
                if not _SHA1_RE.match(target_sha):
                    res.errors.append(f"HEAD branch '{branch_name}' contains invalid hash: {target_sha}")
                    return
                if not store.exists(target_sha):
                    res.errors.append(f"HEAD branch '{branch_name}' references missing commit {target_sha[:7]}...")
                    return
                store.read_commit(target_sha)
                res.head_valid = True
            elif _SHA1_RE.match(head_target):
                if not store.exists(head_target):
                    res.errors.append(f"Detached HEAD references missing commit {head_target[:7]}...")
                    return
                obj = store.read_object(head_target)
                if obj.type != "commit":
                    res.errors.append(f"Detached HEAD references a {obj.type}, expected a commit")
                    return
                res.head_valid = True
            else:
                res.errors.append(f"HEAD contains invalid target: {head_target}")
        except Exception as e:
            res.errors.append(f"HEAD is corrupted: {e}")

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------
    @classmethod
    def _check_index(cls, store: ObjectStore, index: Index, res: FsckResult) -> None:
        """Validate index entries and the stage numbering that merges depend on.

        A path may be either resolved (stage 0) or conflicted (a subset of
        stages 1, 2, 3) -- never both, and never a stage outside that set. A
        path carrying both makes it look simultaneously resolved and conflicted
        to status, diff, and tree building.
        """
        try:
            index.read()
        except Exception as e:
            res.errors.append(f"Index file corrupted: {e}")
            res.index_valid = False
            return

        index_ok = True
        stages_by_path: dict[str, set[int]] = {}
        for entry in index.list_entries():
            stages_by_path.setdefault(entry.path, set()).add(entry.stage)

            if not _SHA1_RE.match(entry.object_id):
                res.errors.append(
                    f"Index entry '{entry.path}' (stage {entry.stage}) has a malformed object id: {entry.object_id}"
                )
                index_ok = False
                continue
            if not store.exists(entry.object_id):
                res.errors.append(f"Index entry '{entry.path}' references missing blob {entry.object_id[:7]}...")
                index_ok = False
                continue
            try:
                store.read_blob(entry.object_id)
            except Exception:
                res.errors.append(f"Index entry '{entry.path}' references corrupted blob {entry.object_id[:7]}...")
                index_ok = False

        for path, stages in sorted(stages_by_path.items()):
            if 0 in stages and len(stages) > 1:
                res.errors.append(
                    f"Index entry '{path}' is both resolved (stage 0) and conflicted (stages {sorted(stages - {0})})"
                )
                index_ok = False
            if stages - {0, 1, 2, 3}:
                res.errors.append(f"Index entry '{path}' has an out-of-range stage: {sorted(stages)}")
                index_ok = False

        res.index_valid = index_ok

    # ------------------------------------------------------------------
    # Format
    # ------------------------------------------------------------------
    @classmethod
    def _check_repository_format(cls, repo_root: Path, res: FsckResult) -> None:
        """Verify core.repositoryformatversion is present, numeric, and supported."""
        config_path = repo_root / ".tinygit" / "config"
        if not config_path.is_file():
            return
        raw = config_path.read_text(encoding="utf-8", errors="replace")
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped.startswith("repositoryformatversion"):
                continue
            if "=" not in stripped:
                res.errors.append(f"Malformed repositoryformatversion line in config: {stripped!r}")
                return
            value = stripped.split("=", 1)[1].strip()
            try:
                version = int(value)
            except ValueError:
                res.errors.append(f"Malformed core.repositoryformatversion in config: {value!r} is not an integer")
                return
            if version > 1:
                res.errors.append(f"Unsupported core.repositoryformatversion in config: {version} (supports up to 1)")
            return

    # ------------------------------------------------------------------
    # Commit graph
    # ------------------------------------------------------------------
    @classmethod
    def _check_commit_graph(cls, store: ObjectStore, res: FsckResult) -> None:
        """Verify the commit graph is acyclic."""
        objects_dir = store.objects_dir
        commit_shas: list[str] = []
        if objects_dir.exists():
            for prefix_dir in objects_dir.iterdir():
                if not prefix_dir.is_dir() or len(prefix_dir.name) != 2:
                    continue
                for obj_file in prefix_dir.iterdir():
                    if obj_file.is_file() and len(obj_file.name) == 38:
                        commit_shas.append(prefix_dir.name + obj_file.name)

        visited: set[str] = set()
        rec_stack: set[str] = set()
        graph_ok = True

        def dfs(c_sha: str) -> bool:
            visited.add(c_sha)
            rec_stack.add(c_sha)
            try:
                commit = store.read_commit(c_sha)
            except Exception:
                rec_stack.discard(c_sha)
                return True
            for p in commit.parents:
                if p not in visited:
                    if not dfs(p):
                        return False
                elif p in rec_stack:
                    res.errors.append(f"Commit graph cycle detected involving {p[:7]}...")
                    return False
            rec_stack.discard(c_sha)
            return True

        for sha in sorted(commit_shas):
            if sha in visited:
                continue
            try:
                obj = store.read_object(sha)
            except Exception:
                continue
            if isinstance(obj, Commit) and not dfs(sha):
                graph_ok = False
                break

        res.commit_graph_valid = graph_ok
