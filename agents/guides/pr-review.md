# PR review

These instructions supplement the global AGENTS.md.

## Review comment triage

The triage rules are in [Review comment triage](../../skills/review-pr/references/comment-triage.md).

### Reviewer and controller

The reviewer and the controller are separate roles. The reviewer never merges.

**Reviewer:** the agent that runs `review-pr`, usually the background agent that `open-pr` starts.

- Classify each round before you change anything. Include attributable CI failures in the batch. Then follow `review-pr` for dispositions, fixes, replies, and when to stop.
- Use the `review-pr` round summary on the PR as the record of each round. Lead it with the verdict. Do not post a separate triage comment.
- For a design round, give each design comment the `Needs decision` disposition. Name the shared root and propose a change to the root choice. Typical changes: narrow the scope, give the job to the tool that owns the state, or use a real implementation instead of a hand-rolled one. Do not fix the other comments in the batch, because a root change can make them irrelevant.
- When you stop, report the final head SHA, the verdict of each round, and the result of [Ready to merge](../../skills/review-pr/references/ready-to-merge.md).

**Controller:** the main agent. It owns final acceptance.

- For a design verdict, bring me the shared root, the proposed root change, its 2 to 4 options with the recommended option, and the per-comment table from the [Round summary](../../skills/review-pr/references/round-summary.md). Wait for my decision before you change code.
- After my decision, restart `review-pr` on the PR, and give it my words verbatim. When I pick an option, my words name its letter. Its own loop applies the decided claims; do not apply them in parallel.
- For edges in the dotfiles repository (`sucramual/mp`) or its private work overlay (`sucramual/mp-private`, checked out at `~/dotfiles-work`), merge only when all of these are true:
  - `review-pr` stopped, and [Ready to merge](../../skills/review-pr/references/ready-to-merge.md) reports `ready` on the current head. Never merge a PR that is `ready with gaps` or `not ready`. Report its gaps to me instead.
  - Each round summary on the PR shows the verdict edges. A round with nothing actionable posts no summary. For it, check on GitHub that the PR has no unresolved review thread. Read the PR yourself. Do not rely on the reviewer's report.
  - The PR head is still the SHA that the reviewer reported.
  - The PR changes no file in [Merge-rule files](#merge-rule-files). Marcus merges a PR that changes one, whatever its verdict.
  - In the overlay, the PR changes only files in the [Overlay merge allowlist](#overlay-merge-allowlist). Marcus merges any other overlay PR, whatever its verdict.
- Before you merge, post one line to `issues/<number>/comments` that says why, as a colleague does when they merge for you. Name the reviewed SHA, the ready verdict, the review rounds, and the CI result. For example: `Merging 4cf0af9 for Marcus: ready, 1 round with no findings, checks and leaks passed.`
- To merge, run `gh pr merge <number> --repo sucramual/mp --squash --match-head-commit <reviewed SHA>`. Where GraphQL is blocked, as in a cloud session, use the REST form with the same pin: `gh api -X PUT repos/sucramual/mp/pulls/<number>/merge -f sha=<reviewed SHA> -f merge_method=squash`. Then read the receipt: `gh api repos/sucramual/mp/pulls/<number> --jq '{merged, merge_commit_sha}'` shows `merged: true`. Then run `dotfiles-pr sync`.
  For the overlay, use the same commands with `sucramual/mp-private` in place of `sucramual/mp`. After the receipt, run `git -C ~/dotfiles-work pull --ff-only`, because `dotfiles-pr sync` does not update the overlay.
- If GitHub blocks the merge for unresolved threads or failed checks, return the PR to `review-pr`. Never resolve threads yourself to unblock a merge. Never pass `--admin` to `gh pr merge`.
- For edges in an employer repository that has a rule in [Employer repository rules](../../skills/review-pr/references/risk-tiers.md#employer-repository-rules), merge only as that rule allows.
- For edges in all other repositories, report that the PR is ready. Do not merge.

### Merge-rule files

These files decide when an agent may merge, what blocks a merge or a push, or which tools an agent may run without a prompt. An agent never merges a PR that changes one of them, because the PR could widen the agent's own merge authority. The /rogue reserved paths in `skills/rogue/SKILL.md` list the same files. Keep the two lists in step.

- `AGENTS.md`
- `agents/global.md`
- `agents/guides/pr-review.md`
- `agents/guides/git-and-worktrees.md`
- `agents/guides/dotfiles-review.md`
- `skills/rogue/SKILL.md`
- `skills/neo/SKILL.md`
- `skills/review-pr/SKILL.md`
- `skills/review-pr/README.md`
- `skills/review-pr/references/ready-to-merge.md`
- `skills/review-pr/references/risk-tiers.md`
- `agents/guides/self-repair.md`
- `config/review-pr/reviewers.json`
- `skills/open-pr/references/spacelift.md`
- `skills/open-pr/references/stack.md`
- `config/claude/settings.cloud.json`
- `config/claude/settings.template.json`
- `config/codex/config.toml`
- `config/claude/merge_cloud_settings.py`
- `config/codex/merge_config.py`
- `scripts/check_leaks.py`
- `config/git-hooks/pre-push`
- `scripts/install_git_hooks.sh`
- `.github/workflows/checks.yml`

### Overlay merge allowlist

In the private work overlay `sucramual/mp-private`, an agent may merge only a PR whose every changed file is on this list. These files hold project knowledge, not permissions, gates, reviewer settings, or installed skills. Every other overlay file, such as `config/**`, `install.sh`, `work.md`, `skills/**`, `tests/**`, and `.github/**`, is for Marcus to merge.

- `agents/local.md`
- `agents/glossary.md`
- `agents/best-practices.md`
- `agents/vocabulary.md`
- `README.md`

## Ready to merge

The ready check that `review-pr`, the controller, and `/rogue` use lives in [`skills/review-pr/references/ready-to-merge.md`](../../skills/review-pr/references/ready-to-merge.md). It is inside the skill folder so that isolated evals of `review-pr` can read it.
