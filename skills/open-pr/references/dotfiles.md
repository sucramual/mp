# Dotfiles repository mode for open-pr

Read this file only when the detection in [SKILL.md](../SKILL.md) finds the dotfiles repository. It sets `DOTFILES_PR`. The step numbers are those of [publish-steps.md](publish-steps.md).
In the dotfiles repository, `dotfiles-pr ship` does the commit, push, and create work. It runs `scripts/check`, commits all changes with `git add -A`, pushes with a plain `git push`, and opens the PR or prints the existing one. Do not run your own `git commit`, `git push`, or `gh pr create` there. Change the steps as follows:

- **Step 1:** run it as written. The branch is the one that `dotfiles-pr start` made.
- **Step 2:** do the inspection and build the intended file list, but do not stage or commit. Because `ship` commits every change in the worktree, stop and ask when any changed or untracked path is not in the intended list.
- **Step 3:** run it only when `git status --porcelain` is empty and `origin/${CURRENT_BRANCH}` does not exist. Otherwise skip it: uncommitted changes block a rebase, and a rebased branch that is already on the remote needs a force-push, which `ship` never does. `dotfiles-pr start` cut the branch from a fresh `origin/main`. The publish steps run steps 3 and 4 as one block. Run only its part above `# Step 4: push.`.
- **Step 4:** skip it. `ship` pushes.
- **Step 5:** the generators compare commits only, so they miss uncommitted changes. When the worktree has uncommitted changes, write the description from `git diff "origin/${DEFAULT_BRANCH}"` and the untracked files. Save the description to a file outside the worktree, because `ship` commits every file in it.
- **Steps 6 and 7:** run them as written.
- **Step 8:** instead of `gh pr create`, run `"$DOTFILES_PR" ship "<conventional commit message>" --body-file <file>` from the worktree. The first line of the message becomes the PR title, and the last line of the output is the PR URL. If step 7 produced reviewers or assignees, add them with `gh pr edit <url> --add-reviewer <names> --add-assignee <names>`. If `ship` fails, for example because the checks fail, stop and report the error.
- **Step 9:** run it as written. The background `review-pr` follow-up is the reason to publish through `open-pr` and not through `dotfiles-pr ship` alone.

Stack mode is not supported in the dotfiles repository, because `dotfiles-pr ship` publishes one branch. Stop and ask.
