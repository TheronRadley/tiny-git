# Changelog

All notable changes to `tiny-git` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

A full audit of the codebase against the invariants the documentation already
claimed. Every item below is covered by a regression test that was verified to
fail against the pre-fix code.

### Security

- **Branch names are validated everywhere they are used to build a path.** An
  absolute or traversal-containing branch name (`/tmp/pwned`, `a/../../escape`)
  previously wrote a ref file outside the repository; committing on a malicious
  initial branch could overwrite an external file. `init -b` is covered too.
- **Tree entries are validated before checkout, at both construction and parse
  time.** A crafted tree could previously plant `.tinygit/hooks/post-checkout`.
  Entry names containing a separator, traversal, a metadata directory, or an
  empty name are now rejected as `InvalidObjectError`.
- **`is_ignored()` no longer treats every `.git`-prefixed name as metadata.**
  `.gitignore`, `.github/`, and `.gitattributes` were silently excluded from
  `add .`.
- **Filenames that the index format cannot represent are rejected at staging
  time** rather than producing a tree that cannot be read back.

### Fixed

- **`checkout` of the current branch no longer destroys work.** It reverted
  unstaged edits and deleted newly staged files; it now preserves both.
- **An unreadable tree is no longer treated as an empty snapshot.** A checkout
  targeting a missing tree deleted every tracked file and still moved `HEAD`.
- **`rm` refuses to discard uncommitted edits** unless `--force` is given.
- **The merge index is rebuilt from the merge result.** A clean 3-way merge
  deleted files from disk while keeping them in the resulting commit.
- **Conflict stages are correct.** Conflicted paths had a spurious stage 0 and
  zero hashes were written for nonexistent sides, which broke `diff` and `fsck`
  on a perfectly valid add/add conflict.
- **Arbitrary bytes survive a merge.** Non-UTF-8 content was rewritten with
  replacement characters even when the merge reported success; undecodable
  content is now treated as binary.
- **Merge-base selection is ancestry-based, not distance-based.** The old
  heuristic returned a non-maximal common ancestor in 34 of 394 randomly
  generated DAGs; multiple merge bases are now detected and handled explicitly.
- **Executable-bit changes are real changes.** Mode-only edits are now reported
  by `status` and `diff`, carried through `merge` and `checkout`, and `restore`
  clears an exec bit instead of leaving it set.
- **Paths given on the command line resolve relative to the caller's
  directory**, so `tiny-git add file` from a subdirectory stages that file.
- **`fsck` validates far more**: referent object types, index/stage consistency,
  `HEAD` commit types, malformed and newer `repositoryformatversion` values, and
  unsafe names anywhere in a flattened tree path.

### Added

- **Operation locking.** `FileLock` with stale-lock recovery serialises mutating
  commands, and ref updates are compare-and-swap, so concurrent writers cannot
  lose commits.
- **Recoverable failures.** Mutating operations validate their whole plan before
  touching disk, propagate filesystem errors instead of swallowing them, and
  `fsync` parent directories after metadata renames.
- **`tiny-git checkout --force`** re-materialises a revision's tree, which is the
  recovery path after an interrupted checkout or merge.
- **`.tinygitignore`** with documented gitignore-lite semantics, plus explicit
  tracked-file behaviour and an `add --force` override.
- **`tiny-git reflog [-n N]`** backed by `.tinygit/logs/HEAD`.
- **`tiny-git status --short` and `--porcelain`.**
- **Merge lifecycle enforcement**: while a merge is in progress, `checkout` and a
  second `merge` are refused until the merge is committed or aborted.

### Changed

- **Development status is `4 - Beta`, not `5 - Production/Stable`.** The
  classifier was aspirational; this audit found reachable data-loss and
  repository-corruption bugs in released code.
- **Crash-safety claims are narrowed.** `atomic_write_file` still guarantees a
  per-file atomic replacement, and now fsyncs the containing directory as well.
  There is no journal, so a command interrupted *between* writes is not
  recoverable automatically. [`docs/failure-model.md`](docs/failure-model.md)
  states the boundary explicitly.

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
