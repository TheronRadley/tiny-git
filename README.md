# Tiny Git

```
             ┌────────────────────────────────────────────────────────┐
             │                       TINY GIT                         │
             │     A small, educational, Git-inspired content-        │
             │        addressed version-control system.               │
             └────────────────────────────────────────────────────────┘
```

**[Python 3.12+]  [License: MIT]  [Tests: 98 Passed (0 Failed)]  [CLI Commands: 16 (Frozen)]**

`tiny-git` (`tiny-git`) is a small, cleanly designed open-source version-control system built from scratch in modern Python 3.12+. It implements content-addressed objects, a staging index, immutable commits, references, branching, unified diffs, and three-way merges without invoking Git.

---

## Why This Project Exists

Version control systems like Git are often perceived as mysterious "black boxes." While developers use `git` daily, fewer understand the fundamental mechanics of SHA-1 content-addressed storage, staging indices, immutable commit snapshots, lowest common ancestor (LCA) graph traversal, and three-way merging.

`tiny-git` was built with one primary engineering goal:
**To demonstrate the core internal concepts of Git with maximum correctness, simplicity, understandability, and clean architecture.**

Our killer feature is simple:
> **We built a small Git-like VCS whose internals you can read and understand in an afternoon.**

We explicitly prioritize:
1. **Correctness & Invariants**: Strict content-addressed invariants, atomic filesystem operations, and safe checkout/merge semantics that protect uncommitted work.
2. **Repository Integrity**: Comprehensive integrity checking (`tiny-git fsck`), crash consistency, and format versioning.
3. **Simplicity**: Small, sharply separated modules with clear data structures and no magic.
4. **Testability**: 98 tests covering unit behavior, property invariants, crash consistency, a 30+ scenario merge matrix, and full CLI workflows in isolated temporary directories.
5. **No Fake Completeness**: Every feature claimed in this README works in code and is verified by tests.

---

## Key Architectural & Reliability Features

```
      Working Tree           Index (Staging Area)           Object Database
      (Disk Files)           (.tinygit/index)            (.tinygit/objects/)

     ┌────────────┐            ┌────────────┐              ┌────────────┐
     │            │  add       │            │  commit      │            │
     │  main.py   ├───────────►│  main.py   ├─────────────►│  Blob      │
     │  README.md │            │  README.md │  (build      │  Tree      │
     │            │            │            │   tree)      │  Commit    │
     └─────▲──────┘            └─────▲──────┘              └─────▲──────┘
           │                         │                           │
           │                         │                           │
           └─────────────────────────┴───────────────────────────┘
                    checkout / merge (restore snapshots)
```

- **Content-Addressable Object Store (`.tinygit/objects/`)**:
  - Implements SHA-1 content-addressed storage with deduplication for Blobs, Trees, and Commits, using standard `xx/yyyy...` two-character prefix directory sharding.
  - **Security & Algorithm Extension Point**: SHA-1 is used explicitly to mirror Git's historical object model for educational clarity, not for modern cryptographic collision resistance. The store is decoupled via the `HashAlgorithm` enum and `get_hasher()` abstraction, allowing future algorithms (like SHA-256) without rewriting storage logic.
- **Repository Integrity Checker (`tiny-git fsck`)**:
  - Validates object hashes, tree entry references, parent commit existence, ref validity, HEAD target integrity, index blob existence, and commit graph acyclicity.
- **Atomic File Writes (`atomic_write_file`)**:
  - Metadata and object files (`HEAD`, `refs`, `index`, `config`, `objects/`) are written using temporary files, `os.fsync()`, and atomic renames to prevent partial file corruption on process crash or power loss.
- **Format Versioning (`core.repositoryformatversion`)**:
  - Stores `repositoryformatversion = 1` in `.tinygit/config`. Rejects newer versions safely with an `UnsupportedRepositoryFormatError`.
- **Symlink & Byte-Oriented Storage Policy**:
  - Symlinks are explicitly unsupported in V1 for security and determinism; filesystem traversals never follow or stage symlink targets.
  - Blobs are strictly byte-oriented (`read_bytes()` / `write_bytes()`), supporting binary files and arbitrary character encodings safely.
- **Revision Resolver (`RevisionResolver`)**:
  - Unified resolution engine for `HEAD`, branches, short SHA prefixes, and ancestry syntax (`HEAD~1`, `HEAD^`, `main~2^2`).

---

## Installation

### Prerequisites
- Python 3.12 or higher

### Installing from Source (Editable Mode)

Clone the repository and install it in editable mode using `pip`:

```bash
git clone https://github.com/example/tiny-git.git
cd tiny-git
pip install -e .
```

Verify the installation:

```bash
tiny-git --help
```

---

## Quick Start & Demo

```bash
mkdir demo
cd demo

# Initialize empty repository
tiny-git init

# Configure author identity
tiny-git config user.name "Ron"
tiny-git config user.email "ron@example.com"

# Create and stage a file
echo "hello" > hello.txt
tiny-git add hello.txt
tiny-git commit -m "Initial commit"

# Make a modification and inspect diff
echo "world" >> hello.txt
tiny-git diff

# Stage and commit
tiny-git add hello.txt
tiny-git commit -m "Update greeting"

# Inspect commit log
tiny-git log --oneline

# Verify repository integrity
tiny-git fsck
```

### Sample Output from `tiny-git fsck`
```
Checking repository...
✓ 3 objects checked
✓ 1 refs checked
✓ HEAD valid
✓ index valid
✓ commit graph valid

Repository is healthy.
```

---

## The 16 Core CLI Commands (Frozen V1.0 Surface)

Every command is implemented in `tinygit.cli` and executable via `tiny-git <command> [options]`:

```
                           ┌───────────────────┐
                           │   TINY-GIT CLI    │
                           └─────────┬─────────┘
            ┌────────────────────────┼────────────────────────┐
            ▼                        ▼                        ▼
     [Repository]            [Working Tree]           [Inspection]
      • init                  • add                    • status
      • config                • rm                     • log
                              • restore                • diff
                              • commit                 • show
                              • branch                 • cat-file
                              • checkout               • rev-parse
                              • merge                  • fsck
```

### Repository Creation & Configuration
- **`tiny-git init [-b <default-branch>] [<path>]`**: Initializes `.tinygit/`, default branch (`main`), empty index, and INI config with `core.repositoryformatversion = 1`.
- **`tiny-git config <key> [<value>]`**: Gets or sets repository configuration in `.tinygit/config`.

### Staging & Working Tree Modification
- **`tiny-git add <files>...`**: Stages files, directories, or all changes/deletions (`.`) in `.tinygit/index`.
- **`tiny-git rm <files>... [--cached]`**: Stages file deletions. Use `--cached` to remove from `.tinygit/index` while leaving the working tree file untouched.
- **`tiny-git restore <files>... [--staged]`**: Restores working tree files from index (default) or unstages index modifications from `HEAD` (`--staged`).
- **`tiny-git commit -m "<message>" [--allow-empty]`**: Creates an immutable snapshot from the staging area.

### Inspection & Debugging
- **`tiny-git status`**: Compares `HEAD -> Index -> Working Tree` to report staged, unstaged, unmerged, and untracked changes.
- **`tiny-git log [--oneline] [-n <max-count>]`**: Traverses parent chains to format commit logs matching Git.
- **`tiny-git diff [--cached]`**: Generates unified diffs (`--- a/file` / `+++ b/file`) for unstaged or staged changes.
- **`tiny-git show [<rev>]`**: Displays commit metadata and unified diff against its first parent.
- **`tiny-git cat-file <object> [-t | -s | -p]`**: Low-level object database inspection. Show type (`-t`), size (`-s`), or pretty-printed content (`-p`).
- **`tiny-git rev-parse <rev>`**: Resolves revision expressions (`HEAD~1`, `main`, short SHAs) to a full 40-character SHA-1.
- **`tiny-git fsck`**: Checks repository integrity, object references, index blobs, and commit graph acyclicity.

### Branching & Merging
- **`tiny-git branch [<name>]`**: Lists branches (indicating current branch with `*`) or creates a new branch pointing to HEAD.
- **`tiny-git checkout <target>`**: Safely switches branches or checks out commit SHAs (detached HEAD) without overwriting uncommitted work.
- **`tiny-git merge <branch> [--abort]`**: Executes fast-forward merges or true 3-way line merges, reporting clean convergence or conflict marker files. Use `--abort` to discard a conflicted merge and restore pre-merge state.

---

## Architecture

`tiny-git` follows a strictly layered architecture to separate user input parsing from version-control domain logic and filesystem serialization:

```
                  ┌─────────────────────────────────────────┐
                  │              CLI Layer                  │  (cli.py, __main__.py)
                  │  • Argument parsing (argparse)          │
                  │  • Human-readable error formatting      │
                  └────────────────────┬────────────────────┘
                                       │
                  ┌────────────────────▼────────────────────┐
                  │          Repository Layer               │  (repository.py, config.py)
                  │  • Central facade (Repository class)    │
                  │  • Enforces format version & invariants │
                  └────────┬───────────┬───────────┬────────┘
                           │           │           │
      ┌────────────────────┼───────────┴───────────┼────────────────────┐
      ▼                    ▼                       ▼                    ▼
┌───────────┐      ┌───────────────┐       ┌───────────────┐    ┌───────────────┐
│ Status &  │      │  Branching &  │       │  Merge & Diff │    │ Working Tree  │
│ Working   │      │  Refs Logic   │       │    Engine     │    │   I/O & Safe  │
│ Tree Diff │      │   (refs.py)   │       │(merge/diff.py)│    │   Checkout    │
└─────┬─────┘      └───────┬───────┘       └───────┬───────┘    └───────┬───────┘
      │                    │                       │                    │
      └────────────────────┼───────────────────────┴────────────────────┘
                           ▼
                  ┌─────────────────────────────────────────┐
                  │          Staging Area / Index           │  (index.py)
                  │  • Structured JSON index (.tinygit/index)│
                  └────────────────────┬────────────────────┘
                                       │
                  ┌────────────────────▼────────────────────┐
                  │      Content-Addressable Storage        │  (objects.py)
                  │  • SHA-1 digest ("<type> <size>\0...")  │
                  │  • Blob, Tree, Commit serialization     │
                  └────────────────────┬────────────────────┘
                                       │
                  ┌────────────────────▼────────────────────┐
                  │          Local Filesystem               │  (.tinygit/objects/xx/yy...)
                  └─────────────────────────────────────────┘
```

For detailed architectural diagrams, see [`docs/architecture.md`](docs/architecture.md).

---

## Object Model & Storage

`tiny-git` stores all data inside `.tinygit/` at the root of your project:

```
.tinygit/
├── objects/           # SHA-1 content-addressed database (sharded by xx/yyyy...)
├── refs/
│   └── heads/         # References storing 40-character commit SHA-1 hashes
├── HEAD               # Symbolic reference pointing to current branch (ref: refs/heads/main)
├── index              # Structured JSON staging area representing proposed next snapshot
└── config             # Local repository configuration file (INI format)
```

- **`Blob`**: Raw file contents (`blob 12\0hello world\n`). Filenames are never stored in Blobs.
- **`Tree`**: Directory structures (`040000 <sha> src\n100644 <sha> README.md\n`).
- **`Commit`**: Root Tree snapshot, 0..N parents, author identity, timestamp, and message.

See [`docs/object-model.md`](docs/object-model.md) and [`docs/storage.md`](docs/storage.md) for full serialization specifications.

---

## Branching, Safe Checkouts, and 3-Way Merges

```
                  B  (current branch / HEAD)
                 / \
                A   C  (incoming branch)
                 \ /
                  M  (resulting merge commit)
```

- **Branching**: Branches are lightweight text files in `.tinygit/refs/heads/` storing commit SHAs.
- **Safe Checkouts**: Before any checkout or merge, `tiny-git` checks if any file changing between the current commit and target commit has uncommitted local edits or untracked collisions. If so, it aborts immediately with `WorkingTreeDirtyError`.
- **Three-Way Merge**: `tiny-git` locates the Lowest Common Ancestor (`A`) of current HEAD (`B`) and target branch (`C`) using BFS. For divergent histories, it compares `A -> B` and `A -> C`:
  - Non-conflicting edits are combined automatically.
  - Overlapping edits inject Git-compatible conflict markers:
    ```
    <<<<<<< HEAD
    Current branch changes
    =======
    Incoming branch changes
    >>>>>>> feature
    ```
  - Clean merges create a multi-parent commit object referencing both `B` and `C`.
  - Use `tiny-git merge --abort` at any time during a conflicted merge to restore the repository to its exact pre-merge state.

See [`docs/branching.md`](docs/branching.md) and [`docs/merging.md`](docs/merging.md) for deeper walkthroughs.

---

## The 8 Fundamental Repository Invariants

`tiny-git` is built around an explicit engineering specification defined in [`docs/invariants.md`](docs/invariants.md):

| # | Invariant | Enforcement Mechanism | Verifying Test Suite |
| :-: | :--- | :--- | :--- |
| **1** | **Object Reachability** | Every referenced object ID must exist in `.tinygit/objects/`. | `test_fsck.py`, `test_state_machine.py` |
| **2** | **Object Immutability** | Written objects are never overwritten; hash checksums are verified on read. | `test_invariants.py`, `test_fsck_adversarial.py` |
| **3** | **Branch Reference Validity** | Branch files must store 40-character hex strings pointing to valid commits. | `test_branch.py`, `test_invariants.py` |
| **4** | **HEAD Consistency** | `.tinygit/HEAD` stores either a valid symbolic ref or a detached SHA-1. | `test_checkout.py`, `test_fsck.py` |
| **5** | **Commit Tree Existence** | Every Commit's root `tree` header must reference an existing Tree object. | `test_invariants.py`, `test_fsck.py` |
| **6** | **Tree Hierarchy Integrity** | Every Tree entry must reference an existing valid Blob or Tree object. | `test_checkout_topology.py`, `test_fsck.py` |
| **7** | **Worktree Data Protection** | Checkouts and merges never overwrite uncommitted edits or untracked files. | `test_checkout.py`, `test_merge.py`, `test_merge_abort_brutal.py` |
| **8** | **Atomic Filesystem Durability** | Metadata writes use temp files, `os.fsync()`, and atomic rename (`.replace()`). | `test_atomic_crash_safety.py`, `test_state_machine.py` |

---

## Testing & Verification

`tiny-git` has an extensive test suite built with `pytest` where every test uses an isolated temporary directory (`tmp_path`):

```bash
pytest -v
```

### Test Suite Summary (`98 Passed / 0 Failed`)
1. **Unit Tests**: Object hashing, blob deduplication, JSON index serialization, reference management, diff generation, revision resolution, fsck diagnostics, `cat-file`/`show` inspection, `rm`/`restore` behaviors.
2. **Property & Invariant Tests (`test_invariants.py`)**:
   - Same content -> same SHA-1 ID; different content -> different SHA-1 ID.
   - Commit hash uniqueness under message/author/tree changes.
   - Branch isolation invariance.
   - Exact snapshot reproduction on checkout.
   - Clean merge union invariance.
3. **Crash Consistency & Atomic Writes (`test_atomic_crash_safety.py`)**:
   - Verifies zero temporary file leakage on write, format version rejection, and `fsck` corruption detection.
4. **Comprehensive Merge Matrix (`test_merge_matrix.py`, `test_merge_adversarial_v2.py`, `test_merge_abort_brutal.py`)**:
   - Over 25 dedicated test functions testing 30+ scenarios: adjacent line edits, identical edits, overlapping conflict hunk injection, modify/delete conflicts, delete/modify conflicts, binary file collisions, empty files, criss-cross DAG LCA ancestor resolution, and exact pre-merge state restoration on abort.
5. **State-Machine Fuzzer (`test_state_machine.py`)**:
   - Runs 10 distinct random seeds x 100 operations each (1,000 total operations) across files, staging, commits, branches, checkouts, and merges, asserting all 8 invariants after every step.
6. **End-to-End Workflow & CLI Contract Tests (`test_end_to_end.py`, `test_cli_contract.py`)**:
   - Complete lifecycle verification across Python `Repository` API and live CLI subprocess execution, auditing error messages, non-zero exit codes, and zero tracebacks.
7. **Static Analysis**:
   - `ruff check src tests`: **0 errors** (`All checks passed!`).
   - `mypy src`: **0 errors** (`Success: no issues found in 16 source files`).

---

## Performance Benchmarking (`benchmarks/run_benchmarks.py`)

`tiny-git` includes an automated benchmark suite verifying linear $O(N)$ execution scaling without quadratic filesystem bottlenecks:

```bash
python3 benchmarks/run_benchmarks.py
```

### Measured Execution Times (ms)
| Operation | 100 Files | 1,000 Files | 2,500 Files | Scaling Behavior |
| :--- | :---: | :---: | :---: | :---: |
| **`init`** | 1.16 ms | 1.23 ms | 0.96 ms | $O(1)$ |
| **`add .`** | 35.46 ms | 345.97 ms | 806.34 ms | $O(N)$ |
| **`commit`** | 1.33 ms | 6.08 ms | 13.71 ms | $O(N)$ |
| **`status`** | 16.80 ms | 150.05 ms | 374.86 ms | $O(N)$ |
| **`diff`** | 21.24 ms | 191.54 ms | 478.00 ms | $O(N)$ |
| **`checkout`** | 18.63 ms | 177.00 ms | 435.75 ms | $O(N)$ |
| **`fsck`** | 18.16 ms | 156.09 ms | 369.77 ms | $O(N)$ |

---

## Roadmap

- **v1.0.0 (Current Frozen Release)**:
  - 16 Core CLI commands: `init`, `config`, `add`, `commit`, `status`, `log`, `branch`, `checkout`, `diff`, `merge`, `fsck`, `cat-file`, `show`, `rev-parse`, `rm`, `restore`.
  - Correctness hardening: atomic `fsync` writes, `core.repositoryformatversion = 1`, `tiny-git fsck`, safe checkouts, `merge --abort`, 98 automated tests.
- **v1.1 — Reference Extensions & Maintenance (Planned)**:
  - `tiny-git tag` (lightweight and annotated tags in `.tinygit/refs/tags/`).
  - `tiny-git count-objects` and reachability analysis.
  - `tiny-git gc --dry-run` and `tiny-git prune --dry-run`.
- **v2.0 — Remote Protocols (Future Exploration)**: Simple HTTP/SSH loose-object transfer (`clone`, `fetch`, `push`, `pull`).

---

## License

This project is open-source software licensed under the **MIT License**. See [`LICENSE`](LICENSE) for details.
