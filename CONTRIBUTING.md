# Contributing to Tiny Git

First off, thank you for considering contributing to `tiny-git`! It is through contributions from software engineers, educators, and students that this educational project remains clean, understandable, and technically correct.

---

## 1. Core Design Philosophy

When contributing code or documentation, always adhere to our core priorities:
1. **Correctness beats cleverness.**
2. **Simplicity beats feature count.**
3. **Tests beat claims.**
4. **Real implementation beats scaffolding.**
5. **Safety beats convenience.**

We do not add features merely to make the repository look larger. Every line of code must be readable, typed, tested, and genuinely useful.

---

## 2. Development Setup

1. Fork the repository and clone your fork:
   ```bash
   git clone https://github.com/<your-username>/tiny-git.git
   cd tiny-git
   ```
2. Create an isolated Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install the package in editable mode with development tools:
   ```bash
   pip install -e ".[dev]"
   ```

---

## 3. Code Standards & Typing

- **Python Version**: Write modern Python 3.12+.
- **Type Hints**: Use complete type hints (`from __future__ import annotations`, explicit return types, explicit parameter types).
- **No Traceback Dumps**: Custom error classes in `tinygit.errors` must provide human-readable descriptions.
- **No TODO or Placeholder Code**: Do not leave `# TODO implement later`, `pass`, or `raise NotImplementedError` in production code.

---

## 4. Testing Requirements

- Every new feature or bugfix **must** include tests in `tests/`.
- Never write tests that write to `/tmp` directly or mutate the global filesystem; always use pytest's `tmp_path` fixture.
- Run the full test suite before submitting a Pull Request:
  ```bash
  pytest -v
  ```

---

## 5. Pull Request Guidelines

1. Create a descriptive feature branch (`git checkout -b fix-checkout-safety`).
2. Write clean commits explaining *why* the change was made.
3. Include tests verifying the fix or behavior.
4. Ensure all existing tests pass (`pytest -v`).
5. Open a Pull Request on GitHub and describe the architectural reasoning behind any data structure or workflow changes.
