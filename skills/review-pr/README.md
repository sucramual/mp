# review-pr

This file records the skill-level decisions of `review-pr`. Read it before you change the skill.
`SKILL.md` tells the agent what to do.

## No engine

Until 2026-10-29 this skill wrapped the round engine of [ro](https://github.com/sucramual/ro): a state file, a ledger, triage JSON, polling, and push and post wrappers.
An audit of 9 PRs found that the engine caught no real defect, and that it failed in cloud sessions. Bot reviewers and CI found every real defect, and the agent fixed each one by hand.
So the skill is now prose over `gh` and `git`. Do not add a state file or a wrapper command back without new evidence that prose fails.

## Reviewer list

`config/review-pr/reviewers.json` names one reviewer per repository: its `login`, an optional `retrigger` text, an optional `doneReaction`, and an optional `doneComment`: text that the reviewer's own comment holds when it has reviewed the head, with `{head}` for the full head SHA. The installers link it to `~/.config/review-pr/reviewers.json`. The private work overlay holds the entries for work repositories in its own `config/review-pr/reviewers.json`, and its installer links that file to `~/.config/review-pr/work-reviewers.json`.
The [Ready to merge](references/ready-to-merge.md) check reads it to decide reviewer coverage.
`tests/test_review_pr_skill.py` checks the file's shape.

## Decisions that belong to the skill

| Decision | Why |
| --- | --- |
| One ready check, in `references/ready-to-merge.md`, for this skill, the controller, and `/rogue`. | Two copies drift. The check reads REST only, because cloud sessions block GraphQL. It lives in the skill folder because `/eval-skill` copies only that folder, so an isolated eval can read it. |
| One risk-tier definition, in `references/risk-tiers.md`, for `/rogue`, `/neo`, and the self-repair guide. | Copies of the tier rules drift. It sits next to the ready check so that an isolated eval can read it. |
| Wait with PR-activity wakes in cloud sessions, and `gh pr checks --watch` locally. | The harness wakes the agent. In-process polling cost minutes per round and died on proxy errors. |
| In local Claude Code, watch the checks with `run_in_background: true` and wait for the reviewer with Monitor running `scripts/wait-for-activity.sh`. Codex keeps the foreground `perl` wait. | On 2026-11-02 the Claude Code desktop app blocked a foreground `sleep` and the `perl` watch, and it names a chain of short sleeps as a workaround that it refuses. A foreground watch also hit the 600-second Bash limit before `alarm` fired. Codex 0.157 ran a 40-second foreground sleep, so its path stays. The Monitor limit of 15 minutes matches the reviewer re-trigger time in step 2. |
| The reviewer wait is a script, not an inline loop, and it compares comment IDs with `updated_at`, not counts. | In the first run on PR 20, Claude Code's worktree guard refused the inline loop in a worktree-isolated agent. The Codex reviewer reports "done" by editing its summary comment, so a count never changes. `tests/test_review_pr_wait.py` covers the edit and a failed read. |
| One round-summary format, in `references/round-summary.md`, for the design stop and each published round. | The controller reads the summaries to check every round's verdict, so they need one shape. It sits in the skill folder so that an isolated eval can read it. |
| Push with plain `git push`, never force. | A plain push already refuses when the remote moved. |
| Replies go through `gh api` with the `agent on behalf of` footer. | The footer shows that an agent wrote the text, not Marcus. |
| Resolve only threads that a bot or the PR author opened. | A person's thread is theirs to close. |
| A guard claim that fails safe gets No change, not a push. | Every push starts a new full review, and a safe failure only waits or stops. |
| A design batch stops, leaves its threads open, and messages Marcus. | Marcus owns design. An open thread blocks the merge until he decides. |
| Reviewer mode posts one review through `gh api .../reviews` with `commit_id`. | The pin ties the verdict to the head that was read. `gh pr review` cannot pin it. |
| The agent never merges, never dismisses a human review, and never force-pushes. | Marcus owns the merge. No command enforces these rules, so they stay in prose. |
| Part 3 follows `references/comment-triage.md`. | That file holds the design-verdict rules that Marcus decided. |

## Before you merge a change to this skill

- A skill change goes through `/improve-skill`. A mechanical or feature change records its class and reason in the PR, in place of `/eval-skill`.
