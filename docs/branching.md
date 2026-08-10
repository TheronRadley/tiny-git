# Branching & HEAD

In `tiny-git`, a branch is simply a named pointer to a commit SHA-1 hash.

---

## 1. How Branches Work

When you initialize a repository, `HEAD` is created pointing to `refs/heads/main`:
```
HEAD -> "ref: refs/heads/main"
```

Before your first commit, `.tinygit/refs/heads/main` does not exist yet. This is called an **unborn branch**.
When you make your first commit (`commit A`), `.tinygit/refs/heads/main` is created on disk containing `A`'s SHA-1 hash.

### Creating a Branch
Executing `tiny-git branch feature` creates a new text file at `.tinygit/refs/heads/feature` containing the commit SHA-1 currently referenced by `HEAD`:
```
main    -> commit A
feature -> commit A
```

---

## 2. Detached HEAD State

When you check out an existing branch name (`tiny-git checkout feature`), `.tinygit/HEAD` stores a symbolic reference (`ref: refs/heads/feature`).

When you check out a direct commit hash or prefix (`tiny-git checkout a82f1c2`), `.tinygit/HEAD` stores that 40-character SHA-1 directly:
```
HEAD -> a82f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d
```
In this state, any new commits you create will advance `HEAD`, but will not advance any branch pointer.

---

## 3. Checkout Safety Engine

A fundamental safety invariant in `tiny-git` is:
> **Never silently destroy user work.**

When executing `tiny-git checkout <target>`, `tiny-git` compares the target branch snapshot against the current `HEAD` snapshot and the user's working directory/index.

### Safety Rules
An operation is aborted with a `WorkingTreeDirtyError` if:
1. **Unstaged Working Tree Modification**: A file differs between `HEAD` and `<target>`, and the file on disk has been modified since `HEAD`.
2. **Staged Index Modification**: A file differs between `HEAD` and `<target>`, and the user has staged a modification in `.tinygit/index`.
3. **Untracked File Overwrite**: `<target>` contains a file that is untracked in `HEAD`, but currently exists as an untracked file in the working directory.

This guarantees that `checkout` can never overwrite uncommitted edits.
