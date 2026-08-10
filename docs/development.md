# Development Guide

This document covers testing, debugging, and maintaining `tiny-git`.

---

## 1. Local Setup

1. Clone your fork and enter the repository:
   ```bash
   git clone https://github.com/<your-username>/tiny-git.git
   cd tiny-git
   ```
2. Install editable package with development tools:
   ```bash
   pip install -e ".[dev]"
   ```

---

## 2. Running the Test Suite

Run pytest with verbose output:
```bash
pytest -v
```

### Running Specific Subsystem Tests
```bash
# Test content-addressed storage
pytest tests/test_objects.py

# Test staging area
pytest tests/test_index.py

# Test 3-way merge engine
pytest tests/test_merge.py

# Test property invariants
pytest tests/test_invariants.py
```

---

## 3. Debugging Object Storage

When debugging a repository state, you can inspect `.tinygit/objects/` directly using standard Python or shell tools:

```bash
# Find all stored object files
find .tinygit/objects -type f

# Check HEAD reference
cat .tinygit/HEAD

# Check branch target
cat .tinygit/refs/heads/main
```

To parse an object programmatically:
```python
from pathlib import Path
from tinygit.objects import ObjectStore

store = ObjectStore(Path("."))
obj = store.read_object("a82f1c2b48a1c9e3e7f4a56b8c9d0e1f2a3b4c5d")
print(obj.type)
print(obj.serialize().decode("utf-8"))
```
