---
name: neo
description: Takes one written ticket, usually Linear, to a merged and verified result that passes the ticket's checks, without Marcus watching. One intake message fixes a pass/fail check for each requirement and tests every tool the run needs, then the run loops change, verify, keep or fix. Use for "/neo", "neo this ticket", or "run this ticket end to end without me". Not for a plain request to open or publish a PR (open-pr), or for "/rogue" and "go rogue" (rogue). Sets the hard limits - guarded changes wait for Marcus, merges are pinned to the reviewed SHA, Spacelift is read-only.
---

# neo

Take one written ticket to a merged result that passes its checks. Marcus is present only at intake. Never come back to him mid-run.

## Intake

Send Marcus one message:

- **Goal.** Give each ticket requirement a pass/fail check. Write unclear points as proposals with a default. List each test that the plan removes or weakens.
- **Access.** List the logins and tools the goal needs. Check push access to each target repository first, with the claude-code-remote `check_repo_access` tool or `git push --dry-run`. If the session lacks it, ask Marcus in this message to start the run session with the repository attached for push, or to approve `add_repo` now. Run `auth-helper check --require <logins> --horizon <run length> --json`, for example `--require gh,gcloud,spacelift`. If `~/.claude/work-neo.md` exists, read it and follow it. For each login that is not `ok`, give Marcus its `fix` to run now. When a check needs a signed-in page on the devbox, add `okta` to `--require`: `auth-helper` reads the `verify-browser` Chrome. If `okta` is `expired`, Marcus signs in now through the noVNC page that its `fix` names. On a headless host without `verify-browser`, each signed-in check becomes an acceptance item for Marcus. Test each tool that `auth-helper` does not cover once with a real call, so permission prompts and proxy blocks show at intake. For Linear, post one `save_comment` on the ticket while Marcus is present, so he sees whether the connector still asks. Run `agent-trace collect --ensure` once, so the run's native spans reach the local receiver.

## Loop

Change, verify, then keep or fix. Plan, test, and split PRs as you judge best. Before you publish with `open-pr`, have a reviewer with fresh context read the diff. Take each PR to ready with `review-pr`.

Trace the run with `agent-trace` through Bash. Chain each call onto a command that you run anyway, so it costs no extra turn: `agent-trace span start --id impl --name "implement" --kind phase && <command>`.

- Pass `--ticket <ID>` on the first call in each session, the main one and each child. Later calls in that session reuse it.
- Open a span for each phase, PR, wait, infra step, and check: `span start --id <id> --name <text> --kind <phase|pr|wait|infra|check> [--parent <id>]`. End it with `span end --id <id> --status <ok|error|parked> [--note <text>]`.
- Each time you hit friction that you want fixed, run `agent-trace note friction --category <permission|doc|flaky|workaround|missing-tool> --what <text> --fix <text>`.
- A hook records each `gh pr create` and `gh pr merge`. Do not write `LOG` lines.
- When a call exits non-zero, fix the arguments from its error and run it again. A warning that collect is not reachable needs no action.

After each merge, run `verify`. Fix a failed check in a follow-up PR under the same rules.

Make reversible choices yourself and continue. Write to the ticket only at the start, when a decision needs recording, and in the two close comments below. Never use the Linear attachment tools (`prepare_attachment_upload`, `create_attachment_from_upload`).

## Close

1. Run `agent-trace show --ticket <ID>`. Add `--session <id>` for each session of the run that made no `agent-trace` call.
2. Answer each item in its `Reconcile` list: `agent-trace note friction ... --ref <ref>`, or `agent-trace note none --ref <ref>` when the item was no friction. Run `show` again until it prints `Reconcile: none`.
3. Post the run log comment: the `text` fence from `show`, each PR with its reviewed SHA and merge SHA, each CI or deploy run as a link, and each park.
4. Then post the closing comment: the verdict; for each "Done when" check, its evidence marked `live` or `unit only`; the decisions and their evidence as text and links; the open items; and a link to the run log comment.

## Hard limits

- Irreversible or guarded changes wait for Marcus: data, migrations, infra applies, auth, IAM, secrets, CI workflows, agent settings, messages outside his team, product decisions the ticket does not settle, and in `sucramual/mp` each file that [Merge-rule files](https://github.com/sucramual/mp/blob/main/agents/guides/pr-review.md#merge-rule-files) lists. Park only that item and keep working.
- A removed or weakened test is intended only when the ticket or the intake approved it. Otherwise park it.
- Before a merge, classify the PR's tier with [Risk tiers](../review-pr/references/risk-tiers.md). Merge only a Low or Medium PR that changes no reserved path. Park a High PR. When you are not sure, the tier is High.
- Spacelift is read-only for the agent. Never confirm, apply, or discard a Spacelift run.
- Merge only the reviewed commit: `gh pr merge <pr> --squash --match-head-commit <reviewed SHA>`, or `expectedHeadOid` set to the reviewed SHA with a merge queue. Never pass `--admin`. Never use `gh stack merge`; merge stack layers one at a time, bottom first.
- At the end, send Marcus one message with every park and its pinned merge command. Wait in the background and end the turn. After he merges, run `verify`: a "merged" message is not proof.
- Done means every ticket check passes on the merged result, not that the PR merged.
