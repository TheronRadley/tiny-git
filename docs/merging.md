# Merging & Conflict Resolution

`tiny-git merge <target-branch>` combines divergent development histories into a unified snapshot.

---

## 1. Lowest Common Ancestor (LCA) Search

When merging target branch `C` into current HEAD branch `B`, `tiny-git` must first locate their best common ancestor `A`:

```
        B  (current branch / HEAD)
       / \
      A   C  (target branch)
```

1. `tiny-git` performs a Breadth-First Search (BFS) starting at commit `B`, recording all ancestors and their topological depth.
2. It then performs a BFS starting at commit `C`, searching for the first commit that is also present in `B`'s ancestor set.
3. This commit is chosen as the **Lowest Common Ancestor (`A`)**.

---

## 2. Fast-Forward Merge

If `A == B` (the current branch is an ancestor of the target branch), no divergent history exists:

```
A (HEAD / main) ───► C (feature)
```

In this case, `tiny-git` performs a **Fast-Forward Merge**:
1. Working tree files and index entries are updated to match snapshot `C`.
2. The current branch reference (`refs/heads/main`) is advanced directly to `C`.
3. No merge commit is created.

---

## 3. Three-Way Merge Algorithm

When `B` and `C` have diverged from `A`, `tiny-git` performs a true three-way merge across all files:

| Ancestor (`A`) | HEAD (`B`) | Target (`C`) | Result | Explanation |
| :---: | :---: | :---: | :---: | :--- |
| `val` | `val` | `val_C` | **`val_C`** | Only Target changed; take Target's change |
| `val` | `val_B` | `val` | **`val_B`** | Only HEAD changed; take HEAD's change |
| `val` | `val_B` | `val_B` | **`val_B`** | Both made identical changes; clean merge |
| `val` | `val_B` | `val_C` | **3-Way Text** | Both changed differently; perform line merge |

### Line-Level Three-Way Merge
For text files where both `B` and `C` made changes:
- `tiny-git` computes edit regions from `A → B` and `A → C`.
- If `B` and `C` modified **non-overlapping** lines of `A`, the changes are combined automatically without conflict.
- If `B` and `C` modified **overlapping** lines of `A` with different content, `tiny-git` inserts conflict markers into the working directory file:
  ```
  <<<<<<< HEAD
  Current HEAD lines...
  =======
  Incoming feature branch lines...
  >>>>>>> feature
  ```

---

## 4. Merge Commits

When a three-way merge succeeds without conflicts, `tiny-git` creates a **Merge Commit**:
- It has **two parents**: `[HEAD_commit, target_commit]`.
- Its commit message defaults to `Merge branch '<target>'`.
- It records the combined snapshot tree in `.tinygit/objects/`.
