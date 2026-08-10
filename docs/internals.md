# Tiny Git Internals

Understanding how `tiny-git` stores a snapshot requires tracing how a simple file in the **Working Tree** is transformed into a **Commit** referenced by **HEAD**.

---

## 1. The Core Conceptual Chain

```
Working Tree
      ↓  (tiny-git add)
    Index
      ↓  (tiny-git commit: build_tree_from_index)
    Tree
      ↓  (tiny-git commit: create Commit object)
   Commit
      ↓  (tiny-git commit: update branch ref)
    Ref
      ↓  (symbolic reference)
    HEAD
```

### Step 1: Working Tree → Index
When you run `tiny-git add src/main.py`:
1. `tiny-git` reads the raw bytes of `src/main.py` from disk.
2. A `Blob` object is created and written to `.tinygit/objects/xx/yyyy...` using its SHA-1 hash.
3. An entry is added to `.tinygit/index` recording:
   - `path`: `"src/main.py"`
   - `object_id`: `"a82f1c2..."` (SHA-1 of the blob)
   - `mode`: `"100644"` (normal file mode)

### Step 2: Index → Tree
When you run `tiny-git commit -m "Initial commit"`:
1. `tiny-git` reads all staged entries from `.tinygit/index`.
2. It groups entries by directory hierarchy.
3. It recursively builds `Tree` objects. A subdirectory like `src/` becomes a Tree object containing its file entries, and the root directory becomes a root Tree referencing `src/` (`mode 040000`).
4. Each Tree object is hashed and written to `.tinygit/objects/`.

### Step 3: Tree → Commit
Once the root Tree SHA-1 is computed:
1. A `Commit` object is instantiated containing:
   - `tree`: Root Tree SHA-1
   - `parent`: Current commit hash (if any)
   - `author`: Author name and email from `.tinygit/config`
   - `timestamp`: Current date and time
   - `message`: User commit message
2. The Commit object is serialized and hashed, producing a new 40-character commit SHA-1.

### Step 4: Commit → Ref → HEAD
1. `tiny-git` checks `.tinygit/HEAD`. Suppose it contains `ref: refs/heads/main`.
2. It updates `.tinygit/refs/heads/main` to store the new commit SHA-1.
3. Thus, `HEAD` indirectly points to the new commit via the branch reference.

---

## 2. Why Use Content-Addressable Storage?

Traditional version control systems stored files as deltas or patches over time. Git-like systems use **content-addressable storage**, where the database key for any object is the cryptographic hash (SHA-1) of its payload.

This provides three critical properties:
1. **Deduplication**: If two files in different directories (or across different commits) have identical contents, they hash to the exact same SHA-1 string and share a single file on disk.
2. **Immutability & Integrity**: Once written, an object can never be silently altered. Any change to a byte of content changes its SHA-1 hash.
3. **Fast Snapshot Comparison**: Comparing whether two directory trees are identical is an $O(1)$ operation: if their root Tree SHA-1 hashes are identical, their entire subtrees are guaranteed to be identical.
