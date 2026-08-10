# The Tiny Git Object Model

All version-controlled data in `tiny-git` is stored as immutable objects in `.tinygit/objects/`.

An object is always serialized with a standard header:
```
<object-type> <payload-size-in-bytes>\0<payload-bytes>
```

---

## Cryptographic Digest Policy & Extension Point

- **V1 Object Format**: SHA-1
- **Reason**:
  - Mirrors Git's historical object model.
  - Keeps the implementation educational and conceptually compatible with Git literature.
  - Is **not** intended to provide modern cryptographic collision resistance.
- **Architectural Extension Point**: The object layer uses the `HashAlgorithm` enum (`SHA1 = "sha1"`) and `get_hasher(algorithm)` factory. A future algorithm (e.g. `SHA256 = "sha256"`) can be swapped in at this abstraction boundary without modifying object serialization or storage interfaces.

---

Let's examine the three core object types.

---

## 1. Blob (`type = "blob"`)

A Blob represents the contents of a file.

### Example
For a file containing `hello world\n` (12 bytes):
```
blob 12\0hello world\n
```

### Key Properties
- **No Filenames**: A blob does not know its filename, directory, or modification time.
- **Deduplication**: Creating ten files with `hello world\n` in different directories results in only one blob in `.tinygit/objects/`.

---

## 2. Tree (`type = "tree"`)

A Tree represents a single directory snapshot. It contains a sorted list of entries mapping names to object IDs and modes.

### Serialized Format
Each line in a Tree object follows:
```
<mode> <object-sha-1> <entry-name>\n
```
Entries are sorted alphabetically by `<entry-name>`.

### Example
```
040000 72904eb260d883cbccdfdf8c1af810883f9e3c9e src
100644 a82f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d README.md
```

### Modes
- `100644`: Normal non-executable file (Blob)
- `100755`: Executable file (Blob)
- `040000`: Directory (Tree)

---

## 3. Commit (`type = "commit"`)

A Commit ties a root Tree snapshot to its historical context.

### Serialized Format
```
tree <root-tree-sha-1>
parent <parent-commit-sha-1>   (0 times for initial commit, 1 for normal commit, 2+ for merge commit)
author <author-name> <<author-email>> <timestamp>

<commit-message>
```

### Example (Normal Commit)
```
tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904
parent 92a71ef3b4a2c1e8d9f0a7b6c5d4e3f2a1b0c9e8
author Ron <ron@example.com> 2026-08-09 14:30:00

Add authentication module
```

### Example (Merge Commit with Two Parents)
```
tree 8f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d4e
parent 92a71ef3b4a2c1e8d9f0a7b6c5d4e3f2a1b0c9e8
parent 3b4c5d4e8f1c2b48a1c9e3e7f4a56b8c9d0e1f2
author Ron <ron@example.com> 2026-08-09 15:00:00

Merge branch 'feature'
```
