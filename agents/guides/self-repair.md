# Self-repair

These instructions supplement the global AGENTS.md.

Use this guide when a bug in your own tooling blocks or slows your task, and you can fix it.
Your tooling is code and config in `sucramual/mp`: the scripts of a skill, a tool under `tools/`, or a config file.
The fix ships as its own PR. It merges without Marcus only when [Risk tiers](../../skills/review-pr/references/risk-tiers.md) allows it.

## Not a bug

- A guard, gate, check, permission prompt, or review finding that stopped you did its job. Park the item or ask Marcus. Never change it to get past it.
- A bug in another repository is out of scope. Run `agent-trace note friction --category workaround --what <the bug> --fix <suggested fix>`, work around the bug, and do not fix it under this guide.

## Steps

1. Run `agent-trace note friction --category workaround --what <the bug> --fix self-repair`. After the PR opens, run it again with `--fix <PR URL>`.
2. Start a separate worktree with `dotfiles-pr start <slug>`, as [Git and worktrees](git-and-worktrees.md) describes. Never put the fix in the task's PR or worktree.
3. Write a test that fails on the bug. Then fix the bug, and run `scripts/check`.
4. Publish with `open-pr`. Let `review-pr` take the PR to a verdict.
5. Classify the tier with [Risk tiers](../../skills/review-pr/references/risk-tiers.md).
6. If the tier is Low or Medium and the PR changes no reserved path, merge it under the controller merge rule in [PR review](pr-review.md#reviewer-and-controller). Then run `dotfiles-pr sync`. Otherwise park it: name the PR and one merge command pinned to the reviewed SHA in your final report.
7. Continue the task. If the fix parked, use a workaround. Do not wait for the merge.

## Limits

- Open one fix PR for each blocker. If `review-pr` stops on a design verdict or on its round limit, park the PR. Do not start a second fix.
- Skill and guide prose is High, so a prose fix always parks.
- Never weaken, skip, or delete a test.
- Never pass `--auto` or `--admin`.
- Use this guide only in `sucramual/mp`.
