# Tiny Git

```
             ┌────────────────────────────────────────────────────────┐
             │                       TINY GIT                         │
             │     A small, educational, Git-inspired content-        │
             │        addressed version-control system.               │
             └────────────────────────────────────────────────────────┘
```

[![Tests](https://github.com/TheronRadley/tiny-git/actions/workflows/tests.yml/badge.svg)](https://github.com/TheronRadley/tiny-git/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%20|%203.11%20|%203.12%20|%203.13-blue.svg)](pyproject.toml)

`tiny-git` is a small, cleanly designed version-control system built from scratch in modern Python. It implements content-addressed objects, a staging index, immutable commits, references, branching, unified diffs, and three-way merges — without ever invoking Git.

> ### Why `tiny-git` and `tinygit`?
>
> They are the same project spelled two ways, because Python packaging and Python imports disagree about hyphens.
>
> | Where | Name | Why |
> | :--- | :--- | :--- |
> | PyPI distribution, `pip install`, the command you type | **`tiny-git`** | Hyphens read naturally in a project name and on a command line. |
> | Importable Python package (`src/tinygit/`) | **`tinygit`** | A hyphen is not a legal character in a Python identifier, so `import tiny-git` is impossible. |
>
> In practice: `pip install tiny-git`, run `tiny-git init` in your shell, and `from tinygit.repository import Repository` in your code.

---

## Why This Project Exists

Version control systems like Git are often perceived as mysterious "black boxes." While developers use `git` daily, fewer understand the fundamental mechanics of SHA-1 content-addressed storage, staging indices, immutable commit snapshots, lowest common ancestor (LCA) graph traversal, and three-way merging.

`tiny-git` was built with one primary engineering goal:
**To demonstrate the core internal concepts of Git with maximum correctness, simplicity, understandability, and clean architecture.**

Our killer feature is simple:
> **We built a small Git-like VCS whose internals you can read and understand in an afternoon.**

We explicitly prioritize:
1. **Correctness & Invariants**: Strict content-addressed invariants, atomic filesystem operations, and safe checkout/merge semantics that protect uncommitted work.
2. **Repository Integrity**: Comprehensive integrity checking (`tiny-git fsck`), per-file atomic writes, a HEAD reflog, and format versioning.
3. **Simplicity**: Small, sharply separated modules with clear data structures and no magic.
4. **Testability**: A test suite covering unit behavior, property invariants, crash consistency, a large merge scenario matrix, and full CLI workflows in isolated temporary directories. See [`docs/testing.md`](docs/testing.md).
5. **No Fake Completeness**: Every feature claimed in this README works in code and is verified by tests.

---

## Installation

### Prerequisites
- Python 3.10 or higher (see [`pyproject.toml`](pyproject.toml) for the supported floor)

### Installing from Source (Editable Mode)

Clone the repository and install it in editable mode using `pip`:

```bash
git clone https://github.com/TheronRadley/tiny-git.git
cd tiny-git
pip install -e ".[dev]"
```

Drop `.[dev]` for a plain install; the `dev` extra adds `pytest`, `ruff`, and `mypy`.

Verify the installation:

```bash
tiny-git --help
```

---

## Quick Start

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

# Stage, commit, inspect, and verify
tiny-git add hello.txt
tiny-git commit -m "Update greeting"
tiny-git log --oneline
tiny-git fsck
```

Sample output from the run above:

```console
$ tiny-git diff
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1,2 @@
 hello
+world

$ tiny-git log --oneline
b9d7d97 Update greeting
2758798 Initial commit

$ tiny-git fsck
Checking repository...
✓ 6 objects checked
✓ 1 refs checked
✓ HEAD valid
✓ index valid
✓ commit graph valid

Repository is healthy.
```

---

## The 16 Core CLI Commands (Frozen V1 Surface)

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
- **`tiny-git add <files>... [-f]`**: Stages files, directories, or all changes/deletions (`.`) in `.tinygit/index`. Files matched by `.tinygitignore` are skipped when staging a directory; naming one explicitly is refused unless `-f` is given, so `add` never looks like it worked while staging nothing.
- **`tiny-git rm <files>... [--cached] [--force]`**: Stages file deletions. Use `--cached` to remove from `.tinygit/index` while leaving the working tree file untouched. A file with uncommitted edits is refused unless `--force` is given.
- **`tiny-git restore <files>... [--staged]`**: Restores working tree files from index (default) or unstages index modifications from `HEAD` (`--staged`).
- **`tiny-git commit -m "<message>" [--allow-empty]`**: Creates an immutable snapshot from the staging area.

### Inspection & Debugging
- **`tiny-git status [-s | --porcelain]`**: Compares `HEAD -> Index -> Working Tree` to report staged, unstaged, unmerged, and untracked changes. `-s` prints a compact two-column summary; `--porcelain` prints stable `XY <path>` lines for scripts.
- **`tiny-git log [--oneline] [-n <max-count>]`**: Traverses parent chains to format commit logs matching Git.
- **`tiny-git diff [--cached]`**: Generates unified diffs (`--- a/file` / `+++ b/file`) for unstaged or staged changes.
- **`tiny-git show [<rev>]`**: Displays commit metadata and unified diff against its first parent.
- **`tiny-git cat-file <object> [-t | -s | -p]`**: Low-level object database inspection. Show type (`-t`), size (`-s`), or pretty-printed content (`-p`).
- **`tiny-git rev-parse <rev>`**: Resolves revision expressions (`HEAD~1`, `main`, short SHAs) to a full 40-character SHA-1.
- **`tiny-git fsck`**: Checks repository integrity, object references, index blobs, and commit graph acyclicity.
- **`tiny-git reflog [-n <max-count>]`**: Prints the `HEAD` movement log from `.tinygit/logs/HEAD`, so a commit that no branch points at can still be named and recovered.

### Branching & Merging
- **`tiny-git branch [<name>]`**: Lists branches (indicating current branch with `*`) or creates a new branch pointing to HEAD.
- **`tiny-git checkout <target> [-f]`**: Safely switches branches or checks out commit SHAs (detached HEAD) without overwriting uncommitted work. `-f` discards local changes and re-materialises the target tree exactly, which is also the recovery path after a checkout or merge was interrupted part-way through.
- **`tiny-git merge <branch> [--abort]`**: Executes fast-forward merges or true 3-way line merges, reporting clean convergence or conflict marker files. Use `--abort` to discard a conflicted merge and restore pre-merge state. While a merge is in progress, `checkout` and a second `merge` are refused: resolve and commit, or abort, before switching branches.

### Ignoring files: `.tinygitignore`

Place a `.tinygitignore` at the repository root to keep generated files out of
`add .`, `status`, and `diff`. It supports a small, documented subset of
gitignore:

| Pattern | Matches |
| --- | --- |
| `*.pyc` | `mod.pyc`, `pkg/mod.pyc` — no slash means match the basename at any depth |
| `/root.txt` | `root.txt` only — a leading slash anchors to the repository root |
| `docs/*.md` | `docs/a.md` but not `docs/sub/a.md` — a slash in the middle also anchors, and `*` never crosses a directory separator |
| `build/` | everything below a `build` directory, at any depth |
| `**` | crosses directory separators, unlike `*` |
| `!keep.log` | re-includes a path an earlier pattern excluded |

`#` starts a comment and blank lines are ignored. The last matching pattern
wins, so negations must come after the rule they cancel.

Two behaviours are worth spelling out, because both are easy to get wrong:

- **A tracked file is never un-tracked by a later rule.** If `data.log` is
  already committed and you then add `*.log`, `add .` stages your *modification*
  to it rather than staging a deletion, and `checkout` still restores it.
- **Naming an ignored file explicitly is refused, not silently skipped.**
  `tiny-git add build.log` prints an error naming the rule and exits non-zero;
  add `-f` if you really mean to track it.

---

## Architecture

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

`tiny-git` follows a strictly layered architecture: `cli.py` parses arguments, `repository.py` is the facade that enforces format versions and invariants, and the subsystems below it (`status.py`, `refs.py`, `merge.py`, `diff.py`, `working_tree.py`, `index.py`, `objects.py`) each own one concern. Metadata and object writes go through `atomic_write_file` — temporary file, `os.fsync()`, atomic rename, then an `fsync` of the containing directory — so a crash mid-write cannot leave half a file behind. Note that this guarantee is per file: `tiny-git` has no journal, so a command interrupted *between* writes can leave the working tree and the references out of step. [`docs/failure-model.md`](docs/failure-model.md) states precisely what is and is not covered, and how to recover.

The full layer diagram, module responsibilities, and data-flow walkthroughs live in [`docs/architecture.md`](docs/architecture.md).

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

### ⚠️ Not wire-compatible with real Git

**Real `git` cannot read a `.tinygit` repository, and `tiny-git` cannot read a `.git` one.** The on-disk *formats* deliberately differ so the files stay human-readable:

| Component | `tiny-git` | Real `git` |
| :--- | :--- | :--- |
| Tree objects | UTF-8 text lines, `mode sha name\n` | Binary, `mode name\0` + 20 raw digest bytes |
| Loose objects | Stored uncompressed | zlib-deflated |
| Index (`.tinygit/index`) | JSON | Custom binary format |
| Repository directory | `.tinygit/` | `.git/` |

What *is* intentionally shared is the conceptual layer — the `<type> <size>\0<content>` SHA-1 hashing scheme, `xx/yyyy...` sharding, `ref: refs/heads/<branch>` HEAD syntax, `~N`/`^N` ancestry syntax, unified-diff formatting, and `<<<<<<< HEAD` conflict markers. So the ideas transfer directly to Git; the bytes do not. See [`docs/git-comparison.md`](docs/git-comparison.md).

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

## Documentation Index

| Document | What it covers |
| :--- | :--- |
| [`docs/architecture.md`](docs/architecture.md) | Layer diagram, module responsibilities, data flow |
| [`docs/invariants.md`](docs/invariants.md) | The 8 fundamental repository invariants and how each is enforced |
| [`docs/object-model.md`](docs/object-model.md) | Blob, Tree, and Commit schemas |
| [`docs/storage.md`](docs/storage.md) | On-disk layout, sharding, atomic write protocol |
| [`docs/branching.md`](docs/branching.md) | Refs, HEAD, detached HEAD |
| [`docs/merging.md`](docs/merging.md) | LCA search, 3-way merge, conflict handling |
| [`docs/testing.md`](docs/testing.md) | What the test suite covers and how to run it |
| [`docs/benchmarks.md`](docs/benchmarks.md) | Measured scaling numbers and the exact conditions they were taken under |
| [`docs/git-comparison.md`](docs/git-comparison.md) | Where `tiny-git` matches Git and where it diverges |
| [`docs/failure-model.md`](docs/failure-model.md) | Crash consistency and corruption behaviour |
| [`docs/repository-lifecycle.md`](docs/repository-lifecycle.md) | End-to-end lifecycle walkthrough |
| [`docs/development.md`](docs/development.md) | Local setup, running tests, debugging the object store |
| [`docs/social-preview.png`](docs/social-preview.png) | 1280×640 Open Graph banner, uploaded under **Settings → General → Social preview** |

---

## Correctness at a Glance

`tiny-git` is built around eight explicit engineering invariants — object reachability, object immutability, branch reference validity, HEAD consistency, commit tree existence, tree hierarchy integrity, worktree data protection, and atomic filesystem durability.

The full table of invariants, their enforcement points, and the test suites that verify each one is in **[`docs/invariants.md`](docs/invariants.md)**.

Verification is continuous rather than aspirational: the [Tests workflow](https://github.com/TheronRadley/tiny-git/actions/workflows/tests.yml) runs `pytest`, `ruff check src tests`, and `mypy src` on every push and pull request across Python 3.10–3.13 on Ubuntu and macOS. The badge at the top of this README is that workflow's live status.

**Windows is not yet supported.** A Windows job runs on every push but is deliberately marked non-blocking: `os.chmod()` only flips the read-only bit there, so the executable-file-mode round-trip tests in `test_symlink_encoding.py`, `test_merge_adversarial.py`, `test_merge_abort_brutal.py`, and `test_state_machine.py` cannot pass. The workflow file names those call sites; once they skip on platforms without POSIX mode bits, the job moves into the blocking matrix.

See [`docs/testing.md`](docs/testing.md) for what the suite covers.

---

## Roadmap

- **v1.0.0 (Current Frozen Release)**:
  - 16 core CLI commands: `init`, `config`, `add`, `commit`, `status`, `log`, `branch`, `checkout`, `diff`, `merge`, `fsck`, `cat-file`, `show`, `rev-parse`, `rm`, `restore`.
  - Correctness hardening: atomic `fsync` writes, `core.repositoryformatversion = 1`, `tiny-git fsck`, safe checkouts, `merge --abort`.
- **v1.1 — Reference Extensions & Maintenance (Planned)**:
  - `tiny-git tag` (lightweight and annotated tags in `.tinygit/refs/tags/`).
  - `tiny-git count-objects` and reachability analysis.
  - `tiny-git gc --dry-run` and `tiny-git prune --dry-run`.
- **v2.0 — Remote Protocols (Future Exploration)**: Simple HTTP/SSH loose-object transfer (`clone`, `fetch`, `push`, `pull`).

See [`CHANGELOG.md`](CHANGELOG.md) for what shipped in each release.

---

## Contributing

Bug reports, feature requests, and pull requests are welcome — please read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. This project follows a [Code of Conduct](CODE_OF_CONDUCT.md) and has a [security disclosure policy](SECURITY.md).

---

## License

This project is open-source software licensed under the **MIT License**. See [`LICENSE`](LICENSE) for details.
