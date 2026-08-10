# Comparison: Tiny Git vs. Git

`tiny-git` is designed to be an educational content-addressed version-control system inspired by Git.
This document explains where `tiny-git` is intentionally compatible with Git and where it diverges for architectural simplicity.

---

## 1. Where Tiny Git Matches Git (Intentional Compatibility)

To ensure that concepts learned in `tiny-git` transfer directly to Git, the following formats and semantics match real Git:

| Layer / Feature | Tiny Git (`tiny-git`) | Real Git (`git`) | Compatibility Notes |
| :--- | :--- | :--- | :--- |
| **Object Hashing** | `<type> <size>\0<content>` + SHA-1 | `<type> <size>\0<content>` + SHA-1 / SHA-256 | Blob, Tree, and Commit payloads produce identical SHA-1 digests for standard known vectors. |
| **Directory Sharding** | `objects/xx/yyyy...` | `objects/xx/yyyy...` | Loose objects use 2-character prefix sharding. |
| **Commit Headers** | `tree`, `parent`, `author`, `\n\n` | `tree`, `parent`, `author`, `committer`, `\n\n` | Supports 0, 1, or multiple `parent` headers for merge commits. |
| **Symbolic References** | `ref: refs/heads/<branch>` | `ref: refs/heads/<branch>` | `.tinygit/HEAD` matches `.git/HEAD` syntax. |
| **Detached HEAD** | 40-hex SHA-1 in `HEAD` | 40-hex SHA-1 in `HEAD` | Detached HEAD points directly to a commit hash. |
| **Unified Diff** | `--- a/file` / `+++ b/file` | `--- a/file` / `+++ b/file` | Standard line-level unified diff formatting. |
| **Conflict Markers** | `<<<<<<< HEAD` / `=======` / `>>>>>>>` | `<<<<<<< HEAD` / `=======` / `>>>>>>>` | Line-level 3-way merge conflict hunk markers. |
| **Ancestry Syntax** | `~N`, `^N`, `HEAD~1^2` | `~N`, `^N`, `HEAD~1^2` | Standard parent indexing and ancestry chains. |

---

## 2. Where Tiny Git Diverges (Educational Simplicity)

| Layer / Feature | Tiny Git (`tiny-git`) | Real Git (`git`) | Architectural Reason |
| :--- | :--- | :--- | :--- |
| **Index Serialization** | Human-readable JSON (`.tinygit/index`) | Custom binary index format (`.git/index`) | A JSON array is inspectable with standard text editors and debuggers without needing binary parsers. |
| **Packfile Compression** | Loose objects only (`objects/xx/yy...`) | Packfiles (`.pack`) and index files (`.idx`) | Packfile delta compression adds significant complexity; loose objects demonstrate content-addressing clearly. |
| **Symlinks & Submodules** | Unsupported (`100644`, `100755`, `040000` only) | Supported (`120000` symlinks, `160000` gitlinks) | Eliminates symlink path-traversal vulnerabilities and cross-platform symlink edge cases. |
| **Networking & Remotes** | Local repositories only (`init`, `add`, `commit`...) | Rich remote transport (`clone`, `fetch`, `push`...) | Local version-control correctness is hardened first before introducing network protocols. |
