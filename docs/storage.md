# Storage & Filesystem Layout

`tiny-git` stores all repository data inside the `.tinygit/` directory at the root of your project.

---

## 1. Directory Sharding in `.tinygit/objects/`

If all objects were written into a single directory, filesystems would experience severe performance degradation once thousands of commits were created.

To prevent this, `tiny-git` shards object files using the first two hexadecimal characters of the SHA-1 hash as the subdirectory name, and the remaining 38 characters as the filename:

```
SHA-1 Hash: a82f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d

Path on disk:
.tinygit/objects/a8/2f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d
```

### Atomic Writes
When writing an object, `tiny-git` writes data to a temporary file (`.tmp`) first and then renames it atomically to the target path. This ensures that a process crash or power loss can never leave a partially written or corrupted object file in the database.

---

## 2. Staging Area (`.tinygit/index`)

The staging area is stored in a structured JSON format in `.tinygit/index`. It contains an array of staged entries sorted alphabetically by POSIX relative file path:

```json
[
  {
    "path": "README.md",
    "object_id": "a82f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d",
    "mode": "100644",
    "stat_size": 1042,
    "stat_mtime": 1754740000.0
  },
  {
    "path": "src/main.py",
    "object_id": "72904eb260d883cbccdfdf8c1af810883f9e3c9e",
    "mode": "100755",
    "stat_size": 420,
    "stat_mtime": 1754740010.0
  }
]
```

---

## 3. References and HEAD

- **`.tinygit/refs/heads/<branch-name>`**: Contains a single line of text with the 40-character commit SHA-1 followed by a newline:
  ```
  a82f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d
  ```
- **`.tinygit/HEAD`**:
  - Symbolic reference: `ref: refs/heads/main\n`
  - Detached HEAD: `a82f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d\n`

---

## 4. Configuration (`.tinygit/config`)

User configuration and repository format metadata are stored in `.tinygit/config` using standard INI syntax:

```ini
[core]
repositoryformatversion = 1

[user]
name = Ron
email = ron@example.com
```

- **`core.repositoryformatversion`**: Indicates the repository format version. `tiny-git` validates this on load and raises `UnsupportedRepositoryFormatError` if a repository format version > 1 is encountered.

---

## 5. Atomic File Writes & Crash Consistency

Every metadata and object file (`.tinygit/HEAD`, `.tinygit/refs/heads/*`, `.tinygit/index`, `.tinygit/config`, and `.tinygit/objects/xx/yyyy...`) is written using `atomic_write_file()`:
1. Data is written to a unique temporary file (`.tmp_tinygit_*`) in the target directory.
2. The file stream is flushed and `os.fsync()` is called to force filesystem block persistence.
3. The temporary file is atomically renamed (`.replace()`) to the target path.

This guarantees that an interrupted command, power loss, or process crash can never leave a partial or corrupted metadata file in the repository.

