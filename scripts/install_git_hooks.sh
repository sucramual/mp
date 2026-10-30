#!/usr/bin/env bash
# Turn on the tracked Git hooks in config/git-hooks for this checkout. install.sh and scripts/cloud-bootstrap run it.
# The pre-push hook runs the private-term leak check on each pushed commit. See config/git-hooks/pre-push.
#
# core.hooksPath is relative, so each worktree runs its own tracked copy of the hooks.
# The main checkout and its linked worktrees share one Git config, so only a run from the main checkout
# writes it. A run from a linked worktree, such as a test run in a `dotfiles-pr` worktree, changes nothing.
# A different existing value stays, with a warning. This step never fails the installer.
set -euo pipefail

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hooks_path="config/git-hooks"
set_command="git -C \"$DOTFILES_DIR\" config core.hooksPath $hooks_path"

if ! command -v git >/dev/null 2>&1; then
  echo "  WARNING: git is unavailable; skipped core.hooksPath (the pre-push leak check)"
  exit 0
fi
if ! git_dirs="$(git -C "$DOTFILES_DIR" rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null)"; then
  echo "  $DOTFILES_DIR is not a Git checkout; skipped core.hooksPath (the pre-push leak check)"
  exit 0
fi
git_dir="$(printf '%s\n' "$git_dirs" | sed -n 1p)"
common_dir="$(printf '%s\n' "$git_dirs" | sed -n 2p)"
if [ "$git_dir" != "$common_dir" ]; then
  echo "  $DOTFILES_DIR is a linked worktree; skipped core.hooksPath. Run the installer from the main checkout."
  exit 0
fi

current="$(git -C "$DOTFILES_DIR" config --get core.hooksPath || true)"
if [ "$current" = "$hooks_path" ]; then
  echo "  Git hooks already on (core.hooksPath = $hooks_path)"
elif [ -n "$current" ]; then
  echo "  WARNING: core.hooksPath is already '$current', so the pre-push leak check is off. Left it unchanged."
  echo "  To turn the check on, run: $set_command"
else
  git -C "$DOTFILES_DIR" config core.hooksPath "$hooks_path"
  echo "  Set core.hooksPath = $hooks_path (the pre-push leak check)"
fi
