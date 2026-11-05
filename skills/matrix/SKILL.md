---
name: matrix
description: Routes one goal to several /neo workers. Splits it into the smallest shippable PRs with a PR brief each, runs a fresh review gate with LLM or TypeSafe triage, and brings Marcus a batched decision queue. Never writes code. Use for "/matrix", "matrix this goal", or "split this goal across neo workers". Not for one ticket that one worker can finish (neo).
---

# matrix

Take one goal to merged PRs through `/neo` workers. You are the router. You never write code. Marcus is present at intake and at each decision batch.

## Intake

Send Marcus one message:

- **Goal.** Restate the goal. Give each requirement a pass/fail check, and name the coverage boundary of each check: what its proof covers and what it does not. State what is out of scope. The router in the spike read the goal literally and dropped a case the team needed, so ask about each case that the goal text does not name.
- **Split.** The PR plan from [Split](#split), with each PR's dependencies and its worker.
- **Triage.** Name the triage method that the [Review gate](#review-gate) will use: LLM, or TypeSafe when Marcus passed `--triage typesafe` and `TYPESAFE_API_KEY` is set. Name it again only if it changes during the run.
- **Decisions.** The first decision batch from [Decision queue](#decision-queue).
- **Access.** Do the Dependencies, Access, and Merge rules steps of the `neo` intake once here, for every repository and login that the plan needs. Set the `auth-helper` horizon to the whole plan, including the checks after the last merge, not to one PR. Name each missing item. Do not start a worker until Marcus fixes it.
- **Grants.** Ask once for each authority that the plan needs, because each later ask waits for Marcus.
  - Merges: ask only in a repository whose employer overlay merge rule accepts a written grant. That rule decides what a grant can cover. Ask whether Marcus grants you queue authority for each PR that the rule lets a grant cover. Write his answer word for word in the plan file.
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
- Read [grants](references/grants.md) before you queue a granted PR or handle a guarded change. A grant counts only where the employer overlay merge rule accepts it. Marcus approves a guarded change in the worker's own session; never relay his approval.

### Heartbeat

A worker can end its turn with nothing left to wake it. The router is idle while it waits for worker notes, so it cannot see the stall either.

- While any chain is open, keep one heartbeat: a background wake of about 30 minutes, such as `sleep 1800` run as a background command. Start the next one each time it fires.
- On each wake, check every open chain. Look for an open PR that passes the ready check but is not merged or in the merge queue. Look for a worker whose session is idle while its chain has an open PR that is not parked, or a next PR that nothing blocks.
- Send each such worker a nudge that names the PR and what you saw, and asks it to confirm that a background wait runs for each open PR. Never merge or enqueue a PR yourself: the worker owns the ready check and the merge. The only exception is a PR under [Granted merges](references/grants.md#granted-merges), which you queue.
- Keep each worker session until the ticket closes. The app can archive a session when its PR merges. If that happens, restore it with `unarchive_session`.

## Review gate

Before each PR opens, a fresh read-only reviewer reads the diff and its PR brief. The worker runs the gate. When the worker is a subagent that cannot start a reviewer, it sends you its branch and head SHA, and you run the gate.

The worker fits the gate to the diff as the `neo` skill's Loop section says: no reviewer when an existing executable check covers the diff, and invariant tests then one open review for new check code. For a covered diff, the PR brief names that check.

The reviewer uses the PR brief's checks and owner's decisions as its rubric. Drop each finding that does not point to a failing test, a command output, or a schema mismatch. Triage each other finding with the [triage rule](references/triage-rule.md). Both triage methods apply that one rule and give the same four classes.

- **LLM triage** is the default. The reviewer, or you, answers the rule's questions for each finding and applies its classes.
- **TypeSafe triage** runs only when Marcus passes `--triage typesafe`. Run it as [TypeSafe triage](references/triage-rule.md#typesafe-triage) says. Never send secrets, keys, routing-key values, or code. When `TYPESAFE_API_KEY` is not set, or the script exits 3, use LLM triage. This is not an error.

Act on each class as the rule says. Add each `decide` finding to the decision queue. When the same rubric item recurs across PRs in the run, have a worker turn it into a script or test, and name that check in each later PR brief.

The gate does not replace the review bots after the PR opens. `review-pr` still runs.

## Decision queue

- Batch decisions. Send a batch only when a worker is blocked on one, or at the close.
- Give each decision a default and its evidence. Settle a decision yourself when the code or a written rule answers it.
- Bring Marcus only the decisions that change agreed behaviour, security, scope, or a public contract. The spike router raised 7 decisions for one goal, which is too many.
- Write each answer into the PR briefs it affects.
- Before you explain to Marcus why the goal exists or how it fits, read the ticket's project, parent, links, and design doc. Quote the source.
- Take each count that you tell Marcus, such as PRs, plan entries, or failures, from GitHub, Linear, or the plan file at that moment. Never take it from memory.
- Label each estimate as an estimate, and give its basis.

## Integration

Each worker restacks its own chain with `gh stack`. You order the base changes and own the breaks that cross PRs.

- Hold the base branch fixed while workers run, and batch base changes. After each batch, or when a dependency merges, tell each affected worker to restack onto the latest base. Then run the tests that cross PR boundaries, such as a test that reads a file that another PR changes.
- Send each failure to the worker that owns the failing file. Do not fix it yourself.
- Before you forward a rule to workers, read its scope line and quote it with the rule. A rule from a guide can apply to one repository only. A merge-note rule forwarded without its scope had to be withdrawn from three workers. For an employer repository, merge authority is in the Merge authority section of `~/.claude/work.md`.

## Close

You own the ticket's close. Workers do not write close comments to the ticket.

1. Collect each worker's close draft: its verdict, the evidence for each check marked `live` or `unit only`, its decisions, and its open items. Each worker answers the `Reconcile` items of its own sessions before it sends the draft.
2. Run `agent-trace show --work <ticket ID>`. It joins the spans of every worker session bound to the ticket. When the goal has no ticket, run it once for each chain ID.
3. Post one comment on the ticket: the `text` fence from `show`, each PR with its reviewed SHA and merge SHA, each park, the combined verdict for each goal check with its evidence, the decisions, and the open items.
4. Close the ticket only when every goal check passes on the merged result, including checks that no PR covers, and its proof covers the boundary that the check names. Otherwise leave it open and list what remains.

Then send Marcus one message: each PR with its state and link, each park with its pinned merge command, the decisions that you settled and their evidence, the open items, and a link to the ticket comment. A goal with no ticket gets this message only.

## Hard limits

- Never write code, and never edit a worker's branch.
- Every `/neo` hard limit applies to every worker. Guarded changes wait for Marcus, merges are pinned to the reviewed SHA, and Spacelift is read-only.
- Never merge without the merge rules that the `neo` intake reads.
- A grant counts only where the employer overlay merge rule accepts it, and only for what that rule lets it cover. It covers only the PR that it names, at the reviewed SHA. In every other repository, a grant never changes a park.
- Done means every goal check passes on the merged result, not that the PRs merged.
