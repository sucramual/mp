---
name: matrix
description: Routes one goal to several /neo workers. Splits it into the smallest shippable PRs with a PR brief each, runs a fresh review gate with LLM or TypeSafe triage, and brings Marcus a batched decision queue. Never writes code. Use for "/matrix", "matrix this goal", or "split this goal across neo workers". Not for one ticket that one worker can finish (neo).
---

# matrix

Take one goal to merged PRs through `/neo` workers. You are the router. You never write code. Marcus is present at intake and at each decision batch.

`<skill-dir>` is the folder of this `SKILL.md`.

## Intake

Send Marcus one message:

- **Goal.** Restate the goal. Give each requirement a pass/fail check. State what is out of scope. The router in the spike read the goal literally and dropped a case the team needed, so ask about each case that the goal text does not name.
- **Split.** The PR plan from [Split](#split), with each PR's dependencies and its worker.
- **Triage.** Name the triage method that the [Review gate](#review-gate) will use: LLM, or TypeSafe when Marcus passed `--triage typesafe` and `TYPESAFE_API_KEY` is set.
- **Decisions.** The first decision batch from [Decision queue](#decision-queue).
- **Access.** Do the Dependencies, Access, and Merge rules steps of the `neo` intake once here, for every repository and login that the plan needs. Set the `auth-helper` horizon to the whole plan, including the checks after the last merge, not to one PR. Name each missing item. Do not start a worker until Marcus fixes it.
- **Grants.** Ask once for each authority that the plan needs, because each later ask waits for Marcus.
  - Merges: ask only in a repository whose employer overlay merge rule accepts a written grant. That rule decides what a grant can cover. Ask whether Marcus grants you queue authority for each PR that the rule lets a grant cover. Write his answer word for word in the plan file. [Granted merges](#granted-merges) says how you use it.
  - Sign-offs: name each person outside the run whose agreement a PR needs, and where the link to that agreement goes.
  - Messages: list each message to a person outside the run that the plan needs, with its text. Ask Marcus to send it, to let you send it, or to drop it.
- **Earlier findings.** When the goal comes from earlier findings, such as a spike, read them into the plan file: the baseline runs by run ID, the methods that prove a change, the known traps, the dropped ideas, and the open decisions with their owners. Put each part that the results do not give in this message as a question.

Then start the workers. Do not come back to Marcus except with a decision batch or the close.

## Split

Read the code that the goal touches before you split. A split from the goal text alone missed cross-file tests in the spikes.

- Split into the smallest shippable PRs. A shippable PR merges alone, leaves main working, and has its own check. In a repository with a size gate, such as `yarn pr:size`, that gate is the upper bound.
- Give each file one owner. When a test reads a file, the owner of that file owns the test too.
- Group PRs into chains. A chain is a sequence of PRs where each one builds on the one before, or small PRs in one area. One `/neo` owns one chain. Give each chain an ID, such as `CH-2`. The [vocabulary](https://raw.githubusercontent.com/sucramual/mp/main/skills/neo-vocabulary.md) defines these terms.
- A ticket is optional. One ticket can have several PRs. A PR with no ticket still has a PR brief.

## PR briefs

A PR brief is everything one `/neo` worker needs to build one PR. Write one PR brief for each PR. Keep all PR briefs and the decision queue in one plan file in the session scratch directory. This file is the one record of the run: rewrite a section when a decision changes it.

Each PR brief has:

- **Checks.** The pass/fail checks this PR must pass, and how to prove each one: the test, or the run and the method that make the check work. When a check compares with an earlier run, cite that run by ID, not as a copied number. Add any known trap. The worker writes each test first and sees it fail before it changes the code. Workers skipped this until a spike brief stated it.
- **Files.** The files this PR owns. The worker reports any other file it must change as a contract change. It does not change it silently.
- **Dependencies.** The PRs or merged code that this PR needs first, and the base branch.
- **Grants.** Marcus's merge grant for this PR, word for word, when he gave one.
- **Owner's decisions.** Every decision that Marcus or the code already settled, with its reason. The review gate reads this. A thin PR brief made the gate report settled decisions as bugs.
- **Siblings.** The other PRs that touch nearby files, and what each one changes.
- **Chain and ticket.** The chain ID, the worker that owns the chain, and the ticket ID when there is one.

## Workers

- One PR has exactly one `/neo` for its whole life. One `/neo` can own several PRs in its chain.
- A `/neo` never starts another `/neo`. Only you start workers.
- Start each `/neo` in its own session, or in a background agent with its own worktree. In the Claude desktop app, start a session for each chain. Brief it: "Run /neo with the PR brief at `<path>`. It owns `<PR list>`."
- Start independent chains in parallel. Start a dependent chain when its dependency merges, or when the PR brief gives it a written contract to build against.
- Near its context budget, a worker hands off its whole chain to one new worker. Never split a chain between two workers.
- Put no ticket ID in a worker's branch name or PR title. Only you close the ticket, at [Close](#close). Linear closes a ticket when a merged PR's branch name or title holds its ID: a branch named after its ticket closed the ticket while two goal checks were still open. Instead, the worker writes `Part of <ID>` in the PR body. Linear links the PR but does not close the ticket on merge.
- Tell each worker to pass `--work` on its first `agent-trace` call: the ticket ID, so its spans join the ticket, or its chain ID when the goal has no ticket. Tell it to send you its close draft instead of posting it.

### Heartbeat

A worker can end its turn with nothing left to wake it. The router is idle while it waits for worker notes, so it cannot see the stall either.

- While any chain is open, keep one heartbeat: a background wake of about 30 minutes, such as `sleep 1800` run as a background command. Start the next one each time it fires.
- On each wake, check every open chain. Look for an open PR that passes the ready check but is not merged or in the merge queue. Look for a worker whose session is idle while its chain has an open PR that is not parked, or a next PR that nothing blocks.
- Send each such worker a nudge that names the PR and what you saw, and asks it to confirm that a background wait runs for each open PR. Do not merge or enqueue the PR yourself: the worker owns the ready check and the merge. The one exception is a PR under [Granted merges](#granted-merges).
- Keep each worker session until the ticket closes. The app can archive a session when its PR merges. If that happens, restore it with `unarchive_session`.

### Granted merges

When Marcus granted queue authority for a PR at intake, its worker parks the PR to you with its reviewed SHA when the ready check passes. You queue it, because the grant is in your session: a permission check can refuse an approval that one session relays to another.

1. Read the PR state from GitHub. Check that the head is the reviewed SHA and that the ready check holds on it.
2. Check that each person that the PR needs has signed off, with the link in the plan file. When a link is missing, ask Marcus. Do not assume agreement.
3. Queue the PR with the pinned call that the merge rules name for the repository. Tell the worker, so that it starts its checks after the merge.

A grant counts only in a repository whose employer overlay merge rule accepts it. In every other repository, the PR parks for Marcus. A grant does not cover a Spacelift confirm, a head that changed after review, or a PR whose files grew beyond its PR brief. Send those to Marcus.

### Guarded changes

A guarded change, such as a change to a test that guards a secret, is parked in the worker's own session. Marcus approves it there. Do not relay his approval, because a permission check accepts it only from Marcus in that session. Add the park to the decision queue, and send the batch at once when the park blocks the chain. Name the session to open and the change.

## Review gate

Before each PR opens, a fresh read-only reviewer reads the diff and its PR brief. The worker runs the gate. When the worker is a subagent that cannot start a reviewer, it sends you its branch and head SHA, and you run the gate.

Triage each finding with the [triage rule](references/triage-rule.md). Both triage methods apply that one rule and give the same four classes.

- **LLM triage** is the default. The reviewer, or you, answers the rule's questions for each finding and applies its classes.
- **TypeSafe triage** runs only when Marcus passes `--triage typesafe`. Write the input file `{"pr_brief": "<PR brief text>", "findings": [{"id": "<id>", "text": "<finding>"}]}`. Send only the PR brief and the finding text, with `file:line` references. Never send secrets, keys, routing-key values, or code. Then run `python3 <skill-dir>/scripts/triage.py <input file>`. It needs `TYPESAFE_API_KEY` and prints one class for each finding.
- When `--triage typesafe` is set but `TYPESAFE_API_KEY` is not set, or the script exits 3, use LLM triage. This is not an error.
- Tell Marcus once which method ran: in the intake message, and again only if the method changes during the run.

Act on each class as the rule says. Add each `decide` finding to the decision queue.

The gate does not replace the review bots after the PR opens. `review-pr` still runs.

## Decision queue

- Batch decisions. Send a batch only when a worker is blocked on one, or at the close.
- Give each decision a default and its evidence. Settle a decision yourself when the code or a written rule answers it.
- Bring Marcus only the decisions that change agreed behaviour, security, scope, or a public contract. The spike router raised 7 decisions for one goal, which is too many.
- Write each answer into the PR briefs it affects.

## Integration

Restacks and cross-PR breaks are yours.

- Hold the base branch fixed while workers run. Batch base changes, and rebase every affected branch once for each batch.
- After a dependency merges, rebase each branch that depends on it onto the latest base. Run the tests that cross PR boundaries, such as a test that reads a file that another PR changes.
- Send each failure to the worker that owns the failing file. Do not fix it yourself.
- Before you forward a rule to workers, read its scope line and quote it with the rule. A rule from a guide can apply to one repository only. A merge-note rule forwarded without its scope had to be withdrawn from three workers. For an employer repository, merge authority is in the Merge authority section of `~/.claude/work.md`.

## Close

You own the ticket's close. Workers do not write close comments to the ticket.

1. Collect each worker's close draft: its verdict, the evidence for each check marked `live` or `unit only`, its decisions, and its open items. Each worker answers the `Reconcile` items of its own sessions before it sends the draft.
2. Run `agent-trace show --work <ticket ID>`. It joins the spans of every worker session bound to the ticket. When the goal has no ticket, run it once for each chain ID.
3. Post one comment on the ticket: the `text` fence from `show`, each PR with its reviewed SHA and merge SHA, each park, the combined verdict for each goal check with its evidence, the decisions, and the open items.
4. Close the ticket only when every goal check passes on the merged result, including checks that no PR covers. Otherwise leave it open and list what remains.

Then send Marcus one message: each PR with its state and link, each park with its pinned merge command, the decisions that you settled and their evidence, the open items, and a link to the ticket comment. A goal with no ticket gets this message only.

## Hard limits

- Never write code, and never edit a worker's branch except to rebase it.
- Every `/neo` hard limit applies to every worker. Guarded changes wait for Marcus, merges are pinned to the reviewed SHA, and Spacelift is read-only.
- Never merge without the merge rules that the `neo` intake reads.
- A grant counts only where the employer overlay merge rule accepts it, and only for what that rule lets it cover. It covers only the PR that it names, at the reviewed SHA. In every other repository, a grant never changes a park.
- Done means every goal check passes on the merged result, not that the PRs merged.
