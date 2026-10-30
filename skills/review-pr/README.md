# review-pr

This file records the skill-level decisions of `review-pr`. Read it before you change the skill.
`SKILL.md` tells the agent what to do.

## No engine

Until 2026-10-29 this skill wrapped the round engine of [ro](https://github.com/sucramual/ro): a state file, a ledger, triage JSON, polling, and push and post wrappers.
An audit of 9 PRs found that the engine caught no real defect, and that it failed in cloud sessions. Bot reviewers and CI found every real defect, and the agent fixed each one by hand.
So the skill is now prose over `gh` and `git`. Do not add a state file or a wrapper command back without new evidence that prose fails.

## Reviewer list

`config/review-pr/reviewers.json` names one reviewer per repository: its `login`, an optional `retrigger` text, and an optional `doneReaction`. The installers link it to `~/.config/review-pr/reviewers.json`. The private work overlay holds the entries for work repositories in its own `config/review-pr/reviewers.json`, and its installer links that file to `~/.config/review-pr/work-reviewers.json`.
The [Ready to merge](references/ready-to-merge.md) check reads it to decide reviewer coverage.
`tests/test_review_pr_skill.py` checks the file's shape.

## Decisions that belong to the skill

| Decision | Why |
| --- | --- |
| One ready check, in `references/ready-to-merge.md`, for this skill, the controller, and `/rogue`. | Two copies drift. The check reads REST only, because cloud sessions block GraphQL. It lives in the skill folder because `/eval-skill` copies only that folder, so an isolated eval can read it. |
| One risk-tier definition, in `references/risk-tiers.md`, for `/rogue`, `/neo`, and the self-repair guide. | Copies of the tier rules drift. It sits next to the ready check so that an isolated eval can read it. |
| Wait with PR-activity wakes in cloud sessions, and `gh pr checks --watch` locally. | The harness wakes the agent. In-process polling cost minutes per round and died on proxy errors. |
| Push with plain `git push`, never force. | A plain push already refuses when the remote moved. |
| Replies go through `gh api` with the `agent on behalf of` footer. | The footer shows that an agent wrote the text, not Marcus. |
| Resolve only threads that a bot or the PR author opened. | A person's thread is theirs to close. |
| A guard claim that fails safe gets No change, not a push. | Every push starts a new full review, and a safe failure only waits or stops. |
| A design batch stops, leaves its threads open, and messages Marcus. | Marcus owns design. An open thread blocks the merge until he decides. |
| Reviewer mode posts one review through `gh api .../reviews` with `commit_id`. | The pin ties the verdict to the head that was read. `gh pr review` cannot pin it. |
| The agent never merges, never dismisses a human review, and never force-pushes. | Marcus owns the merge. No command enforces these rules, so they stay in prose. |
| Part 3 follows `agents/guides/pr-review.md`. | That guide holds the design-verdict rules that Marcus decided. |

## Before you merge a change to this skill

- A skill change goes through `/improve-skill`. A mechanical or feature change records its class and reason in the PR, in place of `/eval-skill`.
