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

5. Delete the worktree's branch on the remote if it's still there. A worktree
   is created on its own branch, which is usually pushed to open a PR; once that
   PR is merged (squash-merges leave the branch tip off `main`'s history, so
   check the PR state rather than `git branch --merged`), the remote branch is
   stale and should go too:

```bash
git fetch --prune origin                 # drop remote-tracking refs already deleted upstream
git branch -r | grep <branch>            # is the branch still on the remote?
git push origin --delete <branch>        # delete it if so (skip if PR is unmerged/open)
```

   Do not delete a remote branch whose PR is still open or unmerged — only ones
   whose work has already landed. If unsure, confirm with the user.

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
