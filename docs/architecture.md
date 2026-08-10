# Tiny Git Architecture

`tiny-git` is structured as a layered system where high-level command-line requests are transformed into content-addressed immutable snapshots on disk.

---

## 1. The Version Control Pipeline

Understanding `tiny-git` begins with understanding the flow of data across three core areas:

```
 Working Tree           Index (Staging Area)           Object Database
 (Disk Files)           (.tinygit/index)            (.tinygit/objects/)

┌────────────┐            ┌────────────┐              ┌────────────┐
│            │  add (read)│            │  commit      │            │
│  main.py   ├───────────►│  main.py   ├─────────────►│  Blob      │
│  README.md │            │  README.md │  (build      │  Tree      │
│            │            │            │   tree)      │  Commit    │
└─────▲──────┘            └─────▲──────┘              └─────▲──────┘
      │                         │                           │
      │                         │                           │
      └─────────────────────────┴───────────────────────────┘
               checkout / merge (restore snapshots)
```

1. **Working Tree**: The directory where the user edits regular files on disk.
2. **Index (Staging Area)**: A structured file (`.tinygit/index`) storing the proposed snapshot for the next commit.
3. **Object Database**: A content-addressed store (`.tinygit/objects/`) where Blobs, Trees, and Commits are stored immutably by their SHA-1 digest.

---

## 2. Layer Separation

The codebase in `src/tinygit/` is organized into distinct responsibilities:

```
┌────────────────────────────────────────────────────────┐
│                      cli.py                            │
│  • Parses arguments via argparse                       │
│  • Catches TinyGitError exceptions                     │
│  • Outputs human-readable messages and exit codes       │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                   repository.py                        │
│  • Central facade (Repository class)                   │
│  • Orchestrates init, add, commit, status, log, etc.   │
│  • Validates repository invariants                     │
└─────┬─────────────────────┬──────────────────────┬─────┘
      │                     │                      │
┌─────▼──────┐        ┌─────▼──────┐        ┌──────▼─────┐
│ working_   │        │ refs.py &  │        │ diff.py &  │
│ tree.py    │        │ index.py   │        │ merge.py   │
│ • Disk I/O │        │ • HEAD/refs│        │ • 3-way    │
│ • Safety   │        │ • Staging  │        │   merge    │
└─────┬──────┘        └─────┬──────┘        └──────┬─────┘
      │                     │                      │
      └─────────────────────┼──────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                    objects.py                          │
│  • ObjectStore (write_object, read_object)             │
│  • Hashing ("<type> <size>\\0<content>")               │
│  • Blob, Tree, Commit classes                          │
└────────────────────────────────────────────────────────┘
```

### Module Breakdown
- `cli.py`: Parses CLI flags, delegates to `Repository`, and formats output without exposing tracebacks.
- `repository.py`: Combines low-level operations into atomic commands (`init`, `commit`, `checkout`, `merge`).
- `objects.py`: Defines immutable objects and SHA-1 content-addressed disk storage.
- `index.py`: Manages staging area serialization and updates.
- `refs.py`: Handles branch files and symbolic `HEAD` resolution.
- `working_tree.py`: Scans disk files, builds Tree objects from the index, and checks for safe checkout conditions.
- `diff.py`: Computes unified diffs between snapshots.
- `merge.py`: Performs LCA BFS search, fast-forward checks, line-level 3-way merging, and conflict marking.
- `status.py`: Computes delta categories (`HEAD → Index → Working Tree`).
- `config.py`: Reads and writes `.tinygit/config`.
