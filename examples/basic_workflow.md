# Example: Basic Workflow

This example walkthrough demonstrates a complete local version-control session using `tiny-git`.

---

## 1. Initializing and Configuring

```bash
mkdir project
cd project

# Initialize new repository
tiny-git init

# Configure user identity
tiny-git config user.name "Ron"
tiny-git config user.email "ron@example.com"
```

---

## 2. Staging and Committing

```bash
# Create README.md
echo "# Project Title" > README.md

# Check status (untracked file)
tiny-git status

# Stage the file
tiny-git add README.md

# Check status (staged file)
tiny-git status

# Commit
tiny-git commit -m "Initial commit"
```

---

## 3. Creating a Branch and Making Edits

```bash
# Create feature branch and switch to it
tiny-git branch feature
tiny-git checkout feature

# Modify README.md and commit
echo "More details added." >> README.md
tiny-git add README.md
tiny-git commit -m "Update README on feature branch"

# Inspect commit log
tiny-git log --oneline
```

---

## 4. Merging Back to Main

```bash
# Switch back to main
tiny-git checkout main

# Verify README.md is back to initial version
cat README.md

# Merge feature branch (Fast-forward merge)
tiny-git merge feature

# Verify updated README.md
cat README.md
```
