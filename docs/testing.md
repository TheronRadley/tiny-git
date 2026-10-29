# Testing & Verification

`tiny-git` treats tests as the specification. Every claim about behaviour in the README is backed by an executable test, and every test runs in an isolated temporary directory (`pytest`'s `tmp_path` fixture) so the suite never touches your real filesystem.

---

## Running the Suite

Install the development extra and run `pytest`:

```bash
pip install -e ".[dev]"
pytest -v
```

Static analysis is part of the same bar:

```bash
ruff check src tests   # lint
mypy src               # type check
```

All three are enforced on every push and pull request by the
[Tests workflow](https://github.com/TheronRadley/tiny-git/actions/workflows/tests.yml). The badge at the top of the README is that workflow's live status — check it rather than trusting a number written in prose.

To reproduce the suite inventory yourself:

```bash
pytest --collect-only -o addopts="" -q | tail -1   # total collected count
```

---

## What the Suite Covers

### 1. Unit tests
Object hashing and blob deduplication (`test_objects.py`), JSON index serialization (`test_index.py`), reference management (`test_branch.py`), diff generation (`test_diff.py`), revision resolution (`test_resolver.py`), fsck diagnostics (`test_fsck.py`), `cat-file`/`show` inspection (`test_cat_file_show.py`), and `rm`/`restore` semantics (`test_rm_restore.py`, `test_restore_table.py`).

### 2. Property & invariant tests (`test_invariants.py`)
Behaviour that must hold for *any* input, not just the inputs the author thought of:

- Same content → same SHA-1 ID; different content → different SHA-1 ID.
- Commit hash uniqueness under message/author/tree changes.
- Branch isolation — committing on one branch never moves another.
- Exact snapshot reproduction on checkout.
- Clean merge union invariance.

### 3. Crash consistency & atomic writes (`test_atomic_crash_safety.py`)
Zero temporary-file leakage on write, format-version rejection, and `fsck` detection of injected corruption.

### 4. Merge matrix
Six files dedicated to merging: `test_merge_matrix.py`, `test_merge.py`, `test_merge_adversarial.py`, `test_merge_adversarial_v2.py`, `test_merge_abort_brutal.py`, `test_merge_state_abort.py`. Together they exercise adjacent line edits, identical edits, overlapping conflict-hunk injection, modify/delete and delete/modify conflicts, binary collisions, empty files, criss-cross DAG LCA resolution, and exact restoration of pre-merge state on `merge --abort`.

### 5. State-machine fuzzer (`test_state_machine.py`)
Parametrised over 10 distinct seeds, each running a 100-step randomized sequence across file creation, staging, commits, branch creation, checkouts, and merges — asserting all eight invariants after *every* step. One thousand randomised operations per run.

### 6. End-to-end & CLI contract (`test_end_to_end.py`, `test_cli_contract.py`)
The full lifecycle through the Python `Repository` API and through `tinygit.cli.main()` called in-process, auditing human-readable error messages, non-zero exit codes, and the absence of raw tracebacks in user-facing output.

> **Note.** No test yet spawns the installed `tiny-git` entry point as a real subprocess. `tests/test_audit_locking_lifecycle.py` does use `subprocess.Popen`, but it launches `sys.executable` workers that drive the library in-process, to prove the file lock actually serialises real processes. The contract tests call `main()` directly, which covers argument parsing and exit codes but not console-script wiring or `PYTHONPATH` setup. Adding a genuine subprocess smoke test (`python -m tinygit status` via `sys.executable`) is an open gap, and it is also the natural place to catch cross-platform argv and encoding differences.

### 7. Git-compatibility & encoding (`test_git_compatibility.py`, `test_symlink_encoding.py`)
Guards the shared conceptual surface (hashing scheme, HEAD syntax, diff and conflict-marker formats) and the byte-oriented storage policy that rejects symlinks.

---

## Suite Inventory

Snapshot of the collected suite, taken on 2026-10-29 with Python 3.11.2 / pytest 9.1.1. The seven `test_audit_*` modules are the regression suite for the audit described in the [Unreleased changelog entry](../CHANGELOG.md); each was checked to fail against the pre-fix code. Regenerate it with the `--collect-only` command above — treat this table as a map, not as a live count.

| Test module | Tests | Area |
| :--- | :-: | :--- |
| `test_audit_ref_validation.py` | 45 | Branch/ref name validation |
| `test_audit_additions.py` | 43 | `.tinygitignore`, reflog, porcelain status |
| `test_audit_modes_paths_fsck.py` | 40 | Exec modes, path resolution, `fsck` hardening |
| `test_audit_tree_and_checkout.py` | 27 | Tree entry validation, checkout safety |
| `test_audit_rm_and_merge.py` | 22 | `rm` protection, merge index/stages/bytes/LCA |
| `test_audit_locking_lifecycle.py` | 21 | Locking, CAS refs, merge lifecycle |
| `test_audit_failure_injection.py` | 13 | Interrupted multi-file operations |
| `test_merge_matrix.py` | 11 | Merge scenarios |
| `test_state_machine.py` | 10 | Randomised invariant fuzzing |
| `test_objects.py` | 6 | Content-addressed storage |
| `test_cli_contract.py` | 6 | CLI subprocess contract |
| `test_merge_adversarial.py` | 5 | Merge edge cases |
| `test_invariants.py` | 5 | Property invariants |
| `test_merge_adversarial_v2.py` | 4 | Merge edge cases |
| `test_merge.py` | 4 | Three-way merge engine |
| `test_working_tree.py` | 3 | Checkout safety |
| `test_symlink_encoding.py` | 3 | Symlink & encoding policy |
| `test_rm_restore.py` | 3 | `rm` / `restore` |
| `test_resolver.py` | 3 | Revision resolution |
| `test_index.py` | 3 | Staging index |
| `test_branch.py` | 3 | References |
| `test_atomic_crash_safety.py` | 3 | Atomic writes |
| `test_status.py` | 2 | Status reporting |
| `test_merge_state_abort.py` | 2 | `merge --abort` |
| `test_init.py` | 2 | Repository creation |
| `test_git_compatibility.py` | 2 | Git-compatible formats |
| `test_fsck.py` | 2 | Integrity checking |
| `test_end_to_end.py` | 2 | Full lifecycle |
| `test_diff.py` | 2 | Unified diff |
| `test_checkout_topology.py` | 2 | Checkout tree integrity |
| `test_checkout.py` | 2 | Branch switching |
| `test_add.py` | 2 | Staging |
| `test_restore_table.py` | 1 | Restore semantics table |
| `test_merge_abort_brutal.py` | 1 | Abort under duress |
| `test_log.py` | 1 | Commit log |
| `test_fsck_adversarial.py` | 1 | Corruption detection |
| `test_commit.py` | 1 | Commit creation |
| `test_cat_file_show.py` | 1 | Object inspection |
| **38 modules** | **309** | |

---

## Writing New Tests

From [`CONTRIBUTING.md`](../CONTRIBUTING.md):

- Every new feature or bugfix must ship with tests.
- Never write to `/tmp` directly or mutate the global filesystem — use `tmp_path`.
- Run the full suite before opening a pull request.

The invariants each test is expected to preserve are documented in [`invariants.md`](invariants.md).
