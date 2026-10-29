# Tiny Git Failure & Crash Recovery Model

Version control software operates on untrusted filesystems where processes can be killed (`SIGKILL`), power can fail, disks can fill up, and users can manually edit or delete repository metadata.

`tiny-git` is designed with an explicit failure model:
> **A failed command may leave unreachable objects in `.tinygit/objects/`, but must never leave the repository in an invalid metadata state.**

---

## 1. Atomic File Writes (`atomic_write_file`)

Every critical filesystem modification in `tiny-git` is executed via `atomic_write_file`:

```
               ┌─────────────────────────────────────┐
               │  1. Create temporary file           │
               │     (.tinygit/.tmp_tinygit_*)        │
               └──────────────────┬──────────────────┘
                                  │
               ┌──────────────────▼──────────────────┐
               │  2. Write complete payload bytes    │
               └──────────────────┬──────────────────┘
                                  │
               ┌──────────────────▼──────────────────┐
               │  3. Flush stream & call os.fsync()  │
               └──────────────────┬──────────────────┘
                                  │
               ┌──────────────────▼──────────────────┐
               │  4. Atomic rename (.replace())      │
               │     over target metadata path       │
               └──────────────────┬──────────────────┘
                                  │
               ┌──────────────────▼──────────────────┐
               │  5. fsync the containing directory  │
               │     so the rename itself is durable │
               └─────────────────────────────────────┘
```

### Why Why This Matters
- **POSIX Atomic Rename**: On POSIX filesystems, renaming a file over an existing file in the same directory is atomic. A reader never sees a half-written file.
- **`os.fsync` Durability**: Calling `os.fsync(f.fileno())` forces the operating system to flush the file's own buffers to storage before the rename occurs, so a reader never sees a short file.
- **Directory fsync**: A rename is itself a directory entry update. Without an `fsync` of the *containing* directory, the new name can be lost on power failure even though the file's bytes are safe. `atomic_write_file` therefore fsyncs the parent directory after the rename. On platforms that cannot open a directory as a file descriptor (Windows), this step is skipped and durability is left to the filesystem's own journal.
- **Not a journal**: `fsync` makes *one* file's replacement durable. It says nothing about a sequence of files. See section 3 for what that costs.

---

## 2. Unreachable Objects vs. Corrupt Metadata

Suppose a user executes `tiny-git commit -m "Large commit"` and the process crashes after writing a Blob object but before updating `.tinygit/refs/heads/main`.
- **State on Disk**: The Blob object exists in `.tinygit/objects/`, but is not referenced by any Commit or Tree.
- **Repository Consistency**: Because `.tinygit/refs/heads/main` and `.tinygit/index` were never atomically replaced, the repository remains in its exact pre-command state.
- **Recovery**: The repository continues operating normally. Unreachable loose objects are harmless and can be identified by reachability analysis.

---

## 3. What is *not* guaranteed

The claim above is deliberately narrow. `tiny-git` has no write-ahead log and no
undo journal, so operations that touch several files are only individually
atomic, never collectively so.

| Scenario | Behaviour |
| --- | --- |
| Crash mid-write of one file | That file keeps its exact previous content; a stray `.tmp_tinygit_*` may be left behind. |
| Crash between two file writes | Each file is internally consistent; the pair may be out of step (for example a moved branch ref whose working tree still reflects the old commit). |
| Working tree files | These are written directly, not through `atomic_write_file`. A checkout interrupted part-way through leaves some files new and some old. |
| `HEAD` and `refs/heads/*` | Updated through compare-and-swap under a lock, so a concurrent writer cannot clobber a ref it did not read. A *crash* is still not a concurrency problem and is not protected against beyond the atomic write. |

Recovery from an interrupted multi-file operation is therefore explicit rather
than automatic:

- `tiny-git fsck` reports whether the object database and references are intact.
- `tiny-git reflog` shows where `HEAD` was, so a commit that no branch points at
  can still be named and checked out.
- `tiny-git checkout --force <rev>` re-materialises a revision's tree over the
  working directory, which is the way back from a half-applied checkout or merge.

`tiny-git` is an educational implementation. Treat it as a teaching tool, not as
the only copy of anything you care about.

---

## 4. Handling Filesystem Corruption (`tiny-git fsck`)

If a disk failure or manual user error corrupts an object file or reference in `.tinygit/`, `tiny-git fsck` detects the exact corruption:
- **Hash Verification**: Every object read from `.tinygit/objects/` is hashed and compared to its filename.
- **Non-Crashing Diagnostics**: `tiny-git fsck` catches all exceptions during inspection, reporting structured diagnostics (`ERROR: Object abc123... is malformed or corrupted`) instead of terminating with Python tracebacks.
