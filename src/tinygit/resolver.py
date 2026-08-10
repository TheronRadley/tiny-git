"""Revision resolution engine for Tiny Git.

Resolves revision expressions such as:
  - HEAD
  - branch names (main, feature)
  - full or short SHA-1 prefixes (a82f1c2)
  - ancestry suffixes (~N, ^N, ^^, ~2^)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tinygit.errors import RevisionNotFoundError
from tinygit.objects import ObjectStore
from tinygit.refs import ReferenceManager


@dataclass
class Revision:
    """Resolved revision representing a commit SHA-1 and its reference context."""

    expression: str
    commit_sha: str
    is_branch: bool = False
    branch_name: str | None = None


class RevisionResolver:
    """Service for resolving arbitrary revision expressions to full commit SHA-1 hashes."""

    @classmethod
    def resolve(
        cls,
        expression: str,
        refs: ReferenceManager,
        store: ObjectStore,
    ) -> Revision:
        expr = expression.strip()
        if not expr:
            raise RevisionNotFoundError(expr)

        # Separate base name from ancestry modifiers (~N, ^N)
        match = re.search(r"[~^]", expr)
        if match:
            base_name = expr[: match.start()]
            modifiers = expr[match.start() :]
        else:
            base_name = expr
            modifiers = ""

        # 1. Resolve base name
        base_sha = refs.get_ref_commit(base_name)
        if not base_sha:
            raise RevisionNotFoundError(expression)

        is_branch = False
        branch_name = None
        if not modifiers and refs.branch_exists(base_name):
            is_branch = True
            branch_name = base_name

        # 2. Apply ancestry modifiers (~N, ^N)
        current_sha = base_sha
        if modifiers:
            if not re.match(r"^([~^]\d*)+$", modifiers):
                raise RevisionNotFoundError(expression)
            tokens = re.findall(r"([~^])(\d*)", modifiers)
            for op, count_str in tokens:
                count = int(count_str) if count_str != "" else 1
                if op == "~":
                    for _ in range(count):
                        current_sha = cls._get_parent(current_sha, 0, store, expression)
                elif op == "^":
                    if count == 0:
                        continue
                    parent_idx = (count - 1) if count > 0 else 0
                    current_sha = cls._get_parent(current_sha, parent_idx, store, expression)

        return Revision(
            expression=expression,
            commit_sha=current_sha,
            is_branch=is_branch,
            branch_name=branch_name,
        )

    @staticmethod
    def _get_parent(commit_sha: str, parent_idx: int, store: ObjectStore, original_expr: str) -> str:
        try:
            commit = store.read_commit(commit_sha)
        except Exception:
            raise RevisionNotFoundError(original_expr) from None
        if parent_idx < 0 or parent_idx >= len(commit.parents):
            raise RevisionNotFoundError(original_expr)
        return commit.parents[parent_idx]
