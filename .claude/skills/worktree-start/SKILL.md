---
name: worktree-start
description: Before writing or editing any source/test files to implement a planned feature or fix in this repo, enter a dedicated git worktree first. Use as soon as a plan is approved (exiting plan mode) or before the first Edit/Write for any non-trivial implementation task — not for quick one-off edits the user explicitly asks to happen in place.
---

# Start implementation work in a worktree

This repo's convention: implementation work (new features, fixes, refactors
spanning more than a couple of lines) happens in an isolated git worktree, not
directly on `main` in the primary checkout. This keeps `main` clean and
in-progress work from entangling with other changes.

## Steps

1. Before the first `Edit`/`Write` call for the task, check current state:

```bash
git status
git branch --show-current
```

2. If already on `main` (or another long-lived branch) with a clean tree, call
   `EnterWorktree` with a descriptive `name` matching the feature (e.g.
   `risk-controls`) before making any changes.

3. If implementation was already started directly on `main` before realizing
   this (uncommitted changes present), preserve the work rather than
   discarding it:

```bash
git stash push -u -m "<short description of in-progress work>"
```

Then call `EnterWorktree`, and once inside the new worktree:

```bash
git stash pop
```

4. Continue all implementation, testing, and verification inside the
   worktree. Only leave it (`ExitWorktree`) when the user asks to exit, or at
   session end (they'll be prompted to keep or remove it).

## When to skip this

- The user explicitly asks for a small, targeted edit "right here" / "on
  main" / "in this branch".
- Read-only exploration, research, or answering questions — no worktree
  needed until actual file changes begin.
