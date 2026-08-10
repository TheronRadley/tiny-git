# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in `tiny-git`, please report it privately to the maintainers rather than opening a public issue.

---

## Security Model & Cryptographic Policies

`tiny-git` treats repository data and command-line path arguments as untrusted input:

### 1. SHA-1 Object Digest Policy
- **V1 Object Format**: SHA-1
- **Reason**: Mirrors Git's historical object model and keeps the implementation educational. It is **not** intended to provide modern collision resistance against adversary-crafted prefix collisions.
- **Extension Point**: The object hashing engine uses the `HashAlgorithm` abstraction (`get_hasher()`), providing a clean architectural boundary where future hash algorithms (e.g. SHA-256) can be introduced without modifying object storage or serialization logic.

### 2. Path Traversal & Symlink Policy
- **Path Traversal Protection**: All filesystem paths passed to `add`, `checkout`, `rm`, `restore`, and `working_tree` operations are checked via `validate_path(path, repo_root)`. Any attempt to escape the repository directory using `../..` or absolute paths outside `repo_root` is rejected immediately with an `InvalidPathError`.
- **Symlink Rejection**: Symlinks are **unsupported in V1** for security and determinism. Any symlink path or target is rejected before resolution so `tiny-git add .` can never follow a symlink out of the repository.

### 3. Atomic Writes & Crash Consistency
- All metadata and object writes (`.tinygit/HEAD`, `.tinygit/refs/heads/*`, `.tinygit/index`, `.tinygit/config`, and `.tinygit/objects/xx/yyyy...`) use `atomic_write_file()`. Files are written to temporary filenames, flushed, `os.fsync()`'d, and atomically renamed. An interrupted write or process crash will never leave a partial or corrupted metadata file on disk.

### 4. Integrity Verification & Safe Checkouts
- **Object Integrity**: Objects loaded from `.tinygit/objects/` are verified against their digest upon reading. If an object's payload hash does not match its filename, an `InvalidObjectError` is raised immediately.
- **Repository Fsck**: The `tiny-git fsck` command validates object checksums, ref targets, parent commit existence, tree references, and commit graph acyclicity.
- **Safe Checkout**: `checkout_tree` never overwrites local uncommitted modifications or untracked files without explicit verification.
