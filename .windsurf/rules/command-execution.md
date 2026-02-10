---
description: Rules for executing commands in the terminal
---

# Command Execution Rules

- **Never run `cd` commands** — use `Cwd` parameter instead
- **Sequential git commands** — always wait for `git add` to complete before `git commit`
- **Avoid parallel git operations** — git commands that modify state should run sequentially
- **Use `python3`** — never use bare `python` (may not exist in pyenv)

# No Parallel Execution That Causes Race Conditions

- **DO NOT execute parallel operations that could cause race conditions or merge conflicts**
- Examples of operations that must be sequential:
  - Multiple edits to the same file
  - Git operations (add, commit, push)
  - Operations where one depends on the result of another
- Parallel execution is acceptable for independent read-only operations (e.g., reading multiple files)
