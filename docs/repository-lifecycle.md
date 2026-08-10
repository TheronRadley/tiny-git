# Repository Lifecycle & Merge State Model

This document traces the internal lifecycle of a `tiny-git` repository from initial creation through divergent branching, conflicted merging, and conflict resolution.

---

## 1. Repository Initialization & Unborn Branches

```bash
tiny-git init
```
1. Creates directory layout `.tinygit/objects/` and `.tinygit/refs/heads/`.
2. Writes `[core] repositoryformatversion = 1` into `.tinygit/config`.
3. Writes `ref: refs/heads/main\n` into `.tinygit/HEAD`.
4. At this point, `.tinygit/refs/heads/main` does not exist on disk. This state is called an **unborn branch**.

---

## 2. Normal Staging & Committing

```bash
tiny-git add src/main.py
tiny-git commit -m "Initial commit"
```
1. `add` computes the SHA-1 blob hash of `src/main.py`, writes the Blob object to `.tinygit/objects/`, and records an entry in `.tinygit/index` at **stage 0** (normal stage).
2. `commit` builds a root Tree from stage-0 index entries, writes the Commit object, and creates `.tinygit/refs/heads/main` pointing to the commit hash.
3. `HEAD` now resolves via `refs/heads/main` to the initial commit.

---

## 3. Conflicted Three-Way Merges (`MERGE_HEAD` & Index Stages)

```bash
tiny-git merge feature
```

When a three-way merge encounters overlapping modifications to the same file (`src/main.py`), `tiny-git` transitions the repository into an explicit **Merge State**:

```
.tinygit/
├── MERGE_HEAD          ← Stores the target commit SHA-1 (incoming branch tip)
├── MERGE_MODE          ← Stores the target branch name ("feature")
└── index               ← Stores conflict stages (1, 2, 3) for unmerged paths
```

### Conflict Index Stages
For each unmerged path, `tiny-git` records up to three entries in `.tinygit/index`:
- **Stage 1 (LCA / Common Ancestor)**: The file hash in the Lowest Common Ancestor commit (`A`).
- **Stage 2 (Ours / HEAD)**: The file hash in current `HEAD` (`B`).
- **Stage 3 (Theirs / Incoming)**: The file hash in the target branch (`C`).

While in this state:
- `tiny-git status` reports `You are currently merging feature.` and lists unmerged paths.
- `tiny-git commit` refuses to commit until all conflicts are resolved (`WorkingTreeDirtyError`).

---

## 4. Conflict Resolution & Multi-Parent Commits

```bash
# 1. User edits src/main.py to remove conflict markers
# 2. User stages the resolved file
tiny-git add src/main.py
```
1. Calling `add` on an unmerged path removes stages 1, 2, and 3 from `.tinygit/index` and records the resolved content at **stage 0**.
2. Once all paths are at stage 0, `tiny-git commit` reads `.tinygit/MERGE_HEAD`, creates a Commit object with **two parents** (`[HEAD_sha, MERGE_HEAD_sha]`), and deletes `.tinygit/MERGE_HEAD` and `.tinygit/MERGE_MODE`.
3. The merge state is completed and the repository returns to a clean state.

---

## 5. Aborting a Conflicted Merge

```bash
tiny-git merge --abort
```
If the user decides to discard a conflicted merge:
1. `tiny-git` checks that `.tinygit/MERGE_HEAD` exists.
2. It restores the working directory files and index entries to match the pre-merge `HEAD` tree snapshot.
3. It removes `.tinygit/MERGE_HEAD` and `.tinygit/MERGE_MODE`.
