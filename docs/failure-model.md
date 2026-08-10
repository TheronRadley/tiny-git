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
               │     (.tinygit/index.tmp_tinygit_*)   │
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
               └─────────────────────────────────────┘
```

### Why Why This Matters
- **POSIX Atomic Rename**: On POSIX filesystems, renaming a file over an existing file in the same directory is atomic. A reader never sees a half-written file.
- **`os.fsync` Durability**: Calling `os.fsync(f.fileno())` forces the operating system to flush kernel buffers to storage hardware before the rename occurs, preventing data corruption on power loss.

---

## 2. Unreachable Objects vs. Corrupt Metadata

Suppose a user executes `tiny-git commit -m "Large commit"` and the process crashes after writing a Blob object but before updating `.tinygit/refs/heads/main`.
- **State on Disk**: The Blob object exists in `.tinygit/objects/`, but is not referenced by any Commit or Tree.
- **Repository Consistency**: Because `.tinygit/refs/heads/main` and `.tinygit/index` were never atomically replaced, the repository remains in its exact pre-command state.
- **Recovery**: The repository continues operating normally. Unreachable loose objects are harmless and can be identified by reachability analysis.

---

## 3. Handling Filesystem Corruption (`tiny-git fsck`)

If a disk failure or manual user error corrupts an object file or reference in `.tinygit/`, `tiny-git fsck` detects the exact corruption:
- **Hash Verification**: Every object read from `.tinygit/objects/` is hashed and compared to its filename.
- **Non-Crashing Diagnostics**: `tiny-git fsck` catches all exceptions during inspection, reporting structured diagnostics (`ERROR: Object abc123... is malformed or corrupted`) instead of terminating with Python tracebacks.
