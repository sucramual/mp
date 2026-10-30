# Stack mode

A layer is one PR in a stack. The bottom layer's parent is the trunk. Each other layer's parent is the layer below it.
This file replaces steps 3, 4, and 8 of [SKILL.md](../SKILL.md). Run steps 1, 2, and 5–7 once for each layer, bottom to top. Run the replacement step 8 once, after every layer is ready. Check out the layer's branch before its step 1 and step 2, because `gh stack init` leaves the top layer checked out. Use `gh stack --help` for syntax.

## Layers

- Take the layers from the caller, from Marcus, or from the spec's `landing.layers`.
- A layer is whole files or existing commits. Never split a hunk or rewrite a commit to make a boundary. With no clean boundary, stop and ask.
- Use one commit for each layer. Run the repository PR skill's per-layer checks and size gate with the parent layer as the base.
- Pass the trunk as a branch name such as `main`, never `origin/main`.
- If `gh stack view --json` fails, adopt the branches with `gh stack init --base <trunk> <bottom> ... <top>`. Then later restacks work.
- A `gh stack` command that prints a `⚠` line has failed, even with exit 0. Stop and report.

## Instead of steps 3 and 4: restack and push

1. Run `git fetch origin`. Never run `git rebase origin/<default>` on a layer.
2. Before any rewrite, stop if any layer's `origin/<layer>` has commits that the local branch lacks. Test with `git merge-base --is-ancestor`.
3. Run `gh stack rebase --remote origin`. After a conflict, resolve and stage the paths. Then run `gh stack rebase --continue`, never `git rebase --continue`.
4. Run `gh stack push --remote origin`. It is not atomic. If a branch is rejected, fix it and run the command again.

## Steps 5–7 for each layer, then step 8 once

Steps 5–7: pass `--base-branch "origin/<parent>"` to the description generator, and take reviewers from that layer's own diff.
Each PR here is one layer of a stack, so each gets a change map. Show the other layers as dashed nodes. Then replace step 8 as follows.

1. Create each layer's PR, bottom to top: `gh pr create --base <parent> --head <layer>`. Use its real title, body, and reviewers.
2. Link the PRs: `gh stack link --remote origin --base <trunk> <PR numbers, bottom to top>`.
3. Do not use `gh stack submit --auto`. It opens PRs with generated text, and a review bot can run once when a PR opens and not again when the body is edited or a draft becomes ready.
4. If a layer already has a PR, do not create one. Fix its base, title, or body only if wrong.

## Read back before step 9

For each layer, check that the local head, `origin/<layer>`, and the PR's `headRefOid` match.
Check that the PR base is the layer below (the trunk for the bottom layer), the PR is open, and `autoMergeRequest` is null.
If any check fails, stop before step 9.

To update a stack, commit on the lowest layer that the change affects. Restack as above, push, and read back.
Never merge, `gh stack modify`, `gh stack unstack`, or `gh pr merge` a layer from this skill. Stop and ask.

## Start the follow-up

This replaces the one-PR follow-up of step 9. Skip it when `--no-review` was passed.
A restack rewrites the upper branches, so a running agent's push is refused. Only one writer works on the stack at a time.

1. If a stack follow-up already runs, stop the follow-up before you change the stack. Start a new one after the change.
2. Read the layers in order with `gh stack view --json`. Record each layer's PR number, branch, and head SHA.
3. Start one background agent for the whole stack, as step 9 describes. Do not start one agent for each layer.

## Agent brief

Work on one layer at a time, bottom to top. Pin the isolated worktree to the layer's branch and its current remote head.
Invoke the installed `review-pr` skill for the layer's PR. Wait until the run stops. Then follow the first case that applies:

- The run stopped for a decision, a design batch, or its round limit. Stop and report the layer and the reason.
- The run pushed a fix to this layer, and a layer remains above it. Stop and report "restack needed from `<branch>`".
- Otherwise, go to the next layer.

Never edit, commit, or push to another layer's branch. A fix lands on the lowest layer that it affects.
When a claim on this layer needs a change to a lower layer, triage it as `Needs decision` and name that layer.
Never restack, rebase, or force-push. The parent owns restacks.
At the end, report each layer's PR, its [Ready to merge](../../review-pr/references/ready-to-merge.md) result, and its gaps.

## Restack after a fix

The parent does this when the agent reports "restack needed".

1. Fetch. Fast-forward the fixed layer's local branch to its remote branch. The agent pushed from another worktree, so a restack from the stale local branch discards the fix.
2. For each layer above, confirm that its remote branch is not ahead of its local branch.
3. Check out the fixed layer. Run `gh stack rebase --upstack --no-trunk --remote origin`, then `gh stack push --remote origin`. Read back, then start the follow-up again.
