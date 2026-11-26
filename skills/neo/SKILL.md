---
name: neo
description: Takes one written ticket, usually Linear, or a /matrix PR brief, to a merged and verified result that passes the ticket's checks, without Marcus watching. One intake message fixes a pass/fail check for each requirement and tests every tool the run needs, then the run loops change, verify, keep or fix. Use for "/neo", "neo this ticket", or "run this ticket end to end without me". Not for a plain request to open or publish a PR (open-pr), or for a spike or experiment that ends in a decision and merges nothing (perf). Sets the hard limits - guarded changes wait for Marcus, merges are pinned to the reviewed SHA, Spacelift is read-only.
---

# neo

Take one written ticket to a merged result that passes its checks. Marcus is present only at intake. Never come back to him mid-run.

## Intake

Send Marcus one message:

- **Dependencies.** Check that the `open-pr`, `review-pr`, and `verify` skills are in the skill list, and that `auth-helper` and `agent-trace` run from `PATH`. A neo-only install has none of them. Name each missing one in this message, with the [install steps](https://github.com/sucramual/mp/blob/main/skills/README.md#install). Do not start the loop until Marcus installs them.
- **Goal.** Restate the ticket's `## Goal`: the outcome and why. Give each ticket requirement a pass/fail check. Write unclear points as proposals with a default. List each test that the plan removes or weakens.
- **Done when.** Draft the ticket's Done when list from these checks: one item each, in the format that the [vocabulary](https://raw.githubusercontent.com/sucramual/mp/main/skills/neo-vocabulary.md) gives, with `owner: neo`. Keep the items that the ticket has, and rewrite only an item that is not pass/fail or lacks a proof or covers field. Keep no second list beside it. Put the draft in this message. After Marcus says OK, write it to the ticket description with a `save_issue` patch. Close ticks these items, so each must be a check that the run can prove.
- **Access.** List the logins and tools the goal needs. Check push access to each target repository first, with the claude-code-remote `check_repo_access` tool or `git push --dry-run`. If the session lacks it, ask Marcus in this message to start the run session with the repository attached for push, or to approve `add_repo` now. Run `auth-helper check --require <logins> --horizon <run length> --json`, for example `--require gh,gcloud,spacelift`. If `~/.claude/work-neo.md` exists, read it and follow it. For each login that is not `ok`, give Marcus its `fix` to run now. When a check needs a signed-in page on the devbox, add `okta` to `--require`: `auth-helper` reads the `verify-browser` Chrome. If `okta` is `expired`, Marcus signs in now through the noVNC page that its `fix` names. On a headless host without `verify-browser`, each signed-in check becomes an acceptance item for Marcus. Test each tool that `auth-helper` does not cover once with a real call, so permission prompts and proxy blocks show at intake. For Linear, post one `save_comment` on the ticket while Marcus is present, so he sees whether the connector still asks. Run `agent-trace collect --ensure` once, so the run's native spans reach the local receiver.
- **Merge rules.** Read [Risk tiers](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/risk-tiers.md) and the [Merge-rule files](https://raw.githubusercontent.com/sucramual/mp/main/agents/guides/pr-review.md) section of PR review with `curl -fsSL <URL>` or `gh api`. Do not use a web-fetch tool: it returns a summary, not the exact text. Read them once here and use them for the whole run. If a read fails, treat each PR as High tier and park it. Never merge without these rules.

## Started by /matrix

When `/matrix` starts you with a PR brief, the PR brief is your ticket, and these rules change the run:

- Skip the intake message. `/matrix` sent it. Still read the merge rules as the Merge rules step says, and still run the `auth-helper` check. Send a failed check to `/matrix`, not to Marcus.
- Own every PR that the PR brief assigns to you, in order. Never start another `/neo`.
- Change only the files that the PR brief gives you. Report any other file as a contract change.
- Triage the review gate's findings with the `matrix` skill's triage rule, by the method that its Review gate section names. Fix `before-merge` findings in this PR. Add `fix-forward` findings to the next PR in your chain. Send `decide` findings to `/matrix`.
- Send each message to `/matrix`, including decisions, parks, and the close draft, with `SendMessage` to the `from` address of its last message to you. When no message from it has reached you, or the send fails, append the message to the router inbox that the PR brief names. Do not ask Marcus which session is the router.
- On every wake, read the router outbox that the PR brief names. Act on each entry that has no `[done]` mark, then add that mark to it. `/matrix` writes there when its `SendMessage` to you fails. Before you end each turn, run one outbox watch with `run_in_background: true`, after you mark the entries: `f=<outbox>; s=$(cksum < "$f"); until [ "$(cksum < "$f")" != "$s" ]; do sleep 30; done; echo "event: outbox"`. Keep it next to the PR watchers, and start it again when it exits. In one run, the laptop that hosts the desktop app was offline for hours, every router message failed, and a worker with no running wait did not start its next PR until the laptop reconnected.
- Send every decision to `/matrix`, with a default. Never ask Marcus. The one exception is a guarded change from [Hard limits](#hard-limits): park it in this session, with the diff and the failing case, and keep working on items that it does not block. Tell `/matrix` about the park. Marcus approves it in this session, because a permission check refuses an approval that `/matrix` relays.
- When the PR brief gives Marcus's merge grant for a PR, do not merge that PR. When its ready check passes, park it to `/matrix` with its reviewed SHA. The `matrix` skill's Granted merges section says when the grant counts.
- Write to Linear only to add `red:` to the items that the PR brief assigns to you, and to tick them, as [Close](#close) step 4 says. Never change an item's text: send a change to `/matrix`.
- Put no ticket ID in your branch name or PR title, and write `Part of <ID>` in the PR body. Linear closes a ticket when a merged PR's branch name or title holds its ID, and only `/matrix` closes the ticket.
- Trace the run as [Loop](#loop) says. On your first `agent-trace` call, pass `--work` with the work ID that the PR brief names, so `/matrix` can join your sessions with the other workers'.
- Do not post the [Close](#close) comments. `/matrix` posts one close comment for the whole ticket. Do Close steps 1 and 2 for your own sessions with `agent-trace show --session <id>`. Do steps 4 and 7 for the items you own. Then send your close draft to `/matrix`: the verdict, each item you own by ID with its evidence marked `live` or `unit only`, each PR with its reviewed SHA and merge SHA, each park, the decisions, and the open items.

## Loop

Change, verify, then keep or fix. Plan, test, and split PRs as you judge best. Before you publish with `open-pr`, have a reviewer with fresh context read the diff. Fit that review to what already checks the diff:

- When an existing executable check fails on each defect class that the diff could add, such as a conformance test, a schema check, a guard test, or a typecheck, run no reviewer. Name that check in the PR body.
- When the diff adds or changes a check, a test helper that other tests use, or other code that verifies code, first write the invariants as failing tests. Then have one reviewer read the diff with an open brief, not a rubric.
- Never skip a configured reviewer of the repository: its entry in `reviewers.json`, or `work-reviewers.json` for a work repository, names one reviewer or a list. Re-trigger each one only with its own `retrigger` text, and never where a reviewer sets `threadRepliesOnly: true`.
- Before a PR is ready, and for every wait on an external state, follow [Live proof and waits](references/live-proof-and-waits.md).

Publish with `open-pr --no-review`. You take each PR to ready yourself, inline, with `review-pr` as the procedure. Start no background `review-pr` agent, because two writers would push to one branch. Never end the run at an open PR.

- In local Claude Code, the PR watcher is the only wake source for an open PR. Run `bash <review-pr skill dir>/scripts/watch-pr.sh <owner>/<repo> <pr>` with `run_in_background: true`, one for each open PR, and end the turn. Add `--timeout 900` while the reviewer has not covered the head, so `event: timeout` sends you to `review-pr` step 2 and its re-trigger. It exits when a required check fails, every required check has passed, the review decision changes, a comment, review, or reaction arrives, the head moves, a conflict appears, the PR becomes ready, or it merges or closes. It prints one `event:` line for each. It ignores bot status comments and your own posts.
- When it exits, handle each event inline with `review-pr` steps 2 to 6, then start the watcher again. When it exits 1, read the PR again and stop on the failure if the read fails again. Never use another wait script. In a cloud session, which blocks the GraphQL reads of the watcher, wait as `review-pr` step 1 says for a cloud session.
- Auto-fix (the Claude desktop app's PR monitor) is not a wake source. After `open-pr`, turn Auto-fix off for this PR with the app's `set_monitor` tool (`auto_fix: false` and the PR URL). If the call fails or the tool is missing, as in Codex or a terminal, continue: the watcher is the only wake source either way.
- Each time the run wakes, read the current head from GitHub and run the ready check: [Ready to merge](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/ready-to-merge.md), or the overlay rule in an employer repository. When every condition holds, merge under the hard limits below, or park it to `/matrix` when the PR brief gives a merge grant for it. The check waits for each configured reviewer: a finding from a reviewer that the config did not list once came after a park and cost a fourth PR.
- A throwaway PR is one that you open only to test, never to merge. It gets no ready check and no watcher. When its test ends, close it. Delete its branch and any environment it made.

### Turn end

Before each `wrap_up`, and before you end any turn, check that one of these holds:

- Each open PR has a running PR watcher, or a PR-activity subscription in a cloud session. A parked PR keeps its watcher too, so the run wakes when Marcus merges it.
- The ticket is finished: Close is done.

A status note, a merge note, a message to `/matrix`, or a `wrap_up` is not a stop point. When neither condition holds, start the missing wait, then end the turn. Under `/matrix`, also keep the outbox watch running until Close. When work remains that no wait, park, or decision blocks, such as the next PR in the chain, do that work now instead of ending the turn. Nothing else wakes the run when a PR becomes ready, except the heartbeat below.

When a wait can last more than 30 minutes, such as a wait for a dependency PR to merge, also keep a heartbeat in your own session, such as a `CronCreate` wake every 30 minutes that reads the PR state again. Stop it when the wait ends. A watcher's wake is lost when the turn it starts ends in an API error: in one run that left a worker idle 5 hours after its dependency merged.

### Run state

Context compaction drops rules from the conversation.

- Before the first change, write a run-state file in the session scratch directory, such as `<scratchpad>/neo-run-state.md`. List the standing obligations: the work ID and the open `agent-trace` spans, a wait for each open PR, and each decision rule that intake or `/matrix` gave the run, with its source. Add the next step.
- Update the file when a PR opens or merges, when a decision rule is added, and when the next step changes.
- When a turn starts with "continued from a previous conversation", read the run-state file first, before any other action.

Trace the run with `agent-trace` through Bash. Append each call to a command that you run anyway, so it costs no extra turn: `agent-trace span start --id impl --name "implement" --kind phase && <command>`.

- Pass `--work <ID>` on the first call in each session, the main one and each child. The work ID is the ticket ID, or the chain ID when the chain has no ticket. Later calls in that session reuse it. The [vocabulary](https://raw.githubusercontent.com/sucramual/mp/main/skills/neo-vocabulary.md) defines these terms.
- Open a span for each phase, PR, wait, infra step, and check: `span start --id <id> --name <text> --kind <phase|pr|wait|infra|check> [--parent <id>]`. End it with `span end --id <id> --status <ok|error|parked> [--note <text>]`.
- Each time you hit friction that you want fixed, run `agent-trace note friction --category <permission|doc|flaky|workaround|missing-tool> --what <text> --fix <text>`.
- A hook records each `gh pr create` and `gh pr merge`. Do not write `LOG` lines.
- When a call exits non-zero, fix the arguments from its error and run it again. A warning that collect is not reachable needs no action.

After each merge, run `verify`. Fix a failed check in a follow-up PR under the same rules.

Make reversible choices yourself and continue. Write to the ticket only at the start, when a decision needs recording, and in the Close steps below. Never use the Linear attachment tools (`prepare_attachment_upload`, `create_attachment_from_upload`).

## Close

1. Run `agent-trace show --work <ID>`. Add `--session <id>` for each session of the run that made no `agent-trace` call.
2. Answer each item in its `Reconcile` list: `agent-trace note friction ... --ref <ref>`, or `agent-trace note none --ref <ref>` when the item was no friction. Run `show` again until it prints `Reconcile: none`.
3. Post the run log comment: the `text` fence from `show`, which is the gaps view (run totals, GAPS ranked by cost, the span chart), each PR with its reviewed SHA and merge SHA, each CI or deploy run as a link, and each park.
4. Tick each item you own whose check passed on the merged result with the proof that the item names, with a `save_issue` patch. Tick only an item with a `red:` field, which you add when its check first fails before your change. Leave each other item `[ ]`, and list it as an open item.
5. In a standalone run, audit the ticks before the closing comment. Start one fresh-context, read-only subagent. Give it each ticked item with its `red:` and evidence links, and each PR with its merge SHA, but not your verdict. Ask it to disprove each tick: evidence that is missing or unrelated, `unit only` where the proof asks for live proof, or evidence outside the covers field. Untick each item that it refutes, and list it as an open item. Append `— audited` to each item that stands. A run that checks only its own ticks has no second reader. Under `/matrix`, skip this step, because `/matrix` audits.
6. Then post the closing comment: the verdict; for each item, its evidence marked `live` or `unit only`; the decisions and their evidence as text and links; the open items; and a link to the run log comment.
7. Read the ticket again with `get_issue`. Each item must match its verdict in the closing comment. When one does not, fix it. The verdict is done only when every item is ticked. Otherwise move the ticket out of a Done state if Linear closed it on merge, and say why in the closing comment.

## Hard limits

- Irreversible or guarded changes wait for Marcus: data, migrations, infra applies, auth, IAM, secrets, CI workflows, agent settings, messages outside his team, product decisions the ticket does not settle, and in `sucramual/mp` each file that [Merge-rule files](https://github.com/sucramual/mp/blob/main/agents/guides/pr-review.md#merge-rule-files) lists. Park only that item and keep working.
- A removed or weakened test is intended only when the ticket or the intake approved it. Otherwise park it.
- Before a merge, classify the PR's tier with the [Risk tiers](https://raw.githubusercontent.com/sucramual/mp/main/skills/review-pr/references/risk-tiers.md) that you read at intake. Merge only a Low or Medium PR that changes no reserved path. Park a High PR. In an employer repository with an overlay rule, follow the Employer repository rules section of Risk tiers instead. When you are not sure, the tier is High.
- A merge grant never changes a park, except where an employer overlay merge rule accepts grants. There, `/matrix` queues the PR, not you.
- Spacelift is read-only for the agent. Never confirm, apply, or discard a Spacelift run.
- Merge only the reviewed commit: `gh pr merge <pr> --squash --match-head-commit <reviewed SHA>`, or `expectedHeadOid` set to the reviewed SHA with a merge queue. Never pass `--admin`. Never use `gh stack merge`; merge stack layers one at a time, bottom first.
- At the end, send Marcus one message with every park and its pinned merge command. Give only the call that the merge rules allow for that repository, such as `enqueuePullRequest` with `expectedHeadOid` where an overlay rule forbids `gh pr merge`. Keep each parked PR's watcher running and end the turn. After he merges, run `verify`: a "merged" message is not proof.
- Done means every Done when item passes on the merged result, not that the PR merged.
