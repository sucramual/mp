---
name: rogue
description: Take one goal from intent to a proven, merged, end-to-end result without Marcus watching, after a single interactive intake message. Use for "/rogue", "go rogue", "run this autonomously end to end", or a request to finish work unattended through implementation, PR, review, merge, deploy, and real-environment proof. Covers the run contract, reserved decisions, the pinned merge, and Spacelift plan checks.
---

# Rogue

Intake is the only planned stop. After it, start each step only when the previous step left proof. Silence, a timeout, or a missing check is never proof. Retry a step at most twice, then stop loud: post the step, the evidence, and the fix to the ticket, and continue independent work.

## Intake

If only reserved merges or confirms remain, offer Marcus a checklist instead of a run. Otherwise send him one message with:

- **Goal** and the Linear ticket.
- **Done-checks:** the ticket's "Done when" list, each a check that passes or fails. If the list is missing or an item cannot be checked by a machine, draft it here, and write it to the ticket after approval. The intake message and the run contract keep no separate done-check list.
- **Deploy path**, or `none`.
- **Declared test removals**, or `none`.
- **Grants:** repositories in scope; merge of low and medium tiers, pinned to the reviewed SHA; revert of this run's own merges; the deadline.
- Questions only where an answer changes the plan, each with a default.
- The preflight result.

After Marcus accepts, post the message to the ticket as one comment headed `## /rogue run contract`, before any work. If the write fails, stop. This comment is the only authority; chat approvals do not survive a resume. On a resume or a wake, re-read it and run the preflight again before you act.

## Preflight

Run `auth-helper check --require <logins the plan needs> --horizon <expected run length> --json`, for example `--require gh,gcloud,spacelift`. `rogue-auth` is an alias of `auth-helper`. If `ok` is false, each provider whose status is not `ok` is a missing item; show its `fix`. When `auth-helper` is not on `PATH`, use `gh auth status` and check the other logins by hand, such as `gcloud auth print-access-token` or `spacectl whoami`. `auth-helper` comes from the `tools/` folder of the dotfiles repository; see its [README](https://github.com/sucramual/mp/blob/main/tools/auth-helper/README.md).

Read the merge rules once, at preflight, and use them for the whole run: [Risk tiers](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/risk-tiers.md), [Ready to merge](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/ready-to-merge.md), and [PR review](https://raw.githubusercontent.com/sucramual/mp/main/agents/guides/pr-review.md) for its Merge-rule files. Read each with `curl -fsSL <URL>` or `gh api`. Do not use a web-fetch tool: it returns a summary, not the exact text. If a read fails, treat each PR as High tier and park it. Never merge without these rules.

- **Blocks the start:** `gh`, the Linear connector, and a clean worktree on a feature branch (never `main` or `main-NN`). If one fails, stop and list each fix.
- **Parks only its steps:** every other login. List each failure with its fix in the intake message, start the run, and check again before that step.
- Okta: on the devbox, add `okta` to `--require`. `auth-helper` reads the `verify-browser` Chrome. When `okta` is `expired` or `error`, Marcus runs its `fix` at intake: a noVNC sign-in, or a `verify-browser` restart. On the laptop, confirm the session in Chrome. On a headless host without `verify-browser`, make each signed-in done-check an acceptance item for Marcus, and use Playwright Chromium for public pages.

## Reserved decisions and parks

Always reserved for Marcus, and no grant covers them: messages to people outside Marcus's team, production data, money, shared infrastructure applies, and changes to auth, IAM, secrets, CI workflow, or infra paths, and the merge and authority rules that [Repository specifics](#repository-specifics) reserves.

- Park a reserved or uncovered decision: post it to the ticket with a proposed default, continue independent work, and batch parks into one message.
- Never weaken, skip, delete, or edit a test, CI check, or evaluator to make a step pass. Remove a test only when the contract's declared test removals list it.
- Revert only merges that this run made.

## Steps

Each time you hit friction that you want fixed, run `agent-trace note friction --category <permission|doc|flaky|workaround|missing-tool> --what <text> --fix <text>`. When `agent-trace` is not on `PATH`, list the friction in the run's final report instead.

1. **Plan** the change and the files it touches.
2. **Implement** through workers. Run the repository's checks.
3. **Fresh-context review.** Run `/age` in a new read-only worker with the diff, the goal, and the done-checks, not the chat. A removed or skipped test is important. Fix every important finding, and record the reviewed head SHA. After a clean rebase whose `git range-diff` shows every commit unchanged, rerun the tests and reuse this review.
4. **PR and review.** Run `open-pr --no-review`. The PR body links the contract comment and has a `## Proof` section. Then run `review-pr`. If it stops on a design batch, a decision, or its round limit, park the PR.
5. **Risk tier**, from the diff, as [Risk tiers](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/risk-tiers.md) defines it. High tier or a reserved path: do not merge; park the PR. The one exception is a [Spacelift PR](#spacelift). In an employer repository with an overlay rule, follow the Employer repository rules section of Risk tiers instead of the tiers.
6. **Merge.** Run [Ready to merge](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/ready-to-merge.md). Merge only on `ready`. Park `ready with gaps` and `not ready`, and report the gaps.
   Exception, for a low-tier PR only: a gap that is only a missing reviewer or missing reviewer configuration does not park it. Record the gap in the proof bundle (the PR body's `## Proof` section and the closing comment). Classify the tier (step 5) before you decide to park on this gap. A missing CI check on the head parks the PR at every tier.
   If the head differs from the step 3 SHA, run step 3 again on the current head, then step 4.
   - Without a merge queue: `gh pr merge <pr> --repo <owner/repo> --squash --match-head-commit <reviewed SHA>`. Where GraphQL is blocked: `gh api -X PUT repos/<owner>/<repo>/pulls/<pr>/merge -f sha=<reviewed SHA> -f merge_method=squash`.
   - With a merge queue: GraphQL `enqueuePullRequest` with `expectedHeadOid` set to the reviewed SHA. If it fails, do not merge another way.
   - Never pass `--admin` or `--auto`. Never resolve review threads yourself to unblock a merge. If a safety check blocks the merge, stop loud.
   - Receipt: `gh pr view <pr> --repo <owner/repo> --json state,mergeCommit,headRefOid` (or `gh api repos/<owner>/<repo>/pulls/<pr>`) shows `MERGED`. If `headRefOid` differs from the reviewed SHA, the merge is not covered by review: run step 3 on the diff between the two.
   - **Parked merge.** Give Marcus one pinned command for the reviewed SHA. Wait in the background and end the turn: subscribe to PR activity in a cloud session; locally, poll `gh api repos/<owner>/<repo>/pulls/<pr> --jq .state` every 5 minutes, for up to 24 hours. After the wake, read the receipt yourself. A "merged" report from Marcus or from chat is not proof.
   - **Stacked PRs.** Never use `gh stack merge`. Merge one layer at a time, bottom first, each pinned to its own reviewed SHA after its own ready check. A layer whose head moved after a rebase needs step 3 and step 4 again on its new head. A high-tier layer or a reserved path parks that layer and every layer above it.
7. **Infra apply**, for each affected Spacelift stack, as [Spacelift](#spacelift) describes.
8. **Deploy** the merged commit, or skip when the deploy path is `none`.
9. **Done-checks** against the merged commit, or the deploy when a check needs it. Tick each "Done when" item with its evidence link on the same line. Leave an item unticked while it has no evidence. With deploy path `none` and a low or medium tier, skip steps 7 and 8.
10. **Close.** Post one closing comment on the ticket: links to the PR, the merge receipt, the CI run, and the screenshots, and one line for each time Marcus was needed. A ticket that the GitHub integration closed is not proof. If it closed before this comment, reopen it and say so.

## Repository specifics

Also reserved, at every tier:

- Each path in the [Reserved paths](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/risk-tiers.md#reserved-paths) section of Risk tiers.
- Merge and authority rules in `sucramual/mp`. The Merge-rule files section of [PR review](https://raw.githubusercontent.com/sucramual/mp/main/agents/guides/pr-review.md#merge-rule-files) lists the same files:
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

When you are not sure that a path is reserved, treat it as reserved.

### Spacelift

Spacelift is read-only for the agent. Read plans only. Never confirm, apply, or discard a Spacelift run. Never run `spacectl stack deploy`.

**Spacelift PRs (Marcus, 2026-10-18).** Queue a Spacelift PR only through `open-pr`'s merge-queue rule for Marcus's Spacelift PRs, pinned to the reviewed SHA, and only when all of these hold. Otherwise park it.

- The Terraform changes no auth, IAM, or secrets path.
- Every other change in the PR keeps the tier gate and the reserved paths.
- Queue only when every affected stack waits for a confirm before it applies: `autodeploy` is off in `spacectl stack show --id <stack> -o json`.
- Before the merge, the proposed run of each stack on the reviewed SHA has a change list within the intent, with no unrelated drift.

Marcus still confirms every apply.

**Plan comparison before you send a confirm link.**

1. Find the tracked run after the merge (`spacectl stack run list --id <stack> -o json`). Its commit must equal the merge commit.
2. Get the change lists of the tracked run and the reviewed proposed run with `spacectl stack changes --id <stack> --run <run-id>`. Compare their sorted `<action> <resource address>` lines with `diff`. An entry without an action or an address stops the comparison.
3. If the plans differ, or the run is for another SHA, stop loud and send no confirm link. Show the difference.
4. If they are identical, send Marcus the confirm link, "plan identical to the reviewed plan", and the compared lines. Park this stack.
5. After the run reaches `FINISHED`, run the PR's post-apply checks, and add the results to the PR body's `## Proof` section.

At step 9, for a devbox server, `scripts/devbox.sh url <port>` on the laptop prints the URL for Marcus.
