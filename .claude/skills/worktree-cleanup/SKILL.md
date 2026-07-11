---
name: worktree-cleanup
description: Remove a git worktree and delete its directory. Use when the user asks to clean up, remove, or delete a worktree.
---

# Worktree cleanup

Removes a worktree from git's tracking and deletes the directory on disk.

## Steps

1. Identify the worktree path (confirm with the user if ambiguous).
2. Run `git worktree list` to verify it exists before doing anything.
3. Remove the worktree:

```bash
git worktree remove <path>
```

This deregisters it from git and deletes the directory. If git refuses because
the worktree has uncommitted changes, report this to the user and ask whether
to force-remove (`--force`) or leave it.

4. Confirm the directory is gone:

```bash
git worktree list
```

## Force removal

Only use `--force` if the user explicitly confirms they want to discard
uncommitted changes in that worktree:

```bash
git worktree remove --force <path>
```

## Notes

- Run all git commands from the main worktree (not from inside the worktree
  being removed).
- `git worktree remove` handles both deregistration and directory deletion in
  one step — do not manually `rm -rf` the directory unless `git worktree
  remove` has already been run and left the directory behind.
