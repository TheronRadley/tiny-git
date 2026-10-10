# Changelog

All notable changes to `tiny-git` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-10

First tagged release. The 16-command V1 surface is frozen — see the
[Roadmap](README.md#roadmap) for what is planned next.

> **A note on this entry.** Earlier drafts of this file split the work below across
> `1.0.0` and `1.1.0` entries dated a day apart. Neither version was ever tagged,
> released on GitHub, or published to PyPI, and every feature listed under both is
> present in the shipped code. They have been consolidated here so that this file,
> `pyproject.toml`, and the `v1.0.0` tag all agree. `1.1.0` remains reserved for the
> reference-extension work in the roadmap.

### Added

#### Core CLI
- **Core CLI Application**: `tiny-git` command with the full subcommand suite (`init`, `add`, `commit`, `status`, `log`, `branch`, `checkout`, `merge`, `diff`, `config`).
- **Configuration Engine**: `.tinygit/config` INI parser for `user.name` and `user.email`.

#### Content-addressed storage
- **Content-Addressable Object Storage**: SHA-1 hashed `Blob`, `Tree`, and `Commit` models stored under `.tinygit/objects/xx/yyyy...` with deduplication.
- **SHA-1 Extension Point**: `HashAlgorithm` enum and `get_hasher()` abstraction decoupling the hashing algorithm from object storage, so a future SHA-256 mode needs no storage rewrite.
- **Symlink & Byte-Oriented Storage Policy**: symlinks are explicitly rejected in `validate_path()` to prevent filesystem-traversal escapes; blobs are stored byte-for-byte so binary files and arbitrary encodings round-trip safely.

#### Staging & references
- **Staging Area / Index**: structured `.tinygit/index` JSON format supporting addition, modification, and staged deletions.
- **Symbolic References**: managed `.tinygit/HEAD` and `.tinygit/refs/heads/<branch>` with detached HEAD support.
- **Revision Resolver (`RevisionResolver`)**: unified engine supporting branch names, short SHA prefixes, and ancestry syntax (`~N`, `^N`, `HEAD~1`, `HEAD^2`).

#### Working-tree operations
- **Working Tree Safety Engine**: validation preventing checkouts or merges from overwriting uncommitted user changes.
- **Working-Tree Completeness**:
  - `tiny-git rm <files>... [--cached]`: remove files from index and working tree (or `--cached` for index only).
  - `tiny-git restore <files>... [--staged]`: restore working-tree files from the index, or unstage index modifications from `HEAD`.
- **Unified Diff Engine**: standard-library diff formatting (`--- a/file` / `+++ b/file`) for unstaged (`diff`) and staged (`diff --cached`) changes, with binary detection.
- **Three-Way Merge Engine**: Lowest Common Ancestor (LCA) BFS search, fast-forward detection, line-level 3-way merge, Git conflict markers (`<<<<<<< HEAD`), multi-parent merge commits, and `merge --abort` restoring exact pre-merge state.

#### Integrity & inspection
- **Repository Integrity Checker (`tiny-git fsck`)**: comprehensive verification of `.tinygit/objects`, `refs`, `HEAD`, `index`, trees, commits, and blobs for corruption, missing references, and topological cycles.
- **Developer Inspection Commands**:
  - `tiny-git cat-file <object> [-t | -s | -p]`: inspect object type, size, or pretty-printed payload.
  - `tiny-git show [<rev>]`: show commit metadata and unified diff against its first parent.
  - `tiny-git rev-parse <rev>`: resolve arbitrary revision expressions to full 40-character SHA-1 hashes.

#### Durability
- **Atomic File Writes (`atomic_write_file`)**: temporary-file write, `os.fsync()`, and atomic rename across `HEAD`, `refs`, `index`, `config`, and `objects/` to guarantee crash consistency.
- **Repository Format Versioning**: enforced `core.repositoryformatversion = 1` in `.tinygit/config`, raising `UnsupportedRepositoryFormatError` on newer formats.

#### Testing & documentation
- **Test Suite**: unit, property-invariant, crash-consistency, merge-matrix, state-machine fuzzing, and CLI-contract tests across 31 modules — see [`docs/testing.md`](docs/testing.md).
- **Documentation & Architecture**: educational documentation in `docs/` and `examples/`.
