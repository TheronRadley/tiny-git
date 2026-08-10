# Changelog

All notable changes to `tiny-git` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2026-08-10

### Added
- **Repository Integrity Checker (`tiny-git fsck`)**: Comprehensive integrity verification inspecting `.tinygit/objects`, `refs`, `HEAD`, `index`, `trees`, `commits`, and `blobs` for corruption, missing references, and topological cycles.
- **Developer Inspection Commands**:
  - `tiny-git cat-file <object> [-t | -s | -p]`: inspect object type, size, or pretty-printed payload.
  - `tiny-git show [<rev>]`: show commit metadata and unified diff against its first parent.
  - `tiny-git rev-parse <rev>`: resolve arbitrary revision expressions to full 40-character SHA-1 hashes.
- **Revision Resolver (`RevisionResolver`)**: Dedicated engine supporting branch names, short SHAs, and ancestry syntax (`~N`, `^N`, `HEAD~1`, `HEAD^2`).
- **Working-Tree Completeness**:
  - `tiny-git rm <files>... [--cached]`: remove files from index and working tree (or `--cached` for index only).
  - `tiny-git restore <files>... [--staged]`: restore working tree files from index or unstage index modifications from HEAD.
- **Atomic File Writes (`atomic_write_file`)**: Temporary file write, `fsync`, and atomic rename across `HEAD`, `refs`, `index`, `config`, and `objects/` to guarantee crash consistency.
- **Repository Format Versioning**: Enforced `core.repositoryformatversion = 1` in `.tinygit/config`, raising `UnsupportedRepositoryFormatError` on newer formats.
- **SHA-1 Extension Point**: Added `HashAlgorithm` enum and `get_hasher()` abstraction to decouple hashing algorithms from object storage.
- **Symlink & Byte-Oriented Storage Policy**: Explicitly reject symlinks in `validate_path()` to prevent filesystem traversal escapes; guarantee byte-oriented storage for binary files and arbitrary encodings.
- **Merge Matrix & Invariant Tests**: Expanded test suite to 63 pytest test cases across 21 files, covering a 30+ scenario merge test matrix, criss-cross DAG LCA ancestor resolution, executable file mode preservation, crash consistency, and developer tooling.

---

## [1.0.0] - 2026-08-09

### Added
- **Core CLI Application**: `tiny-git` command with full subcommand suite (`init`, `add`, `commit`, `status`, `log`, `branch`, `checkout`, `merge`, `diff`, `config`).
- **Content-Addressable Object Storage**: Implemented SHA-1 hashed `Blob`, `Tree`, and `Commit` models stored under `.tinygit/objects/xx/yyyy...` with deduplication.
- **Staging Area / Index**: Structured `.tinygit/index` JSON format supporting addition, modification, and staged deletions.
- **Symbolic References**: Managed `.tinygit/HEAD` and `.tinygit/refs/heads/<branch>` with detached HEAD support.
- **Working Tree Safety Engine**: Comprehensive safety validation preventing checkouts or merges from overwriting uncommitted user changes.
- **Unified Diff Engine**: Python standard-library diff formatting (`--- a/file` / `+++ b/file`) for unstaged (`diff`) and staged (`diff --cached`) changes with binary detection.
- **Three-Way Merge Engine**: Lowest Common Ancestor (LCA) BFS search, fast-forward detection, line-level 3-way merge, Git conflict markers (`<<<<<<< HEAD`), and multi-parent merge commits.
- **Configuration Engine**: `.tinygit/config` INI parser for `user.name` and `user.email`.
- **Documentation & Architecture**: Comprehensive educational documentation in `docs/` and `examples/`.
- **Test Suite**: Complete unit, invariant, and end-to-end tests across pytest test cases.
