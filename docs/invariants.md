# Tiny Git Engineering Specification: Fundamental Invariants

To guarantee correctness, data durability, and survival under adversarial attack, `tiny-git` enforces eight fundamental invariants across its object database, staging area, references, and working directory.

This specification documents each invariant in terms of its motivation, enforcement mechanisms, verification tests, and failure behaviors.

---

## 1. Object Reachability & Reference Integrity

### Invariant
Every object referenced by a reachable commit graph, tree entry, branch reference (`refs/heads/*`), or index entry must exist in `.tinygit/objects/xx/yyyy...` and be parseable according to its declared schema.

### Why it exists
A content-addressable version control system is a Directed Acyclic Graph (DAG) of cryptographic pointers. If a pointer references a nonexistent or unparseable object ID, any traversal (history log, checkout, diff, merge) will crash or fail to reconstruct the snapshot.

### Where it is enforced
- **`ObjectStore.read_object`** (`src/tinygit/objects.py`): Rejects missing objects with `ObjectNotFoundError` and malformed payloads with `InvalidObjectError`.
- **`IntegrityChecker.check`** (`src/tinygit/fsck.py`): Validates that every commit tree, parent commit, tree child entry, and index blob hash exists in the store.

### How it is tested
- **`tests/test_fsck.py`**: Asserts that commits referencing nonexistent parents or trees are flagged.
- **`tests/test_fsck_adversarial.py`**: Deliberately deletes and corrupts referenced blobs and trees.
- **`tests/test_state_machine.py`**: Verifies 1,000 randomized operations without introducing dangling references.

### What happens if violated
- `tiny-git fsck` reports an explicit diagnostic: `ERROR: Commit <sha> references missing object <sha>`.
- Any command attempting to read the missing reference fails cleanly with an `ObjectNotFoundError` without corrupting repository metadata.

---

## 2. Object Immutability & Content Digest Identity

### Invariant
Once a `Blob`, `Tree`, or `Commit` object is written to `.tinygit/objects/xx/yyyy...`, its byte payload is immutable. Its SHA-1 digest must equal its computed SHA-1 hash over `<type> <size>\0<content>`.

### Why it exists
Content-addressable storage relies on hash digests as immutable identities. If an object's payload could be silently modified on disk, historical commits and snapshots would be silently corrupted without detection.

### Where it is enforced
- **`ObjectStore.write_object`** (`src/tinygit/objects.py`): Idempotent write check (`if target_path.exists(): return sha`). Does not overwrite existing object files.
- **`ObjectStore.read_object`** (`src/tinygit/objects.py`): Recomputes SHA-1 over the payload on read; raises `InvalidObjectError("SHA-1 integrity verification failed")` on mismatch.

### How it is tested
- **`tests/test_invariants.py::test_invariant_object_identity_and_mutation`**: Verifies identical bytes produce identical digests and different bytes produce different digests.
- **`tests/test_fsck_adversarial.py`**: Overwrites disk blob bytes with garbage and verifies `fsck` detects SHA-1 checksum corruption.

### What happens if violated
- `tiny-git fsck` reports: `ERROR: Object <sha> is malformed or corrupted: SHA-1 integrity verification failed`.
- Subsequent reads raise `InvalidObjectError`, preventing corrupted data from entering working tree checkouts.

---

## 3. Branch Reference Validity

### Invariant
Every reference file under `.tinygit/refs/heads/<branch>` must contain a 40-character hexadecimal SHA-1 string representing an existing, valid `Commit` object.

### Why it exists
Branches are lightweight named pointers to commit history tips. A reference pointing to a Blob, Tree, or non-hex string breaks history traversal and revision resolution.

### Where it is enforced
- **`ReferenceManager.create_branch` / `update_branch`** (`src/tinygit/refs.py`): Enforces syntactic reference naming rules and atomic writes.
- **`RevisionResolver.resolve`** (`src/tinygit/resolver.py`): Verifies reference target exists and resolves to a Commit object.

### How it is tested
- **`tests/test_branch.py`**: Asserts clean branch creation, listing, and updates.
- **`tests/test_invariants.py::test_invariant_branch_isolation`**: Verifies committing on branch A never mutates reference B.
- **`tests/test_fsck_adversarial.py`**: Injects non-hex strings into reference files and verifies `fsck` detection.

### What happens if violated
- `tiny-git fsck` reports: `ERROR: Reference refs/heads/<branch> contains invalid hash` or `references missing commit`.
- Commands invoking that branch raise `InvalidReferenceError`.

---

## 4. HEAD Symbolic & Detached Consistency

### Invariant
`.tinygit/HEAD` must always store either:
1. A symbolic reference string (`ref: refs/heads/<branch>`), where `<branch>` is a valid reference (or an unborn branch before the first commit).
2. A detached 40-character hexadecimal SHA-1 string representing an existing `Commit` object.

### Why it exists
`HEAD` defines the current working context for new commits, checkouts, diffs, and status comparisons. An invalid `HEAD` leaves the repository in an undefined state.

### Where it is enforced
- **`ReferenceManager.set_head_to_branch` / `set_head_to_commit`** (`src/tinygit/refs.py`): Restricts writes to valid symbolic or detached strings.
- **`IntegrityChecker.check`** (`src/tinygit/fsck.py`): Verifies symbolic targets or detached SHA-1 existence.

### How it is tested
- **`tests/test_checkout.py`**: Asserts transitions between symbolic branch checkouts and detached HEAD commit checkouts.
- **`tests/test_fsck_adversarial.py`**: Overwrites `.tinygit/HEAD` with arbitrary text and verifies `fsck` detection.

### What happens if violated
- `tiny-git fsck` reports: `ERROR: HEAD contains invalid target` or `Detached HEAD references missing commit`.
- Commands depending on `HEAD` fail safely with `InvalidReferenceError`.

---

## 5. Root Tree Snapshot Existence

### Invariant
The `tree <sha>` header in every `Commit` object must resolve to an existing `Tree` object in `.tinygit/objects/`.

### Why it exists
A commit without a root Tree represents a metadata header without a filesystem snapshot.

### Where it is enforced
- **`Commit.parse`** (`src/tinygit/objects.py`): Verifies `tree ` header presence on deserialization.
- **`IntegrityChecker.check`** (`src/tinygit/fsck.py`): Checks existence and type validity of commit tree SHAs.

### How it is tested
- **`tests/test_fsck.py`**: Tests missing tree object detection.
- **`tests/test_invariants.py`**: Verifies commit creation always stores its root tree in `ObjectStore`.

### What happens if violated
- `tiny-git fsck` reports: `ERROR: Commit <sha> references missing object <tree_sha>`.
- Any `checkout` or `diff` referencing the commit fails with `ObjectNotFoundError`.

---

## 6. Directory Hierarchy Integrity

### Invariant
In every `Tree` object, each entry (`<mode> <sha> <name>\n`) must reference a valid object matching its mode:
- Mode `040000` must reference a valid `Tree`.
- Mode `100644` or `100755` must reference a valid `Blob`.

### Why it exists
Directory structures are represented as nested Trees. A mode mismatch or missing child SHA breaks recursive tree traversal and working tree restoration.

### Where it is enforced
- **`WorkingTree.build_tree_from_index`** (`src/tinygit/working_tree.py`): Constructs syntactically correct nested mode trees.
- **`IntegrityChecker.check`** (`src/tinygit/fsck.py`): Verifies every tree entry SHA exists in `.tinygit/objects/`.

### How it is tested
- **`tests/test_checkout_topology.py`**: Asserts safe File $\rightarrow$ Directory and Directory $\rightarrow$ File transitions.
- **`tests/test_fsck_adversarial.py`**: Tests tree entries referencing missing blob/tree SHAs.

### What happens if violated
- `tiny-git fsck` reports: `ERROR: Tree <sha> references missing object <sha> (<name>)`.
- `checkout_tree` raises `InvalidObjectError` or `ObjectNotFoundError` without performing partial writes.

---

## 7. Working-Tree Protection Against Uncommitted Data Loss

### Invariant
No operation (`checkout`, `merge`, `restore`) may silently overwrite or delete a working tree file that contains unstaged local modifications, staged index modifications, or untracked collisions.

### Why it exists
A version control system's highest duty is protecting user data. Overwriting uncommitted work without explicit force flags causes irreversible data loss.

### Where it is enforced
- **`WorkingTree.check_safe_checkout`** (`src/tinygit/working_tree.py`): Validates changing paths against disk SHAs and index stages.
- **`MergeEngine.merge`** (`src/tinygit/merge.py`): Verifies working tree and index cleanliness before merge execution, and checks for untracked file collisions before writing merged files.

### How it is tested
- **`tests/test_checkout.py::test_checkout_abort_on_dirty_worktree`**: Asserts checkout aborts when a modified file would be overwritten.
- **`tests/test_merge.py::test_merge_refused_on_dirty_worktree`**: Asserts merge refusal on dirty working tree.
- **`tests/test_merge_abort_brutal.py`**: Asserts untracked files and uncommitted edits are protected during conflicted merges and aborts.

### What happens if violated
- The operation aborts immediately with a `WorkingTreeDirtyError`:
  `error: Your local changes to file '<path>' would be overwritten by checkout.`
- No working tree files or index entries are modified.

---

## 8. Atomic Metadata Durability & Format Compatibility

### Invariant
All metadata and object file writes (`HEAD`, `refs`, `index`, `config`, and `objects/`) must be atomic (`atomic_write_file`), and the repository format version must not exceed `core.repositoryformatversion = 1`.

### Why it exists
Incomplete writes from power loss or process crashes cause partially written metadata files. Format versioning prevents older versions of `tiny-git` from corrupting newer repository layouts.

### Where it is enforced
- **`atomic_write_file`** (`src/tinygit/utils.py`): Temporary file creation + `os.fsync` + POSIX `.replace()`.
- **`Repository._validate_format_version`** (`src/tinygit/repository.py`): Enforces version $\le 1$ on repository open.

### How it is tested
- **`tests/test_atomic_crash_safety.py`**: Verifies zero temporary file leakage and immediate `UnsupportedRepositoryFormatError` on format version 99.
- **`tests/test_state_machine.py`**: Verifies 1,000 randomized operations maintain clean atomic state.

### What happens if violated
- On crash during write: the temporary file is discarded; the target file retains its exact pre-write content.
- On format mismatch: `Repository.init` / `find_repo` raises `UnsupportedRepositoryFormatError` immediately, preventing incompatible modifications.
